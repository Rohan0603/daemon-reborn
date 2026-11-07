# ORC-186 Canonical Sprite Assets Design

## Intent

Load the schema-versioned artifacts emitted by ORC-185 as a typed, immutable
runtime catalog. The loader is the trust boundary before animation code sees
frame rectangles, durations, clips, or image pixels.

## Goals and non-goals

- Validate `manifest.json`, `atlas.png`, `provenance.json`, and `SHA256SUMS.txt`
  fail-closed under a caller-supplied asset root.
- Enforce schema version 1, bounded dimensions/counts, exact in-root regular
  files, SHA-256 parity, RGBA PNG data, frame geometry, clips, and fallbacks.
- Provide immutable metadata, digest/version cache invalidation, and a Qt GUI
  thread boundary for `QPixmap` creation.
- Adapt validated clip/frame timings to existing `SpriteClip`/`SpriteFrame`
  without changing player behavior.
- Do not rewrite the raw Pixelorama adapter, exporter, player, or asset files.

## Approach

Use a new `assets/canonical.py` module with frozen dataclasses and one
`CanonicalAssetError`. It derives clips from ORC-185 tags when explicit clips
are absent, accepts optional v1 anchors/overlay metadata, and validates every
referenced path against the asset root before reading it. A small in-memory
cache keys entries by schema version plus all verified artifact digests. Qt
pixmaps are constructed only through an explicit GUI-thread method.

## Constraints

Python `>=3.12,<3.13`, PySide6 `>=6.8,<7`, no model-provided paths, no
arbitrary filesystem writes, no new dependency, and no merge or unrelated
issue work. Native Windows display/Qt evidence remains a separate NOT RUN gate
unless available in this checkout.
