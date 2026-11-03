"""Windows Job Object ownership for terminating an entire worker tree."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from subprocess import Popen


class _BasicLimitInformation(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _IoCounters(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    ]


class _ExtendedLimitInformation(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BasicLimitInformation),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _ThreadEntry32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ThreadID", wintypes.DWORD),
        ("th32OwnerProcessID", wintypes.DWORD),
        ("tpBasePri", ctypes.c_long),
        ("tpDeltaPri", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
    ]


class WindowsJobObject:
    """Keep a worker and its descendants in a kill-on-close Windows job."""

    _KILL_ON_JOB_CLOSE = 0x00002000
    _EXTENDED_LIMIT_INFORMATION = 9
    _SNAP_THREAD = 0x00000004
    _THREAD_SUSPEND_RESUME = 0x0002
    _INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

    def __init__(self, process: Popen[bytes]) -> None:
        if ctypes.sizeof(ctypes.c_void_p) not in (4, 8):
            raise OSError("unsupported Windows pointer size")

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            wintypes.LPVOID,
            wintypes.DWORD,
        ]
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        self._terminate_job = kernel32.TerminateJobObject
        self._terminate_job.argtypes = [wintypes.HANDLE, wintypes.UINT]
        self._terminate_job.restype = wintypes.BOOL
        self._close_handle = kernel32.CloseHandle
        self._close_handle.argtypes = [wintypes.HANDLE]
        self._close_handle.restype = wintypes.BOOL

        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        self._handle: wintypes.HANDLE | None = handle

        limits = _ExtendedLimitInformation()
        limits.BasicLimitInformation.LimitFlags = self._KILL_ON_JOB_CLOSE
        if not kernel32.SetInformationJobObject(
            handle,
            self._EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(limits),
            ctypes.sizeof(limits),
        ):
            self.close()
            raise ctypes.WinError(ctypes.get_last_error())

        process_handle = kernel32.OpenProcess(0x0001 | 0x0100, False, process.pid)
        if not process_handle:
            error = ctypes.get_last_error()
            self.close()
            raise ctypes.WinError(error)
        try:
            if not kernel32.AssignProcessToJobObject(handle, process_handle):
                error = ctypes.get_last_error()
                self.close()
                raise ctypes.WinError(error)
        finally:
            kernel32.CloseHandle(process_handle)

    def close(self) -> None:
        """Terminate surviving descendants, then release the job handle."""

        if self._handle is None:
            return
        handle = self._handle
        self._handle = None
        if not self._terminate_job(handle, 1):
            error = ctypes.get_last_error()
            self._close_handle(handle)
            raise ctypes.WinError(error)
        if not self._close_handle(handle):
            raise ctypes.WinError(ctypes.get_last_error())

    @classmethod
    def resume_suspended_process(cls, process_id: int) -> None:
        """Resume the still-suspended primary thread after job assignment."""

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        kernel32.Thread32First.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ThreadEntry32)]
        kernel32.Thread32First.restype = wintypes.BOOL
        kernel32.Thread32Next.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ThreadEntry32)]
        kernel32.Thread32Next.restype = wintypes.BOOL
        kernel32.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenThread.restype = wintypes.HANDLE
        kernel32.ResumeThread.argtypes = [wintypes.HANDLE]
        kernel32.ResumeThread.restype = wintypes.DWORD
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

        snapshot = kernel32.CreateToolhelp32Snapshot(cls._SNAP_THREAD, 0)
        if snapshot == cls._INVALID_HANDLE_VALUE:
            raise ctypes.WinError(ctypes.get_last_error())
        found = False
        try:
            entry = _ThreadEntry32()
            entry.dwSize = ctypes.sizeof(entry)
            has_entry = kernel32.Thread32First(snapshot, ctypes.byref(entry))
            while has_entry:
                if entry.th32OwnerProcessID == process_id:
                    thread_handle = kernel32.OpenThread(
                        cls._THREAD_SUSPEND_RESUME,
                        False,
                        entry.th32ThreadID,
                    )
                    if thread_handle:
                        try:
                            if kernel32.ResumeThread(thread_handle) == 0xFFFFFFFF:
                                raise ctypes.WinError(ctypes.get_last_error())
                            found = True
                            break
                        finally:
                            kernel32.CloseHandle(thread_handle)
                has_entry = kernel32.Thread32Next(snapshot, ctypes.byref(entry))
        finally:
            kernel32.CloseHandle(snapshot)
        if not found:
            raise OSError("suspended worker thread was not found")
