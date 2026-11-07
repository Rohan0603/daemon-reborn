from __future__ import annotations

import hashlib
import json
import struct
import zlib
from collections.abc import Callable
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from daemon_reborn.assets.canonical import (
    CanonicalAssetCache,
    CanonicalAssetError,
    load_canonical_assets,
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


def _write_pack(root: Path, *, duration_ms: int = 100, tags: list[dict[str, object]] | None = None) -> None:
    root.mkdir(parents=True, exist_ok=True)
    atlas = _png_rgba(4, 2)
    (root / "atlas.png").write_bytes(atlas)
    manifest = {
        "schema_version": 1,
        "editor": {"name": "Pixelorama", "version": "v1.2.4-stable"},
        "canvas": {"width": 2, "height": 2, "fps": 10},
        "frames": [
            {"id": 0, "duration_ms": duration_ms, "x": 0, "y": 0, "width": 2, "height": 2},
            {"id": 1, "duration_ms": 200, "x": 2, "y": 0, "width": 2, "height": 2},
        ],
        "tags": tags or [{"name": "idle", "from_frame": 0, "to_frame": 1}],
        "fallback": "idle",
        "atlas": {"filename": "atlas.png", "width": 4, "height": 2, "sha256": hashlib.sha256(atlas).hexdigest()},
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


def test_loads_immutable_canonical_metadata_and_player_clips(tmp_path: Path) -> None:
    _write_pack(tmp_path)

    pack = load_canonical_assets(tmp_path)

    assert pack.schema_version == 1
    assert pack.canvas == (2, 2)
    assert pack.atlas_sha256 == hashlib.sha256((tmp_path / "atlas.png").read_bytes()).hexdigest()
    assert [(clip.name, [frame.key for frame in clip.frames]) for clip in pack.to_player_clips()] == [
        ("idle", ["frame-0", "frame-1"])
    ]
    with pytest.raises(FrozenInstanceError):
        pack.schema_version = 2  # type: ignore[misc]


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda root: (root / "atlas.png").write_bytes(b"tampered"), "atlas.png digest"),
        (lambda root: (root / "manifest.json").write_text('{"schema_version": 99}', encoding="utf-8"), "manifest.json digest"),
        (lambda root: (root / "manifest.json").write_text(
            json.dumps({"schema_version": 1, "atlas": {"filename": "../atlas.png"}}), encoding="utf-8"
        ), "manifest.json digest"),
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
