"""Generate a legally original 64x64 multi-tag Aseprite import fixture for ORC-166.

Requires Python 3.12+ stdlib only. Output .aseprite is an import candidate,
NOT a Pixelorama .pxo and NOT proof that Pixelorama's CLI works.
Spec: https://github.com/aseprite/aseprite/blob/main/docs/ase-file-specs.md
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import struct
import zlib

WIDTH = HEIGHT = 64
DURATIONS_MS = (100, 160, 120, 200)
TAGS = (("idle", 0, 1), ("blink", 2, 3))
OUTLINE = (25, 33, 60, 255)
BODY = (101, 214, 207, 255)
SHADE = (46, 138, 161, 255)
LIGHT = (193, 248, 227, 255)
EYES = (17, 24, 44, 255)
CLEAR = (0, 0, 0, 0)


def pixels(frame: int) -> bytes:
    """Procedural synthetic ghost/imp placeholder: no borrowed art/assets."""
    grid = [[CLEAR for _ in range(WIDTH)] for _ in range(HEIGHT)]

    def rect(x0: int, y0: int, x1: int, y1: int, color: tuple[int, ...]) -> None:
        for y in range(max(0, y0), min(HEIGHT, y1)):
            for x in range(max(0, x0), min(WIDTH, x1)):
                grid[y][x] = color

    # Two asymmetrical antennae and a broad, readable 64px silhouette.
    rect(16, 12, 23, 27, OUTLINE)
    rect(18, 14, 21, 26, SHADE)
    rect(40, 9, 47, 27, OUTLINE)
    rect(42, 12, 45, 26, SHADE)
    rect(14, 23, 50, 49, OUTLINE)
    rect(18, 19, 47, 52, OUTLINE)
    rect(17, 25, 48, 47, BODY)
    rect(21, 23, 45, 49, BODY)
    rect(25, 48, 31, 54, OUTLINE)
    rect(37, 48, 43, 54, OUTLINE)
    rect(22, 29, 26, 34, LIGHT)
    rect(38, 31, 42, 34, SHADE)
    # Frames 2-3 are blink-tagged; idle frame 1 is visibly displaced.
    blink = frame >= 2
    if blink:
        rect(24, 35, 30, 37, EYES)
        rect(36, 35, 42, 37, EYES)
    else:
        rect(24, 33 + frame, 29, 39 + frame, EYES)
        rect(36, 33 + frame, 41, 39 + frame, EYES)
    rect(30, 41, 35, 43 if frame != 3 else 44, EYES)
    return bytes(component for row in grid for pixel in row for component in pixel)


def string(value: str) -> bytes:
    data = value.encode("utf-8")
    return struct.pack("<H", len(data)) + data


def chunk(kind: int, data: bytes) -> bytes:
    return struct.pack("<IH", len(data) + 6, kind) + data


def render() -> bytes:
    output_frames = []
    for index, duration in enumerate(DURATIONS_MS):
        chunks = []
        if index == 0:
            # Visible/editable image layer, full opacity, normal blending.
            layer = struct.pack("<6HB3x", 3, 0, 0, 0, 0, 0, 255) + string("Original test ghost")
            chunks.append(chunk(0x2004, layer))
            tags = struct.pack("<H8x", len(TAGS))
            for name, begin, end in TAGS:
                tags += struct.pack("<HHBH6x3BB", begin, end, 0, 0, 90, 185, 210, 0)
                tags += string(name)
            chunks.append(chunk(0x2018, tags))
        data = pixels(index)
        cel = struct.pack("<HhhBHh5xHH", 0, 0, 0, 255, 2, 0, WIDTH, HEIGHT)
        chunks.append(chunk(0x2005, cel + zlib.compress(data, level=9)))
        body = b"".join(chunks)
        output_frames.append(struct.pack("<IHHH2xI", 16 + len(body), 0xF1FA, len(chunks), duration, len(chunks)) + body)
    frames = b"".join(output_frames)
    header = struct.pack("<IHHHHHIHII", 128 + len(frames), 0xA5E0, len(DURATIONS_MS), WIDTH, HEIGHT, 32, 1, 100, 0, 0)
    header += struct.pack("<B3xHBBhhHH", 0, 0, 1, 1, 0, 0, 16, 16)
    header = header.ljust(128, b"\0")
    assert len(header) == 128
    return header + frames


def inspect(data: bytes) -> None:
    """Structural check independent of image producer; does not prove importer compatibility."""
    size, magic, nframes, width, height, depth = struct.unpack_from("<I5H", data)
    assert (size, magic, nframes, width, height, depth) == (len(data), 0xA5E0, 4, 64, 64, 32)
    offset = 128
    seen = []
    tags_seen = []
    for duration in DURATIONS_MS:
        frame_len, fmagic, n, got_ms = struct.unpack_from("<IHHH", data, offset)
        assert (fmagic, got_ms) == (0xF1FA, duration)
        pos = offset + 16
        for _ in range(n):
            chunk_len, kind = struct.unpack_from("<IH", data, pos)
            payload = data[pos + 6:pos + chunk_len]
            if kind == 0x2005:
                w, h = struct.unpack_from("<HH", payload, 16)
                assert (w, h) == (64, 64)
                pixels_out = zlib.decompress(payload[20:])
                assert len(pixels_out) == 64 * 64 * 4
                seen.append(hashlib.sha256(pixels_out).hexdigest())
                assert any(pixels_out[i + 3] == 0 for i in range(0, len(pixels_out), 4))
                assert any(pixels_out[i + 3] == 255 for i in range(0, len(pixels_out), 4))
            if kind == 0x2018:
                count = struct.unpack_from("<H", payload)[0]
                pos_tag = 10
                for _ in range(count):
                    begin, end = struct.unpack_from("<HH", payload, pos_tag)
                    text_len = struct.unpack_from("<H", payload, pos_tag + 17)[0]
                    name = payload[pos_tag + 19:pos_tag + 19 + text_len].decode()
                    tags_seen.append((name, begin, end))
                    pos_tag += 19 + text_len
            pos += chunk_len
        assert pos == offset + frame_len
        offset += frame_len
    assert offset == len(data)
    assert tags_seen == list(TAGS), tags_seen
    assert len(seen) == 4 and len(set(seen)) >= 3


def main() -> None:
    output = pathlib.Path(__file__).resolve().parent / "generated"
    output.mkdir(exist_ok=True)
    binary = render()
    inspect(binary)
    filename = output / "original_ghost_64x64.aseprite"
    filename.write_bytes(binary)
    manifest = {
        "provenance": "Generated original synthetic placeholder by this repository script; no imported art",
        "format": "Aseprite RGBA 32-bit import candidate (NOT a native Pixelorama .pxo)",
        "size": [64, 64],
        "durations_ms": list(DURATIONS_MS),
        "tags": [{"name": name, "from_frame_0_based": a, "to_frame_0_based": b} for name, a, b in TAGS],
        "alpha": "Includes fully transparent and fully opaque pixels",
        "image_file_sha256": hashlib.sha256(binary).hexdigest(),
        "pixel_sha256": [hashlib.sha256(pixels(i)).hexdigest() for i in range(4)],
        "foot_anchor": [32, 54],
        "validation": "Aseprite binary structural checks PASS; Pixelorama import/.pxo/export NOT RUN",
    }
    (output / "expected.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print("PASS structural Aseprite fixture", filename, len(binary), manifest["image_file_sha256"])


if __name__ == "__main__":
    main()
