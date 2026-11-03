# Daemon Reborn

Daemon Reborn is a clean-slate, privacy-first Windows desktop companion. Project requirements,
architecture, decisions, current work and acceptance evidence are maintained in the [Linear project](https://linear.app/agtorchestrator/project/daemon-reborn-9b03c799740c).

## Project direction

Linear is the source of truth for project planning and decisions. Start with the [project and issue tracker](https://linear.app/agtorchestrator/project/daemon-reborn-9b03c799740c), then use its current documents:

- [Product requirements](https://linear.app/agtorchestrator/document/01-product-requirements-and-scope-prd-869b420eb07b)
- [Architecture blueprint](https://linear.app/agtorchestrator/document/02-architecture-blueprint-and-boundaries-d3a340b5cc98)
- [Agent operating contract](https://linear.app/agtorchestrator/document/06-agent-operating-contract-required-task-lifecycle-c88d55f4572a)
- [Decision register](https://linear.app/agtorchestrator/document/08-decision-register-adrs-approved-and-pending-5951be6efd5e)

Follow the root [AGENTS.md](AGENTS.md) before making changes. It is an entrypoint to Linear, not a separate backlog or policy source.

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

## Run the desktop shell

Start the minimal Windows shell from a development checkout:

```powershell
uv run python -m daemon_reborn
```

The shell shows a small placeholder character and a system-tray menu with Show pet, Hide pet, Settings, and Exit. Use Show/Hide pet to toggle the character, or Exit to shut down. Settings currently opens a placeholder notice. This shell does not start network, language-model, speech, or worker services and requires a Windows system tray.

## Current project scope

The `src/daemon_reborn` package establishes boundaries for app orchestration, standard-library-only
domain code, animation, Qt UI, voice, intelligence, memory and integrations. The CLI is a bootstrap
entrypoint for the current shell; further product behavior is implemented through the scoped Linear
issues.

PySide6 distribution and packaging obligations remain subject to the project's separate license
review before release.
