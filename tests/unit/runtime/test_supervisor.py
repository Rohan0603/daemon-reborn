"""Failure-path tests for worker supervision."""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from daemon_reborn.runtime.supervisor import (
    RestartPolicy,
    SupervisorState,
    WorkerSpec,
    WorkerSupervisor,
)
from daemon_reborn.runtime.windows_job import WindowsJobObject


def wait_for_state(
    supervisor: WorkerSupervisor,
    expected: SupervisorState,
    timeout: float = 3.0,
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if supervisor.snapshot().state is expected:
            return
        time.sleep(0.01)
    pytest.fail(f"supervisor did not reach {expected}; snapshot={supervisor.snapshot()!r}")


def test_worker_spec_requires_an_executable() -> None:
    with pytest.raises(ValueError, match="command"):
        WorkerSpec(command=())


def test_diagnostic_mode_disables_external_capabilities() -> None:
    spec = WorkerSpec(
        command=(sys.executable, "-c", "pass"),
        environment={"WORKER_API_TOKEN": "explicit-secret"},
        diagnostic=True,
    )

    environment = spec.build_environment(
        {
            "PATH": os.environ.get("PATH", ""),
            "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
            "OPENAI_API_KEY": "inherited-secret",
        }
    )

    assert environment["PATH"]
    assert environment["DAEMON_DIAGNOSTIC"] == "1"
    assert environment["DAEMON_DISABLE_LLM"] == "1"
    assert environment["DAEMON_DISABLE_TTS"] == "1"
    assert environment["DAEMON_DISABLE_SENSORS"] == "1"
    assert "OPENAI_API_KEY" not in environment
    assert "WORKER_API_TOKEN" not in environment


def test_supervisor_restarts_crashing_worker_only_within_policy() -> None:
    supervisor = WorkerSupervisor(
        WorkerSpec(command=(sys.executable, "-c", "raise SystemExit(7)")),
        restart_policy=RestartPolicy(max_restarts=2, initial_delay=0.01, max_delay=0.02),
        poll_interval=0.01,
    )

    supervisor.start()
    wait_for_state(supervisor, SupervisorState.FAILED)
    snapshot = supervisor.snapshot()

    assert snapshot.restart_count == 2
    assert snapshot.last_exit_code == 7
    assert supervisor.wait_stopped(timeout=1.0)


def test_stop_is_nonblocking_and_reaps_worker() -> None:
    supervisor = WorkerSupervisor(
        WorkerSpec(command=(sys.executable, "-c", "import time; time.sleep(30)")),
        restart_policy=RestartPolicy(max_restarts=0),
        shutdown_timeout=0.05,
        poll_interval=0.01,
    )
    supervisor.start()
    wait_for_state(supervisor, SupervisorState.RUNNING)

    before = time.monotonic()
    supervisor.request_stop()
    elapsed = time.monotonic() - before

    assert elapsed < 0.1
    assert supervisor.wait_stopped(timeout=3.0)
    assert supervisor.snapshot().state is SupervisorState.STOPPED


def test_graceful_stop_hook_allows_worker_to_exit_cleanly(tmp_path: Path) -> None:
    stop_file = tmp_path / "stop"
    script = (
        f"from pathlib import Path; import time; p=Path({str(stop_file)!r}); "
        + "exec('while not p.exists(): time.sleep(0.01)')"
    )
    command = (
        sys.executable,
        "-c",
        script,
    )

    def request_stop(_pid: int) -> None:
        stop_file.write_text("stop")

    supervisor = WorkerSupervisor(
        WorkerSpec(command=command),
        restart_policy=RestartPolicy(max_restarts=0),
        request_graceful_stop=request_stop,
        poll_interval=0.01,
    )

    supervisor.start()
    wait_for_state(supervisor, SupervisorState.RUNNING)
    supervisor.request_stop()

    assert supervisor.wait_stopped(timeout=3.0)
    snapshot = supervisor.snapshot()
    assert snapshot.state is SupervisorState.STOPPED
    assert snapshot.last_exit_code == 0


def test_graceful_stop_hook_failure_does_not_orphan_worker(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def fail_stop(_pid: int) -> None:
        raise KeyError("private-hook-detail")

    supervisor = WorkerSupervisor(
        WorkerSpec(command=(sys.executable, "-c", "import time; time.sleep(30)")),
        restart_policy=RestartPolicy(max_restarts=0),
        shutdown_timeout=0.01,
        poll_interval=0.01,
        request_graceful_stop=fail_stop,
    )
    supervisor.start()
    wait_for_state(supervisor, SupervisorState.RUNNING)

    supervisor.request_stop()

    assert supervisor.wait_stopped(timeout=3.0)
    assert supervisor.snapshot().state is SupervisorState.STOPPED
    assert "private-hook-detail" not in caplog.text
    assert "worker_graceful_stop_failed" in caplog.text


def test_hung_graceful_stop_hook_does_not_exceed_shutdown_deadline(
    caplog: pytest.LogCaptureFixture,
) -> None:
    entered = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def hang_stop(_pid: int) -> None:
        entered.set()
        release.wait()
        finished.set()

    supervisor = WorkerSupervisor(
        WorkerSpec(command=(sys.executable, "-c", "import time; time.sleep(30)")),
        restart_policy=RestartPolicy(max_restarts=0),
        shutdown_timeout=0.05,
        poll_interval=0.01,
        request_graceful_stop=hang_stop,
    )
    supervisor.start()
    wait_for_state(supervisor, SupervisorState.RUNNING)

    before = time.monotonic()
    supervisor.request_stop()

    assert entered.wait(timeout=1.0)
    assert supervisor.wait_stopped(timeout=3.0)
    assert time.monotonic() - before < 1.0
    assert supervisor.snapshot().state is SupervisorState.STOPPED
    assert "worker_graceful_stop_timed_out" in caplog.text
    with pytest.raises(RuntimeError, match="graceful stop hook"):
        supervisor.start()
    release.set()
    assert finished.wait(timeout=1.0)


def test_crash_diagnostics_do_not_capture_worker_output(caplog: pytest.LogCaptureFixture) -> None:
    secret = "private-worker-output"
    supervisor = WorkerSupervisor(
        WorkerSpec(
            command=(
                sys.executable,
                "-c",
                f"import sys; print({secret!r}, file=sys.stderr); sys.exit(3)",
            )
        ),
        restart_policy=RestartPolicy(max_restarts=0),
        poll_interval=0.01,
    )

    supervisor.start()
    wait_for_state(supervisor, SupervisorState.FAILED)

    assert secret not in caplog.text
    assert "worker_exited" in caplog.text


@pytest.mark.skipif(os.name != "nt", reason="Windows process tree ownership")
def test_windows_worker_is_suspended_until_job_assignment(tmp_path: Path) -> None:
    marker = tmp_path / "started"
    process = subprocess.Popen(
        [sys.executable, "-c", f"from pathlib import Path; Path({str(marker)!r}).touch()"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | 0x00000004,
    )
    job = WindowsJobObject(process)
    try:
        assert not marker.exists(), "worker executed before job assignment completed"
        WindowsJobObject.resume_suspended_process(process.pid)
        deadline = time.monotonic() + 3.0
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert marker.exists(), "worker did not resume after job assignment"
    finally:
        job.close()
        process.wait(timeout=3.0)


@pytest.mark.skipif(os.name != "nt", reason="Windows process tree ownership")
def test_crashed_worker_does_not_leave_a_child_process(tmp_path: Path) -> None:
    pid_file = tmp_path / "grandchild.pid"
    script = (
        "import subprocess, sys; "
        f"child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']); "
        f"open({str(pid_file)!r}, 'w').write(str(child.pid)); sys.exit(7)"
    )
    supervisor = WorkerSupervisor(
        WorkerSpec(command=(sys.executable, "-c", script)),
        restart_policy=RestartPolicy(max_restarts=0),
        poll_interval=0.01,
    )

    supervisor.start()
    deadline = time.monotonic() + 3.0
    while not pid_file.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert pid_file.exists(), "worker did not create its child PID file"
    child_pid = int(pid_file.read_text())
    wait_for_state(supervisor, SupervisorState.FAILED)

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    kernel32.WaitForSingleObject.restype = ctypes.c_ulong
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    process_handle = kernel32.OpenProcess(0x00100000 | 0x00001000, False, child_pid)
    if process_handle:
        try:
            assert kernel32.WaitForSingleObject(process_handle, 3000) == 0, (
                "child process is still running after worker crash cleanup"
            )
        finally:
            kernel32.CloseHandle(process_handle)
