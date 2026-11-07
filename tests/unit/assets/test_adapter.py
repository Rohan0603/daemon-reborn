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
    assert [(tag.name, tag.from_frame, tag.to_frame) for tag in manifest.tags] == [("idle", 0, 1)]


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


def test_adapts_captured_pixelorama_v124_export_fixture() -> None:
    path = Path(__file__).parents[2] / "fixtures" / "orc166_pixelorama_v1_2_4_export.json"

    manifest = load_runtime_manifest(path)

    assert manifest.size == (64, 64)
    assert [frame.duration_ms for frame in manifest.frames] == [100, 160, 120, 200]
    assert [(tag.name, tag.from_frame, tag.to_frame) for tag in manifest.tags] == [
        ("idle", 0, 1),
        ("blink", 2, 3),
    ]


@pytest.mark.parametrize(
    "duration", [float("nan"), float("inf"), -float("inf"), 0.0001, 1e308, 10**400]
)
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


def test_normalizes_pixelorama_one_based_tag_ranges_to_frame_ids(tmp_path: Path) -> None:
    path = tmp_path / "ranges.json"
    path.write_text(json.dumps(export_snapshot()), encoding="utf-8")

    manifest = load_runtime_manifest(path)

    assert [(tag.from_frame, tag.to_frame) for tag in manifest.tags] == [(0, 1)]


def test_adapts_captured_fixture_with_zero_based_tag_ranges() -> None:
    path = Path(__file__).parents[2] / "fixtures" / "orc166_pixelorama_v1_2_4_export.json"

    manifest = load_runtime_manifest(path)

    assert [(tag.name, tag.from_frame, tag.to_frame) for tag in manifest.tags] == [
        ("idle", 0, 1),
        ("blink", 2, 3),
    ]


def test_adapts_canonical_pipeline_manifest_without_reinterpreting_milliseconds(
    tmp_path: Path,
) -> None:
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "canvas": {"width": 64, "height": 64, "fps": 10},
                "frames": [
                    {"id": 0, "duration_ms": 700, "width": 64, "height": 64},
                    {"id": 1, "duration_ms": 100, "width": 64, "height": 64},
                ],
                "tags": [{"name": "idle", "from_frame": 0, "to_frame": 1}],
            }
        ),
        encoding="utf-8",
    )

    manifest = load_runtime_manifest(path)

    assert [(frame.id, frame.duration_ms) for frame in manifest.frames] == [(0, 700), (1, 100)]
    assert [(tag.name, tag.from_frame, tag.to_frame) for tag in manifest.tags] == [("idle", 0, 1)]
