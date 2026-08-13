"""
The tick loop. Owns the StateMachine; everything else is injected.

LAYER: Controller.

WHAT IT IS IN PHASE 2
    A paced no-op loop that publishes Tick events and heartbeats the log — the
    roadmap's exact exit test. It proves pacing, clean shutdown and injection
    before any hardware exists to complicate them.

WHAT PLUGS IN LATER (without changing this file's shape)
    Phase 3: launchpad service subscribed to Tick for renders, publishing PadEvent.
    Phase 5: ableton supervisor polled from tick.
    The controller stays a scheduler + state owner; it never grows device code.

WHY clock/sleep ARE INJECTED
    Tests must run a thousand ticks in milliseconds and assert pacing maths
    without real time passing. Wall-clock in a unit test is flake by design.

HOW IT FAILS
    A tick overrun (tick took longer than the period) is logged and the schedule
    re-anchors — it must not try to "catch up" with a burst of back-to-back
    ticks, which on stage would look like the rig freezing then convulsing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable

from rig.events import EventBus, Tick
from rig.state import StateMachine

log = logging.getLogger(__name__)

HEARTBEAT_EVERY_S = 10.0


@dataclass
class RigController:
    machine: StateMachine
    bus: EventBus
    tick_hz: int
    clock: Callable[[], float]
    sleep: Callable[[float], None]
    #: Called in order, once per tick, after the Tick event is published. Kept as
    #: plain callables so the controller knows nothing about Launchpads, set
    #: browsers or Ableton — it owns pacing and state, and nothing else.
    on_tick: list[Callable[[], None]] = field(default_factory=list)

    _running: bool = field(default=False, init=False)
    _ticks: int = field(default=0, init=False)
    _overruns: int = field(default=0, init=False)
    _hook_errors: int = field(default=0, init=False)

    def run(self, max_ticks: int | None = None) -> int:
        """
        Loop until stop() or max_ticks. Returns ticks executed.
        max_ticks exists for tests and bench runs; production passes None.
        """
        period = 1.0 / self.tick_hz
        heartbeat_every = max(1, int(HEARTBEAT_EVERY_S * self.tick_hz))
        self._running = True
        log.info("controller running at %d Hz (period %.1f ms)", self.tick_hz, period * 1000)

        deadline = self.clock()
        while self._running and (max_ticks is None or self._ticks < max_ticks):
            self._tick()
            if self._ticks % heartbeat_every == 0:
                log.info(
                    "heartbeat: tick=%d state=%s overruns=%d",
                    self._ticks,
                    self.machine.state.value,
                    self._overruns,
                )
            deadline += period
            remaining = deadline - self.clock()
            if remaining > 0:
                self.sleep(remaining)
            else:
                # Overrun: re-anchor rather than burst-catch-up.
                self._overruns += 1
                deadline = self.clock()

        log.info("controller stopped after %d ticks (%d overruns)", self._ticks, self._overruns)
        return self._ticks

    def stop(self, reason: str) -> None:
        log.info("stop requested: %s", reason)
        self._running = False

    @property
    def ticks(self) -> int:
        return self._ticks

    @property
    def overruns(self) -> int:
        return self._overruns

    @property
    def hook_errors(self) -> int:
        return self._hook_errors

    def _tick(self) -> None:
        self._ticks += 1
        self.bus.publish(Tick(self._ticks))
        for hook in self.on_tick:
            try:
                hook()
            except Exception:  # noqa: BLE001
                # A service that throws must not take the rig down with it. The
                # show keeps running; the log carries the stack trace.
                self._hook_errors += 1
                log.exception("tick hook raised (%d so far) — continuing", self._hook_errors)
