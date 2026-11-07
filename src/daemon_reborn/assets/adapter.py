"""Fail-closed adapter for Pixelorama export snapshots."""

from __future__ import annotations

import json
import math
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
class RuntimeTag:
    name: str
    from_frame: int
    to_frame: int


@dataclass(frozen=True)
class RuntimeManifest:
    size: tuple[int, int]
    frames: tuple[RuntimeFrame, ...]
    tags: tuple[RuntimeTag, ...]


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
    if "canvas" in snapshot:
        return _adapt_canonical_manifest(snapshot)
    return _adapt_snapshot(snapshot)


def _adapt_canonical_manifest(snapshot: Mapping[str, object]) -> RuntimeManifest:
    """Adapt the export pipeline's versioned millisecond manifest."""

    if snapshot.get("schema_version") != 1:
        raise ManifestError("unsupported canonical manifest schema")
    raw_canvas = snapshot.get("canvas")
    if not isinstance(raw_canvas, dict):
        raise ManifestError("canonical manifest canvas must be an object")
    width = _positive_int(raw_canvas, "width")
    height = _positive_int(raw_canvas, "height")
    raw_frames = snapshot.get("frames")
    raw_tags = snapshot.get("tags")
    if not isinstance(raw_frames, list) or not raw_frames:
        raise ManifestError("canonical manifest frames must be a non-empty array")
    if not isinstance(raw_tags, list) or not raw_tags:
        raise ManifestError("canonical manifest tags must be a non-empty array")

    frames: list[RuntimeFrame] = []
    for frame_id, raw_frame in enumerate(raw_frames):
        if not isinstance(raw_frame, dict):
            raise ManifestError(f"canonical frame {frame_id} must be an object")
        if raw_frame.get("id") != frame_id:
            raise ManifestError(f"canonical frame {frame_id} has an invalid id")
        if raw_frame.get("width") != width or raw_frame.get("height") != height:
            raise ManifestError(f"canonical frame {frame_id} has invalid dimensions")
        duration_ms = raw_frame.get("duration_ms")
        if isinstance(duration_ms, bool) or not isinstance(duration_ms, int):
            raise ManifestError(f"canonical frame {frame_id} has invalid duration")
        if not 1 <= duration_ms <= 2_147_483_647:
            raise ManifestError(f"canonical frame {frame_id} has invalid duration")
        frames.append(RuntimeFrame(frame_id, duration_ms))

    names: set[str] = set()
    ranges: list[RuntimeTag] = []
    for raw_tag in raw_tags:
        if not isinstance(raw_tag, dict):
            raise ManifestError("canonical tag must be an object")
        name = raw_tag.get("name")
        begin = raw_tag.get("from_frame")
        end = raw_tag.get("to_frame")
        if not isinstance(name, str) or not name.strip() or name in names:
            raise ManifestError("canonical tag names must be unique and non-empty")
        if (
            isinstance(begin, bool)
            or not isinstance(begin, int)
            or isinstance(end, bool)
            or not isinstance(end, int)
            or begin < 0
            or end < begin
            or end >= len(frames)
        ):
            raise ManifestError(f"canonical tag {name} has invalid range")
        names.add(name)
        ranges.append(RuntimeTag(name, begin, end))

    covered = {frame for tag in ranges for frame in range(tag.from_frame, tag.to_frame + 1)}
    missing = sorted(set(range(len(frames))) - covered)
    if missing:
        raise ManifestError(f"canonical frames not covered by tags: {missing}")
    return RuntimeManifest((width, height), tuple(frames), tuple(ranges))


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
        if isinstance(duration, bool) or not isinstance(duration, (int, float)):
            raise ManifestError(f"frame {frame_id} has invalid duration")
        try:
            duration_value = float(duration)
            duration_ms = round(duration_value * 1000)
        except (OverflowError, ValueError) as exc:
            raise ManifestError(f"frame {frame_id} has invalid duration") from exc
        if (
            not math.isfinite(duration_value)
            or duration_value <= 0
            or not 1 <= duration_ms <= 2_147_483_647
        ):
            raise ManifestError(f"frame {frame_id} has invalid duration")
        if not isinstance(cels, list) or not cels:
            raise ManifestError(f"frame {frame_id} has no cels")
        for cel in cels:
            if not isinstance(cel, dict):
                raise ManifestError(f"frame {frame_id} has invalid cel")
            match = _IMAGE_SIZE.fullmatch(str(cel.get("image_size", "")))
            if not match or (int(match[1]), int(match[2])) != (width, height):
                raise ManifestError(f"frame {frame_id} has invalid image size")
        frames.append(RuntimeFrame(frame_id, duration_ms))

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
    return RuntimeManifest(
        (width, height),
        tuple(frames),
        tuple(RuntimeTag(name, begin - 1, end - 1) for name, begin, end in ranges),
    )


def _positive_int(snapshot: Mapping[str, object], key: str) -> int:
    value = snapshot.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ManifestError(f"{key} must be a positive integer")
    return value
