"""Fail-closed, deterministic promotion of a Pixelorama CLI export."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import struct
import subprocess
import tempfile
import uuid
import zlib
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


class AssetExportError(RuntimeError):
    """Raised when an export cannot be safely promoted."""


def export_pixelorama(
    *,
    source: Path,
    executable: Sequence[str],
    output_dir: Path,
    source_license: str,
    expected_version: str = "v1.2.4-stable",
    fps: int = 10,
    timeout_seconds: float = 60.0,
) -> Path:
    """Run Pixelorama v1.2.4 CLI and atomically publish validated assets."""

    if not executable:
        raise AssetExportError("Pixelorama executable is required")
    if not source.is_file() or source.is_symlink():
        raise AssetExportError(f"source project is missing or unsafe: {source}")
    if not source_license.strip():
        raise AssetExportError("source license is required")
    if fps <= 0 or timeout_seconds <= 0 or not math.isfinite(timeout_seconds):
        raise AssetExportError("fps and timeout must be positive finite values")
    _reject_symlink_components(output_dir)
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    if output_dir.exists() and not output_dir.is_dir():
        raise AssetExportError(f"output path is not a directory: {output_dir}")

    stage = Path(tempfile.mkdtemp(prefix=".orc185-export-", dir=output_dir.parent))
    try:
        atlas_path = stage / "atlas.png"
        command = [
            *executable,
            "--headless",
            "--quit",
            "--",
            "--export",
            "--spritesheet",
            "--json",
            "--output",
            str(atlas_path),
            str(source),
        ]
        try:
            completed = subprocess.run(
                command,
                cwd=source.parent,
                check=False,
                capture_output=True,
                timeout=timeout_seconds,
                text=True,
            )
        except subprocess.TimeoutExpired as exc:
            raise AssetExportError("Pixelorama export timed out") from exc
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()
            raise AssetExportError(f"Pixelorama export failed ({completed.returncode}): {detail}")

        json_candidates = [path for path in stage.glob("*.json") if _regular_file(path)]
        if not _regular_file(atlas_path) or len(json_candidates) != 1:
            raise AssetExportError("export output is missing atlas PNG or JSON")
        json_path = json_candidates[0]
        if json_path.name != "atlas.json":
            normalized_json_path = stage / "atlas.json"
            json_path.replace(normalized_json_path)
            json_path = normalized_json_path
        snapshot = _read_json(json_path)
        manifest = _canonical_manifest(
            snapshot,
            atlas_path,
            expected_version=expected_version,
            fps=fps,
            source=source,
            source_license=source_license,
        )
        manifest_path = stage / "manifest.json"
        _write_json(manifest_path, manifest)
        file_hashes: dict[str, str] = {
            "atlas.png": _sha256(atlas_path),
            "manifest.json": _sha256(manifest_path),
        }
        provenance: dict[str, Any] = {
            "schema_version": 1,
            "editor": {"name": "Pixelorama", "version": expected_version},
            "source": {
                "filename": source.name,
                "sha256": _sha256(source),
                "license": source_license,
            },
            "files": file_hashes,
        }
        provenance_path = stage / "provenance.json"
        _write_json(provenance_path, provenance)
        checksummed_files = {**file_hashes, "provenance.json": _sha256(provenance_path)}
        sums = "".join(f"{checksummed_files[name]}  {name}\n" for name in sorted(checksummed_files))
        (stage / "SHA256SUMS.txt").write_text(sums, encoding="utf-8", newline="\n")
        _publish(stage, output_dir)
        return output_dir
    except AssetExportError:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    except (OSError, ValueError, zlib.error, struct.error) as exc:
        shutil.rmtree(stage, ignore_errors=True)
        raise AssetExportError(str(exc)) from exc


def _canonical_manifest(
    snapshot: Mapping[str, Any],
    atlas_path: Path,
    *,
    expected_version: str,
    fps: int,
    source: Path,
    source_license: str,
) -> dict[str, Any]:
    if snapshot.get("pixelorama_version") != expected_version:
        raise AssetExportError("unsupported Pixelorama version")
    if snapshot.get("export_profile", {}).get("export_json") != "true":
        raise AssetExportError("Pixelorama JSON export is not enabled")
    width = _positive_int(snapshot, "size_x")
    height = _positive_int(snapshot, "size_y")
    raw_frames = snapshot.get("frames")
    raw_tags = snapshot.get("tags")
    if not isinstance(raw_frames, list) or not raw_frames:
        raise AssetExportError("frames must be a non-empty array")
    if not isinstance(raw_tags, list) or not raw_tags:
        raise AssetExportError("tags must be a non-empty array")
    durations: list[int] = []
    for index, raw_frame in enumerate(raw_frames):
        if not isinstance(raw_frame, dict):
            raise AssetExportError(f"frame {index} is invalid")
        duration = raw_frame.get("duration")
        cels = raw_frame.get("cels")
        if isinstance(duration, bool) or not isinstance(duration, (int, float)):
            raise AssetExportError(f"frame {index} has invalid duration")
        duration_value = float(duration)
        duration_ms = round(duration_value * 1000 / fps)
        if (
            not math.isfinite(duration_value)
            or duration_value <= 0
            or not 1 <= duration_ms <= 2_147_483_647
        ):
            raise AssetExportError(f"frame {index} has invalid duration")
        if not isinstance(cels, list) or not cels:
            raise AssetExportError(f"frame {index} has no cels")
        for cel in cels:
            if not isinstance(cel, dict) or cel.get("image_size") != f"Vector2i({width}, {height})":
                raise AssetExportError(f"frame {index} has invalid cel size")
        durations.append(duration_ms)

    tags: list[dict[str, int | str]] = []
    names: set[str] = set()
    covered: set[int] = set()
    for raw_tag in raw_tags:
        if not isinstance(raw_tag, dict):
            raise AssetExportError("tag is invalid")
        name = raw_tag.get("name")
        begin = raw_tag.get("from")
        end = raw_tag.get("to")
        if not isinstance(name, str) or not name.strip() or name in names:
            raise AssetExportError("tag names must be unique and non-empty")
        if (
            isinstance(begin, bool)
            or not isinstance(begin, int)
            or isinstance(end, bool)
            or not isinstance(end, int)
        ):
            raise AssetExportError(f"tag {name} has invalid range")
        if begin < 1 or end < begin or end > len(raw_frames):
            raise AssetExportError(f"tag {name} has invalid range")
        frame_ids = set(range(begin - 1, end))
        if covered & frame_ids:
            raise AssetExportError(f"tag {name} overlaps another tag")
        names.add(name)
        covered.update(frame_ids)
        tags.append({"name": name, "from_frame": begin - 1, "to_frame": end - 1})
    missing = set(range(len(raw_frames))) - covered
    if missing:
        raise AssetExportError(f"frames are not covered by tags: {sorted(missing)}")

    atlas_width, atlas_height, has_alpha = _inspect_png(atlas_path)
    if (atlas_width, atlas_height) != (width * len(raw_frames), height) or not has_alpha:
        raise AssetExportError("atlas PNG dimensions or RGBA alpha channel are invalid")
    return {
        "schema_version": 1,
        "editor": {"name": "Pixelorama", "version": expected_version},
        "source": {"filename": source.name, "license": source_license, "sha256": _sha256(source)},
        "canvas": {"width": width, "height": height, "fps": fps},
        "frames": [
            {
                "id": index,
                "duration_ms": duration,
                "x": index * width,
                "y": 0,
                "width": width,
                "height": height,
            }
            for index, duration in enumerate(durations)
        ],
        "tags": tags,
        "atlas": {
            "filename": "atlas.png",
            "width": atlas_width,
            "height": atlas_height,
            "sha256": _sha256(atlas_path),
        },
    }


def _inspect_png(path: Path) -> tuple[int, int, bool]:
    data = path.read_bytes()
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise AssetExportError("atlas is not a PNG")
    offset = 8
    idat = bytearray()
    width = height = color_type = bit_depth = None
    while offset < len(data):
        if offset + 12 > len(data):
            raise AssetExportError("truncated PNG")
        size = struct.unpack(">I", data[offset : offset + 4])[0]
        kind = data[offset + 4 : offset + 8]
        payload_end = offset + 8 + size
        if payload_end + 4 > len(data):
            raise AssetExportError("truncated PNG chunk")
        payload = data[offset + 8 : payload_end]
        if kind == b"IHDR":
            if len(payload) != 13:
                raise AssetExportError("invalid PNG header")
            width, height, bit_depth, color_type, compression, filtering, interlace = struct.unpack(
                ">IIBBBBB", payload
            )
            if (bit_depth, color_type, compression, filtering, interlace) != (8, 6, 0, 0, 0):
                raise AssetExportError("PNG must be non-interlaced 8-bit RGBA")
        elif kind == b"IDAT":
            idat.extend(payload)
        elif kind == b"IEND":
            break
        offset = payload_end + 4
    if width is None or height is None or not idat:
        raise AssetExportError("PNG is missing required data")
    try:
        decoded = zlib.decompress(bytes(idat))
    except zlib.error as exc:
        raise AssetExportError("PNG image data is invalid") from exc
    row_size = width * 4
    if len(decoded) != height * (row_size + 1):
        raise AssetExportError("PNG scanline data is incomplete")
    previous = bytearray(row_size)
    has_alpha = True
    for row in range(height):
        filter_type = decoded[row * (row_size + 1)]
        encoded = decoded[row * (row_size + 1) + 1 : (row + 1) * (row_size + 1)]
        current = _unfilter(encoded, previous, filter_type, 4)
        previous = current
    return width, height, has_alpha


def _unfilter(encoded: bytes, previous: bytearray, filter_type: int, bpp: int) -> bytearray:
    current = bytearray(encoded)
    for index, value in enumerate(encoded):
        left = current[index - bpp] if index >= bpp else 0
        up = previous[index]
        upper_left = previous[index - bpp] if index >= bpp else 0
        if filter_type == 1:
            current[index] = (value + left) & 255
        elif filter_type == 2:
            current[index] = (value + up) & 255
        elif filter_type == 3:
            current[index] = (value + ((left + up) // 2)) & 255
        elif filter_type == 4:
            estimate = left + up - upper_left
            distances = (abs(estimate - left), abs(estimate - up), abs(estimate - upper_left))
            predictor = (left, up, upper_left)[distances.index(min(distances))]
            current[index] = (value + predictor) & 255
        elif filter_type != 0:
            raise AssetExportError("unsupported PNG filter")
    return current


def _publish(stage: Path, output_dir: Path) -> None:
    backup: Path | None = None
    if output_dir.exists():
        backup = output_dir.parent / f".{output_dir.name}.backup-{uuid.uuid4().hex}"
        output_dir.rename(backup)
    try:
        stage.rename(output_dir)
    except OSError as exc:
        if backup is not None and not output_dir.exists():
            backup.rename(output_dir)
        raise AssetExportError(f"atomic asset promotion failed: {exc}") from exc
    if backup is not None:
        shutil.rmtree(backup)


def _read_json(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AssetExportError("export JSON is malformed") from exc
    if not isinstance(value, dict):
        raise AssetExportError("export JSON root must be an object")
    return value


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )


def _positive_int(snapshot: Mapping[str, Any], key: str) -> int:
    value = snapshot.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise AssetExportError(f"{key} must be a positive integer")
    return value


def _regular_file(path: Path) -> bool:
    return path.is_file() and not path.is_symlink()


def _reject_symlink_components(path: Path) -> None:
    current = Path(path.anchor) if path.is_absolute() else Path.cwd()
    for component in path.parts[1:] if path.is_absolute() else path.parts:
        current /= component
        if current.is_symlink():
            raise AssetExportError(f"path contains symlink: {current}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export and validate a Pixelorama asset pack")
    parser.add_argument("--source", type=Path, required=True, help="source .pxo project")
    parser.add_argument("--output-dir", type=Path, required=True, help="published asset directory")
    parser.add_argument("--source-license", required=True, help="license of the source artwork")
    parser.add_argument(
        "--executable", nargs="+", required=True, help="Pixelorama executable command"
    )
    parser.add_argument("--expected-version", default="v1.2.4-stable")
    parser.add_argument("--fps", type=int, default=10)
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    args = parser.parse_args(argv)
    try:
        export_pixelorama(
            source=args.source,
            executable=args.executable,
            output_dir=args.output_dir,
            source_license=args.source_license,
            expected_version=args.expected_version,
            fps=args.fps,
            timeout_seconds=args.timeout_seconds,
        )
    except AssetExportError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
