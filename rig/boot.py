"""
The boot gate: what has to be true before the rig leaves the splash screen.

LAYER: Controller policy. Pure — every check is injected, so the whole thing is
testable with no hardware, no Ableton and no Windows.

THE DEFINITION, from the person who has to play through it
    "Boot complete means Ableton is up and running smoothly, connected to EVO sound,
     with no complications — otherwise the error screen on the Launchpad."

    That is the right requirement and it is stricter than "the process exists". It
    decomposes into checks of very different confidence, and the whole point of this
    module is to keep that difference visible instead of averaging it into a boolean.

WHAT CAN BE PROVEN
    Launchpad connected              certain
    EVO 8 enumerated on USB          certain that it enumerated
    Ableton process alive            certain
    Ableton holds the EVO's ASIO dll strong: it opened THAT driver, not another
    settle time elapsed              a timing GUESS (see ableton/readiness.py)

WHAT CANNOT BE PROVEN, AND MUST NOT BE CLAIMED
    That audio is reaching the mixer. There is no software answer to this. An
    ESD-wedged EVO enumerates perfectly, loads its driver, and outputs silence —
    its own manual says so (docs/audient-evo-8-reference.md §6). Ableton will look
    healthy the entire time.

    So this gate proves "correctly wired and running". It cannot prove "making
    sound", and the day it claims to is the day it lies on stage. The only real
    detector for silence is a human with ears, or a loopback measurement nobody has
    built. Until then: BOOT_COMPLETE means the rig is as ready as software can tell.

WHY A TIMEOUT EXISTS
    A rig that sits on the splash screen forever is indistinguishable, on a
    screenless machine, from a rig that has crashed. If the gate cannot pass within
    the deadline it goes to ERROR and NAMES the check that failed, so the Launchpad
    can say which thing is wrong rather than just going red.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable

log = logging.getLogger(__name__)

__all__ = ["Check", "CheckResult", "BootGate", "BootOutcome", "Confidence"]


class Confidence(Enum):
    """How much a passing check actually tells you. Recorded, not averaged away."""

    CERTAIN = "certain"  # observed directly: a process exists, a device enumerated
    STRONG = "strong"  # a good proxy: Ableton opened that specific driver
    GUESS = "guess"  # a timer with no confirmation behind it


@dataclass(frozen=True)
class CheckResult:
    ok: bool
    detail: str  # shown to a human; on failure this is what Error Mode reports


@dataclass(frozen=True)
class Check:
    """
    One precondition.

    `probe` returns a CheckResult and MUST NOT raise — a boot check that throws
    would take down the boot sequence it exists to protect. BootGate wraps it anyway,
    because "must not" is not the same as "does not".
    """

    name: str
    confidence: Confidence
    probe: Callable[[], CheckResult]
    #: A check that is allowed to fail without blocking boot. The Launchpad itself is
    #: NOT optional (no surface means no rig), but a missing sets folder, say, might be.
    required: bool = True


class BootOutcome(Enum):
    WAITING = "waiting"  # still inside the deadline, not everything passes yet
    COMPLETE = "complete"  # every required check passes
    FAILED = "failed"  # deadline expired; go to ERROR and say which check


@dataclass
class BootGate:
    checks: list[Check]
    timeout_s: float
    clock: Callable[[], float]

    _started_at: float | None = field(default=None, init=False)
    _last_failures: list[str] = field(default_factory=list, init=False)
    _announced: set[str] = field(default_factory=set, init=False)

    def start(self) -> None:
        self._started_at = self.clock()
        self._last_failures = []
        self._announced = set()
        log.info(
            "boot gate started: %d check(s), %.0fs deadline",
            len(self.checks),
            self.timeout_s,
        )

    def evaluate(self) -> BootOutcome:
        """Run every check. Safe to call every tick; cheap probes are the caller's job."""
        if self._started_at is None:
            self.start()

        failures: list[str] = []
        for check in self.checks:
            try:
                result = check.probe()
            except Exception as exc:  # noqa: BLE001 — a probe must never break boot
                result = CheckResult(False, f"probe raised: {exc}")
            if result.ok:
                if check.name in self._announced:
                    log.info("boot check now passing: %s — %s", check.name, result.detail)
                    self._announced.discard(check.name)
                continue
            if check.required:
                failures.append(f"{check.name}: {result.detail}")
            # Say each distinct failure once, not thirty times a second.
            if check.name not in self._announced:
                log.warning("boot check failing: %s — %s", check.name, result.detail)
                self._announced.add(check.name)

        self._last_failures = failures
        if not failures:
            log.info("boot complete: every required check passes")
            return BootOutcome.COMPLETE

        assert self._started_at is not None
        if self.clock() - self._started_at >= self.timeout_s:
            log.error("boot FAILED after %.0fs: %s", self.timeout_s, "; ".join(failures))
            return BootOutcome.FAILED
        return BootOutcome.WAITING

    @property
    def failures(self) -> list[str]:
        """Why boot has not completed. This is what Error Mode should display."""
        return list(self._last_failures)

    def summary(self) -> str:
        """
        One line for the log, and for whatever the Launchpad can scroll.

        Deliberately names the failing CHECK, not a generic 'boot failed'. On a
        screenless rig the difference between "EVO 8 missing" and "Ableton not
        running" is the difference between checking a cable and checking a set.
        """
        if not self._last_failures:
            return "boot ok"
        return " | ".join(self._last_failures)
