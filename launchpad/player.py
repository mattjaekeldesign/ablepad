"""
Animation player — plays one animation against the controller's tick.

LAYER: Services. Pure pull model: the controller (or Phase 3 renderer) calls
frame(now_ms) once per tick and composites whatever comes back. The player
never sleeps, never threads, never touches a port — "non-blocking, killable"
(roadmap Phase 3) falls out of the design instead of being bolted on.

THE INTRO/DURING CONTRACT (from the Lab's animation system, 2026-08-08)
    intro   plays once, full-cover; ANY pad press skips it (the caller routes
            PadEvent to skip()); a failsafe cap ends it regardless, because a
            boot animation that outlives boot is a rig that looks hung.
    during  loops under/over a screen until cancel(); layering is the
            renderer's business, not the player's.

HOW IT ENDS
    frame() returns None exactly once the animation is over (finished, skipped,
    cancelled, or capped) and fires on_finished exactly once. Idle thereafter.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable

from launchpad.animations import Frame, animation_frame

log = logging.getLogger(__name__)

INTRO_FAILSAFE_MS = 15_000  # Lab player contract: no intro may outlive this


class PlayMode(Enum):
    INTRO = "intro"
    DURING = "during"


@dataclass
class AnimationPlayer:
    _anim: dict | None = field(default=None, init=False)
    _mode: PlayMode = field(default=PlayMode.DURING, init=False)
    _started_at: float | None = field(default=None, init=False)
    _on_finished: Callable[[], None] | None = field(default=None, init=False)

    def play(
        self,
        anim: dict,
        mode: PlayMode,
        now_ms: float,
        on_finished: Callable[[], None] | None = None,
    ) -> None:
        """Replaces whatever is playing. The old animation's on_finished fires."""
        if self.is_playing:
            self._finish("replaced")
        self._anim = anim
        self._mode = mode
        self._started_at = now_ms
        self._on_finished = on_finished
        log.info("playing %s as %s", anim.get("id", "<unnamed>"), mode.value)

    def frame(self, now_ms: float) -> Frame | None:
        """The frame for this tick, or None when nothing is playing."""
        if self._anim is None or self._started_at is None:
            return None
        t = now_ms - self._started_at
        if self._mode is PlayMode.INTRO and t >= INTRO_FAILSAFE_MS:
            log.warning("intro hit the %d ms failsafe — ending it", INTRO_FAILSAFE_MS)
            self._finish("failsafe")
            return None
        frame = animation_frame(self._anim, t)
        if frame is None:
            self._finish("finished")
            return None
        return frame

    def skip(self) -> bool:
        """Any-press skip. Only intros skip; during-loops ignore presses. True if skipped."""
        if self._anim is not None and self._mode is PlayMode.INTRO:
            self._finish("skipped")
            return True
        return False

    def cancel(self) -> None:
        """Killable, mid-run, from any state. Safe to call when idle."""
        if self._anim is not None:
            self._finish("cancelled")

    @property
    def mode(self) -> PlayMode:
        """
        INTRO or DURING. Public because the compositor needs it: an intro COVERS the
        surface and a during-loop composites under or over it, and that is the
        caller's decision to make, not something to infer from a private field.
        """
        return self._mode

    @property
    def is_playing(self) -> bool:
        return self._anim is not None

    def _finish(self, why: str) -> None:
        log.info("animation ended: %s", why)
        callback, self._on_finished = self._on_finished, None
        self._anim = None
        self._started_at = None
        if callback is not None:
            callback()
