"""
The restart budget — recovery without thrash.

LAYER: Services (pure policy, injected clock).

THE RULE (roadmap Phase 5)
    A crash gets ONE automatic restart. A restart that itself crashes quickly
    means something is genuinely wrong — more restarts would thrash the machine
    mid-gig while the performer watches LEDs strobe. The budget refills only
    after a restart SURVIVES for stable_s, which is what separates "transient
    hiccup" from "the set is cursed tonight".

WHO CALLS IT
    ableton/supervisor.py, exclusively. The controller only hears the outcome.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable

log = logging.getLogger(__name__)


@dataclass
class RestartBudget:
    max_attempts: int
    stable_s: float
    clock: Callable[[], float]

    _attempts: int = field(default=0, init=False)
    _last_restart_at: float | None = field(default=None, init=False)

    def note_stable_if_due(self) -> None:
        """Call while running. A restart that lasted stable_s refills the budget."""
        if (
            self._attempts > 0
            and self._last_restart_at is not None
            and self.clock() - self._last_restart_at >= self.stable_s
        ):
            log.info("run stable for %.0fs — restart budget reset", self.stable_s)
            self._attempts = 0
            self._last_restart_at = None

    def allow_restart(self) -> bool:
        """One crash consultation. True consumes an attempt."""
        if self._attempts >= self.max_attempts:
            log.error(
                "restart budget exhausted (%d/%d) — NOT restarting again",
                self._attempts,
                self.max_attempts,
            )
            return False
        self._attempts += 1
        self._last_restart_at = self.clock()
        log.warning("restart %d/%d authorised", self._attempts, self.max_attempts)
        return True

    @property
    def attempts_used(self) -> int:
        return self._attempts
