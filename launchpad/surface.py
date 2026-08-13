"""
The bridge: rig state in, lit surface out, named actions back.

LAYER: Services. Above launchpad/service.py (which owns the cable) and below
rig/controller.py (which owns the tick loop and the state machine).

WHAT IT DOES EACH TICK
    1. work out which ModeConfig the current RigState wants
    2. if the state just changed, arm that mode's intro animation
    3. ask the player for this instant's animation frame
    4. render state + frame + held pads into 81 LedSpecs
    5. hand them to the service, and take back whatever was pressed
    6. turn presses into NAMED ACTIONS, honouring hold-to-confirm

WHY HOLD-TO-CONFIRM LIVES HERE
    LOAD_SET is a 2000 ms hold and SYSTEM_SHUTDOWN is 6000 ms (mappings.ACTION_HOLDS).
    Those numbers exist because the alternative is changing song — or powering off —
    because a foot brushed a pad between numbers.

    It belongs at this layer, not in the device and not in the controller: the device
    should not know what a pad means, and the controller should not know that pads
    exist. Here is the only place that knows both.

    The hold is measured against the tick clock rather than a timer thread. A hold
    that depends on a thread being scheduled is a hold that can fire late on a busy
    machine, and this loop is already running at 30 Hz.

WHAT IT DELIBERATELY DOES NOT DO
    Execute anything. It publishes ActionRequested and stops. Who loads a set, who
    reboots the machine, and what happens if the interface is missing are all Phase 5
    and Phase 6 concerns living behind the command dispatcher. Keeping execution out
    means the surface can be exercised without a rig attached.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable

from launchpad.holdfeedback import hold_leds
from launchpad.mappings import ConfigLibrary, ModeConfig
from launchpad.modes import resolve
from launchpad.player import AnimationPlayer, PlayMode
from launchpad.renderer import Overlay, render
from launchpad.service import LaunchpadService
from rig.events import (
    ActionArmed,
    ActionCancelled,
    ActionRequested,
    EventBus,
    PadEvent,
)
from rig.state import RigState, StateMachine

log = logging.getLogger(__name__)

__all__ = ["Surface", "Hold"]


@dataclass
class Hold:
    """A press waiting to become an action."""

    pad: int
    action: str
    params: dict
    hold_ms: int
    started_ms: float

    def elapsed(self, now_ms: float) -> float:
        return now_ms - self.started_ms

    def ready(self, now_ms: float) -> bool:
        return self.elapsed(now_ms) >= self.hold_ms


@dataclass
class Surface:
    service: LaunchpadService
    library: ConfigLibrary
    machine: StateMachine
    bus: EventBus
    player: AnimationPlayer = field(default_factory=AnimationPlayer)
    #: Optional per-mode LED overrides, keyed by config id. The Set Browser uses this
    #: to paint which slots actually hold a set. Kept as callables so the surface
    #: never learns what a set is -- it asks, paints, and forgets.
    overrides_for: dict[str, "Callable[[], dict[int, dict]]"] = field(default_factory=dict)
    #: Returns True while the RIG should be driving the surface, False while it
    #: belongs to Ableton. Injected rather than computed here: the surface knows
    #: about pads and modes, not about whether a DAW is running.
    rig_owns_surface: "Callable[[], bool]" = field(default=lambda: True)

    _last_state: RigState | None = field(default=None, init=False)
    _held: dict[int, Hold] = field(default_factory=dict, init=False)
    _pressed: set[int] = field(default_factory=set, init=False)

    # -- per tick ---------------------------------------------------------

    def tick(self, now_ms: float) -> None:
        """One frame. Never raises: the service swallows device faults already."""
        if not self._own_surface():
            return
        config = self._config_for_current_state()
        self._arm_on_state_change(config, now_ms)

        overlay = self._overlay(config, now_ms)
        overrides = None
        if config is not None and (provider := self.overrides_for.get(config.id)):
            try:
                overrides = provider()
            except Exception:  # noqa: BLE001 -- a bad override must not blank the surface
                log.exception("override provider for %s failed — painting without it", config.id)
        specs = render(
            config,
            overlay=overlay,
            pressed=frozenset(self._pressed),
            overrides=overrides,
            # Computed here rather than inside render() because the holds are this
            # object's state and the renderer is pure. One tick of lag: a press is
            # read after this call, so its first ramp frame lands 33 ms later.
            holds=hold_leds(self._held, now_ms),
        )

        for event in self.service.tick(now_ms / 1000.0, specs):
            self._on_pad(event, config, now_ms)

        self._expire_holds(now_ms)

    def _own_surface(self) -> bool:
        """
        Take or release the device to match policy, and say whether to paint.

        Releasing clears held pads and any running animation: a hold in progress
        when the surface goes away must not fire two minutes later when it comes
        back, and an animation resumed mid-frame on a device Ableton has been
        driving would paint over its session view.
        """
        try:
            rig_owns = bool(self.rig_owns_surface())
        except Exception:  # noqa: BLE001 -- a bad policy must not blank the rig
            log.exception("surface ownership check failed — keeping the surface")
            rig_owns = True

        if rig_owns:
            self.service.acquire()
            return True

        if not self.service.released:
            self.service.release()
            self._held.clear()
            self._pressed.clear()
            self.player.cancel()
            self._last_state = None  # so the next re-acquire re-arms its intro
        return False

    # -- mode -------------------------------------------------------------

    def _config_for_current_state(self) -> ModeConfig | None:
        try:
            return resolve(self.machine.state, self.library)
        except Exception as exc:  # noqa: BLE001
            # A missing config must not stop the rig. missing_configs() at startup
            # is where this is supposed to be caught; reaching here means the
            # library changed underneath us, and a dark surface beats a dead loop.
            log.error("no surface for %s (%s) — showing nothing", self.machine.state, exc)
            return None

    def _arm_on_state_change(self, config: ModeConfig | None, now_ms: float) -> None:
        state = self.machine.state
        if state == self._last_state:
            return
        self._last_state = state
        self._held.clear()  # a mode change abandons any hold in progress
        self._pressed.clear()
        self.player.cancel()
        if config is None:
            return
        intro = config.animations.get("intro")
        if intro and (anim := self.library.animations.get(intro["ref"])):
            self.player.play(anim, PlayMode.INTRO, now_ms, on_finished=lambda: self._start_during(now_ms))
            log.info("mode %s: intro %s", config.id, intro["ref"])
        else:
            self._start_during(now_ms)

    def _start_during(self, now_ms: float) -> None:
        """The ambient loop, once any intro is out of the way."""
        config = self._config_for_current_state()
        if config is None:
            return
        during = config.animations.get("during")
        if during and (anim := self.library.animations.get(during["ref"])):
            self.player.play(anim, PlayMode.DURING, now_ms)

    def _overlay(self, config: ModeConfig | None, now_ms: float) -> Overlay | None:
        frame = self.player.frame(now_ms)
        if frame is None or config is None:
            return None
        is_intro = self.player.mode is PlayMode.INTRO
        layer = "under"
        if not is_intro:
            during = config.animations.get("during") or {}
            layer = during.get("layer", "under")
        return Overlay(frame=frame, cover=is_intro, layer=layer)

    # -- input ------------------------------------------------------------

    def _on_pad(self, event: PadEvent, config: ModeConfig | None, now_ms: float) -> None:
        if event.pressed:
            self._pressed.add(event.note)
            # Any press skips an intro — §22. The player ignores this for during-loops.
            if self.player.skip():
                self._start_during(now_ms)
            self._press(event.note, config, now_ms)
        else:
            self._pressed.discard(event.note)
            self._release(event.note, now_ms)

    def _press(self, pad: int, config: ModeConfig | None, now_ms: float) -> None:
        if config is None:
            return
        binding = config.pads.get(pad)
        if binding is None or binding.action.type == "NONE":
            return
        action = binding.action
        hold_ms = action.hold_ms or 0
        if hold_ms <= 0:
            self._fire(action.type, action.params, pad)
            return
        self._held[pad] = Hold(pad, action.type, dict(action.params), hold_ms, now_ms)
        self.bus.publish(ActionArmed(action=action.type, pad=pad, hold_ms=hold_ms))
        log.debug("armed %s on pad %d (%d ms)", action.type, pad, hold_ms)

    def _release(self, pad: int, now_ms: float) -> None:
        hold = self._held.pop(pad, None)
        if hold is None:
            return
        # Released before the hold completed: the action did NOT happen, and saying
        # so matters — this is the path that saves a set from a scuffed pad.
        self.bus.publish(
            ActionCancelled(action=hold.action, pad=pad, held_ms=hold.elapsed(now_ms))
        )
        log.info("cancelled %s on pad %d after %.0f ms", hold.action, pad, hold.elapsed(now_ms))

    def _expire_holds(self, now_ms: float) -> None:
        for pad, hold in list(self._held.items()):
            if hold.ready(now_ms):
                del self._held[pad]
                self._fire(hold.action, hold.params, pad)

    def _fire(self, action: str, params: dict, pad: int) -> None:
        log.info("action %s from pad %d", action, pad)
        self.bus.publish(ActionRequested(action=action, params=dict(params), pad=pad))

    # -- introspection ----------------------------------------------------

    @property
    def holding(self) -> dict[int, Hold]:
        """Pads mid-hold. The renderer does not use this yet; §23 progress-ring will."""
        return dict(self._held)
