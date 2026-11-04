"""Fail-closed adapter for Pixelorama export snapshots."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


class ManifestError(ValueError):
    """Raised when an export cannot be promoted to a runtime manifest."""


@dataclass(frozen=True)
class RuntimeFrame:
    id: int
    duration_ms: int


@dataclass(frozen=True)
class RuntimeManifest:
    size: tuple[int, int]
    frames: tuple[RuntimeFrame, ...]
    tags: tuple[str, ...]


_IMAGE_SIZE = re.compile(r"^Vector2i\((\d+), (\d+)\)$")


def load_runtime_manifest(path: Path) -> RuntimeManifest:
    """Load and validate one complete JSON export; never accept partial output."""

    if not path.is_file():
        raise ManifestError(f"JSON manifest does not exist: {path}")
    try:
        snapshot = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ManifestError(f"invalid JSON manifest: {path}") from exc
    if not isinstance(snapshot, dict):
        raise ManifestError("JSON manifest root must be an object")
    return _adapt_snapshot(snapshot)


def _adapt_snapshot(snapshot: Mapping[str, object]) -> RuntimeManifest:
    width = _positive_int(snapshot, "size_x")
    height = _positive_int(snapshot, "size_y")
    export_profile = snapshot.get("export_profile")
    if not isinstance(export_profile, dict) or export_profile.get("export_json") != "true":
        raise ManifestError("JSON export is not enabled")
    raw_frames = snapshot.get("frames")
    raw_tags = snapshot.get("tags")
    if not isinstance(raw_frames, list) or not raw_frames:
        raise ManifestError("frames must be a non-empty array")
    if not isinstance(raw_tags, list) or not raw_tags:
        raise ManifestError("tags must be a non-empty array")

    frames: list[RuntimeFrame] = []
    for frame_id, raw_frame in enumerate(raw_frames):
        if not isinstance(raw_frame, dict):
            raise ManifestError(f"frame {frame_id} must be an object")
        duration = raw_frame.get("duration")
        cels = raw_frame.get("cels")
        if isinstance(duration, bool) or not isinstance(duration, (int, float)) or duration <= 0:
            raise ManifestError(f"frame {frame_id} has invalid duration")
        if not isinstance(cels, list) or not cels:
            raise ManifestError(f"frame {frame_id} has no cels")
        for cel in cels:
            if not isinstance(cel, dict):
                raise ManifestError(f"frame {frame_id} has invalid cel")
            match = _IMAGE_SIZE.fullmatch(str(cel.get("image_size", "")))
            if not match or (int(match[1]), int(match[2])) != (width, height):
                raise ManifestError(f"frame {frame_id} has invalid image size")
        frames.append(RuntimeFrame(frame_id, round(float(duration) * 1000)))

    ranges: list[tuple[str, int, int]] = []
    names: set[str] = set()
    for raw_tag in raw_tags:
        if not isinstance(raw_tag, dict):
            raise ManifestError("tag must be an object")
        name = raw_tag.get("name")
        begin = raw_tag.get("from")
        end = raw_tag.get("to")
        if not isinstance(name, str) or not name.strip():
            raise ManifestError("tag name is missing")
        if name in names:
            raise ManifestError(f"duplicate tag: {name}")
        if (
            isinstance(begin, bool)
            or not isinstance(begin, int)
            or isinstance(end, bool)
            or not isinstance(end, int)
        ):
            raise ManifestError(f"tag {name} has invalid range")
        if begin < 1 or end < begin or end > len(frames):
            raise ManifestError(f"tag {name} has invalid range")
        names.add(name)
        ranges.append((name, begin, end))

    covered = {frame for _, begin, end in ranges for frame in range(begin, end + 1)}
    missing = sorted(set(range(1, len(frames) + 1)) - covered)
    if missing:
        raise ManifestError(f"frames not covered by tags: {missing}")
    return RuntimeManifest((width, height), tuple(frames), tuple(name for name, _, _ in ranges))


def _positive_int(snapshot: Mapping[str, object], key: str) -> int:
    value = snapshot.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ManifestError(f"{key} must be a positive integer")
    return value
