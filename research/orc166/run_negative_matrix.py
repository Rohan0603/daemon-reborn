"""Re-run ORC-166 Pixelorama negative fixtures on a targetable Windows host.

This is evidence tooling, NOT a production exporter. It tests the pinned native
.pxo and the repository-owned fail-closed adapter, and writes to a NEW output
directory so committed/stale output cannot make a failed export look successful.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "research" / "orc166" / "native-evidence" / "original_ghost_64x64.pxo"
REPORTED_ARCHIVE_SHA256 = "8CE63C264338B88FD36527F8EDB3B7F6BBA614D92451EFC406EF7CE45B41DA85"
REPORTED_FIXTURE_SHA256 = "6F675C9F6DEFCB01CD8EB3B9E07CC39C2D9F46C5B9E12B592CD4145675299458"


def sha256_file(path: Path) -> str:
    """Hash a file as observed on the executing machine, without trusting a label."""

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def tail(value: bytes | str | None) -> str:
    """TimeoutExpired output is bytes even when subprocess text=True."""

    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")[-2000:]
    return (value or "")[-2000:]


def variant(name: str, mutate, run_root: Path) -> Path:
    destination = run_root / f"{name}.pxo"
    with zipfile.ZipFile(FIXTURE) as source, zipfile.ZipFile(destination, "w") as target:
        for info in source.infolist():
            payload = source.read(info)
            if info.filename == "data.json":
                document = json.loads(payload)
                mutate(document)
                payload = json.dumps(document, separators=(",", ":")).encode()
            target.writestr(info, payload)
    return destination


def run_case(
    name: str, project: Path, *, json_export: bool, executable: Path, run_root: Path
) -> dict[str, object]:
    output = run_root / name / "atlas.png"
    output.parent.mkdir(parents=True, exist_ok=False)
    command = [
        str(executable),
        "--headless",
        "--display-driver",
        "headless",
        "--audio-driver",
        "Dummy",
        "--rendering-method",
        "gl_compatibility",
        "--quit",
        "--",
        "--export",
        "--spritesheet",
    ]
    if json_export:
        command.append("--json")
    command.extend(["--output", str(output), str(project)])
    try:
        completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=15)
        result: dict[str, object] = {
            "returncode": completed.returncode,
            "timed_out": False,
            "stdout_tail": tail(completed.stdout),
            "stderr_tail": tail(completed.stderr),
        }
    except subprocess.TimeoutExpired as exc:
        result = {
            "returncode": None,
            "timed_out": True,
            "stdout_tail": tail(exc.stdout),
            "stderr_tail": tail(exc.stderr),
        }
    json_paths = sorted(output.parent.glob("*.json"))
    result["png_exists"] = output.is_file()
    result["json_files"] = [path.name for path in json_paths]
    result["json_exists"] = bool(json_paths)
    try:
        from daemon_reborn.assets.adapter import ManifestError, load_runtime_manifest

        if len(json_paths) != 1:
            raise ManifestError(f"expected exactly one JSON sidecar, found {len(json_paths)}")
        load_runtime_manifest(json_paths[0])
        result["adapter"] = "accepted"
    except ManifestError as exc:
        result["adapter"] = f"rejected: {type(exc).__name__}: {exc}"

    # Process exit 0 and emitted files are NOT sufficient for promotion.
    result["success_manifest"] = bool(
        result["returncode"] == 0
        and not result["timed_out"]
        and result["png_exists"]
        and result["json_exists"]
        and result["adapter"] == "accepted"
    )
    result["command"] = command
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pixelorama-exe", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, help="Must be new or empty; never overwrite historical evidence")
    args = parser.parse_args()

    executable = args.pixelorama_exe.resolve()
    if not executable.is_file():
        parser.error(f"Pixelorama executable missing: {executable}")
    if not FIXTURE.is_file() or sha256_file(FIXTURE) != REPORTED_FIXTURE_SHA256:
        parser.error("original native .pxo does not match the recorded fixture SHA-256")

    # Only the adapter in the very same checked-out repository may qualify an export.
    sys.path.insert(0, str(ROOT / "src"))
    try:
        from daemon_reborn.assets import adapter
    except ImportError as exc:
        parser.error(f"repository adapter unavailable; merge ORC-259/PR #14 first: {exc}")
    _ = adapter

    if args.output_dir is None:
        run_root = Path(tempfile.mkdtemp(prefix="orc166-negative-"))
    else:
        run_root = args.output_dir.resolve()
        if run_root.exists() and any(run_root.iterdir()):
            parser.error(f"refusing nonempty output directory with possible stale JSON/PNG: {run_root}")
        run_root.mkdir(parents=True, exist_ok=True)

    duplicate = variant(
        "duplicate-tags",
        lambda doc: doc.update({"tags": [dict(doc["tags"][0]), dict(doc["tags"][0])]}),
        run_root,
    )
    missing = variant(
        "missing-tag-coverage",
        lambda doc: doc.update({"tags": [{"color": "ffffffff", "from": 1, "name": "idle", "to": 2}]}),
        run_root,
    )
    results = {
        "historically_reported_archive_sha256_not_reverified": REPORTED_ARCHIVE_SHA256,
        "fixture_sha256_verified": sha256_file(FIXTURE),
        "pixelorama_executable_sha256_verified": sha256_file(executable),
        "output_directory": str(run_root),
        "duplicate_tags": run_case(
            "duplicate-tags-run", duplicate, json_export=True, executable=executable, run_root=run_root
        ),
        "missing_tag_coverage": run_case(
            "missing-tag-run", missing, json_export=True, executable=executable, run_root=run_root
        ),
        "missing_json": run_case(
            "missing-json-run", FIXTURE, json_export=False, executable=executable, run_root=run_root
        ),
    }
    (run_root / "results.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
