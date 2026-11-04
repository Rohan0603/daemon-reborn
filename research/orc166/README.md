# ORC-166 — original Pixelorama qualification fixture (research, not production)

Status: **STRUCTURAL GENERATOR PASS; NATIVE POSITIVE ROUND-TRIP PASS; NEGATIVE/POLICY GATES OPEN**.

## Evidence baseline

- Generator: python research/orc166/generate_original_fixture.py (Python 3.12+ standard library).
- Local structural run: Debian 13, CPython 3.13.5. Output generated/original_ghost_64x64.aseprite is 1,152 bytes; SHA-256 05eaf29872159428fadb1bfbc9b8e0008037d32bee4df4789ec3cb3065888bad. The generator independently validates 4 RGBA 64×64 frames, per-frame durations [100, 160, 120, 200] ms, two tags idle (frames 0–1) and blink (frames 2–3), and transparent/opaque pixels.
- This script makes an **Aseprite import candidate**, not a Pixelorama-native editable .pxo. It creates original synthetic art. **It does not qualify the Pixelorama importer or CLI.**
- Sources: [Aseprite file format specification](https://github.com/aseprite/aseprite/blob/main/docs/ase-file-specs.md), [Pixelorama import support](https://pixelorama.org/user_manual/Import/), [Pixelorama .pxo format](https://pixelorama.org/concepts/project/), [Pixelorama CLI](https://pixelorama.org/user_manual/cli/), [Pixelorama v1.2.4](https://github.com/Orama-Interactive/Pixelorama/releases/tag/v1.2.4).
- Existing ORC-166 Windows evidence: Pixelorama v1.2.4 ZIP SHA-256 8CE63C264338B88FD36527F8EDB3B7F6BBA614D92451EFC406EF7CE45B41DA85; one official fixture had identical repeated PNG bytes, two other official fixtures crashed 0xC0000005, and one successful export required process termination. Do not classify these failures as passing.
- Native positive evidence (2026-11-04) is recorded in native-roundtrip-evidence.md: Windows 11 build 26200, Pixelorama v1.2.4, native editable .pxo SHA-256 6F675C9F6DEFCB01CD8EB3B9E07CC39C2D9F46C5B9E12B592CD4145675299458, and two deterministic 256×64 RGBA exports sharing SHA-256 B5979C701DF2DA389D0C0CCB7246E518C4A2BC9632DB67A0E88ABD0566F497BF. The export manifest preserved four durations and the idle/blink tags; only the documented output-directory field differed.

## Required Windows round-trip and negative matrix

1. The pinned Windows artifact, exact host/build, binary version, and archive hash are recorded in native-roundtrip-evidence.md.
2. The generated .aseprite was opened with Pixelorama; four frames, named tags, differing durations, 64×64 canvas and alpha were inspected. Pixelorama saved original_ghost_64x64.pxo with blended images included; the editable artifact and hash are attached.
3. Against the pinned binary, two exact CLI exports completed with exit code 0 and no timeout. Record stdout/stderr, return codes and any timeout/manual termination. **Killed/timeout process is FAILURE by default even if output exists**, until an explicit reviewed policy governs it.
4. Compare decoded PNG pixels, RGBA/alpha, atlas dimensions/rect mapping and file hashes. Canonicalize **only documented absolute output-directory differences** in JSON; fail on any other semantic difference. Compare tags/frame IDs/durations/order to generated/expected.json. Retain raw and normalized JSON.
5. Negative cases are exercised in `native-evidence/negative-matrix-20261105/results.json`. Duplicate tags and missing tag coverage both exited 0 and emitted files, but the adapter rejected them (`duplicate tag: idle` and `frames not covered by tags: [3, 4]`). Missing JSON exited 0 with a PNG but no JSON sidecar, and the staged-output gate rejected it. Earlier observations remain: truncated `.pxo` exited 0 with an `untitled.json` sidecar; missing `.pxo` exceeded the 15-second harness timeout; unsupported option exited 0 while logging `Unknown option`; protected unwritable output exited 0 without required files. Each case refuses promotion when the caller requires complete outputs plus adapter validation.
6. Publish exact observed Windows versions, exit codes, timing, hashes and errors; propose allowlisted JSON-to-runtime adapter contract under ORC-185. Independent review and owner approval are required for any timeout handling exception.

## Fail-closed acceptance (proposal, not approval)

Only promote from staging after accepted process exit, complete PNG+JSON, exact expected frame/tag counts, positive frame durations, valid atlas rectangles and alpha, provenance/license, stable canonical repeat agreement and safe real paths. Unknown structural fields, symlink/junction output escapes, duplicate tags, malformed snapshots and partial writes are errors. Never assume upstream JSON export_profile.directory_path is a stable runtime manifest.

This is a research fixture and protocol, **not product implementation**. Leave PR draft and ORC-166 In Review until independent acceptance of the reconciled evidence and fail-closed policy. ORC-184/185 stay blocked until that review gate is resolved.
