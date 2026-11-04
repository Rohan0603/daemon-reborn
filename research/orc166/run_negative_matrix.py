"""Run the remaining native Pixelorama negative cases on Windows.

This is evidence tooling for ORC-166, not product code. It copies the pinned
native .pxo, mutates only its data.json tags, runs the pinned executable, and
records process/output/adapter results as JSON.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ADAPTER_ROOT = Path(r"C:\Users\ponna\.codex\worktrees\orc-259-adapter\src")
FIXTURE = ROOT / "research" / "orc166" / "native-evidence" / "original_ghost_64x64.pxo"
EXE = Path(r"C:\Users\ponna\AppData\Local\Temp\orc166-pixelorama-20261104\app\Pixelorama-Windows-64bit\Pixelorama.exe")


def variant(name: str, mutate) -> Path:
    destination = RUN_ROOT / f"{name}.pxo"
    with zipfile.ZipFile(FIXTURE) as source, zipfile.ZipFile(destination, "w") as target:
        for info in source.infolist():
            payload = source.read(info)
            if info.filename == "data.json":
                document = json.loads(payload)
                mutate(document)
                payload = json.dumps(document, separators=(",", ":")).encode()
            target.writestr(info, payload)
    return destination


def run_case(name: str, project: Path, *, json_export: bool) -> dict[str, object]:
    output = RUN_ROOT / name / "atlas.png"
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [
        str(EXE),
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
        completed = subprocess.run(command, capture_output=True, text=True, timeout=15)
        result: dict[str, object] = {"returncode": completed.returncode, "timed_out": False}
        result["stdout_tail"] = completed.stdout[-2000:]
        result["stderr_tail"] = completed.stderr[-2000:]
    except subprocess.TimeoutExpired as exc:
        result = {
            "returncode": None,
            "timed_out": True,
            "stdout_tail": (exc.stdout or "")[-2000:],
            "stderr_tail": (exc.stderr or "")[-2000:],
        }
    json_paths = sorted(output.parent.glob("*.json"))
    result["png_exists"] = output.is_file()
    result["json_files"] = [path.name for path in json_paths]
    result["json_exists"] = bool(json_paths)
    result["success_manifest"] = bool(result["returncode"] == 0 and result["png_exists"] and result["json_exists"])
    try:
        sys.path.insert(0, str(ADAPTER_ROOT))
        from daemon_reborn.assets.adapter import load_runtime_manifest

        if not json_paths:
            raise FileNotFoundError("no JSON sidecar")
        load_runtime_manifest(json_paths[0])
        result["adapter"] = "accepted"
    except Exception as exc:  # evidence must preserve the exact rejection
        result["adapter"] = f"rejected: {type(exc).__name__}: {exc}"
    return result


RUN_ROOT = ROOT / "research" / "orc166" / "native-evidence" / "negative-matrix-20261105"
RUN_ROOT.mkdir(parents=True, exist_ok=True)
duplicate = variant("duplicate-tags", lambda doc: doc.update({"tags": [dict(doc["tags"][0]), dict(doc["tags"][0])]}))
missing = variant("missing-tag-coverage", lambda doc: doc.update({"tags": [{"color": "ffffffff", "from": 1, "name": "idle", "to": 2}]}))
results = {
    "pixelorama_archive_sha256": "8CE63C264338B88FD36527F8EDB3B7F6BBA614D92451EFC406EF7CE45B41DA85",
    "fixture_sha256": "6F675C9F6DEFCB01CD8EB3B9E07CC39C2D9F46C5B9E12B592CD4145675299458",
    "duplicate_tags": run_case("duplicate-tags-run", duplicate, json_export=True),
    "missing_tag_coverage": run_case("missing-tag-run", missing, json_export=True),
    "missing_json": run_case("missing-json-run", FIXTURE, json_export=False),
}
(RUN_ROOT / "results.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
print(json.dumps(results, indent=2))
