"""
The System Mode pads, made real.

LAYER: Controller. Each class is one named command; none of them knows what a pad
is, and none is constructed with a pad number.

WHAT THIS IS FOR
    Matt's framing, and it is the right one: the Set Browser is where the rig lands
    when Ableton is closed or something has gone wrong, so there have to be
    troubleshooting options one step away. System Mode is that step
    (configs/system.json, reachable by holding pad 98 in the browser).

    They were designed in the Config Lab months before anything could execute them:
    the config declared ABLETON_RESTART, SYSTEM_REBOOT, SYSTEM_SHUTDOWN and
    HOTSPOT_TOGGLE, the loader validated them, and nothing was subscribed. Exactly
    the shape SWITCH_MODE was in.

WHY COMMANDS AND NOT HANDLERS
    CLAUDE.md §4: no RestartAbletonButton. A pad names a COMMAND, the dispatcher
    finds it, and the pad has no idea what happens next. That is what lets the same
    action be triggered later by the Ampero, by SSH, or by a health check with no
    change here.

ORDER OF DESTRUCTIVENESS, and how each is protected
    ABLETON_RESTART   2000 ms hold   recoverable; costs a set reload
    SYSTEM_REBOOT     4000 ms hold   unrecoverable without physical access
    SYSTEM_SHUTDOWN   6000 ms hold   as above, and the rig cannot turn itself on

    The holds live in configs/system.json, not here. A command must not be able to
    weaken its own confirmation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from ableton.launcher import AbletonLauncher, LaunchRefused
from windows.power import PowerController

log = logging.getLogger(__name__)

__all__ = ["RestartAbleton", "Reboot", "Shutdown"]


@dataclass
class RestartAbleton:
    """
    Stop Live and start it again on the same set.

    The first thing to reach for when a set is misbehaving, and the only one of
    these three that does not cost you the machine. Stop is graceful-then-kill
    (ableton/launcher.py), so a clean Live tidies its crash journal on the way out
    and the next launch does not meet a recovery dialog.
    """

    launcher: AbletonLauncher
    #: What to restart. A callable rather than a Path because the answer changes
    #: every time a set is loaded, and a command that captured it at wiring time
    #: would restart whatever was playing when the rig booted.
    current_set: "callable"

    name = "ABLETON_RESTART"

    def execute(self, context: Mapping[str, object]) -> None:
        live_set = self.current_set()
        if live_set is None:
            log.warning("ABLETON_RESTART with no set loaded — nothing to restart")
            return
        live_set = Path(live_set)
        log.info("restarting Ableton with %s", live_set.name)
        self.launcher.stop()
        try:
            self.launcher.launch(live_set)
        except LaunchRefused as exc:
            # The preconditions are real -- a missing interface, a missing file. Say
            # so and stop; the supervisor and the boot gate report it in their words.
            log.error("restart refused: %s", "; ".join(exc.reasons))


@dataclass
class Reboot:
    """Restart Windows. 4000 ms hold, and no way back without physical access."""

    power: PowerController

    name = "SYSTEM_REBOOT"

    def execute(self, context: Mapping[str, object]) -> None:
        log.warning("SYSTEM_REBOOT from the surface")
        self.power.reboot()


@dataclass
class Shutdown:
    """
    Power off. The most destructive thing the surface can do: the rig cannot turn
    itself back on, so this is a walk to the machine at minimum.
    """

    power: PowerController

    name = "SYSTEM_SHUTDOWN"

    def execute(self, context: Mapping[str, object]) -> None:
        log.warning("SYSTEM_SHUTDOWN from the surface")
        self.power.shutdown()
