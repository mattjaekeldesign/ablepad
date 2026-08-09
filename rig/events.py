"""
Domain events and the bus that carries them.

LAYER: shared vocabulary between Drivers (producers) and Controller (consumer).

WHY EVENTS AND NOT CALLBACKS-INTO-MODULES
    The Launchpad driver (Phase 3) must not know what a pad press MEANS — meaning
    is per-mode and lives in the controller. Drivers publish facts; the controller
    subscribes and decides. That is the whole decoupling that lets Phase 8 swap
    Python for Bome behind the same events.

WHO CALLS IT
    Publishers: launchpad/ (Phase 3), ableton/ (Phase 5), windows/ (Phase 6).
    Subscribers: rig/controller.py, and logging taps in tests.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, TypeVar

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Event:
    """Base. Events are immutable facts about the past; handlers cannot edit them."""


@dataclass(frozen=True)
class PadEvent(Event):
    """
    A physical pad changed state.

    `note` is the Programmer-mode number (11–99). `pressed` is explicit rather
    than derived, because the Launchpad X signals release as note-on velocity 0
    (manual p.6) — deriving it at every consumer is how that fact gets forgotten.
    """

    note: int
    velocity: int
    pressed: bool


@dataclass(frozen=True)
class StateChanged(Event):
    """The rig moved between modes. Published by StateMachine, never manually."""

    old: str
    new: str
    reason: str


@dataclass(frozen=True)
class Tick(Event):
    """One controller heartbeat. Carries the count so consumers can rate-divide."""

    count: int


@dataclass(frozen=True)
class AbletonCrashed(Event):
    """The Live process vanished without being asked to. Supervisor decides next."""

    set_name: str


@dataclass(frozen=True)
class AbletonRestarted(Event):
    """The supervisor spent a budget attempt and relaunched the same set."""

    set_name: str


@dataclass(frozen=True)
class AbletonGaveUp(Event):
    """Budget exhausted or restart refused. The controller must enter Error Mode."""

    set_name: str


E = TypeVar("E", bound=Event)
Handler = Callable[[Event], None]


@dataclass
class EventBus:
    """
    Synchronous, in-process pub/sub.

    Deliberately NOT threaded and NOT queued: Phase 2 has one thread, and a queue
    would hide ordering bugs the tests should catch. If Phase 3's MIDI callback
    thread needs a queue, it goes in the driver, not here.

    A handler that raises is logged and skipped — one bad subscriber must not
    take down the event loop mid-show. That is an appliance rule, not a style
    choice.
    """

    _handlers: dict[type, list[Handler]] = field(default_factory=dict)

    def subscribe(self, event_type: type[E], handler: Callable[[E], None]) -> Callable[[], None]:
        """Register. Returns an unsubscribe function — no unsubscribe-by-identity API."""
        bucket = self._handlers.setdefault(event_type, [])
        bucket.append(handler)  # type: ignore[arg-type]

        def unsubscribe() -> None:
            if handler in bucket:
                bucket.remove(handler)  # type: ignore[arg-type]

        return unsubscribe

    def publish(self, event: Event) -> None:
        for handler in list(self._handlers.get(type(event), ())):
            try:
                handler(event)
            except Exception:  # noqa: BLE001 -- isolation is the contract
                log.exception("handler %r failed on %r; continuing", handler, event)
