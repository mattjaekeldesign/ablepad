"""
Launch and stop Ableton Live — after refusing every launch that cannot work.

LAYER: Services.

THE PRECONDITION RULE (roadmap Phase 5)
    Refuse to launch when the audio interface is absent, or when the .als does
    not exist, or when the exe does not exist. ALL failing preconditions are
    reported together — a gig-night refusal must name everything wrong at once.

    Presence is NOT health: an ESD-wedged EVO 8 still enumerates (manual p.10),
    so a passing precondition means "worth trying", never "will make sound".

WHO CALLS IT
    The supervisor (crash restarts) and, via commands, the controller (set
    loads). Nobody else may start the process.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from ableton.crash_recovery import CrashRecovery
from ableton.ready_signal import ReadySignal
from ableton.process import ProcessController, ProcessHandle
from rig.exceptions import RigError

log = logging.getLogger(__name__)

GRACEFUL_CLOSE_TIMEOUT_S = 10.0


class AudioInterfacePresence(Protocol):
    """Implemented in Phase 5 on Windows PnP data; faked in tests until then."""

    def is_present(self) -> bool: ...


class LaunchRefused(RigError):
    """One or more preconditions failed. Carries all of them."""

    def __init__(self, reasons: list[str]) -> None:
        self.reasons = list(reasons)
        super().__init__("launch refused: " + "; ".join(self.reasons))


@dataclass
class AbletonLauncher:
    exe: Path
    processes: ProcessController
    audio: AudioInterfacePresence
    #: Clears Live's crash journal so the "recover the last session?" dialog never
    #: appears -- unanswerable on a rig with no keyboard. Optional: absent means the
    #: dialog is possible, not that anything breaks.
    recovery: CrashRecovery | None = None
    #: Cleared at every launch so a signal from the previous set can never be read
    #: as confirmation for this one. Optional: absent just means the boot gate waits
    #: out its settle timer.
    ready_signal: ReadySignal | None = None

    _handle: ProcessHandle | None = field(default=None, init=False)

    def preconditions(self, live_set: Path) -> list[str]:
        """Every reason a launch would be doomed. Empty list = go."""
        reasons: list[str] = []
        if not self.exe.exists():
            reasons.append(f"Ableton exe not found: {self.exe}")
        if not live_set.exists():
            reasons.append(f"set file not found: {live_set}")
        if not self.audio.is_present():
            reasons.append("audio interface not present (see docs/audient-evo-8-reference.md §6)")
        return reasons

    def adopt(self, pid: int) -> ProcessHandle:
        """
        Take ownership of an Ableton that was already running.

        Needed because the controller can start while Live is up -- a Task Scheduler
        retry, or the controller crashing on its own. Without this, launch() sees no
        handle, starts a SECOND Live, and the two fight over the interface's single
        ASIO device. OBSERVED 2026-08-13: the newcomer lost, the rig went to ERROR,
        and a perfectly healthy set carried on playing underneath.

        Adopting means stop() and is_running() work on it exactly as if we had
        started it. What it does NOT tell us is which set the process has open --
        that is not recoverable from the process, and callers must not assume.
        """
        self._handle = ProcessHandle(pid=pid, exe=str(self.exe))
        log.info("adopted running Ableton (pid %d)", pid)
        return self._handle

    def launch(self, live_set: Path) -> ProcessHandle:
        if self._handle is not None and self.processes.is_running(self._handle):
            raise LaunchRefused(["Ableton is already running — stop it first, one owner only"])
        reasons = self.preconditions(live_set)
        if reasons:
            log.error("refusing to launch: %s", "; ".join(reasons))
            raise LaunchRefused(reasons)
        if self.recovery is not None:
            # Here and nowhere else: preconditions have passed, so a launch is
            # definitely happening, and Live is definitely not running yet -- the one
            # moment when every journal on disk is stale rather than in use.
            self.recovery.clear()
        if self.ready_signal is not None:
            # Before start(), always. A signal left from the last set is
            # indistinguishable from this set's, and reading it would confirm a set
            # that is not loaded -- a false READY, which is the one outcome worse
            # than waiting.
            self.ready_signal.clear()
        self._handle = self.processes.start(self.exe, live_set)
        return self._handle

    def stop(self) -> None:
        """Graceful first, kill second, forget the handle either way."""
        if self._handle is None:
            return
        handle, self._handle = self._handle, None
        if not self.processes.is_running(handle):
            return
        if self.processes.terminate_gracefully(handle, GRACEFUL_CLOSE_TIMEOUT_S):
            log.info("Ableton closed gracefully")
        else:
            log.warning("graceful close timed out after %.0fs — killing", GRACEFUL_CLOSE_TIMEOUT_S)
            self.processes.kill(handle)

    @property
    def handle(self) -> ProcessHandle | None:
        return self._handle

    def is_running(self) -> bool:
        return self._handle is not None and self.processes.is_running(self._handle)
