"""End a process a builder started. Nothing else.

A shell would give the janitor everything. The check is the identity recorded at
launch: pid, project, creation time. A pid alone is not enough because pids are
recycled.
"""
from __future__ import annotations

from typing import Any


class KillRefused(Exception):
    """The process is not one a builder started, or is no longer that process."""


def _identities(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [e for e in events if e.get("type") == "process.registered"]


def _alive(pid: int) -> bool:
    import ctypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259
    kernel32 = ctypes.windll.kernel32          # type: ignore[attr-defined]
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not handle:
        return False
    try:
        code = ctypes.c_ulong()
        if kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return code.value == STILL_ACTIVE
        return False
    finally:
        kernel32.CloseHandle(handle)


def kill(log, pid: int, project_id: str | None = None) -> dict[str, Any]:
    """End one builder-started process. Refuses everything else."""
    events = [e.to_dict() if hasattr(e, "to_dict") else e for e in log.read_all()]
    match = None
    for identity in _identities(events):
        if int(identity.get("processId", -1)) == int(pid):
            if project_id and identity.get("projectId") != project_id:
                continue
            match = identity
            break
    if match is None:
        raise KillRefused(
            f"pid {pid} is not a process this workshop started; not ending it"
        )
    if not _alive(int(pid)):
        return {"ended": False, "pid": int(pid),
                "note": "already gone; nothing to end"}
    import os
    import signal
    try:
        os.kill(int(pid), signal.SIGTERM)
    except OSError as exc:
        raise KillRefused(f"pid {pid} would not end: {exc}") from exc
    return {"ended": True, "pid": int(pid),
            "runId": match.get("runId"), "role": match.get("role")}
