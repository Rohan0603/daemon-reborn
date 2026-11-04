# ORC-166 native Pixelorama round-trip evidence

Date: 2026-11-04
Host: Windows 11 build 26200
Pixelorama: v1.2.4-stable, official Windows 64-bit archive
Archive SHA-256: `8CE63C264338B88FD36527F8EDB3B7F6BBA614D92451EFC406EF7CE45B41DA85`

## Positive path

The original synthetic 64×64 Aseprite fixture was opened in Pixelorama and saved as a native editable `.pxo` with blended images included.

- Native `.pxo` SHA-256: `6F675C9F6DEFCB01CD8EB3B9E07CC39C2D9F46C5B9E12B592CD4145675299458`
- Two independent headless exports exited `0` without timeout.
- Both PNGs are 256×64, RGBA 8-bit, and share SHA-256 `B5979C701DF2DA389D0C0CCB7246E518C4A2BC9632DB67A0E88ABD0566F497BF`.
- Export JSON contains four frames with durations `0.1`, `0.16`, `0.12`, `0.2` seconds.
- Export tags are `idle` frames 1–2 and `blink` frames 3–4.
- JSON differs between runs only in `export_profile.directory_path`; the output directories were intentionally different.

Observed export command shape:

```text
Pixelorama.exe --headless --display-driver headless --audio-driver Dummy --rendering-method gl_compatibility --quit -- --export --spritesheet --json --output <run>\atlas.png <fixture>.pxo
```

## Negative-path results

- Truncated `.pxo`: process exited `0` but emitted an `untitled.json` sidecar; this is a fail-closed defect requiring adapter validation.
- Missing `.pxo`: process exceeded the 15-second harness timeout; no success may be promoted.
- Unsupported option: process exited `0` while logging `Unknown option`; wrapper must inspect output and reject success.
- Unwritable-output coverage remains NOT RUN.

Conclusion: native import/save and deterministic positive export are demonstrated, but ORC-166 remains In Review until the negative-path failure policy and runtime-manifest adapter are independently accepted.
