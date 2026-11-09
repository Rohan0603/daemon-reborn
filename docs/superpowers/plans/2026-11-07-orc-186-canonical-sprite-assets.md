# ORC-186 Canonical Sprite Assets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a bounded schema v1 canonical sprite loader, validator, cache, and Qt-thread pixmap boundary on top of ORC-185 artifacts.

**Architecture:** Keep `assets/adapter.py` as the raw Pixelorama snapshot adapter. Add `assets/canonical.py` with frozen typed metadata, strict root/path and checksum validation, PNG/frame/clip validation, a digest-keyed cache, and player adaptation.

**Tech Stack:** Python 3.12, PySide6 6.8+, pytest, Ruff, mypy, setuptools.

**Spec:** `docs/superpowers/specs/2026-11-07-orc-186-canonical-sprite-assets-design.md`

## Global Constraints

- Canonical schema version is exactly `1`.
- Asset paths are exact filenames under the caller-supplied root; traversal, symlink/reparse components, and outside-root resolution fail closed.
- Metadata is immutable; errors use one actionable exception type.
- QPixmap construction is GUI-thread-only; raw adapter and SpritePlayer semantics remain unchanged.
- Bounds must reject oversized dimensions, frame counts, clip counts, and file reads before large allocations.

## Review Focus

- Tampered or missing digest/provenance/checksum entries: canonical error names the artifact and expected/actual digest.
- Symlink/reparse and traversal paths: no read escapes the asset root.
- Malformed PNG and oversized dimensions: reject before unbounded decompression/allocation.
- Duplicate/overlapping/out-of-bounds frames and clips: reject deterministically.
- Fallback chains and cache keys: missing idle/cycles fail; changed verified digests produce a new object.

### Task 1: RED contract tests

**Files:**
- Create: `tests/unit/assets/test_canonical.py`

- [ ] Add a valid ORC-185-shaped fixture and tests for immutable metadata, checksum/provenance parity, player adaptation, rejection cases above, cache invalidation, and GUI-thread pixmap construction.
- [ ] Run the targeted file and record the expected missing-module failures.

### Task 2: Canonical typed loader and validator

**Files:**
- Create: `src/daemon_reborn/assets/canonical.py`
- Modify: `src/daemon_reborn/assets/__init__.py`

- [ ] Implement `CanonicalAssetError`, frozen metadata types, bounded JSON/checksum parsing, root/path checks, PNG inspection, schema v1/frame/clip/fallback validation, and `load_canonical_assets(root)`.
- [ ] Implement `CanonicalAssetPack.to_player_clips()` using existing `SpriteClip`/`SpriteFrame` units.
- [ ] Run targeted tests.

### Task 3: Digest cache and Qt boundary

**Files:**
- Modify: `src/daemon_reborn/assets/canonical.py`
- Modify: `tests/unit/assets/test_canonical.py`

- [ ] Implement `CanonicalAssetCache` keyed by schema version and verified artifact digests; add GUI-thread-only `QPixmap` construction from bounded `QImage` data.
- [ ] Run targeted tests, then full pytest, Ruff, mypy, build, and `git diff --check`.
