"""
The Launchpad facade — the one object the controller talks to.

LAYER: Services.

WHO CALLS IT
    rig/controller.py, once per tick: poll() for presses, paint() with whatever the
    renderer produced. Nothing else touches the device.

STATE IT OWNS
    The connection, and only that. Not the current mode, not the selection, not what
    should be on screen — those belong to the controller and the renderer.

WHY IT EXISTS AT ALL
    device.py can open a Launchpad and drive it. What it cannot do is survive losing
    one. The roadmap calls the reconnect path "the single most common way this rig
    dies on stage", and there are two concrete reasons:

      * ESD. The Launchpad X manual says a discharge can disrupt operation and the
        fix is a physical unplug/replug. A guitarist on a dry carpeted stage is an
        ESD source. This is expected, not exotic.
      * USB. Two external hubs sit between this machine and its controllers.

HOW IT FAILS, AND WHAT THAT MUST NOT DO
    A dead Launchpad means the rig has no user interface. It does NOT mean the rig
    should stop: Ableton is still making sound, and the show is still running. So
    nothing in here raises into the tick loop. Every device call is wrapped, failure
    marks the connection dead, and the surface simply goes quiet until it comes back.

    Retries are rate-limited. A 30 Hz loop retrying a missing device 30 times a second
    would spin the CPU and fill the log with the same line 108,000 times an hour.

    Reconnect re-runs the FULL init sequence, never a partial one. The device forgets
    Programmer Mode, LED feedback, velocity curve and aftertouch across a replug
    (manual p.18) — a reconnect that only reopens the port gets a device that looks
    attached and behaves like a different instrument.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Sequence

from launchpad.device import DeviceError, LaunchpadDevice, LedSpec, MidiBackend
from launchpad.ports import PortError
from rig.events import EventBus, PadEvent

log = logging.getLogger(__name__)

__all__ = ["LaunchpadService"]

#: Seconds between reconnect attempts. Long enough not to spin, short enough that a
#: replug mid-song is back before the next chorus.
RETRY_INTERVAL_S = 2.0


@dataclass
class LaunchpadService:
    backend: MidiBackend
    bus: EventBus | None = None
    brightness: int = 40
    retry_interval_s: float = RETRY_INTERVAL_S
    # Passed straight to each device. Here rather than hardcoded because the settle
    # time is still an unmeasured guess (tools/led_batch_tester.py replaces it), and
    # because tests reconnecting twenty times should not pay twenty real delays.
    settle_s: float | None = None
    identify_timeout_s: float | None = None

    #: True while the surface has been deliberately handed to something else --
    #: Ableton's own Launchpad X control surface. Distinct from "disconnected",
    #: which is a fault: released means working as intended, so no retry, no
    #: warning, and no attempt to reconnect until acquire() says so.
    _released: bool = field(default=False, init=False)
    _device: LaunchpadDevice | None = field(default=None, init=False)
    _next_retry_at: float = field(default=0.0, init=False)
    _announced_loss: bool = field(default=False, init=False)
    _connects: int = field(default=0, init=False)
    _losses: int = field(default=0, init=False)

    # -- state ------------------------------------------------------------

    @property
    def connected(self) -> bool:
        return self._device is not None and self._device.connected

    @property
    def stats(self) -> dict[str, int]:
        """For the health check (§36). Repeated losses are a hardware story."""
        return {"connects": self._connects, "losses": self._losses}

    # -- lifecycle --------------------------------------------------------

    def ensure_connected(self, now: float) -> bool:
        """
        Connect if we are not, but no more often than retry_interval_s.

        Returns whether the device is usable right now. Never raises: a rig with no
        surface still has a show to finish.
        """
        if self._released:
            return False  # not a fault; somebody else is meant to have it
        if self.connected:
            return True
        if now < self._next_retry_at:
            return False
        self._next_retry_at = now + self.retry_interval_s

        overrides = {}
        if self.settle_s is not None:
            overrides["settle_s"] = self.settle_s
        if self.identify_timeout_s is not None:
            overrides["identify_timeout_s"] = self.identify_timeout_s
        device = LaunchpadDevice(self.backend, brightness=self.brightness, **overrides)
        try:
            device.connect()
        except (PortError, DeviceError) as exc:
            # Expected while the device is simply absent. Say it once, not 30x/second.
            if not self._announced_loss:
                log.warning("launchpad unavailable: %s", exc)
                self._announced_loss = True
            self._safe_close(device, restore=False)
            return False
        except Exception as exc:  # noqa: BLE001 — a backend can fail in its own ways
            if not self._announced_loss:
                log.error("launchpad connect failed unexpectedly: %s", exc)
                self._announced_loss = True
            self._safe_close(device, restore=False)
            return False

        self._device = device
        self._connects += 1
        self._announced_loss = False
        log.info("launchpad connected (connect #%d)", self._connects)
        return True

    # -- handover ---------------------------------------------------------

    @property
    def released(self) -> bool:
        return self._released

    def release(self) -> None:
        """
        Hand the surface to Ableton: restore Live Mode and stop touching the device.

        MUST restore Live Mode rather than merely closing the port. Programmer Mode
        is device-wide state, and Live's Launchpad X script drives the Session
        layout -- leaving the device in Programmer Mode hands Ableton a surface that
        answers on the wrong layout and lights nothing where it expects.

        Idempotent, and safe while already disconnected.
        """
        if self._released:
            return
        self._released = True
        if self._device is not None:
            log.info("releasing the launchpad to Ableton")
            self._safe_close(self._device)
            self._device = None
        else:
            log.info("launchpad marked released (nothing was connected)")

    def acquire(self) -> None:
        """
        Take the surface back. The next tick reconnects and re-asserts Programmer Mode.

        Reconnect runs the FULL init sequence, which matters more here than after a
        replug: Ableton has been driving the device into DAW mode and its own layout,
        so every setting this rig depends on is in an unknown state.
        """
        if not self._released:
            return
        log.info("re-acquiring the launchpad from Ableton")
        self._released = False
        self._next_retry_at = 0.0  # do not make the operator wait out a retry window

    def close(self) -> None:
        """Restore Live Mode and let go. Safe to call any number of times."""
        if self._device is not None:
            self._safe_close(self._device)
            self._device = None

    # -- per tick ---------------------------------------------------------

    def poll(self) -> list[PadEvent]:
        """
        Presses since the last call, published to the bus if one was given.

        Empty list when disconnected — indistinguishable, to the caller, from nobody
        touching the surface. That is deliberate: the controller should not have to
        branch on connectivity to read input.
        """
        if self._device is None:
            return []
        try:
            events = self._device.read_events()
        except Exception as exc:  # noqa: BLE001
            self._lost("reading", exc)
            return []
        if self.bus is not None:
            for event in events:
                self.bus.publish(event)
        return events

    def paint(self, specs: Sequence[LedSpec]) -> bool:
        """Paint if we can. Returns whether anything reached the device."""
        if self._device is None or not specs:
            return False
        try:
            self._device.set_leds(specs)
            return True
        except Exception as exc:  # noqa: BLE001
            self._lost("painting", exc)
            return False

    def tick(self, now: float, specs: Sequence[LedSpec] | None = None) -> list[PadEvent]:
        """
        The whole per-tick contract in one call: reconnect if needed, read, paint.

        Order matters. Reading BEFORE painting means a press that arrived in the same
        tick is acted on with the frame the controller already computed, rather than
        being held over — at 30 Hz that is the difference between a pad feeling
        instant and feeling like it has a delay on it.
        """
        if self._released:
            # Painting here would fight Ableton for the surface, and reading would
            # steal presses meant for it. Both are silent, confusing failures.
            return []
        self.ensure_connected(now)
        events = self.poll()
        if specs:
            self.paint(specs)
        return events

    # -- internals --------------------------------------------------------

    def _lost(self, doing: str, exc: BaseException) -> None:
        """A device call failed. Drop the connection and let the retry path handle it."""
        self._losses += 1
        log.warning("launchpad lost while %s (%s) — will retry", doing, exc)
        device, self._device = self._device, None
        if device is not None:
            # The device is gone. Do not try to restore Live Mode on it: the writes
            # cannot land, and the device comes back in Live Mode by itself.
            self._safe_close(device, restore=False)
        self._announced_loss = True

    @staticmethod
    def _safe_close(device: LaunchpadDevice, restore: bool = True) -> None:
        """
        close() already swallows its own errors, but it runs on a device we may have
        just decided is gone. Belt and braces: nothing in the teardown path may raise.

        restore=False when the device vanished — see LaunchpadDevice.close().
        """
        try:
            device.close(restore=restore)
        except Exception as exc:  # noqa: BLE001
            log.debug("ignoring error while closing a lost launchpad: %s", exc)
