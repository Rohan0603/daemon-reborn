# Daemon Reborn

Daemon Reborn is a clean-slate, privacy-first Windows desktop companion. Project requirements,
architecture, decisions, current work and acceptance evidence are maintained in the [Linear project](https://linear.app/agtorchestrator/project/daemon-reborn-9b03c799740c).

This repository contains the implementation only. The legacy Daemon repository is reference-only;
no legacy code or assets are used here.

## Development setup

Install [uv](https://docs.astral.sh/uv/), then run:

```powershell
uv sync --locked
uv run python -m daemon_reborn --help
uv run pytest -q
uv run ruff check .
```

The project targets Python 3.12. `.python-version`, `requires-python`, and `uv.lock` pin the
interpreter line and resolved dependencies. PySide6 is a runtime dependency; tests and lint tools
are in the `dev` dependency group. Optional speech/model dependencies are intentionally not
installed by the base environment.

## Current scaffold

The `src/daemon_reborn` package establishes boundaries for app orchestration, standard-library-only
domain code, animation, Qt UI, voice, intelligence, memory and integrations. The CLI is a bootstrap
entrypoint; product behavior is implemented through the scoped Linear issues.

PySide6 distribution and packaging obligations remain subject to the project's separate license
review before release.
