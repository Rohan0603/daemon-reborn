# ORC-259 fail-closed export adapter

Tracking: [ORC-259](https://linear.app/agtorchestrator/issue/ORC-259/w01-run-native-pixelorama-windows-round-trip-for-orc-166) · [ORC-185](https://linear.app/agtorchestrator/issue/ORC-185/a02-implement-pinned-pixelorama-asset-export-and-provenance-pipeline)

The Pixelorama JSON sidecar is an editor/export snapshot, not a Daemon runtime
manifest. `daemon_reborn.assets.adapter.load_runtime_manifest` is a JSON-sidecar
validation boundary: it reads a complete JSON file, validates the dimensions,
frame durations, cel sizes, tag names and frame ranges, converts Pixelorama's
one-based ranges to the manifest's zero-based frame IDs, and preserves those
ranges in an immutable runtime manifest. The caller must
stage and verify both the PNG and JSON outputs, process exit status, and file
completeness before calling this JSON-only function; this module does not infer
or check an atlas path.

Promotion is rejected when:

- the JSON sidecar is missing, unreadable or malformed;
- JSON export was not enabled;
- frames or tags are absent, empty, malformed or out of range;
- a tag name is duplicated;
- any frame is not covered by a tag; or
- a frame has no complete cel at the declared canvas size.

The adapter does not use `export_profile.directory_path` or infer output paths.
Pixelorama process exit status and output-file completeness remain caller
responsibilities; the adapter must be called only after both required files have
been staged. The captured v1.2.4 export shape is covered by the fixture test in
`tests/unit/assets/test_adapter.py`.
