$ErrorActionPreference = "Stop"

uv sync --locked
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

uv run pytest -q
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

uv run ruff check .
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

uv run ruff format --check .
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

uv run mypy
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

uv run python -m daemon_reborn --help
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
