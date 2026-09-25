"""Broker-mediated Windows process containment and tool invocation (TESP §7)."""

from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from progressdesk.events import EventLog

CREATE_SUSPENDED = 0x00000004
CREATE_UNICODE_ENVIRONMENT = 0x00000400
WAIT_OBJECT_0 = 0x00000000
WAIT_TIMEOUT = 0x00000102
WAIT_FAILED = 0xFFFFFFFF
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
FILE_ATTRIBUTE_REPARSE_POINT = 0x400
_BLOCKED_SHELLS = {"cmd.exe", "powershell.exe", "pwsh.exe", "bash", "sh"}


class BrokerError(RuntimeError):
    """Broker refused or failed an invocation."""


@dataclass(frozen=True)
class ToolSpec:
    toolId: str
    version: str
    entrypoint: tuple[str, ...]
    argumentSchema: dict[str, Any]
    permittedResourceAccess: tuple[str, ...]
    outputDescription: str
    sandboxVerificationEvidence: str

    def validate(self) -> None:
        for name in ("toolId", "version", "outputDescription", "sandboxVerificationEvidence"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise BrokerError(f"ToolSpec.{name} must be a non-empty string")
        if not self.entrypoint or any(
            not isinstance(part, str) or not part or "\x00" in part
            for part in self.entrypoint
        ):
            raise BrokerError("ToolSpec.entrypoint must be a non-empty argv string tuple")
        executable = Path(self.entrypoint[0]).name.lower()
        if executable in _BLOCKED_SHELLS:
            raise BrokerError("generic unrestricted shells are not broker capabilities")
        if not isinstance(self.argumentSchema, dict):
            raise BrokerError("ToolSpec.argumentSchema must be an object")
        if not isinstance(self.permittedResourceAccess, tuple):
            raise BrokerError("ToolSpec.permittedResourceAccess must be a tuple")
        if any(not isinstance(item, str) or not item for item in self.permittedResourceAccess):
            raise BrokerError("ToolSpec.permittedResourceAccess entries must be non-empty strings")


@dataclass(frozen=True)
class InvocationPolicy:
    candidateDir: Path
    readPaths: tuple[Path, ...] = ()
    writePaths: tuple[Path, ...] = ()


@dataclass(frozen=True)
class PlannedInvocation:
    projectId: str
    runId: str
    role: str
    toolId: str
    version: str
    argv: tuple[str, ...]
    candidateDir: Path


@dataclass(frozen=True)
class ProcessIdentity:
    projectId: str
    runId: str
    jobName: str
    processId: int
    processCreationTime: int
    role: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "projectId": self.projectId,
            "runId": self.runId,
            "jobName": self.jobName,
            "processId": self.processId,
            "processCreationTime": self.processCreationTime,
            "role": self.role,
        }


class _StartupInfo(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_uint32),
        ("lpReserved", ctypes.c_wchar_p),
        ("lpDesktop", ctypes.c_wchar_p),
        ("lpTitle", ctypes.c_wchar_p),
        ("dwX", ctypes.c_uint32),
        ("dwY", ctypes.c_uint32),
        ("dwXSize", ctypes.c_uint32),
        ("dwYSize", ctypes.c_uint32),
        ("dwXCountChars", ctypes.c_uint32),
        ("dwYCountChars", ctypes.c_uint32),
        ("dwFillAttribute", ctypes.c_uint32),
        ("dwFlags", ctypes.c_uint32),
        ("wShowWindow", ctypes.c_uint16),
        ("cbReserved2", ctypes.c_uint16),
        ("lpReserved2", ctypes.c_void_p),
        ("hStdInput", ctypes.c_void_p),
        ("hStdOutput", ctypes.c_void_p),
        ("hStdError", ctypes.c_void_p),
    ]


class _ProcessInformation(ctypes.Structure):
    _fields_ = [
        ("hProcess", ctypes.c_void_p),
        ("hThread", ctypes.c_void_p),
        ("dwProcessId", ctypes.c_uint32),
        ("dwThreadId", ctypes.c_uint32),
    ]


class _FileTime(ctypes.Structure):
    _fields_ = [
        ("dwLowDateTime", ctypes.c_uint32),
        ("dwHighDateTime", ctypes.c_uint32),
    ]


class _JobObjectBasicAccountingInformation(ctypes.Structure):
    _fields_ = [
        ("TotalUserTime", ctypes.c_longlong),
        ("TotalKernelTime", ctypes.c_longlong),
        ("ThisPeriodTotalUserTime", ctypes.c_longlong),
        ("ThisPeriodTotalKernelTime", ctypes.c_longlong),
        ("TotalPageFaultCount", ctypes.c_uint32),
        ("TotalProcesses", ctypes.c_uint32),
        ("ActiveProcesses", ctypes.c_uint32),
        ("TotalTerminatedProcesses", ctypes.c_uint32),
    ]


def _kernel32():
    if os.name != "nt":
        raise BrokerError("Windows Job Objects are unavailable on this platform")
    library = ctypes.WinDLL("kernel32", use_last_error=True)
    library.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
    library.CreateJobObjectW.restype = ctypes.c_void_p
    library.CreateProcessW.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.POINTER(_StartupInfo),
        ctypes.POINTER(_ProcessInformation),
    ]
    library.CreateProcessW.restype = ctypes.c_int
    library.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    library.AssignProcessToJobObject.restype = ctypes.c_int
    library.ResumeThread.argtypes = [ctypes.c_void_p]
    library.ResumeThread.restype = ctypes.c_uint32
    library.GetProcessTimes.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(_FileTime),
        ctypes.POINTER(_FileTime),
        ctypes.POINTER(_FileTime),
        ctypes.POINTER(_FileTime),
    ]
    library.GetProcessTimes.restype = ctypes.c_int
    library.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    library.WaitForSingleObject.restype = ctypes.c_uint32
    library.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
    library.GetExitCodeProcess.restype = ctypes.c_int
    library.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    library.TerminateProcess.restype = ctypes.c_int
    library.TerminateJobObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    library.TerminateJobObject.restype = ctypes.c_int
    library.QueryInformationJobObject.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_uint32),
    ]
    library.QueryInformationJobObject.restype = ctypes.c_int
    library.CloseHandle.argtypes = [ctypes.c_void_p]
    library.CloseHandle.restype = ctypes.c_int
    library.GetFileAttributesW.argtypes = [ctypes.c_wchar_p]
    library.GetFileAttributesW.restype = ctypes.c_uint32
    return library


def _assert_no_reparse(path: Path, root: Path) -> None:
    if os.name != "nt":
        return
    library = _kernel32()
    current = root
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise BrokerError(f"path escapes workspace: {path}") from exc
    for part in relative.parts:
        current = current / part
        if not current.exists():
            continue
        attributes = library.GetFileAttributesW(os.fspath(current))
        if attributes != 0xFFFFFFFF and attributes & FILE_ATTRIBUTE_REPARSE_POINT:
            raise BrokerError(f"reparse-point path is forbidden: {current}")


class WindowsJob:
    """One project run Job Object; breakaway flags are deliberately not enabled."""

    def __init__(self, project_id: str, run_id: str) -> None:
        self.project_id = project_id
        self.run_id = run_id
        self.job_name = (
            f"Local\\ProgressDesk-{project_id}-{run_id}-{uuid.uuid4().hex}"
        )
        self._library = _kernel32()
        handle = self._library.CreateJobObjectW(None, self.job_name)
        if not handle:
            raise BrokerError(f"CreateJobObjectW failed: {ctypes.get_last_error()}")
        self._handle = ctypes.c_void_p(handle)
        self._closed = False

    def spawn(
        self,
        argv: tuple[str, ...],
        candidate_dir: Path,
        *,
        role: str,
    ) -> tuple[ProcessIdentity, ctypes.c_void_p]:
        if self._closed:
            raise BrokerError("job is already closed")
        info = _ProcessInformation()
        startup = _StartupInfo()
        startup.cb = ctypes.sizeof(startup)
        command_line = subprocess.list2cmdline(list(argv))
        created = self._library.CreateProcessW(
            argv[0],
            command_line,
            None,
            None,
            False,
            CREATE_SUSPENDED | CREATE_UNICODE_ENVIRONMENT,
            None,
            os.fspath(candidate_dir),
            ctypes.byref(startup),
            ctypes.byref(info),
        )
        if not created:
            raise BrokerError(f"CreateProcessW failed: {ctypes.get_last_error()}")
        process = ctypes.c_void_p(info.hProcess)
        thread = ctypes.c_void_p(info.hThread)
        try:
            if not self._library.AssignProcessToJobObject(self._handle, process):
                raise BrokerError(
                    f"AssignProcessToJobObject failed: {ctypes.get_last_error()}"
                )
            creation = _FileTime()
            exit_time = _FileTime()
            kernel_time = _FileTime()
            user_time = _FileTime()
            if not self._library.GetProcessTimes(
                process,
                ctypes.byref(creation),
                ctypes.byref(exit_time),
                ctypes.byref(kernel_time),
                ctypes.byref(user_time),
            ):
                raise BrokerError(f"GetProcessTimes failed: {ctypes.get_last_error()}")
            identity = ProcessIdentity(
                projectId=self.project_id,
                runId=self.run_id,
                jobName=self.job_name,
                processId=int(info.dwProcessId),
                processCreationTime=(int(creation.dwHighDateTime) << 32)
                | int(creation.dwLowDateTime),
                role=role,
            )
            if self._library.ResumeThread(thread) == 0xFFFFFFFF:
                raise BrokerError(f"ResumeThread failed: {ctypes.get_last_error()}")
            return identity, process
        except Exception:
            # The process is still suspended if assignment/identity failed. This
            # is launch cleanup, not an application-level abort.
            self._library.TerminateProcess(process, 1)
            raise
        finally:
            self._library.CloseHandle(thread)

    def wait(self, process: ctypes.c_void_p, timeout_ms: int = 0xFFFFFFFF) -> int:
        result = self._library.WaitForSingleObject(process, timeout_ms)
        if result == WAIT_TIMEOUT:
            raise BrokerError("process wait timed out")
        if result != WAIT_OBJECT_0:
            raise BrokerError(f"WaitForSingleObject failed: {result}")
        code = ctypes.c_uint32()
        if not self._library.GetExitCodeProcess(process, ctypes.byref(code)):
            raise BrokerError(f"GetExitCodeProcess failed: {ctypes.get_last_error()}")
        return int(code.value)

    def active_process_count(self) -> int:
        if self._closed:
            raise BrokerError("job is already closed")
        information = _JobObjectBasicAccountingInformation()
        returned = ctypes.c_uint32()
        if not self._library.QueryInformationJobObject(
            self._handle,
            1,  # JobObjectBasicAccountingInformation
            ctypes.byref(information),
            ctypes.sizeof(information),
            ctypes.byref(returned),
        ):
            raise BrokerError(
                f"QueryInformationJobObject failed: {ctypes.get_last_error()}"
            )
        return int(information.ActiveProcesses)

    def wait_until_empty(self, timeout_ms: int = 5000) -> bool:
        deadline = time.monotonic() + timeout_ms / 1000
        while True:
            if self.active_process_count() == 0:
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.01)

    def _terminate_for_police(self) -> None:
        if not self._library.TerminateJobObject(self._handle, 1):
            raise BrokerError(f"TerminateJobObject failed: {ctypes.get_last_error()}")

    def close(self) -> None:
        if not self._closed:
            self._library.CloseHandle(self._handle)
            self._closed = True


class ProjectRun:
    """Broker-owned run handle. It exposes waiting, never public termination."""

    def __init__(self, job: WindowsJob, process: ctypes.c_void_p, identity: ProcessIdentity):
        self._job = job
        self._process = process
        self.identity = identity
        self._closed = False

    def wait(self, timeout_ms: int = 0xFFFFFFFF) -> int:
        code = self._job.wait(self._process, timeout_ms)
        self.close()
        return code

    def _terminate_for_police(self) -> None:
        self._job._terminate_for_police()

    def active_process_count(self) -> int:
        return self._job.active_process_count()

    def wait_for_termination(self, timeout_ms: int = 5000) -> int:
        """Wait for the process and all job members, then release handles."""
        code = self._job.wait(self._process, timeout_ms)
        if not self._job.wait_until_empty(timeout_ms):
            raise BrokerError("project job did not become quiescent")
        self.close()
        return code

    def close(self) -> None:
        if not self._closed:
            self._job._library.CloseHandle(self._process)
            self._job.close()
            self._closed = True


class ProjectRunRegistry:
    """In-memory live ownership; the event log remains the durable identity."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._runs: dict[str, list[ProjectRun]] = {}
        self._closed: set[str] = set()

    def is_closed(self, project_id: str) -> bool:
        with self._lock:
            return project_id in self._closed

    def register(self, project_id: str, run: ProjectRun) -> None:
        with self._lock:
            if project_id in self._closed:
                raise BrokerError("project dispatch is closed")
            self._runs.setdefault(project_id, []).append(run)

    def unregister(self, run: ProjectRun) -> None:
        with self._lock:
            runs = self._runs.get(run.identity.projectId, [])
            self._runs[run.identity.projectId] = [item for item in runs if item is not run]

    def close_project(self, project_id: str) -> tuple[ProjectRun, ...]:
        with self._lock:
            self._closed.add(project_id)
            return tuple(self._runs.get(project_id, ()))

    def reopen_project(self, project_id: str) -> None:
        with self._lock:
            self._closed.discard(project_id)

    def active(self, project_id: str) -> tuple[ProjectRun, ...]:
        with self._lock:
            return tuple(self._runs.get(project_id, ()))


class PoliceTerminationAuthority:
    """Sole public path to TerminateJobObject (TESP §7.2)."""

    def terminate(self, run: ProjectRun) -> None:
        run._terminate_for_police()

    def terminate_project(self, broker: "Broker", project_id: str) -> tuple[ProjectRun, ...]:
        runs = broker._close_project_dispatch(project_id)
        for run in runs:
            self.terminate(run)
        return runs


class Broker:
    """Validate a scoped invocation, launch suspended, assign, record, resume."""

    def __init__(
        self,
        workspace_root: Path,
        *,
        event_log: EventLog | None = None,
    ) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self.event_log = event_log
        self.runs = ProjectRunRegistry()
        self._dispatch_lock = threading.RLock()

    def _assert_dispatch_open(self, project_id: str) -> None:
        if self.runs.is_closed(project_id):
            raise BrokerError("project dispatch is closed")

    def _close_project_dispatch(self, project_id: str) -> tuple[ProjectRun, ...]:
        with self._dispatch_lock:
            return self.runs.close_project(project_id)

    def reopen_project_after_recovery(self, project_id: str) -> None:
        with self._dispatch_lock:
            self.runs.reopen_project(project_id)

    def active_runs(self, project_id: str) -> tuple[ProjectRun, ...]:
        return self.runs.active(project_id)

    def _forget_run(self, run: ProjectRun) -> None:
        self.runs.unregister(run)

    def _resolve_contained(self, path: Path) -> Path:
        absolute = Path(os.path.abspath(path))
        _assert_no_reparse(absolute, self.workspace_root)
        resolved = absolute.resolve(strict=True)
        try:
            resolved.relative_to(self.workspace_root)
        except ValueError as exc:
            raise BrokerError(f"path escapes workspace: {path}") from exc
        _assert_no_reparse(resolved, self.workspace_root)
        return resolved

    def plan(
        self,
        spec: ToolSpec,
        policy: InvocationPolicy,
        *,
        project_id: str,
        run_id: str,
        role: str,
        arguments: tuple[str, ...],
    ) -> PlannedInvocation:
        spec.validate()
        with self._dispatch_lock:
            self._assert_dispatch_open(project_id)
        if not project_id or not run_id or not role:
            raise BrokerError("projectId, runId, and role are required")
        if any(not isinstance(arg, str) or "\x00" in arg for arg in arguments):
            raise BrokerError("tool arguments must be argv strings without NUL")
        candidate = self._resolve_contained(policy.candidateDir)
        if not candidate.is_dir():
            raise BrokerError("candidateDir must be a directory")
        for path in (*policy.readPaths, *policy.writePaths):
            self._resolve_contained(path)
        if policy.writePaths:
            resolved_writes = [self._resolve_contained(path) for path in policy.writePaths]
            if candidate not in resolved_writes:
                raise BrokerError("candidateDir must be one of the declared write paths")
        return PlannedInvocation(
            projectId=project_id,
            runId=run_id,
            role=role,
            toolId=spec.toolId,
            version=spec.version,
            argv=(*spec.entrypoint, *arguments),
            candidateDir=candidate,
        )

    def invoke(self, planned: PlannedInvocation) -> ProjectRun:
        with self._dispatch_lock:
            self._assert_dispatch_open(planned.projectId)
            return self._invoke_locked(planned)

    def _invoke_locked(self, planned: PlannedInvocation) -> ProjectRun:
        if self.event_log is not None:
            self.event_log.record(
                "action.requested",
                producer="broker",
                payload=json.dumps(
                    {
                        "toolId": planned.toolId,
                        "version": planned.version,
                        "role": planned.role,
                        "argv": list(planned.argv),
                        "candidateDir": os.fspath(planned.candidateDir),
                    },
                    sort_keys=True,
                ).encode("utf-8"),
                project_id=planned.projectId,
                run_id=planned.runId,
            )
        job = WindowsJob(planned.projectId, planned.runId)
        try:
            identity, process = job.spawn(
                planned.argv,
                planned.candidateDir,
                role=planned.role,
            )
        except Exception as exc:
            job.close()
            if self.event_log is not None:
                self.event_log.record(
                    "action.failed",
                    producer="broker",
                    payload=json.dumps(
                        {"toolId": planned.toolId, "version": planned.version,
                         "error": str(exc)},
                        sort_keys=True,
                    ).encode("utf-8"),
                    project_id=planned.projectId,
                    run_id=planned.runId,
                )
            raise
        if self.event_log is not None:
            self.event_log.record(
                "process.registered",
                producer="broker",
                payload=json.dumps(identity.to_dict(), sort_keys=True).encode("utf-8"),
                project_id=planned.projectId,
                run_id=planned.runId,
            )
        run = ProjectRun(job, process, identity)
        self.runs.register(planned.projectId, run)
        return run

    def wait(self, run: ProjectRun) -> int:
        """Wait for a run and record its broker outcome."""
        code = run.wait()
        self.runs.unregister(run)
        if self.event_log is not None:
            self.event_log.record(
                "action.completed",
                producer="broker",
                payload=json.dumps(
                    {"processId": run.identity.processId, "exitCode": code},
                    sort_keys=True,
                ).encode("utf-8"),
                project_id=run.identity.projectId,
                run_id=run.identity.runId,
            )
        return code
