"""
The key strip's three controls: hold one, something happens.

LAYER: Controller policy. Pure -- an injected reader and clock, so every rule here
is testable with no hardware and no Windows.

WHY EVERY ONE IS A HOLD
    Same rule as the pads: how long you must hold tracks what a mistake costs.

        F13   1 s   back to the Set Browser (force-closes Live)   silence
        F15   2 s   restart Live on the SAME set                  silence, keeps place
        F14   4 s   reboot                                        a walk to the machine

    A tap was the first proposal for the Set Browser and it was wrong. This strip
    sits where hands and feet are, and the cost of a knock is the audio stopping
    mid-song. One second removes that for nothing -- the same argument that put a
    hold on LOAD_SET.

WHY IT POLLS RATHER THAN SUBSCRIBES
    A hold is a wall-clock measurement, and the driver below is a poll of global key
    state (windows/hotkeys.py explains why). Both fit the controller's existing tick
    loop, and holding on the tick is the pattern that already works for pads --
    checking only on input events is how the first escape hatch failed, because a
    held key sends nothing between press and release.

WHAT IT DELIBERATELY DOES NOT DO
    Decide what any action means. It reports "this key completed its hold" and
    stops; main.py maps that to a command that already exists. The rig has one
    command dispatcher and this is another way to reach it, not a second one.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable

log = logging.getLogger(__name__)

__all__ = ["Hotkey", "HotkeyControl"]


@dataclass(frozen=True)
class Hotkey:
    """One key, how long it must be held, and what to call when it is."""

    vk: int
    name: str  # for the log, and for saying which key in an error
    hold_ms: int
    action: Callable[[], None]


@dataclass
class HotkeyControl:
    """
    Polled from the tick loop; fires each key's action once per completed hold.

    `keys` empty disables it entirely, which is the honest state until a strip is
    actually plugged in.
    """

    reader: object  # windows.hotkeys.HotkeyReader
    keys: tuple[Hotkey, ...]
    clock: Callable[[], float]  # seconds

    _down_since: dict[int, float] = field(default_factory=dict, init=False)
    _fired: set[int] = field(default_factory=set, init=False)

    def poll(self) -> None:
        """Cheap, safe every tick, and never raises into the loop."""
        if not self.keys:
            return
        now = self.clock()
        for key in self.keys:
            try:
                down = bool(self.reader.pressed(key.vk))
            except Exception as exc:  # noqa: BLE001 -- a dead reader must not stop the rig
                log.debug("cannot read %s (%s)", key.name, exc)
                continue
            self._advance(key, down, now)

    # -- internals --------------------------------------------------------

    def _advance(self, key: Hotkey, down: bool, now: float) -> None:
        if not down:
            if key.vk in self._down_since and key.vk not in self._fired:
                held_ms = (now - self._down_since[key.vk]) * 1000.0
                log.info(
                    "%s released after %.0f ms of %d — nothing fired",
                    key.name, held_ms, key.hold_ms,
                )
            self._down_since.pop(key.vk, None)
            self._fired.discard(key.vk)
            return

        started = self._down_since.get(key.vk)
        if started is None:
            self._down_since[key.vk] = now
            log.debug("%s down", key.name)
            return

        if key.vk in self._fired:
            return  # once per hold, not once per tick
        if (now - started) * 1000.0 < key.hold_ms:
            return

        self._fired.add(key.vk)
        log.info("%s held %d ms — firing", key.name, key.hold_ms)
        try:
            key.action()
        except Exception:  # noqa: BLE001 -- a failing command must not stop the loop
            log.exception("%s action failed", key.name)

    @property
    def held(self) -> dict[int, float]:
        """Keys currently down, with when they went down. For a future progress UI."""
        return dict(self._down_since)
