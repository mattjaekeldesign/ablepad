"""
Reading a dedicated key strip, whatever window has focus.

LAYER: Drivers (OS). Windows-specific; everything above is written against the
Protocol so the policy stays testable off-rig.

WHY THIS EXISTS
    The Launchpad cannot carry system controls during a performance. Measured
    2026-08-13: while Ableton owns the surface only GRID pads reach the rig, their
    note map belongs to whichever Custom layout is loaded, and that map moved under
    us on a firmware update. The frame buttons never arrive at all. Every gesture
    built on that was either fragile or sat on pads Matt plays.

    A separate three-key USB strip removes the whole problem. The Launchpad becomes
    entirely Ableton's -- Session, Note and Matt's own Components layouts, untouched
    -- and the rig gets an input nothing else competes for.

WHY GetAsyncKeyState AND NOT RegisterHotKey
    RegisterHotKey needs a window and a message loop, and it reports a PRESS with no
    release -- so it cannot measure a hold, and every action here is hold-gated.
    GetAsyncKeyState is a poll of global key state: it needs no window, works
    whatever has focus, and press/release falls out of comparing consecutive ticks.
    The controller already runs a 30 Hz loop, which is ample for a 1-4 second hold.

THE KEY CHOICE IS LOAD-BEARING
    This does NOT consume the keystroke. Whatever window has focus sees it too, so
    a key Ableton binds would fire Live's shortcut as well as the rig's action.

    F13-F15 are the right answer: no physical keyboard has them, Live binds nothing
    to them, and most macro strips can be configured to send them. If a strip can
    only send ordinary letters, that is a hardware problem to solve before wiring it
    here -- not something to work around in software.

HOW IT FAILS
    Off-Windows, or with ctypes unavailable, `pressed()` returns False forever and
    the rig simply has no key strip. Never raises: a missing input device must not
    stop a rig that is otherwise working.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

__all__ = ["HotkeyReader", "WindowsHotkeys", "VK_F13", "VK_F14", "VK_F15"]

#: Virtual key codes. F13-F15 exist in Windows and on no keyboard anyone owns,
#: which is exactly why they are safe: nothing else will ever send them.
VK_F13 = 0x7C
VK_F14 = 0x7D
VK_F15 = 0x7E


class HotkeyReader:
    """The seam. Faked in tests; implemented below on Windows."""

    def pressed(self, vk: int) -> bool: ...


@dataclass
class WindowsHotkeys:
    """
    Global key state via user32.GetAsyncKeyState.

    The high-order bit of the return value means "down right now". The low bit means
    "pressed since the last call", which is deliberately NOT used: it is consumed by
    reading it, so two callers would rob each other, and it cannot express a hold.
    """

    _user32: object | None = field(default=None, init=False)
    _warned: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        try:
            import ctypes  # noqa: PLC0415 -- platform import, deliberate

            self._user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001 -- not Windows, or no ctypes
            log.info("no key strip support on this platform (%s)", exc)
            self._user32 = None

    def pressed(self, vk: int) -> bool:
        if self._user32 is None:
            return False
        try:
            return bool(self._user32.GetAsyncKeyState(vk) & 0x8000)
        except Exception as exc:  # noqa: BLE001
            if not self._warned:
                self._warned = True
                log.warning("cannot read key state (%s) — the key strip is inert", exc)
            return False
