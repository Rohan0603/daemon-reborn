import json
from pathlib import Path

import pytest

from daemon_reborn.assets.adapter import ManifestError, load_runtime_manifest


def export_snapshot() -> dict[str, object]:
    return {
        "pixelorama_version": "v1.2.4-stable",
        "size_x": 64,
        "size_y": 64,
        "frames": [
            {"duration": 0.1, "cels": [{"image_size": "Vector2i(64, 64)"}]},
            {"duration": 0.16, "cels": [{"image_size": "Vector2i(64, 64)"}]},
        ],
        "tags": [{"name": "idle", "from": 1, "to": 2, "color": "ffffffff"}],
        "export_profile": {"export_json": "true"},
    }


def test_adapts_only_valid_complete_snapshot(tmp_path: Path) -> None:
    path = tmp_path / "export.json"
    path.write_text(json.dumps(export_snapshot()), encoding="utf-8")

    manifest = load_runtime_manifest(path)

    assert manifest.size == (64, 64)
    assert [(frame.id, frame.duration_ms) for frame in manifest.frames] == [(0, 100), (1, 160)]
    assert manifest.tags == ("idle",)


def test_rejects_duplicate_tag_names(tmp_path: Path) -> None:
    snapshot = export_snapshot()
    snapshot["tags"] = [
        {"name": "idle", "from": 1, "to": 1},
        {"name": "idle", "from": 2, "to": 2},
    ]
    path = tmp_path / "duplicate-tag.json"
    path.write_text(json.dumps(snapshot), encoding="utf-8")

    with pytest.raises(ManifestError, match="duplicate tag"):
        load_runtime_manifest(path)


def test_rejects_missing_tag_coverage(tmp_path: Path) -> None:
    snapshot = export_snapshot()
    snapshot["tags"] = [{"name": "idle", "from": 1, "to": 1}]
    path = tmp_path / "missing-tag.json"
    path.write_text(json.dumps(snapshot), encoding="utf-8")

    with pytest.raises(ManifestError, match="not covered by tags"):
        load_runtime_manifest(path)


def test_rejects_missing_json(tmp_path: Path) -> None:
    with pytest.raises(ManifestError, match="JSON manifest does not exist"):
        load_runtime_manifest(tmp_path / "missing.json")


def test_rejects_export_without_json_sidecar(tmp_path: Path) -> None:
    snapshot = export_snapshot()
    snapshot["export_profile"] = {"export_json": "false"}
    path = tmp_path / "json-disabled.json"
    path.write_text(json.dumps(snapshot), encoding="utf-8")

    with pytest.raises(ManifestError, match="JSON export is not enabled"):
        load_runtime_manifest(path)


@pytest.mark.parametrize("duration", [float("nan"), float("inf"), -float("inf"), 0.0001])
def test_rejects_non_finite_or_sub_millisecond_duration(tmp_path: Path, duration: float) -> None:
    snapshot = export_snapshot()
    frames = snapshot["frames"]
    assert isinstance(frames, list)
    snapshot["frames"] = [
        {"duration": duration, "cels": [{"image_size": "Vector2i(64, 64)"}]},
        frames[1],
    ]
    path = tmp_path / "invalid-duration.json"
    path.write_text(json.dumps(snapshot), encoding="utf-8")

    with pytest.raises(ManifestError, match="invalid duration"):
        load_runtime_manifest(path)
