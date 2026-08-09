"""
The rig's mode state machine.

LAYER: Controller. Depends only on events + exceptions.

WHERE THE STATES COME FROM
    The five-mode tree in CLAUDE.md §3 (Boot / Set Browser / Performance / System /
    Error) plus SHUTDOWN as an explicit terminal — a rig that is stopping on purpose
    must be distinguishable from one that died.

WHERE THE TRANSITION TABLE COMES FROM
    DESIGN DECISION, 2026-08-09 — Start_DOCS is not in the repo, so this table is
    authored here, not cited. Rules encoded:
      - ERROR is reachable from every live state: faults do not queue politely.
      - ERROR recovers to SET_BROWSER only — never straight back into PERFORMANCE,
        because whatever set was playing is gone and pretending otherwise on a
        screenless rig hides the fault.
      - SHUTDOWN is terminal and reachable only deliberately (browser/system/error).
      - Nothing returns to BOOT: recovery re-runs connect sequences, not the boot
        mode. If that proves wrong on hardware, change the TABLE, not call sites.

WHO CALLS IT
    rig/controller.py owns the single instance. Everything else observes via
    StateChanged events on the bus.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum

from rig.events import EventBus, StateChanged
from rig.exceptions import IllegalTransition

log = logging.getLogger(__name__)


class RigState(Enum):
    BOOT = "boot"
    SET_BROWSER = "set_browser"
    PERFORMANCE = "performance"
    SYSTEM = "system"
    ERROR = "error"
    SHUTDOWN = "shutdown"


LEGAL_TRANSITIONS: dict[RigState, frozenset[RigState]] = {
    RigState.BOOT: frozenset({RigState.SET_BROWSER, RigState.ERROR}),
    RigState.SET_BROWSER: frozenset(
        {RigState.PERFORMANCE, RigState.SYSTEM, RigState.ERROR, RigState.SHUTDOWN}
    ),
    RigState.PERFORMANCE: frozenset(
        {RigState.SET_BROWSER, RigState.SYSTEM, RigState.ERROR}
    ),
    RigState.SYSTEM: frozenset(
        {RigState.SET_BROWSER, RigState.ERROR, RigState.SHUTDOWN}
    ),
    RigState.ERROR: frozenset({RigState.SET_BROWSER, RigState.SHUTDOWN}),
    RigState.SHUTDOWN: frozenset(),
}


@dataclass
class StateMachine:
    """
    Holds the current mode and enforces the table. Nothing else may change state.

    Transitions are logged with their reason BEFORE the event is published, so the
    log file always explains the LED surface even if a subscriber dies.
    """

    bus: EventBus
    state: RigState = RigState.BOOT
    history: list[tuple[RigState, RigState, str]] = field(default_factory=list)

    def transition(self, to: RigState, reason: str) -> None:
        allowed = LEGAL_TRANSITIONS[self.state]
        if to not in allowed:
            raise IllegalTransition(
                f"{self.state.value} -> {to.value} is not in the table "
                f"(allowed from {self.state.value}: "
                f"{sorted(s.value for s in allowed) or 'nothing — terminal state'}). "
                f"Reason given: {reason!r}"
            )
        old, self.state = self.state, to
        self.history.append((old, to, reason))
        log.info("state %s -> %s (%s)", old.value, to.value, reason)
        self.bus.publish(StateChanged(old.value, to.value, reason))

    def can(self, to: RigState) -> bool:
        return to in LEGAL_TRANSITIONS[self.state]
