"""
The way back to the launcher without quitting Live.

LAYER: Controller policy. Pure — fed pad events and a clock, returns a decision.

THE PROBLEM IT SOLVES
    Once the rig hands the Launchpad to Ableton, the surface belongs to Live and the
    only route back to the Set Browser is quitting Live. That is fine for a rehearsal
    and poor on stage, where changing sets should not mean shutting down the DAW.

WHAT MADE IT POSSIBLE  (MEASURED 2026-08-13, tools/listen_interface2.py)
    With Live driving interface 1, pressing the Launchpad's CUSTOM button routes pad
    traffic to interface 2 -- the rig's port, which Live does not hold. 36 messages
    arrived while Ableton owned the device. So the rig can stay deaf to nothing and
    still not interfere: it listens, paints nothing, and waits.

    The Custom layout uses a COMPLETELY DIFFERENT note map from Programmer Mode --
    launchpad/grid.py does not apply. The top-left pad is note 64, measured by
    pressing it three times and seeing exactly one note number.

WHY A HOLD, AND WHY THAT PAD
    A hold, because the escape must not fire from a brushed pad: taking the surface
    away mid-song would be worse than not having the feature. Two seconds, matching
    LOAD_SET, so the gesture feels like the rest of the rig.

    The top-left pad because it is the one pad a performer can find in the dark
    without counting. Collision risk with actual playing is low today -- Live is not
    configured to receive interface 2 at all, so Custom-layout pads currently do
    nothing musical. If that ever changes, this is the thing that has to move.

WHAT IT DELIBERATELY DOES NOT DO
    Decide anything about modes or sets. It reports "the performer asked for the
    launcher back" and stops. SurfaceOwner decides what that means.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

__all__ = ["EscapeHatch", "ESCAPE_NOTE", "ESCAPE_HOLD_MS"]

#: Top-left grid pad in the CUSTOM layout. MEASURED on the rig 2026-08-13; this is
#: not derivable from grid.py, which describes Programmer Mode.
ESCAPE_NOTE = 64

#: Same 2000 ms as LOAD_SET. Long enough that a brush cannot take the surface away
#: mid-song, short enough to feel deliberate rather than broken.
ESCAPE_HOLD_MS = 2000


@dataclass
class EscapeHatch:
    """
    Watches raw pad traffic while the surface belongs to Ableton.

    Fed only while released -- the service returns raw events in that state and
    paints nothing. When the rig owns the surface this object is not consulted, and
    reset() clears any hold so a part-finished gesture cannot survive the handover
    and fire later.
    """

    note: int = ESCAPE_NOTE
    hold_ms: int = ESCAPE_HOLD_MS
    enabled: bool = True

    _pressed_at: float | None = field(default=None, init=False)
    _fired: bool = field(default=False, init=False)

    def reset(self) -> None:
        """Forget any hold in progress. Called whenever ownership changes."""
        self._pressed_at = None
        self._fired = False

    def feed(self, note: int, pressed: bool, now_ms: float) -> None:
        """One pad event from the released surface."""
        if not self.enabled or note != self.note:
            return
        if pressed:
            if self._pressed_at is None:
                self._pressed_at = now_ms
                log.debug("escape gesture started on note %d", note)
        else:
            if self._pressed_at is not None and not self._fired:
                log.info(
                    "escape gesture released after %.0f ms of %d — not taking the "
                    "surface back",
                    now_ms - self._pressed_at, self.hold_ms,
                )
            self._pressed_at = None
            self._fired = False

    def wants_surface(self, now_ms: float) -> bool:
        """
        True exactly once per completed hold.

        Once, not while-held: the caller flips ownership on the strength of it, and
        a second True after the surface is already back would be meaningless.
        """
        if self._pressed_at is None or self._fired:
            return False
        if now_ms - self._pressed_at < self.hold_ms:
            return False
        self._fired = True
        log.info("escape gesture completed — the performer wants the launcher back")
        return True
