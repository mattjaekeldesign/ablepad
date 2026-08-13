"""
SWITCH_MODE: a pad asking the rig to change state.

LAYER: Controller policy. Owns exactly one decision — whether a requested mode
change is allowed to happen — and nothing else.

WHY THIS IS NOT A COMMAND
    rig/commands.py dispatches things the rig DOES: launch, restart, shut down.
    A mode switch does nothing; it changes what the surface shows. It belongs next
    to the state machine, and routing it through the command dispatcher would mean
    every mode change carried the failure semantics of an action that touches
    hardware.

WHY IT IS NOT IN surface.py EITHER
    The surface turns presses into named actions and deliberately executes nothing
    (see its module docstring). Letting it move the state machine would make it both
    the reader and the writer of rig state, and the one place that knows about pads
    would also decide what the rig is doing.

THE ILLEGAL CASE IS NORMAL, NOT EXCEPTIONAL
    configs/*.json can offer a SWITCH_MODE from anywhere, but state.py's table
    decides what is reachable — e.g. BOOT goes only to SET_BROWSER or ERROR, so a
    'Browse' pad pressed during boot is a request the rig must refuse. That is a
    user pressing a pad early, not a fault: log it and carry on. Raising would take
    the tick loop down over a mistimed press.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from launchpad.modes import ModeError, state_for
from rig.events import ActionRequested, EventBus
from rig.exceptions import IllegalTransition
from rig.state import StateMachine

log = logging.getLogger(__name__)

__all__ = ["ModeSwitch"]


@dataclass
class ModeSwitch:
    bus: EventBus
    machine: StateMachine

    def __post_init__(self) -> None:
        self.bus.subscribe(ActionRequested, self.on_action)

    def on_action(self, event: ActionRequested) -> None:
        if event.action != "SWITCH_MODE":
            return
        target = event.params.get("target")
        if not isinstance(target, str):
            log.error("SWITCH_MODE from pad %s without a target: %r", event.pad, target)
            return
        try:
            state = state_for(target)
        except ModeError as exc:
            log.error("SWITCH_MODE to %r ignored: %s", target, exc)
            return
        if state is self.machine.state:
            return
        try:
            self.machine.transition(state, f"SWITCH_MODE from pad {event.pad}")
        except IllegalTransition as exc:
            # Expected: a pad offering a mode the rig cannot reach from here.
            log.info("cannot switch to %s right now — %s", target, exc)
