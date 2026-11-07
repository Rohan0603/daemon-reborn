# ORC-185 Pixelorama export pipeline

The production entry point is `daemon-reborn-export-assets`. It runs the
Pixelorama v1.2.4 CLI in headless mode, stages `atlas.png` and `atlas.json` in
a new temporary directory, converts native frame-duration multipliers using
the declared FPS, validates the decoded RGBA atlas and complete non-overlapping
tags, writes canonical `manifest.json` and `provenance.json`, and promotes the
directory only after all checks pass.

Example on Windows (the executable path is intentionally supplied by the
caller and is never hard-coded):

```powershell
uv run daemon-reborn-export-assets `
  --source assets/placeholder/placeholder.pxo `
  --output-dir build/assets/placeholder `
  --source-license CC0-1.0 `
  --executable 'C:\Users\<user>\AppData\Roaming\Orama Interactive\Pixelorama\Pixelorama.exe' `
  --expected-version v1.2.4-stable `
  --fps 10 `
  --timeout-seconds 60
```

The generated `SHA256SUMS.txt` covers the promoted PNG, canonical manifest and
provenance metadata; the checksum file itself is not a self-referential entry.
A failed export leaves an existing published directory unchanged.

Pixelorama's user options must precede the project path after the `--` separator.
The v1.2.4 CLI writes its JSON sidecar using the source project's stem (for
example, `placeholder.json`), so the runner normalizes that single sidecar to
`atlas.json` before validation and promotion.

The automated tests use a local fake exporter to exercise process and output
failure paths without claiming a native Pixelorama run. Native Windows
re-export parity on this worktree, final authored character art, and reviewer
acceptance remain external gates.
