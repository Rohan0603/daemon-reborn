# ORC-166 — original Pixelorama qualification fixture (research, not production)

Status: **STRUCTURAL GENERATOR PASS; PIXELORAMA APPLICATION TEST NOT RUN**.

## Evidence baseline

- Generator: python research/orc166/generate_original_fixture.py (Python 3.12+ standard library).
- Local structural run: Debian 13, CPython 3.13.5. Output generated/original_ghost_64x64.aseprite is 1,152 bytes; SHA-256 05eaf29872159428fadb1bfbc9b8e0008037d32bee4df4789ec3cb3065888bad. The generator independently validates 4 RGBA 64×64 frames, per-frame durations [100, 160, 120, 200] ms, two tags idle (frames 0–1) and blink (frames 2–3), and transparent/opaque pixels.
- This script makes an **Aseprite import candidate**, not a Pixelorama-native editable .pxo. It creates original synthetic art. **It does not qualify the Pixelorama importer or CLI.**
- Sources: [Aseprite file format specification](https://github.com/aseprite/aseprite/blob/main/docs/ase-file-specs.md), [Pixelorama import support](https://pixelorama.org/user_manual/Import/), [Pixelorama .pxo format](https://pixelorama.org/concepts/project/), [Pixelorama CLI](https://pixelorama.org/user_manual/cli/), [Pixelorama v1.2.4](https://github.com/Orama-Interactive/Pixelorama/releases/tag/v1.2.4).
- Existing ORC-166 Windows evidence: Pixelorama v1.2.4 ZIP SHA-256 8CE63C264338B88FD36527F8EDB3B7F6BBA614D92451EFC406EF7CE45B41DA85; one official fixture had identical repeated PNG bytes, two other official fixtures crashed 0xC0000005, and one successful export required process termination. Do not classify these failures as passing.

## Required Windows round-trip (NOT RUN)

1. On disposable Windows 10/11, pin Pixelorama v1.2.4 official artifact, verify ZIP SHA and binary help/version; record exact Windows build, binary path/hash.
2. Run py -3.12 research\orc166\generate_original_fixture.py and compare emitted SHA-256; if mismatch, stop and investigate.
3. Open generated .aseprite **with Pixelorama**; inspect 4 frames, named tags, differing durations, 64×64 canvas and alpha. Save from Pixelorama as original_ghost_64x64.pxo with blended images included. Attach original editable .pxo and SHA-256. If import fails/changes semantics, block.
4. Against the pinned binary, test exact CLI option ordering, for example: & $Pixelorama --headless --quit -- --export --spritesheet --json --output "$Output\run1\atlas.png" "$Fixture\original_ghost_64x64.pxo". Repeat in run2. Record stdout/stderr, return codes and any timeout/manual termination. **Killed/timeout process is FAILURE by default even if output exists**, until an explicit reviewed policy governs it.
5. Compare decoded PNG pixels, RGBA/alpha, atlas dimensions/rect mapping and file hashes. Canonicalize **only documented absolute output-directory differences** in JSON; fail on any other semantic difference. Compare tags/frame IDs/durations/order to generated/expected.json. Retain raw and normalized JSON.
6. Negative cases: corrupt/truncated .pxo, missing/unreadable input, unwritable output, unsupported scale/option, duplicate or missing tag, missing JSON. Each must refuse a success manifest and avoid promoting partial files.
7. Publish exact observed Windows versions, exit codes, timing, hashes and errors; propose allowlisted JSON-to-runtime adapter contract under ORC-185. Independent review and owner approval are required for any timeout handling exception.

## Fail-closed acceptance (proposal, not approval)

Only promote from staging after accepted process exit, complete PNG+JSON, exact expected frame/tag counts, positive frame durations, valid atlas rectangles and alpha, provenance/license, stable canonical repeat agreement and safe real paths. Unknown structural fields, symlink/junction output escapes, duplicate tags, malformed snapshots and partial writes are errors. Never assume upstream JSON export_profile.directory_path is a stable runtime manifest.

This is a research fixture and protocol, **not product implementation**. Leave PR draft and ORC-166 In Review until Pixelorama Windows application round-trip, negative tests, and independent acceptance. ORC-184/185 stay blocked.
