"""Fail-closed loader and cache for the schema-versioned runtime sprite pack."""

from __future__ import annotations

import hashlib
import json
import os
import re
import struct
import threading
import zlib
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

from daemon_reborn.animation.player import PlaybackMode, SpriteClip, SpriteFrame


class CanonicalAssetError(ValueError):
    """Raised when canonical sprite artifacts cannot be trusted or adapted."""


@dataclass(frozen=True, slots=True)
class CanonicalFrame:
    id: int
    duration_ms: int
    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True, slots=True)
class CanonicalClip:
    name: str
    frame_ids: tuple[int, ...]
    loop: bool
    priority: int
    fallback: str | None = None


@dataclass(frozen=True, slots=True)
class CanonicalAssetPack:
    schema_version: int
    canvas: tuple[int, int]
    fps: int
    frames: tuple[CanonicalFrame, ...]
    clips: tuple[CanonicalClip, ...]
    fallback: str
    atlas_sha256: str
    manifest_sha256: str
    provenance_sha256: str
    checksum_sha256: str
    _atlas_bytes: bytes

    def to_player_clips(self) -> tuple[SpriteClip, ...]:
        """Adapt trusted metadata without changing SpritePlayer semantics."""

        frames = {frame.id: frame for frame in self.frames}
        return tuple(
            SpriteClip.from_frames(
                clip.name,
                [
                    SpriteFrame(f"frame-{frame_id}", frames[frame_id].duration_ms / 1000.0)
                    for frame_id in clip.frame_ids
                ],
                PlaybackMode.LOOP if clip.loop else PlaybackMode.HOLD,
            )
            for clip in self.clips
        )

    def build_pixmap(self) -> Any:
        """Construct a QPixmap only on the Qt application thread."""

        try:
            from PySide6.QtCore import QThread
            from PySide6.QtGui import QImage, QPixmap
            from PySide6.QtWidgets import QApplication
        except ImportError as exc:  # pragma: no cover - dependency is project-required
            raise CanonicalAssetError("PySide6 is required to construct a QPixmap") from exc

        application = QApplication.instance()
        if application is None:
            raise CanonicalAssetError(
                "QApplication is required for GUI-thread QPixmap construction"
            )
        if QThread.currentThread() != application.thread():
            raise CanonicalAssetError("QPixmap construction is restricted to the GUI thread")
        image = QImage.fromData(self._atlas_bytes, b"PNG")
        if image.isNull() or image.format() != QImage.Format.Format_RGBA8888:
            image = image.convertToFormat(QImage.Format.Format_RGBA8888)
        if image.isNull() or image.size().width() != self.canvas[0] * len(self.frames):
            raise CanonicalAssetError("validated atlas could not be loaded as RGBA QImage")
        return QPixmap.fromImage(image)


class CanonicalAssetCache:
    """Bounded per-root LRU cache keyed by verified artifact digests."""

    def __init__(self, *, max_roots: int = 32) -> None:
        if isinstance(max_roots, bool) or not isinstance(max_roots, int) or max_roots < 1:
            raise ValueError("max_roots must be a positive integer")
        self._lock = threading.RLock()
        self._max_roots = max_roots
        self._entries: dict[Path, tuple[tuple[object, ...], CanonicalAssetPack]] = {}
        self._roots: OrderedDict[Path, tuple[object, ...]] = OrderedDict()

    def load(self, asset_root: Path) -> CanonicalAssetPack:
        pack, key = _load(asset_root)
        root = _safe_root(asset_root)
        with self._lock:
            cached_key = self._roots.get(root)
            if cached_key == key:
                self._roots.move_to_end(root)
                return self._entries[root][1]
            self._entries[root] = (key, pack)
            self._roots[root] = key
            self._roots.move_to_end(root)
            while len(self._roots) > self._max_roots:
                evicted_root, _ = self._roots.popitem(last=False)
                self._entries.pop(evicted_root, None)
            return pack


def load_canonical_assets(asset_root: Path) -> CanonicalAssetPack:
    """Load and validate one complete ORC-185 canonical asset directory."""

    return _load(asset_root)[0]


def load_canonical_assets_with_fallback(
    asset_root: Path, packaged_idle_root: Path | None = None
) -> CanonicalAssetPack:
    """Load optional assets, falling back to a trusted packaged idle pack."""

    try:
        return load_canonical_assets(asset_root)
    except CanonicalAssetError:
        return (
            load_packaged_idle_assets()
            if packaged_idle_root is None
            else load_canonical_assets(packaged_idle_root)
        )


def load_packaged_idle_assets() -> CanonicalAssetPack:
    """Load the verified, package-owned idle catalog without caller paths."""

    resource = resources.files("daemon_reborn.assets").joinpath("packaged_idle")
    try:
        with resources.as_file(resource) as root:
            return load_canonical_assets(root)
    except (CanonicalAssetError, OSError) as exc:
        raise CanonicalAssetError("packaged idle catalog is missing or invalid") from exc


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MAX_FILE_BYTES = 64 * 1024 * 1024
_MAX_CANVAS = 4096
_MAX_FRAMES = 2048
_MAX_CLIPS = 256
_MAX_PNG_BYTES = 128 * 1024 * 1024


def _load(asset_root: Path) -> tuple[CanonicalAssetPack, tuple[object, ...]]:
    root = _safe_root(asset_root)
    names = ("manifest.json", "atlas.png", "provenance.json", "SHA256SUMS.txt")
    root_fd = _open_root(root)
    try:
        file_bytes = {name: _read_root_file(root, root_fd, name) for name in names}
    finally:
        if root_fd >= 0:
            os.close(root_fd)
    sums_bytes = file_bytes["SHA256SUMS.txt"]
    sums = _parse_sums(sums_bytes)
    actual = {name: _sha256(data) for name, data in file_bytes.items()}
    for name in ("manifest.json", "atlas.png", "provenance.json"):
        expected = sums.get(name)
        if expected != actual[name]:
            raise CanonicalAssetError(
                f"{name} digest mismatch: expected {expected or 'missing'}, actual {actual[name]}"
            )
    manifest_bytes = file_bytes["manifest.json"]
    provenance_bytes = file_bytes["provenance.json"]
    manifest = _json_object(manifest_bytes, "manifest.json")
    provenance = _json_object(provenance_bytes, "provenance.json")
    _validate_manifest_metadata(manifest)
    _validate_provenance(provenance, actual, manifest)
    pack = _parse_manifest(manifest, file_bytes["atlas.png"], actual)
    key = (
        pack.schema_version,
        pack.manifest_sha256,
        pack.atlas_sha256,
        pack.provenance_sha256,
        actual["SHA256SUMS.txt"],
    )
    return pack, key


def _parse_manifest(
    manifest: Mapping[str, Any], atlas_bytes: bytes, actual: Mapping[str, str]
) -> CanonicalAssetPack:
    if manifest.get("schema_version") != 1:
        raise CanonicalAssetError("manifest schema_version must be 1")
    canvas = _object(manifest, "canvas")
    width = _bounded_int(canvas, "width", 1, _MAX_CANVAS)
    height = _bounded_int(canvas, "height", 1, _MAX_CANVAS)
    fps = _bounded_int(canvas, "fps", 1, 1000)
    raw_frames = manifest.get("frames")
    if not isinstance(raw_frames, list) or not raw_frames or len(raw_frames) > _MAX_FRAMES:
        raise CanonicalAssetError(f"frames must contain 1..{_MAX_FRAMES} entries")
    frames: list[CanonicalFrame] = []
    seen_ids: set[int] = set()
    for index, raw in enumerate(raw_frames):
        item = _mapping(raw, f"frame {index}")
        frame_id = _bounded_int(item, "id", 0, _MAX_FRAMES - 1)
        if frame_id in seen_ids:
            raise CanonicalAssetError(f"duplicate frame id: {frame_id}")
        seen_ids.add(frame_id)
        frame = CanonicalFrame(
            frame_id,
            _bounded_int(item, "duration_ms", 1, 2_147_483_647),
            _bounded_int(item, "x", 0, _MAX_PNG_BYTES),
            _bounded_int(item, "y", 0, _MAX_PNG_BYTES),
            _bounded_int(item, "width", 1, _MAX_CANVAS),
            _bounded_int(item, "height", 1, _MAX_CANVAS),
        )
        if frame.x + frame.width > width * len(raw_frames) or frame.y + frame.height > height:
            raise CanonicalAssetError(f"frame {frame_id} rectangle is out of atlas bounds")
        frames.append(frame)
    if seen_ids != set(range(len(frames))):
        raise CanonicalAssetError("frame ids must be contiguous from zero")
    for left_index, left in enumerate(frames):
        for right in frames[left_index + 1 :]:
            if _overlaps(left, right):
                raise CanonicalAssetError(f"frame rectangles overlap: {left.id} and {right.id}")

    atlas_width, atlas_height = _inspect_png(atlas_bytes)
    if (atlas_width, atlas_height) != (width * len(frames), height):
        raise CanonicalAssetError("atlas PNG canvas does not match manifest canvas and frame count")
    atlas = _object(manifest, "atlas")
    if atlas.get("filename") != "atlas.png":
        raise CanonicalAssetError("atlas filename must be exactly atlas.png")
    if atlas.get("width") != atlas_width or atlas.get("height") != atlas_height:
        raise CanonicalAssetError("atlas dimensions do not match the PNG")
    if atlas.get("sha256") != actual["atlas.png"]:
        raise CanonicalAssetError("atlas.png digest does not match manifest")

    clips = _parse_clips(manifest, len(frames))
    fallback = manifest.get("fallback", "idle")
    if not isinstance(fallback, str) or fallback not in {clip.name for clip in clips}:
        raise CanonicalAssetError("fallback clip must reference an existing clip")
    by_name = {clip.name: clip for clip in clips}
    for clip in clips:
        chain: set[str] = set()
        current: str | None = clip.fallback
        while current is not None:
            if current in chain or current not in by_name:
                raise CanonicalAssetError(f"broken or recursive fallback for clip {clip.name}")
            chain.add(current)
            current = by_name[current].fallback
    return CanonicalAssetPack(
        1,
        (width, height),
        fps,
        tuple(sorted(frames, key=lambda frame: frame.id)),
        tuple(sorted(clips, key=lambda clip: (clip.priority, clip.name))),
        fallback,
        actual["atlas.png"],
        actual["manifest.json"],
        actual["provenance.json"],
        actual["SHA256SUMS.txt"],
        atlas_bytes,
    )


def _parse_clips(manifest: Mapping[str, Any], frame_count: int) -> list[CanonicalClip]:
    raw_clips = manifest.get("clips")
    if raw_clips is None:
        raw_tags = manifest.get("tags")
        if not isinstance(raw_tags, list):
            raise CanonicalAssetError("manifest must contain clips or tags")
        raw_clips = []
        for raw_tag in raw_tags:
            tag = _mapping(raw_tag, "tag")
            raw_clips.append(
                {
                    "name": tag.get("name"),
                    "frame_ids": list(
                        range(
                            _bounded_int(tag, "from_frame", 0, frame_count - 1),
                            _bounded_int(tag, "to_frame", 0, frame_count - 1) + 1,
                        )
                    ),
                }
            )
    if not isinstance(raw_clips, list) or not raw_clips or len(raw_clips) > _MAX_CLIPS:
        raise CanonicalAssetError(f"clips must contain 1..{_MAX_CLIPS} entries")
    clips: list[CanonicalClip] = []
    names: set[str] = set()
    used_frames: set[int] = set()
    for index, raw in enumerate(raw_clips):
        item = _mapping(raw, f"clip {index}")
        name = item.get("name")
        if not isinstance(name, str) or not name.strip() or name in names:
            raise CanonicalAssetError("clip names must be unique and non-empty")
        ids = item.get("frame_ids")
        if not isinstance(ids, list) or not ids or len(ids) > _MAX_FRAMES:
            raise CanonicalAssetError(f"clip {name} has invalid frame_ids")
        frame_ids: list[int] = []
        for frame_id in ids:
            if (
                isinstance(frame_id, bool)
                or not isinstance(frame_id, int)
                or not 0 <= frame_id < frame_count
            ):
                raise CanonicalAssetError(f"clip {name} references an out-of-range frame")
            if frame_id in frame_ids:
                raise CanonicalAssetError(f"clip {name} contains duplicate frame ids")
            frame_ids.append(frame_id)
        overlap = used_frames.intersection(frame_ids)
        if overlap:
            raise CanonicalAssetError(
                f"frame ids cannot occur in multiple clips: {sorted(overlap)}"
            )
        used_frames.update(frame_ids)
        loop = item.get("loop", True)
        if not isinstance(loop, bool):
            raise CanonicalAssetError(f"clip {name} has invalid loop flag")
        priority = item.get("priority", 0)
        if (
            isinstance(priority, bool)
            or not isinstance(priority, int)
            or not -1000 <= priority <= 1000
        ):
            raise CanonicalAssetError(f"clip {name} has invalid priority")
        fallback = item.get("fallback")
        if fallback is not None and (not isinstance(fallback, str) or not fallback.strip()):
            raise CanonicalAssetError(f"clip {name} has invalid fallback")
        names.add(name)
        clips.append(CanonicalClip(name, tuple(frame_ids), loop, priority, fallback))
    return clips


def _validate_manifest_metadata(manifest: Mapping[str, Any]) -> None:
    if set(manifest) != {
        "schema_version",
        "editor",
        "source",
        "canvas",
        "frames",
        "tags",
        "fallback",
        "atlas",
    } and set(manifest) != {
        "schema_version",
        "editor",
        "source",
        "canvas",
        "frames",
        "clips",
        "fallback",
        "atlas",
    }:
        raise CanonicalAssetError("manifest contains an unsupported or missing schema field")
    editor = _object(manifest, "editor")
    if set(editor) != {"name", "version"} or not all(
        isinstance(editor.get(key), str) and editor[key].strip() for key in ("name", "version")
    ):
        raise CanonicalAssetError("manifest editor metadata is invalid")
    source = _object(manifest, "source")
    if set(source) != {"filename", "license", "sha256"}:
        raise CanonicalAssetError("manifest source metadata is invalid")
    filename = source.get("filename")
    if (
        not isinstance(filename, str)
        or not filename.strip()
        or Path(filename).name != filename
        or filename in {".", ".."}
    ):
        raise CanonicalAssetError("manifest source filename is invalid")
    if not isinstance(source.get("license"), str) or not source["license"].strip():
        raise CanonicalAssetError("manifest source license is required")
    if not isinstance(source.get("sha256"), str) or not _SHA256.fullmatch(source["sha256"]):
        raise CanonicalAssetError("manifest source sha256 is invalid")


def _validate_provenance(
    provenance: Mapping[str, Any], actual: Mapping[str, str], manifest: Mapping[str, Any]
) -> None:
    if provenance.get("schema_version") != 1:
        raise CanonicalAssetError("provenance schema_version must be 1")
    if set(provenance) != {"schema_version", "editor", "source", "files"}:
        raise CanonicalAssetError("provenance contains an unsupported or missing schema field")
    if provenance["editor"] != manifest["editor"] or provenance["source"] != manifest["source"]:
        raise CanonicalAssetError("provenance metadata has manifest parity mismatch")
    files = _object(provenance, "files")
    if set(files) != {"atlas.png", "manifest.json"}:
        raise CanonicalAssetError("provenance files must name atlas.png and manifest.json exactly")
    for name in ("atlas.png", "manifest.json"):
        if not isinstance(files.get(name), str) or not _SHA256.fullmatch(files[name]):
            raise CanonicalAssetError(f"provenance {name} hash is invalid")
        if files[name] != actual[name]:
            raise CanonicalAssetError(f"provenance {name} digest mismatch")


def _safe_root(path: Path) -> Path:
    if path.is_symlink() or not path.exists() or not path.is_dir():
        raise CanonicalAssetError(f"asset root is missing or unsafe: {path}")
    resolved = path.resolve()
    if _is_reparse(path):
        raise CanonicalAssetError(f"asset root is a reparse point: {path}")
    return resolved


def _safe_file(root: Path, name: str) -> Path:
    candidate = root / name
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise CanonicalAssetError(f"asset path is outside root or missing: {name}") from exc
    if (
        candidate.name != name
        or candidate.is_symlink()
        or _is_reparse(candidate)
        or not candidate.is_file()
    ):
        raise CanonicalAssetError(f"asset path is not a regular in-root file: {name}")
    current = root
    for component in candidate.parts[len(root.parts) : -1]:
        current /= component
        if current.is_symlink() or _is_reparse(current):
            raise CanonicalAssetError(f"asset path contains a symlink or reparse point: {name}")
    return resolved


def _is_reparse(path: Path) -> bool:
    checker = getattr(path, "is_junction", None)
    return bool(checker and checker()) or bool(
        os.name == "nt" and getattr(path.stat(), "st_file_attributes", 0) & 0x400
    )


def _read_bounded(path: Path, name: str) -> bytes:
    size = path.stat().st_size
    if size > _MAX_FILE_BYTES:
        raise CanonicalAssetError(f"{name} exceeds bounded size limit")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise CanonicalAssetError(f"cannot read {name}: {exc}") from exc


def _open_root(root: Path) -> int:
    if os.name == "nt":
        # Windows CPython has no openat/dir_fd. Pin the root directory handle,
        # then compare every opened file's final handle path to that pinned
        # handle before reading; an ancestor junction redirect therefore fails
        # closed even though the pathname APIs themselves are not relative.
        fd = _open_windows_handle(
            root,
            flags=0x00200000 | 0x02000000,  # OPEN_REPARSE_POINT | BACKUP_SEMANTICS
        )
        try:
            actual = _final_path_from_fd(fd)
            if not _same_path(actual, root):
                raise CanonicalAssetError("asset root changed through an ancestor reparse point")
            return fd
        except BaseException:
            os.close(fd)
            raise
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        return os.open(root, flags)
    except OSError as exc:
        raise CanonicalAssetError(f"cannot securely open asset root: {root}") from exc


def _read_root_file(root: Path, root_fd: int, name: str) -> bytes:
    _safe_file(root, name)
    try:
        fd = _open_asset_fd(root, root_fd, name)
    except OSError as exc:
        raise CanonicalAssetError(f"cannot securely open {name}") from exc
    try:
        stat_result = os.fstat(fd)
        if not stat_result.st_mode & 0o170000 == 0o100000:
            raise CanonicalAssetError(f"asset path is not a regular in-root file: {name}")
        if getattr(stat_result, "st_file_attributes", 0) & 0x400:
            raise CanonicalAssetError(f"asset path is a reparse point: {name}")
        if stat_result.st_size > _MAX_FILE_BYTES:
            raise CanonicalAssetError(f"{name} exceeds bounded size limit")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(fd, min(1024 * 1024, _MAX_FILE_BYTES - total + 1))
            if not chunk:
                break
            total += len(chunk)
            if total > _MAX_FILE_BYTES:
                raise CanonicalAssetError(f"{name} exceeds bounded size limit")
            chunks.append(chunk)
        return b"".join(chunks)
    except CanonicalAssetError:
        raise
    except OSError as exc:
        raise CanonicalAssetError(f"cannot read {name}: {exc}") from exc
    finally:
        os.close(fd)


def _open_asset_fd(root: Path, root_fd: int, name: str) -> int:
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    if os.name != "nt":
        return os.open(name, flags, dir_fd=root_fd)

    fd = _open_windows_handle(root / name, flags=0x00200000 | 0x08000000)
    try:
        root_final = _final_path_from_fd(root_fd)
        asset_final = _final_path_from_fd(fd)
        if not _is_descendant_path(asset_final, root_final):
            raise CanonicalAssetError(f"asset path crossed an ancestor reparse point: {name}")
        return fd
    except BaseException:
        os.close(fd)
        raise


def _open_windows_handle(path: Path, *, flags: int) -> int:
    import ctypes
    import msvcrt

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
    ]
    create_file.restype = ctypes.c_void_p
    invalid_handle = ctypes.c_void_p(-1).value
    handle = create_file(
        str(path),
        0x80000000,
        0x00000007,
        None,
        3,
        flags,
        None,
    )
    if handle in (None, invalid_handle):
        error = ctypes.get_last_error()
        raise OSError(error, f"CreateFileW failed for {path.name}")
    try:
        return msvcrt.open_osfhandle(handle, os.O_RDONLY | getattr(os, "O_BINARY", 0))
    except OSError:
        kernel32.CloseHandle(handle)
        raise


def _final_path_from_fd(fd: int) -> str:
    import ctypes
    import msvcrt

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_final_path = kernel32.GetFinalPathNameByHandleW
    get_final_path.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32]
    get_final_path.restype = ctypes.c_uint32
    size = 512
    while size <= 32768:
        buffer = ctypes.create_unicode_buffer(size)
        result = get_final_path(msvcrt.get_osfhandle(fd), buffer, size, 0)
        if result == 0:
            error = ctypes.get_last_error()
            raise OSError(error, "GetFinalPathNameByHandleW failed")
        if result < size:
            return buffer.value
        size *= 2
    raise OSError("asset final path is too long")


def _normal_path(path: str | Path) -> str:
    return str(path).replace("/", "\\").rstrip("\\").casefold()


def _same_path(left: str | Path, right: str | Path) -> bool:
    return _normal_path(left).removeprefix("\\\\?\\") == _normal_path(right).removeprefix("\\\\?\\")


def _is_descendant_path(candidate: str, root: str) -> bool:
    candidate_normal = _normal_path(candidate).removeprefix("\\\\?\\")
    root_normal = _normal_path(root).removeprefix("\\\\?\\")
    return candidate_normal.startswith(root_normal + "\\")


def _json_object(data: bytes, name: str) -> Mapping[str, Any]:
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise CanonicalAssetError(f"{name} is malformed JSON") from exc
    return _mapping(value, name)


def _parse_sums(data: bytes) -> dict[str, str]:
    result: dict[str, str] = {}
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CanonicalAssetError("SHA256SUMS.txt is not valid UTF-8") from exc
    for line in text.splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  (manifest\.json|atlas\.png|provenance\.json)", line)
        if not match or match[2] in result:
            raise CanonicalAssetError("SHA256SUMS.txt contains an invalid or duplicate entry")
        result[match[2]] = match[1]
    if set(result) != {"manifest.json", "atlas.png", "provenance.json"}:
        raise CanonicalAssetError(
            "SHA256SUMS.txt must cover manifest.json, atlas.png, and provenance.json"
        )
    return result


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise CanonicalAssetError(f"{label} must be an object")
    return value


def _object(parent: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    return _mapping(parent.get(key), key)


def _bounded_int(parent: Mapping[str, Any], key: str, minimum: int, maximum: int) -> int:
    value = parent.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise CanonicalAssetError(f"{key} must be an integer in [{minimum}, {maximum}]")
    return value


def _overlaps(left: CanonicalFrame, right: CanonicalFrame) -> bool:
    return (
        left.x < right.x + right.width
        and right.x < left.x + left.width
        and left.y < right.y + right.height
        and right.y < left.y + left.height
    )


def _inspect_png(data: bytes) -> tuple[int, int]:
    if len(data) > _MAX_FILE_BYTES or not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise CanonicalAssetError("atlas.png is not a bounded PNG")
    offset = 8
    idat = bytearray()
    width = height = None
    saw_iend = False
    while offset < len(data):
        if offset + 12 > len(data):
            raise CanonicalAssetError("atlas.png contains a truncated chunk")
        size = struct.unpack(">I", data[offset : offset + 4])[0]
        payload_end = offset + 8 + size
        if payload_end + 4 > len(data):
            raise CanonicalAssetError("atlas.png contains a truncated chunk")
        kind = data[offset + 4 : offset + 8]
        payload = data[offset + 8 : payload_end]
        actual_crc = struct.unpack(">I", data[payload_end : payload_end + 4])[0]
        if zlib.crc32(kind + payload) & 0xFFFFFFFF != actual_crc:
            raise CanonicalAssetError(
                f"atlas.png chunk {kind.decode('ascii', 'replace')} has invalid CRC"
            )
        if kind == b"IHDR":
            if offset != 8 or width is not None:
                raise CanonicalAssetError("atlas.png has an invalid IHDR position")
            if len(payload) != 13:
                raise CanonicalAssetError("atlas.png has an invalid IHDR")
            width, height, depth, color, compression, filtering, interlace = struct.unpack(
                ">IIBBBBB", payload
            )
            if (
                not 1 <= width <= _MAX_CANVAS * _MAX_FRAMES
                or not 1 <= height <= _MAX_CANVAS
                or (depth, color, compression, filtering, interlace) != (8, 6, 0, 0, 0)
            ):
                raise CanonicalAssetError(
                    "atlas.png must be non-interlaced 8-bit RGBA within bounds"
                )
        elif kind == b"IDAT":
            idat.extend(payload)
            if len(idat) > _MAX_PNG_BYTES:
                raise CanonicalAssetError("atlas.png compressed data exceeds bounds")
        elif kind == b"IEND":
            if size != 0:
                raise CanonicalAssetError("atlas.png has an invalid IEND")
            saw_iend = True
            offset = payload_end + 4
            break
        offset = payload_end + 4
    if not saw_iend or offset != len(data):
        raise CanonicalAssetError("atlas.png must end exactly at IEND")
    if width is None or height is None or not idat:
        raise CanonicalAssetError("atlas.png is missing required RGBA data")
    expected = height * (width * 4 + 1)
    if expected > _MAX_PNG_BYTES:
        raise CanonicalAssetError("atlas.png decoded data exceeds bounds")
    try:
        decompressor = zlib.decompressobj()
        decoded = decompressor.decompress(bytes(idat))
        decoded += decompressor.flush()
    except zlib.error as exc:
        raise CanonicalAssetError("atlas.png image data is corrupt") from exc
    if not decompressor.eof or decompressor.unused_data or decompressor.unconsumed_tail:
        raise CanonicalAssetError("atlas.png compressed stream is incomplete or has trailing data")
    if len(decoded) != expected:
        raise CanonicalAssetError("atlas.png scanline data is truncated")
    row_size = width * 4
    for row in range(height):
        filter_type = decoded[row * (row_size + 1)]
        if filter_type > 4:
            raise CanonicalAssetError(f"atlas.png uses unsupported filter {filter_type}")
    return width, height
