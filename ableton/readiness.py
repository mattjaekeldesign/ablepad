"""
Readiness: the honest answer to "is the set actually loaded?"

LAYER: Services (pure policy, injected clock).

THE KNOWN DEBT (roadmap Phase 5, risk register)
    There is NO signal that a set finished loading until an Ableton Remote
    Script exists to send one. Until then readiness is a timing guess, and this
    module's job is to make the guess EXPLICIT rather than scattered: the state
    is named ASSUMED_READY, never READY, so no caller can forget what it is.

HOW IT WORKS
    started_at + settle_s elapsed while the process still runs -> ASSUMED_READY.
    The settle time comes from configuration and should be measured on the
    Beelink with a stopwatch and the real set. When the Remote Script lands,
    mark_confirmed_ready() upgrades the state and the guess retires.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable


class Readiness(Enum):
    NOT_STARTED = "not_started"
    STARTING = "starting"
    ASSUMED_READY = "assumed_ready"  # timing guess — the name is the warning
    CONFIRMED_READY = "confirmed_ready"  # requires the future Remote Script signal
    GONE = "gone"


@dataclass
class ReadinessTracker:
    settle_s: float
    clock: Callable[[], float]

    _started_at: float | None = field(default=None, init=False)
    _confirmed: bool = field(default=False, init=False)

    def mark_started(self) -> None:
        self._started_at = self.clock()
        self._confirmed = False

    def mark_gone(self) -> None:
        self._started_at = None
        self._confirmed = False

    def mark_confirmed_ready(self) -> None:
        """Future Remote Script hook. Nothing calls this yet — that is the debt."""
        self._confirmed = True

    def state(self, process_running: bool) -> Readiness:
        if self._started_at is None:
            return Readiness.NOT_STARTED
        if not process_running:
            return Readiness.GONE
        if self._confirmed:
            return Readiness.CONFIRMED_READY
        if self.clock() - self._started_at >= self.settle_s:
            return Readiness.ASSUMED_READY
        return Readiness.STARTING
