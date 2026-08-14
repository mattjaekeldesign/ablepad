"""
The performer's own kill switch for Live.

LAYER: Controller policy. Pure — fed pad events and a clock, returns a decision.
It only detects the gesture; main.py decides what firing it does (currently:
AbletonSupervisor.force_close(), graceful-then-kill, to get past a stuck save
dialog nothing headless can answer).

THE PROBLEM IT SOLVES
    Once the rig hands the Launchpad to Ableton, the surface belongs to Live, and a
    "Save changes to <set>?" dialog can leave Live unable to quit itself with no
    keyboard on the rig to answer it. This is the deliberate, from-the-surface way
    to end that.

WHAT MADE IT POSSIBLE  (MEASURED 2026-08-13, tools/listen_interface2.py)
    With Live driving interface 1, pressing the Launchpad's CUSTOM button routes pad
    traffic to interface 2 -- the rig's port, which Live does not hold. 36 messages
    arrived while Ableton owned the device. So the rig can stay deaf to nothing and
    still not interfere: it listens, paints nothing, and waits.

    WHICH NOTES ARRIVE IS NOT SETTLED. One capture with Live driving reported the
    top-left pad as note 64; a later one reported 81 -- but that second reading was
    taken with the controller force-killed, which leaves the device in PROGRAMMER
    mode, so it measured the wrong layout and looked entirely plausible doing it.

    The chord is 18 and 81 -- opposite diagonal corners, and BOTH GRID PADS. An
    earlier version paired 81 with 97, a round button, and 97 never arrived: the
    grid sends NOTES to interface 2 where the rig can see them, while the frame
    sends CC to interface 1, which belongs to Live. Round buttons are Live's while
    Ableton owns the device, and pressing one changes LIVE's view -- which looks
    like the rig reacting and is not.

    If a gesture does not fire, main.py logs every event reaching the released
    surface at DEBUG ("released-surface pad: note N"); those numbers are the truth.
    Do not re-measure with a standalone tool -- the state only exists while Ableton
    owns the device, and in that state the rig holds the port.

WHY A CHORD, AND WHY A HOLD AS WELL
    A hold, because the escape must not fire from a brushed control: taking the
    surface away mid-song would be worse than not having the feature.

    A CHORD, because the Custom layout is a view Matt uses in Ableton and the rig
    must not be able to hijack it -- "clicking custom shouldnt be enough to load the
    set bank... i need that view in ableton". One pad was too easy to hit by
    accident while playing; two controls at opposite ends of the surface, held
    together, is not a shape a hand makes by mistake.

    The chord being the safeguard is also why the hold came down from 2000 ms to
    1000: the gesture is already unlikely, so it does not need length as well.

WHAT IT DELIBERATELY DOES NOT DO
    Touch Ableton, or anything else. It reports "the chord completed" and stops --
    main.py is what calls AbletonSupervisor.force_close() in response, the same
    pattern as SurfaceOwner deciding what a plain surface handover means.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

__all__ = ["EscapeHatch", "ESCAPE_NOTES", "ESCAPE_HOLD_MS"]

#: The chord: BOTH must be held at once. Matt's choice of controls -- 81 is the
#: top-left pad of the 8x8 grid, 97 is a round button on the top row.
#:
#: A CHORD, not one pad. The Custom layout is a view Matt uses IN Ableton, so the
#: rig must not be able to hijack it: "clicking custom shouldnt be enough to load
#: the set bank... i need that view in ableton". Two controls at opposite ends of
#: the surface, held together, is not something a hand does while playing.
#:
#: 97 arrives as a CONTROL CHANGE rather than a note -- the 8x8 grid sends notes and
#: the surrounding frame sends CC (device.py, measured across all 80 controls). The
#: device layer already turns both into PadEvents, so nothing here has to care.
#: NEITHER MAY BE A PAD THE SET BROWSER USES. The chord was 18+81 and it worked
#: exactly once: 81 is the browser's slot 0, so the moment the chord dropped the rig
#: back into the bank, holding it again LOADED A SET instead. A control meaning two
#: different things depending on who owns the surface will be pressed in the wrong
#: context -- and the bank is precisely the context you land in after using this.
#:
#: The browser binds rows 8 and 7 (81-88, 71-78) plus 19, 91, 92, 98. The bottom row
#: is free: 11 is bottom-left, 18 is bottom-right.
ESCAPE_NOTES: frozenset[int] = frozenset({11, 18})

#: Shorter than the old single-pad hold, because the chord IS the safeguard. A
#: second is long enough to be deliberate when both controls are already down.
ESCAPE_HOLD_MS = 1000


@dataclass
class EscapeHatch:
    """
    Watches raw pad traffic while the surface belongs to Ableton.

    Fed only while released -- the service returns raw events in that state and
    paints nothing. When the rig owns the surface this object is not consulted, and
    reset() clears any hold so a part-finished gesture cannot survive the handover
    and fire later.
    """

    notes: frozenset[int] = ESCAPE_NOTES
    hold_ms: int = ESCAPE_HOLD_MS
    enabled: bool = True

    _held: set[int] = field(default_factory=set, init=False)
    _pressed_at: float | None = field(default=None, init=False)
    _fired: bool = field(default=False, init=False)

    def reset(self) -> None:
        """Forget any hold in progress. Called whenever ownership changes."""
        self._held.clear()
        self._pressed_at = None
        self._fired = False

    def feed(self, note: int, pressed: bool, now_ms: float) -> None:
        """
        One event from the released surface.

        Everything not in the chord is ignored entirely -- those presses belong to
        whatever the performer is doing in Ableton, and this must be deaf to them.
        """
        if not self.enabled or note not in self.notes:
            return

        if pressed:
            self._held.add(note)
            # The clock starts when the LAST control joins, not the first. Otherwise
            # holding one pad for a minute and then touching the other would fire
            # instantly, which is the opposite of a deliberate gesture.
            if self._held == self.notes and self._pressed_at is None:
                self._pressed_at = now_ms
                log.debug("escape chord complete, timing from now")
            return

        self._held.discard(note)
        if self._pressed_at is not None and not self._fired:
            log.info(
                "escape chord broken after %.0f ms of %d — not force-closing Ableton",
                now_ms - self._pressed_at, self.hold_ms,
            )
        # Breaking the chord abandons the attempt: a partial hold must not survive
        # and complete later on the strength of one control being pressed again.
        self._pressed_at = None
        self._fired = False

    def completed(self, now_ms: float) -> bool:
        """
        True exactly once per completed hold.

        Once, not while-held: the caller force-closes Ableton on the strength of
        it, and a second True after that has already happened would be meaningless.
        """
        if self._pressed_at is None or self._fired:
            return False
        if now_ms - self._pressed_at < self.hold_ms:
            return False
        self._fired = True
        log.info("escape chord completed — the performer wants Ableton force-closed")
        return True
