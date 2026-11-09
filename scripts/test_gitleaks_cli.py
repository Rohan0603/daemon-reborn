"""Exercise the real Gitleaks CLI against a synthetic, non-provider secret."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path


def fixture_text() -> str:
    prefix = "".join(
        chr(code)
        for code in (
            115,
            121,
            110,
            116,
            104,
            101,
            116,
            105,
            99,
            45,
            115,
            101,
            99,
            114,
            101,
            116,
            45,
        )
    )
    return prefix + "".join(format(index % 16, "x") for index in range(32))


def run(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args), cwd=cwd, check=False, capture_output=True, text=True
    )


def main() -> int:
    gitleaks = shutil.which("gitleaks")
    if not gitleaks:
        raise SystemExit("gitleaks CLI is required")

    with tempfile.TemporaryDirectory() as directory:
        repo = Path(directory)
        for args in (("init", "-b", "main"),):
            result = run("git", *args, cwd=repo)
            if result.returncode:
                raise SystemExit(result.stderr)
        for args in (
            ("config", "user.name", "Secret Scan Test"),
            ("config", "user.email", "secret-scan@example.invalid"),
        ):
            result = run("git", *args, cwd=repo)
            if result.returncode:
                raise SystemExit(result.stderr)

        fixture = fixture_text()
        (repo / "synthetic.txt").write_text(
            f"synthetic provider-shaped value: {fixture}\n",
            encoding="utf-8",
        )
        config = repo / ".gitleaks.toml"
        config.write_text(
            "title = 'Synthetic secret test'\n"
            "[[rules]]\n"
            "id = 'synthetic-secret'\n"
            "description = 'Synthetic secret used only for scanner regression testing'\n"
            "regex = '''synthetic-secret-[0-9a-f]{32}'''\n"
            "secretGroup = 0\n",
            encoding="utf-8",
        )
        run("git", "add", "synthetic.txt", cwd=repo)
        commit = run("git", "commit", "-m", "synthetic secret fixture", cwd=repo)
        if commit.returncode:
            raise SystemExit(commit.stderr)

        result = run(
            gitleaks,
            "git",
            "--redact",
            "--no-banner",
            "--exit-code",
            "1",
            f"--config={config}",
            "--log-opts=--all",
            ".",
            cwd=repo,
        )
        if result.returncode != 1:
            raise SystemExit(
                f"expected Gitleaks to reject the synthetic secret, got {result.returncode}"
            )
        if fixture in result.stdout or fixture in result.stderr:
            raise SystemExit("Gitleaks output was not redacted")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
