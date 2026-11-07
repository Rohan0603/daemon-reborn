import json
import struct
import sys
import textwrap
import zlib
from pathlib import Path

import pytest

from daemon_reborn.assets.export import AssetExportError, export_pixelorama


def _png_rgba(width: int, height: int, alpha: int = 255) -> bytes:
    rows = b"".join(b"\x00" + bytes((20, 40, 60, alpha)) * width for _ in range(height))

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


def _write_fake_exporter(tmp_path: Path, *, mode: str = "ok") -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    script = tmp_path / "fake_pixelorama.py"
    script.write_text(
        textwrap.dedent(
            f"""
            import json
            import pathlib
            import sys
            import time

            mode = {mode!r}
            args = sys.argv
            if mode == 'native_shape':
                source = pathlib.Path(next(arg for arg in args if arg.endswith('.pxo')))
                if args.index('--export') > args.index(str(source)):
                    raise SystemExit('Pixelorama options must precede the project path')
            output = pathlib.Path(args[args.index('--output') + 1])
            output.parent.mkdir(parents=True, exist_ok=True)
            if mode == 'sleep':
                time.sleep(2)
            if mode == 'stale':
                output.write_bytes(b'old')
                raise SystemExit(0)
            if mode == 'malformed':
                output.write_bytes(b'not-png')
                (output.parent / 'atlas.json').write_text('{{', encoding='utf-8')
                raise SystemExit(0)
            output.write_bytes({_png_rgba(256, 64)!r})
            snapshot = {{
                'pixelorama_version': 'v1.2.4-stable',
                'size_x': 64,
                'size_y': 64,
                'frames': [
                    {{'duration': 7, 'cels': [{{'image_size': 'Vector2i(64, 64)'}}]}},
                    {{'duration': 7, 'cels': [{{'image_size': 'Vector2i(64, 64)'}}]}},
                    {{'duration': 1, 'cels': [{{'image_size': 'Vector2i(64, 64)'}}]}},
                    {{'duration': 1, 'cels': [{{'image_size': 'Vector2i(64, 64)'}}]}},
                ],
                'tags': [
                    {{'name': 'idle', 'from': 1, 'to': 2}},
                    {{'name': 'blink', 'from': 3, 'to': 4}},
                ],
                'export_profile': {{'export_json': 'true', 'fps': 10}},
            }}
            json_name = f"{{source.stem}}.json" if mode == 'native_shape' else 'atlas.json'
            (output.parent / json_name).write_text(json.dumps(snapshot), encoding='utf-8')
            """
        ),
        encoding="utf-8",
    )
    return script


def _run(tmp_path: Path, *, mode: str = "ok", timeout: float = 1.0) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    source = tmp_path / "placeholder.pxo"
    source.write_bytes(b"approved placeholder source")
    target = tmp_path / "published"
    exporter = _write_fake_exporter(tmp_path, mode=mode)
    return export_pixelorama(
        source=source,
        executable=[sys.executable, str(exporter)],
        output_dir=target,
        source_license="CC0-1.0",
        expected_version="v1.2.4-stable",
        fps=10,
        timeout_seconds=timeout,
    )


def test_export_promotes_canonical_manifest_and_provenance(tmp_path: Path) -> None:
    output = _run(tmp_path)

    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    provenance = json.loads((output / "provenance.json").read_text(encoding="utf-8"))
    assert manifest["frames"][0]["duration_ms"] == 700
    assert manifest["frames"][2]["duration_ms"] == 100
    assert manifest["tags"] == [
        {"name": "idle", "from_frame": 0, "to_frame": 1},
        {"name": "blink", "from_frame": 2, "to_frame": 3},
    ]
    assert manifest["atlas"]["width"] == 256
    assert provenance["editor"]["version"] == "v1.2.4-stable"
    assert provenance["source"]["license"] == "CC0-1.0"
    assert set(provenance["files"]) == {"atlas.png", "manifest.json"}
    assert set((output / "SHA256SUMS.txt").read_text(encoding="utf-8").split()) >= {
        "atlas.png",
        "manifest.json",
        "provenance.json",
    }


def test_repeated_exports_have_identical_semantic_artifacts(tmp_path: Path) -> None:
    first = _run(tmp_path / "first")
    second = _run(tmp_path / "second")

    assert (first / "manifest.json").read_bytes() == (second / "manifest.json").read_bytes()
    assert (first / "atlas.png").read_bytes() == (second / "atlas.png").read_bytes()


def test_export_accepts_pixelorama_cli_option_order_and_json_name(tmp_path: Path) -> None:
    output = _run(tmp_path, mode="native_shape")

    assert (output / "manifest.json").is_file()
    assert (output / "atlas.png").is_file()
    assert (output / "atlas.json").is_file()
    assert not (output / "placeholder.json").exists()


def test_failed_export_preserves_last_known_good(tmp_path: Path) -> None:
    output = _run(tmp_path / "good")
    before = (output / "manifest.json").read_bytes()

    source = tmp_path / "good" / "placeholder.pxo"
    exporter = _write_fake_exporter(tmp_path / "bad", mode="malformed")
    with pytest.raises(AssetExportError, match="PNG|JSON"):
        export_pixelorama(
            source=source,
            executable=[sys.executable, str(exporter)],
            output_dir=output,
            source_license="CC0-1.0",
            expected_version="v1.2.4-stable",
            fps=10,
        )

    assert (output / "manifest.json").read_bytes() == before


@pytest.mark.parametrize(
    ("mode", "message"),
    [("sleep", "timed out"), ("stale", "missing"), ("malformed", "JSON")],
)
def test_export_rejects_bad_process_or_outputs(tmp_path: Path, mode: str, message: str) -> None:
    with pytest.raises(AssetExportError, match=message):
        _run(tmp_path, mode=mode, timeout=0.5 if mode == "sleep" else 5.0)


def test_export_rejects_symlinked_output_directory(tmp_path: Path) -> None:
    source = tmp_path / "placeholder.pxo"
    source.write_bytes(b"source")
    outside = tmp_path / "outside"
    outside.mkdir()
    target = tmp_path / "published"
    target.symlink_to(outside, target_is_directory=True)
    exporter = _write_fake_exporter(tmp_path)

    with pytest.raises(AssetExportError, match="symlink"):
        export_pixelorama(
            source=source,
            executable=[sys.executable, str(exporter)],
            output_dir=target,
            source_license="CC0-1.0",
            expected_version="v1.2.4-stable",
            fps=10,
        )
