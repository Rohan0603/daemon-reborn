from __future__ import annotations

import hashlib
import json
import os
import struct
import zlib
from collections.abc import Callable
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from daemon_reborn.assets import canonical
from daemon_reborn.assets.canonical import (
    CanonicalAssetCache,
    CanonicalAssetError,
    load_canonical_assets,
    load_canonical_assets_with_fallback,
    load_packaged_idle_assets,
)


def _png_rgba(width: int, height: int) -> bytes:
    rows = b"".join(b"\x00" + bytes((20, 40, 60, 255)) * width for _ in range(height))

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


def _replace_idat(data: bytes, replacement: bytes) -> bytes:
    result = bytearray(data[:8])
    offset = 8
    while offset < len(data):
        size = struct.unpack(">I", data[offset : offset + 4])[0]
        kind = data[offset + 4 : offset + 8]
        payload_end = offset + 8 + size
        payload = data[offset + 8 : payload_end]
        if kind == b"IDAT":
            payload = replacement
        result.extend(
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
        )
        offset = payload_end + 4
        if kind == b"IEND":
            break
    return bytes(result)


def _write_pack(
    root: Path,
    *,
    duration_ms: int = 100,
    tags: list[dict[str, object]] | None = None,
) -> None:
    root.mkdir(parents=True, exist_ok=True)
    atlas = _png_rgba(4, 2)
    (root / "atlas.png").write_bytes(atlas)
    manifest = {
        "schema_version": 1,
        "editor": {"name": "Pixelorama", "version": "v1.2.4-stable"},
        "source": {"filename": "placeholder.pxo", "license": "CC0-1.0", "sha256": "0" * 64},
        "canvas": {"width": 2, "height": 2, "fps": 10},
        "frames": [
            {"id": 0, "duration_ms": duration_ms, "x": 0, "y": 0, "width": 2, "height": 2},
            {"id": 1, "duration_ms": 200, "x": 2, "y": 0, "width": 2, "height": 2},
        ],
        "tags": tags or [{"name": "idle", "from_frame": 0, "to_frame": 1}],
        "fallback": "idle",
        "atlas": {
            "filename": "atlas.png",
            "width": 4,
            "height": 2,
            "sha256": hashlib.sha256(atlas).hexdigest(),
        },
    }
    manifest_bytes = (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode()
    (root / "manifest.json").write_bytes(manifest_bytes)
    provenance = {
        "schema_version": 1,
        "editor": manifest["editor"],
        "source": {"filename": "placeholder.pxo", "license": "CC0-1.0", "sha256": "0" * 64},
        "files": {
            "atlas.png": hashlib.sha256(atlas).hexdigest(),
            "manifest.json": hashlib.sha256(manifest_bytes).hexdigest(),
        },
    }
    provenance_bytes = (json.dumps(provenance, sort_keys=True, indent=2) + "\n").encode()
    (root / "provenance.json").write_bytes(provenance_bytes)
    entries = {
        "atlas.png": hashlib.sha256(atlas).hexdigest(),
        "manifest.json": hashlib.sha256(manifest_bytes).hexdigest(),
        "provenance.json": hashlib.sha256(provenance_bytes).hexdigest(),
    }
    (root / "SHA256SUMS.txt").write_text(
        "".join(f"{digest}  {name}\n" for name, digest in sorted(entries.items())), encoding="utf-8"
    )


def _refresh_hashes(root: Path) -> None:
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    atlas = (root / "atlas.png").read_bytes()
    manifest["atlas"]["sha256"] = hashlib.sha256(atlas).hexdigest()
    manifest_bytes = (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode()
    (root / "manifest.json").write_bytes(manifest_bytes)
    provenance = json.loads((root / "provenance.json").read_text(encoding="utf-8"))
    provenance["files"] = {
        "atlas.png": hashlib.sha256(atlas).hexdigest(),
        "manifest.json": hashlib.sha256(manifest_bytes).hexdigest(),
    }
    provenance_bytes = (json.dumps(provenance, sort_keys=True, indent=2) + "\n").encode()
    (root / "provenance.json").write_bytes(provenance_bytes)
    entries = {
        "atlas.png": hashlib.sha256(atlas).hexdigest(),
        "manifest.json": hashlib.sha256(manifest_bytes).hexdigest(),
        "provenance.json": hashlib.sha256(provenance_bytes).hexdigest(),
    }
    (root / "SHA256SUMS.txt").write_text(
        "".join(f"{digest}  {name}\n" for name, digest in sorted(entries.items())), encoding="utf-8"
    )


def test_loads_immutable_canonical_metadata_and_player_clips(tmp_path: Path) -> None:
    _write_pack(tmp_path)

    pack = load_canonical_assets(tmp_path)

    assert pack.schema_version == 1
    assert pack.canvas == (2, 2)
    assert pack.atlas_sha256 == hashlib.sha256((tmp_path / "atlas.png").read_bytes()).hexdigest()
    assert [
        (clip.name, [frame.key for frame in clip.frames]) for clip in pack.to_player_clips()
    ] == [("idle", ["frame-0", "frame-1"])]
    with pytest.raises(FrozenInstanceError):
        pack.schema_version = 2  # type: ignore[misc]


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda root: (root / "atlas.png").write_bytes(b"tampered"), "atlas.png digest"),
        (
            lambda root: (root / "manifest.json").write_text(
                '{"schema_version": 99}', encoding="utf-8"
            ),
            "manifest.json digest",
        ),
        (
            lambda root: (root / "manifest.json").write_text(
                json.dumps({"schema_version": 1, "atlas": {"filename": "../atlas.png"}}),
                encoding="utf-8",
            ),
            "manifest.json digest",
        ),
    ],
)
def test_rejects_tampered_or_unsafe_artifact(
    mutate: Callable[[Path], object], message: str, tmp_path: Path
) -> None:
    _write_pack(tmp_path)
    mutate(tmp_path)

    with pytest.raises(CanonicalAssetError, match=message):
        load_canonical_assets(tmp_path)


def test_rejects_out_of_bounds_and_missing_idle(tmp_path: Path) -> None:
    _write_pack(tmp_path, tags=[{"name": "blink", "from_frame": 0, "to_frame": 2}])

    with pytest.raises(CanonicalAssetError, match="idle|range|integer"):
        load_canonical_assets(tmp_path)


def test_cache_invalidates_after_verified_manifest_digest_changes(tmp_path: Path) -> None:
    _write_pack(tmp_path)
    cache = CanonicalAssetCache()
    first = cache.load(tmp_path)

    second_root = tmp_path.parent / "second"
    _write_pack(second_root, duration_ms=300)
    for name in ("manifest.json", "provenance.json", "SHA256SUMS.txt", "atlas.png"):
        (tmp_path / name).write_bytes((second_root / name).read_bytes())

    second = cache.load(tmp_path)

    assert second is not first
    assert second.frames[0].duration_ms == 300


def test_pixmap_construction_requires_qt_application(tmp_path: Path) -> None:
    _write_pack(tmp_path)

    pack = load_canonical_assets(tmp_path)

    with pytest.raises(CanonicalAssetError, match="QApplication|GUI thread"):
        pack.build_pixmap()


@pytest.mark.parametrize("mutation", ["crc", "trailing", "filter"])
def test_rejects_noncanonical_png_bytes_after_digest_update(tmp_path: Path, mutation: str) -> None:
    _write_pack(tmp_path)
    data = bytearray((tmp_path / "atlas.png").read_bytes())
    if mutation == "crc":
        data[-5] ^= 1
    elif mutation == "trailing":
        data.extend(b"trailing")
    else:
        rows = b"".join(b"\x05" + bytes((20, 40, 60, 255)) * 4 for _ in range(2))
        data = bytearray(_replace_idat(bytes(data), zlib.compress(rows)))
    (tmp_path / "atlas.png").write_bytes(data)
    _refresh_hashes(tmp_path)

    with pytest.raises(CanonicalAssetError, match="CRC|IEND|filter|corrupt"):
        load_canonical_assets(tmp_path)


def test_rejects_trailing_compressed_idat_data_after_digest_update(tmp_path: Path) -> None:
    _write_pack(tmp_path)
    data = (tmp_path / "atlas.png").read_bytes()
    rows = b"".join(b"\x00" + bytes((20, 40, 60, 255)) * 4 for _ in range(2))
    (tmp_path / "atlas.png").write_bytes(_replace_idat(data, zlib.compress(rows) + b"trailing"))
    _refresh_hashes(tmp_path)

    with pytest.raises(CanonicalAssetError, match="compressed stream|trailing"):
        load_canonical_assets(tmp_path)


def test_rejects_frame_reuse_across_clips(tmp_path: Path) -> None:
    _write_pack(
        tmp_path,
        tags=[{"name": "idle", "from_frame": 0, "to_frame": 0}],
    )
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    manifest.pop("tags")
    manifest["clips"] = [
        {"name": "idle", "frame_ids": [0]},
        {"name": "blink", "frame_ids": [0, 1]},
    ]
    (tmp_path / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    _refresh_hashes(tmp_path)

    with pytest.raises(CanonicalAssetError, match="multiple clips|overlap"):
        load_canonical_assets(tmp_path)


def test_rejects_provenance_schema_and_filename_parity_breaks(tmp_path: Path) -> None:
    _write_pack(tmp_path)
    provenance = json.loads((tmp_path / "provenance.json").read_text(encoding="utf-8"))
    provenance["source"]["filename"] = "other.pxo"
    (tmp_path / "provenance.json").write_text(
        json.dumps(provenance, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    _refresh_hashes(tmp_path)

    with pytest.raises(CanonicalAssetError, match="filename|parity"):
        load_canonical_assets(tmp_path)


def test_wraps_invalid_utf8_checksum_as_canonical_error(tmp_path: Path) -> None:
    _write_pack(tmp_path)
    (tmp_path / "SHA256SUMS.txt").write_bytes(b"\xff\xfe")

    with pytest.raises(CanonicalAssetError, match="UTF-8|checksum"):
        load_canonical_assets(tmp_path)


def test_cache_evicts_old_roots_with_lru_bound(tmp_path: Path) -> None:
    cache = CanonicalAssetCache(max_roots=2)
    roots = [tmp_path / str(index) for index in range(3)]
    for root in roots:
        _write_pack(root)
        cache.load(root)

    assert len(cache._entries) == 2
    assert len(cache._roots) == 2


def test_loader_reads_validated_files_without_path_read_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_pack(tmp_path)

    def fail(*_args: object, **_kwargs: object) -> bytes:
        raise AssertionError("validated asset must be read through an opened handle")

    monkeypatch.setattr(Path, "read_bytes", fail)
    load_canonical_assets(tmp_path)


def test_rejects_symlinked_artifact_before_handle_read(tmp_path: Path) -> None:
    _write_pack(tmp_path)
    outside = tmp_path.parent / "outside-manifest.json"
    outside.write_text((tmp_path / "manifest.json").read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "manifest.json").unlink()
    try:
        os.symlink(outside, tmp_path / "manifest.json")
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable in this environment")

    with pytest.raises(CanonicalAssetError, match="outside|symlink|regular|unsafe"):
        load_canonical_assets(tmp_path)


def test_packaged_idle_fallback_is_an_explicit_boundary(tmp_path: Path) -> None:
    packaged = tmp_path / "packaged"
    optional = tmp_path / "optional"
    _write_pack(packaged, duration_ms=777)
    _write_pack(optional)
    (optional / "manifest.json").write_bytes(b"broken")

    pack = load_canonical_assets_with_fallback(optional, packaged)

    assert pack.frames[0].duration_ms == 777


def test_packaged_idle_catalog_is_verified_and_is_the_default_fallback(tmp_path: Path) -> None:
    packaged = load_packaged_idle_assets()

    assert packaged.fallback == "idle"
    assert packaged.clips[0].name == "idle"
    assert packaged.atlas_sha256 == hashlib.sha256(packaged._atlas_bytes).hexdigest()
    assert load_canonical_assets_with_fallback(tmp_path / "missing") == packaged


def test_packaged_idle_catalog_bytes_are_lf_stable_on_windows() -> None:
    root = Path(__file__).parents[3] / "src" / "daemon_reborn" / "assets" / "packaged_idle"
    names = ("manifest.json", "provenance.json", "SHA256SUMS.txt")

    for name in names:
        data = (root / name).read_bytes()
        assert b"\r" not in data, f"{name} must not be EOL-converted on Windows"

    entries = {
        name: hashlib.sha256((root / name).read_bytes()).hexdigest()
        for name in ("atlas.png", "manifest.json", "provenance.json")
    }
    expected = {
        line.split("  ", 1)[1]: line.split("  ", 1)[0]
        for line in (root / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines()
    }
    assert expected == entries


@pytest.mark.parametrize(
    ("candidate", "root", "allowed"),
    [
        (r"\\?\C:\assets\packaged\atlas.png", r"C:\assets\packaged", True),
        (r"\\?\C:\assets\packaged-escape\atlas.png", r"C:\assets\packaged", False),
        (r"\\?\C:\other\atlas.png", r"C:\assets\packaged", False),
    ],
)
def test_windows_handle_final_path_guard_rejects_ancestor_reparse_escape(
    candidate: str, root: str, allowed: bool
) -> None:
    assert canonical._is_descendant_path(candidate, root) is allowed
