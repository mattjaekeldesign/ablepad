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
from dataclasses import dataclass, field
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

    def exit_code(self, handle: ProcessHandle) -> int | None:
        """
        How the process ended: 0 clean, non-zero crashed, None unknown/still running.

        The rig has to tell "Matt quit Live to get back to the launcher" from "Live
        died mid-set". They are the same event -- the process is gone -- and only the
        exit code separates them. Guessing wrong either relaunches a set someone
        deliberately closed, or shrugs at a crash.
        """
        ...

    def terminate_gracefully(self, handle: ProcessHandle, timeout_s: float) -> bool:
        """Ask nicely, wait. True if it exited. False means kill() is next."""
        ...

    def kill(self, handle: ProcessHandle) -> None: ...


@dataclass
class PsutilProcessController:
    """
    The real adapter. UNVERIFIED on Windows until the Phase 5 bench session —
    every method is written to be boring enough that the bench run is a
    confirmation, not a debugging session.
    """

    #: pid -> the Popen we started it with, kept ONLY so exit_code() can work.
    #: psutil can tell you a stranger's process is gone but not how it ended; the
    #: Popen object is the only thing that remembers.
    _started: dict[int, object] = field(default_factory=dict, init=False)

    def start(self, exe: Path, argument: Path) -> ProcessHandle:
        import psutil

        process = psutil.Popen([str(exe), str(argument)])
        self._started[process.pid] = process
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
        """
        Ask Live to close. True if it exited within the timeout.

        MEASURED 2026-08-13: psutil.terminate() is NOT graceful on Windows. It calls
        TerminateProcess, the same syscall as kill(), so the old implementation of
        this method was a hard kill wearing a polite name. Live therefore never ran
        its shutdown, never removed its crash journal, and offered to recover the
        session on every single launch -- including after an ordinary set switch,
        because SetBrowserControl stops Live before loading.

        `taskkill /PID n` WITHOUT /F posts WM_CLOSE to the process's windows, which
        is the only close request Windows offers without writing window-message code
        of our own. That is what makes the exit clean.

        THE HANG THIS CAN CAUSE, AND WHY IT IS STILL RIGHT
            A close request on a set with unsaved changes raises Live's "save
            changes?" prompt, and nothing headless will ever answer it. That run
            burns the full timeout and then gets killed -- exactly the old
            behaviour, no worse. Performance sets are not edited, so the prompt
            should not appear; if these timeouts show up in the log, something is
            modifying sets at runtime and that is the bug to chase.
        """
        import psutil

        try:
            process = psutil.Process(handle.pid)
        except psutil.NoSuchProcess:
            return True  # already gone counts as success

        if not self._request_close(handle.pid):
            # No taskkill (not Windows, or not on PATH). Fall back to psutil, which
            # is graceful on POSIX and a kill on Windows -- the old behaviour, kept
            # so a non-Windows host is not left with no way to stop a process.
            try:
                process.terminate()
            except psutil.NoSuchProcess:
                return True

        try:
            process.wait(timeout=timeout_s)
            return True
        except psutil.NoSuchProcess:
            return True
        except psutil.TimeoutExpired:
            return False

    @staticmethod
    def _request_close(pid: int) -> bool:
        """
        Post WM_CLOSE via taskkill. Returns whether the request was delivered.

        False means "could not ask" (no taskkill), NOT "the process refused" --
        taskkill returns promptly once the message is posted, long before Live has
        finished shutting down. Whether it worked is decided by the wait() above.
        """
        import subprocess

        try:
            result = subprocess.run(
                ["taskkill", "/PID", str(pid)],
                capture_output=True,
                timeout=10,
            )
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired) as exc:
            log.debug("taskkill unavailable for pid %d (%s) — falling back", pid, exc)
            return False
        if result.returncode != 0:
            log.debug(
                "taskkill declined pid %d (rc=%d): %s",
                pid, result.returncode, result.stderr.decode(errors="replace").strip(),
            )
            return False
        log.info("asked Ableton (pid %d) to close", pid)
        return True

    def kill(self, handle: ProcessHandle) -> None:
        import psutil

        try:
            psutil.Process(handle.pid).kill()
        except psutil.NoSuchProcess:
            pass

    def exit_code(self, handle: ProcessHandle) -> int | None:
        """
        None while running, or if this controller did not start it (an ADOPTED
        Ableton has no Popen behind it, so how it ends is genuinely unknowable --
        and saying None is better than inventing a zero and treating every crash as
        a deliberate quit).
        """
        process = self._started.get(handle.pid)
        if process is None:
            return None
        try:
            return process.poll()
        except Exception:  # noqa: BLE001
            return None
