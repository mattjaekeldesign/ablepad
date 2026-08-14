"""
Per-tick supervision: notice a crash, spend the restart budget, or give up loudly.

LAYER: Services. Driven by the controller's tick; speaks to the rig via events.

EXECUTION FLOW, per poll()
    running?  -> refill budget if the run has been stable; done.
    crashed?  -> publish AbletonCrashed
                 budget allows -> relaunch the SAME set -> AbletonRestarted
                 budget empty  -> AbletonGaveUp (controller takes the rig to
                                  Error Mode; supervision stops until reset()).

WHY EVENTS AND NOT RETURN VALUES
    The controller decides what a crash MEANS (Error Mode, LED text, etc.).
    The supervisor only knows process facts — same decoupling as PadEvent.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from typing import Callable

from ableton.launcher import AbletonLauncher, LaunchRefused
from ableton.recovery import RestartBudget
from rig.events import (
    AbletonClosed,
    AbletonCrashed,
    AbletonGaveUp,
    AbletonRestarted,
    EventBus,
)

log = logging.getLogger(__name__)


@dataclass
class AbletonSupervisor:
    launcher: AbletonLauncher
    budget: RestartBudget
    bus: EventBus
    #: Second opinion on how Live ended, for the case exit_code() cannot answer.
    #: Returns True if Live left a crash journal behind. Optional: without it an
    #: adopted Ableton's exit is simply unknowable, which is where this started.
    left_crash_journal: "Callable[[], bool] | None" = None

    _watching: Path | None = field(default=None, init=False)
    _gave_up: bool = field(default=False, init=False)

    def watch(self, live_set: Path) -> None:
        """Arm supervision for an already-launched set."""
        self._watching = live_set
        self._gave_up = False

    def reset(self) -> None:
        """Operator acknowledged the failure (Error Mode exit). Start fresh."""
        self._watching = None
        self._gave_up = False

    def force_close(self, reason: str) -> None:
        """
        The performer is done, and Live is not necessarily going to say so.

        Ends supervision FIRST, then stops the process. Order matters: if stop()
        ran first, the next poll() would see "not running, no exit code" -- exactly
        what an ADOPTED crash looks like -- read the crash journal a kill always
        leaves behind, call it a crash, and spend the restart budget relaunching
        the set nobody asked for again.

        Publishes AbletonClosed itself rather than waiting for poll() to notice,
        so a stuck "Save changes to <set>?" dialog -- unanswerable on a rig with no
        keyboard, and the reason this exists -- runs through the exact same
        recovery on_ableton_closed already does for a normal quit: surface
        released, browser reset, back to the Set Browser. No second path to keep
        in sync with the first.
        """
        live_set = self._watching
        self._watching = None
        self._gave_up = False
        self.launcher.stop()
        if live_set is not None:
            log.info("Ableton force-closed (%s): %s", live_set.name, reason)
            self.bus.publish(AbletonClosed(set_name=live_set.name))

    def _exit_code(self) -> int | None:
        """Best-effort exit code. Never raises into the tick loop."""
        handle = self.launcher.handle
        if handle is None:
            return None
        try:
            return self.launcher.processes.exit_code(handle)
        except Exception as exc:  # noqa: BLE001 -- an older controller may not have it
            log.debug("no exit code available (%s) — treating as a crash", exc)
            return None

    def _code_from_crash_journal(self) -> int | None:
        """0 if Live tidied up after itself, 1 if it did not, None if we cannot tell."""
        if self.left_crash_journal is None:
            return None
        try:
            left_behind = bool(self.left_crash_journal())
        except Exception as exc:  # noqa: BLE001
            log.debug("cannot inspect the crash journal (%s)", exc)
            return None
        log.info(
            "no exit code (adopted process); crash journal %s -> treating as %s",
            "left behind" if left_behind else "cleaned up",
            "a crash" if left_behind else "a clean exit",
        )
        return 1 if left_behind else 0

    def poll(self) -> None:
        if self._watching is None or self._gave_up:
            return
        if self.launcher.is_running():
            self.budget.note_stable_if_due()
            return

        live_set = self._watching

        # A clean exit is somebody quitting Live on purpose -- the way back to the
        # Set Browser now that the Launchpad is handed over during a set. Restarting
        # it would be the rig overruling its operator, and it would do so instantly,
        # so the set would appear to refuse to close.
        #
        # exit_code() is None for an ADOPTED Ableton (no Popen behind it), and None
        # is treated as a crash: assuming "clean" would make every real crash
        # silently unrecoverable, which is the more expensive way to be wrong.
        code = self._exit_code()
        if code is None:
            # An ADOPTED Ableton has no Popen behind it. Rather than call every such
            # exit a crash -- which relaunches sets people deliberately closed, and
            # adoption is the COMMON case whenever the controller restarts under a
            # running Live -- ask the filesystem.
            #
            # MEASURED 2026-08-13: Live writes Preferences\Crash\<stamp>_* at
            # startup and REMOVES it on a clean exit. A journal left behind is
            # exactly the thing that makes Live offer to recover, so its presence is
            # a direct, first-hand statement by Live about how it ended.
            code = self._code_from_crash_journal()

        if code == 0:
            log.info("Ableton closed cleanly (was playing %s)", live_set.name)
            self._watching = None
            self.bus.publish(AbletonClosed(set_name=live_set.name))
            return

        log.error("Ableton is gone (was playing %s, exit code %s)", live_set.name, code)
        self.bus.publish(AbletonCrashed(set_name=live_set.name))

        if not self.budget.allow_restart():
            self._gave_up = True
            self.bus.publish(AbletonGaveUp(set_name=live_set.name))
            return
        try:
            self.launcher.launch(live_set)
            self.bus.publish(AbletonRestarted(set_name=live_set.name))
        except LaunchRefused as exc:
            # The world changed under us (interface gone, file gone). That is
            # not a budget question — stop trying and say why.
            log.error("restart refused: %s", exc)
            self._gave_up = True
            self.bus.publish(AbletonGaveUp(set_name=live_set.name))
