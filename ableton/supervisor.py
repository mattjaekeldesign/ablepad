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

from ableton.launcher import AbletonLauncher, LaunchRefused
from ableton.recovery import RestartBudget
from rig.events import AbletonCrashed, AbletonGaveUp, AbletonRestarted, EventBus

log = logging.getLogger(__name__)


@dataclass
class AbletonSupervisor:
    launcher: AbletonLauncher
    budget: RestartBudget
    bus: EventBus

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

    def poll(self) -> None:
        if self._watching is None or self._gave_up:
            return
        if self.launcher.is_running():
            self.budget.note_stable_if_due()
            return

        live_set = self._watching
        log.error("Ableton is gone (was playing %s)", live_set.name)
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
