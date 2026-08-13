"""
What a pad looks like while it is being held toward an action.

LAYER: drivers/presentation. Pure — takes holds and a clock reading, returns LED
dicts. No device, no state, no knowledge of what any action does.

WHY THIS EXISTS
    LOAD_SET is a 2000 ms hold and SYSTEM_SHUTDOWN is 6000 ms. Until now those were
    silent: the pad looked exactly the same at 0 ms and at 5900 ms, so the only way
    to learn a hold was working was for it to fire.

    OBSERVED 2026-08-13, and the reason this module exists: a 1000 ms SWITCH_MODE
    was released twice at 453 ms and 391 ms and reported as "I hit it but nothing
    happened". The rig was working correctly and had no way to say so. On a rig with
    no screen, an unacknowledged press is indistinguishable from a dead one.

WHY A STATIC RAMP AND NOT A BLINK
    Not a style choice. The Launchpad's flash and pulse lighting types are slaved to
    its MIDI beat clock, not to wall time (roadmap §5), so anything blinking is
    timing-critical feedback the host does not control. A hold is a wall-clock
    measurement; its feedback has to be host-driven, which means a solid colour
    recomputed every tick. At 30 Hz that is smooth enough to read as filling up.

WHY THE RAMP IS COARSE
    Only eight palette indices have ever been confirmed on this hardware
    (colors.VERIFIED), and three of them are greens. That is the whole budget for a
    brightness ramp, so the ramp has three stages. Arbitrary RGB via lighting type 3
    would give a smooth fade and is deliberately not used: it has never been seen
    working on this device, and a progress indicator that might render as nothing is
    worse than a coarse one that certainly renders.

    The stage count is len(HOLD_RAMP). Adding a verified index extends the ramp with
    no other change.
"""

from __future__ import annotations

from typing import Mapping, Protocol

from launchpad import colors

__all__ = ["HOLD_RAMP", "hold_leds", "Held"]


#: "not yet" -> "nearly" -> "about to fire". Every entry MUST be in colors.VERIFIED:
#: this is feedback whose entire job is to be seen, so an unverified index would
#: defeat the purpose in the exact moment it matters.
#:
#: A TRAFFIC LIGHT, NOT A BRIGHTNESS RAMP
#:     Three greens (GREEN_DIM, GREEN, GREEN_BRIGHT) was the first attempt and is
#:     worse for two reasons. They are the least distinguishable trio in the verified
#:     set -- and on a dark stage, at a glance, distinguishable is the whole product.
#:     And GREEN is the Set Browser's own idle colour, so a hold on a set pad would
#:     appear to snap back to idle halfway through.
#:
#:     Hue changes read instantly where brightness steps do not. Any colour here can
#:     still collide with some pad's idle -- holding the red Emergency pad starts on
#:     RED -- but a collision on ONE stage of three still leaves visible movement,
#:     where a collision in the middle of a monochrome ramp reads as a glitch.
HOLD_RAMP: tuple[int, ...] = (colors.RED, colors.YELLOW, colors.GREEN_BRIGHT)


class Held(Protocol):
    """
    The shape of surface.Hold, structurally.

    A Protocol rather than the real import because surface.py imports the renderer
    that consumes this, and importing Hold back from surface would make that a
    cycle. Nothing here needs to know what a Hold is beyond how far along it is.
    """

    hold_ms: int

    def elapsed(self, now_ms: float) -> float: ...


def stage(progress: float) -> int:
    """
    Which ramp colour a 0.0-1.0 progress lands on.

    Clamped at both ends. Progress can exceed 1.0 for the tick between a hold
    completing and the surface firing it, and an IndexError there would black out
    the whole surface at the instant the user finally succeeded.
    """
    if progress <= 0.0:
        return 0
    index = int(progress * len(HOLD_RAMP))
    return min(index, len(HOLD_RAMP) - 1)


def hold_leds(holds: Mapping[int, Held], now_ms: float) -> dict[int, dict]:
    """
    LED dicts for every pad currently mid-hold, keyed by pad index.

    Empty when nothing is held, which is the overwhelmingly common case and costs
    the renderer nothing.
    """
    leds: dict[int, dict] = {}
    for pad, held in holds.items():
        if held.hold_ms <= 0:
            # Instant actions never enter the held set, but a zero here would be a
            # division by zero rather than a visual bug, so it is worth refusing.
            continue
        progress = held.elapsed(now_ms) / held.hold_ms
        leds[pad] = {"type": "static", "palette": HOLD_RAMP[stage(progress)]}
    return leds
