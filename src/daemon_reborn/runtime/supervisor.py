"""Non-blocking supervision for one external worker process tree."""

from __future__ import annotations

import logging
import math
import os
import signal
import subprocess
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Protocol

logger = logging.getLogger(__name__)


class _TreeGuard(Protocol):
    def close(self) -> None: ...


class SupervisorState(StrEnum):
    """Public lifecycle state for a supervised worker."""

    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    BACKOFF = "backoff"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class RestartPolicy:
    """Bounded exponential restart policy for unexpected exits."""

    max_restarts: int = 3
    initial_delay: float = 0.25
    max_delay: float = 5.0

    def __post_init__(self) -> None:
        if isinstance(self.max_restarts, bool) or self.max_restarts < 0:
            raise ValueError("max_restarts must be a non-negative integer")
        if not isinstance(self.max_restarts, int):
            raise TypeError("max_restarts must be an integer")
        if not math.isfinite(self.initial_delay) or self.initial_delay < 0:
            raise ValueError("initial_delay must be finite and non-negative")
        if not math.isfinite(self.max_delay) or self.max_delay < self.initial_delay:
            raise ValueError("max_delay must be finite and at least initial_delay")

    def delay_for(self, restart_number: int) -> float:
        """Return bounded exponential backoff for a one-based restart number."""

        delay = self.initial_delay * (2.0 ** max(0, restart_number - 1))
        return min(delay, self.max_delay)


@dataclass(frozen=True, slots=True)
class WorkerSpec:
    """Command and isolated launch settings for a worker."""

    command: tuple[str, ...]
    cwd: Path | None = None
    environment: Mapping[str, str] = field(default_factory=dict)
    diagnostic: bool = False

    def __post_init__(self) -> None:
        if not self.command or any(not isinstance(part, str) or not part for part in self.command):
            raise ValueError("command must contain a non-empty executable and arguments")
        if not isinstance(self.diagnostic, bool):
            raise TypeError("diagnostic must be a bool")
        if any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in self.environment.items()
        ):
            raise TypeError("environment keys and values must be strings")
        object.__setattr__(self, "command", tuple(self.command))
        object.__setattr__(self, "environment", MappingProxyType(dict(self.environment)))

    def build_environment(self, base: Mapping[str, str] | None = None) -> dict[str, str]:
        """Build a private child environment, disabling external capabilities in diagnostics."""

        environment = dict(os.environ if base is None else base)
        environment.update(self.environment)
        if self.diagnostic:
            environment.update(
                {
                    "DAEMON_DIAGNOSTIC": "1",
                    "DAEMON_DISABLE_LLM": "1",
                    "DAEMON_DISABLE_TTS": "1",
                    "DAEMON_DISABLE_SENSORS": "1",
                }
            )
        return environment


@dataclass(frozen=True, slots=True)
class SupervisorSnapshot:
    """Immutable status safe to poll from the UI thread."""

    state: SupervisorState
    pid: int | None
    restart_count: int
    last_exit_code: int | None
    last_error: str | None
    changed_at: float


class WorkerSupervisor:
    """Own one worker on a background thread; public controls never wait for it."""

    def __init__(
        self,
        spec: WorkerSpec,
        *,
        restart_policy: RestartPolicy | None = None,
        shutdown_timeout: float = 2.0,
        poll_interval: float = 0.05,
        request_graceful_stop: Callable[[int], None] | None = None,
    ) -> None:
        if not math.isfinite(shutdown_timeout) or shutdown_timeout < 0:
            raise ValueError("shutdown_timeout must be finite and non-negative")
        if not math.isfinite(poll_interval) or poll_interval <= 0:
            raise ValueError("poll_interval must be finite and positive")
        self._spec = spec
        self._restart_policy = restart_policy or RestartPolicy()
        self._shutdown_timeout = shutdown_timeout
        self._poll_interval = poll_interval
        self._request_graceful_stop = request_graceful_stop
        self._lock = threading.Lock()
        self._stop_requested = threading.Event()
        self._thread: threading.Thread | None = None
        self._state = SupervisorState.STOPPED
        self._pid: int | None = None
        self._restart_count = 0
        self._last_exit_code: int | None = None
        self._last_error: str | None = None
        self._changed_at = time.monotonic()

    def snapshot(self) -> SupervisorSnapshot:
        """Return an immutable thread-safe view of lifecycle state."""

        with self._lock:
            return SupervisorSnapshot(
                state=self._state,
                pid=self._pid,
                restart_count=self._restart_count,
                last_exit_code=self._last_exit_code,
                last_error=self._last_error,
                changed_at=self._changed_at,
            )

    def start(self) -> None:
        """Start supervision on a daemon thread and return immediately."""

        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                raise RuntimeError("worker supervision is already active")
            self._stop_requested.clear()
            self._restart_count = 0
            self._last_exit_code = None
            self._last_error = None
            self._set_state_locked(SupervisorState.STARTING)
            self._thread = threading.Thread(target=self._run, name="worker-supervisor", daemon=True)
            self._thread.start()

    def request_stop(self) -> None:
        """Request shutdown without blocking the caller."""

        self._stop_requested.set()
        with self._lock:
            if self._state in {
                SupervisorState.STARTING,
                SupervisorState.RUNNING,
                SupervisorState.BACKOFF,
            }:
                self._set_state_locked(SupervisorState.STOPPING)

    def wait_stopped(self, timeout: float | None = None) -> bool:
        """Wait for the supervisor thread; intended for shutdown and tests, not UI callbacks."""

        with self._lock:
            thread = self._thread
        if thread is None:
            return True
        thread.join(timeout)
        return not thread.is_alive()

    def _run(self) -> None:
        while not self._stop_requested.is_set():
            process: subprocess.Popen[bytes] | None = None
            tree_guard: _TreeGuard | None = None
            try:
                process = subprocess.Popen(
                    self._spec.command,
                    cwd=self._spec.cwd,
                    env=self._spec.build_environment(),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    close_fds=True,
                    start_new_session=os.name != "nt",
                    creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0),
                )
                if os.name == "nt":
                    from daemon_reborn.runtime.windows_job import WindowsJobObject

                    tree_guard = WindowsJobObject(process)
                with self._lock:
                    self._pid = process.pid
                    if not self._stop_requested.is_set():
                        self._set_state_locked(SupervisorState.RUNNING)

                while process.poll() is None and not self._stop_requested.wait(self._poll_interval):
                    pass

                if self._stop_requested.is_set():
                    with self._lock:
                        self._set_state_locked(SupervisorState.STOPPING)
                    self._request_graceful_exit(process)
                    try:
                        exit_code = process.wait(timeout=self._shutdown_timeout)
                    except subprocess.TimeoutExpired:
                        self._terminate_tree(process, tree_guard)
                        exit_code = process.wait(timeout=max(self._shutdown_timeout, 1.0))
                    with self._lock:
                        self._last_exit_code = exit_code
                        self._set_state_locked(SupervisorState.STOPPED)
                    return

                exit_code = process.returncode
                with self._lock:
                    self._last_exit_code = exit_code
                if exit_code == 0:
                    with self._lock:
                        self._set_state_locked(SupervisorState.STOPPED)
                    return
                logger.warning(
                    "worker_exited",
                    extra={"event": "worker_exited", "exit_code": exit_code},
                )
                if self._restart_count >= self._restart_policy.max_restarts:
                    with self._lock:
                        self._set_state_locked(SupervisorState.FAILED)
                    return
                with self._lock:
                    self._restart_count += 1
                with self._lock:
                    self._set_state_locked(SupervisorState.BACKOFF)
                if self._stop_requested.wait(self._restart_policy.delay_for(self._restart_count)):
                    with self._lock:
                        self._set_state_locked(SupervisorState.STOPPED)
                    return
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
                if process is not None and process.poll() is None:
                    self._terminate_tree(process, tree_guard)
                    process.wait(timeout=max(self._shutdown_timeout, 1.0))
                with self._lock:
                    self._last_error = type(error).__name__
                    self._set_state_locked(SupervisorState.BACKOFF)
                logger.error(
                    "worker_start_or_supervision_failed",
                    extra={
                        "event": "worker_start_or_supervision_failed",
                        "error_type": type(error).__name__,
                    },
                )
                if self._restart_count >= self._restart_policy.max_restarts:
                    with self._lock:
                        self._set_state_locked(SupervisorState.FAILED)
                    return
                with self._lock:
                    self._restart_count += 1
                if self._stop_requested.wait(self._restart_policy.delay_for(self._restart_count)):
                    with self._lock:
                        self._set_state_locked(SupervisorState.STOPPED)
                    return
            finally:
                if process is not None and tree_guard is not None:
                    self._close_tree_guard(tree_guard)
                with self._lock:
                    self._pid = None

        with self._lock:
            self._set_state_locked(SupervisorState.STOPPED)

    def _set_state_locked(self, state: SupervisorState) -> None:
        self._state = state
        self._changed_at = time.monotonic()

    def _request_graceful_exit(self, process: subprocess.Popen[bytes]) -> None:
        if self._request_graceful_stop is not None:
            self._request_graceful_stop(process.pid)
            return
        try:
            if os.name == "nt":
                process.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                os.killpg(process.pid, signal.SIGTERM)  # type: ignore[attr-defined]
        except (OSError, ValueError):
            # Some Windows GUI parents have no console; bounded tree termination follows.
            return

    def _terminate_tree(
        self,
        process: subprocess.Popen[bytes],
        tree_guard: _TreeGuard | None,
    ) -> None:
        if tree_guard is not None:
            self._close_tree_guard(tree_guard)
            return
        if os.name != "nt":
            try:
                os.killpg(process.pid, signal.SIGKILL)  # type: ignore[attr-defined]
            except ProcessLookupError:
                pass
        else:
            try:
                subprocess.run(
                    ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                    timeout=5.0,
                )
            except (OSError, subprocess.TimeoutExpired):
                process.kill()

    @staticmethod
    def _close_tree_guard(tree_guard: _TreeGuard) -> None:
        tree_guard.close()
