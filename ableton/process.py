"""
The process boundary — the ONLY module in ableton/ allowed to import psutil.

LAYER: Drivers (OS process control).

WHY A PROTOCOL
    Every policy module (launcher, supervisor, recovery) is written against
    ProcessController and tested with a fake. The real adapter below is thin
    enough to verify by inspection plus one bench session on the Beelink —
    which is the only place it CAN be verified, because process semantics
    (exit codes, termination behaviour) are Windows-specific.

KNOWN LIMITS — recorded, not hidden
    * start() proves the process EXISTS, not that a set is LOADED. Readiness
      is a separate, weaker signal (readiness.py).
    * terminate() on Windows kills the process without running Live's save
      prompts — there is no clean-close API without window messages. The
      graceful path is attempted first but is best-effort (§ROADMAP Phase 5).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProcessHandle:
    pid: int
    exe: str


class ProcessController(Protocol):
    def start(self, exe: Path, argument: Path) -> ProcessHandle: ...

    def is_running(self, handle: ProcessHandle) -> bool: ...

    def terminate_gracefully(self, handle: ProcessHandle, timeout_s: float) -> bool:
        """Ask nicely, wait. True if it exited. False means kill() is next."""
        ...

    def kill(self, handle: ProcessHandle) -> None: ...


class PsutilProcessController:
    """
    The real adapter. UNVERIFIED on Windows until the Phase 5 bench session —
    every method is written to be boring enough that the bench run is a
    confirmation, not a debugging session.
    """

    def start(self, exe: Path, argument: Path) -> ProcessHandle:
        import psutil

        process = psutil.Popen([str(exe), str(argument)])
        log.info("started %s (pid %d) with %s", exe.name, process.pid, argument.name)
        return ProcessHandle(pid=process.pid, exe=str(exe))

    def is_running(self, handle: ProcessHandle) -> bool:
        import psutil

        try:
            process = psutil.Process(handle.pid)
            # PID reuse guard: same pid, different program, is not our process.
            return process.is_running() and not process.status() == psutil.STATUS_ZOMBIE
        except psutil.NoSuchProcess:
            return False

    def terminate_gracefully(self, handle: ProcessHandle, timeout_s: float) -> bool:
        import psutil

        try:
            process = psutil.Process(handle.pid)
            process.terminate()
            process.wait(timeout=timeout_s)
            return True
        except psutil.NoSuchProcess:
            return True  # already gone counts as success
        except psutil.TimeoutExpired:
            return False

    def kill(self, handle: ProcessHandle) -> None:
        import psutil

        try:
            psutil.Process(handle.pid).kill()
        except psutil.NoSuchProcess:
            pass
