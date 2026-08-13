"""
Set Browser behaviour: pads to sets, and a held pad to a loaded set.

LAYER: Controller policy. Knows what a LOAD_SET means; knows nothing about MIDI,
registries or processes — the launcher and the browser arrive injected.

WHAT IT OWNS
    The mapping between a config's LOAD_SET slots and the browser's current page,
    and the decision to swap sets. Nothing else.

SLOTS, NOT PAD NUMBERS
    configs/set-browser.json already gives every LOAD_SET pad a `slot` param, 0-15,
    laid out so slot 0 is the top-left of the browser block. That indirection is the
    whole point: the layout is a design decision made in the Config Lab, and moving a
    set to a different pad must never mean editing Python.

SWITCHING SETS INTERRUPTS AUDIO
    Accepted and documented (roadmap, known limitations): stopping Ableton and
    starting it on another file is a silence. It is not solvable without two Live
    instances, and that is not this phase. What IS solvable is not doing it by
    accident, which is why LOAD_SET carries a 2000 ms hold.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from ableton.launcher import AbletonLauncher, LaunchRefused
from ableton.supervisor import AbletonSupervisor
from launchpad import colors
from launchpad.mappings import ModeConfig
from rig.events import ActionRequested, EventBus
from rig.exceptions import IllegalTransition
from rig.state import RigState, StateMachine
from set_browser.service import SetBrowserService

log = logging.getLogger(__name__)

__all__ = ["SetBrowserControl"]


@dataclass
class SetBrowserControl:
    browser: SetBrowserService
    config: ModeConfig  # the set-browser mode, for the slot -> pad mapping
    bus: EventBus
    machine: StateMachine
    launcher: AbletonLauncher | None = None
    supervisor: AbletonSupervisor | None = None

    _slot_pads: dict[int, int] = field(default_factory=dict, init=False)
    _loaded: Path | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        for pad, binding in self.config.pads.items():
            if binding.action.type == "LOAD_SET":
                slot = binding.action.params.get("slot")
                if isinstance(slot, int):
                    self._slot_pads[slot] = pad
        log.info("set browser: %d load slots mapped", len(self._slot_pads))
        self.bus.subscribe(ActionRequested, self.on_action)

    # -- what the surface paints -----------------------------------------

    def led_overrides(self) -> dict[int, dict]:
        """
        Per-pad LED for the current page: a colour where a set exists, dark where
        one does not.

        Dark rather than "leave the config's colour" is deliberate. A lit pad on this
        screen is a promise that something will load, and a pad that lies about that
        is worse than a dark one — you find out by standing in silence.
        """
        page = self.browser.current_page()
        overrides: dict[int, dict] = {}
        for slot, pad in self._slot_pads.items():
            if slot < len(page.items):
                live_set = page.items[slot]
                overrides[pad] = {"type": "static", "palette": colors.by_name(live_set.color)}
            else:
                overrides[pad] = {"type": "off"}
        return overrides

    # -- what the surface reports ----------------------------------------

    def on_action(self, event: ActionRequested) -> None:
        if event.action == "LOAD_SET":
            self._load(event.params.get("slot"))
        elif event.action == "PAGE_NEXT":
            page = self.browser.next_page()
            log.info("page %d/%d", page.index + 1, page.page_count)
        elif event.action == "PAGE_PREV":
            page = self.browser.prev_page()
            log.info("page %d/%d", page.index + 1, page.page_count)
        elif event.action == "RESCAN_SETS":
            count = self.browser.rescan()
            log.info("rescan found %d set(s)", count)
            if self.browser.is_empty:
                # The browser reports emptiness; the CALLER decides it is an error.
                self.machine.transition(RigState.ERROR, "no sets found")

    # -- internals --------------------------------------------------------

    def _load(self, slot: object) -> None:
        if not isinstance(slot, int):
            log.error("LOAD_SET without a valid slot: %r", slot)
            return
        live_set = self.browser.set_at(slot)
        if live_set is None:
            # An unlit pad. Reachable because the surface reports every press, and
            # ignoring it is the right answer -- not an error state.
            log.info("slot %d is empty — nothing to load", slot)
            return
        if self.launcher is None:
            log.warning("would load %s, but no launcher is wired", live_set.display_name)
            return
        if self._loaded == live_set.path:
            log.info("%s is already loaded", live_set.display_name)
            return

        log.info("loading %s", live_set.display_name)
        # Stop first, and accept the silence. One Ableton owns the ASIO device; two
        # would fight over it, and the second would lose in a way that looks like a
        # broken interface rather than a mistake.
        self.launcher.stop()
        try:
            self.launcher.launch(live_set.path)
        except LaunchRefused as exc:
            log.error("refusing to load %s: %s", live_set.display_name, "; ".join(exc.reasons))
            self.machine.transition(RigState.ERROR, f"cannot load {live_set.display_name}")
            return
        self._loaded = live_set.path
        if self.supervisor is not None:
            self.supervisor.watch(live_set.path)
        try:
            self.machine.transition(RigState.PERFORMANCE, f"SET_LOADED {live_set.display_name}")
        except IllegalTransition as exc:
            # The set IS loaded -- Ableton is running it. Refusing to move state is a
            # table problem, not a reason to take the rig down mid-load, and this
            # runs inside an event handler on the tick loop. Loud, and survivable.
            log.error(
                "loaded %s but could not enter PERFORMANCE: %s. The set is running; "
                "the state machine disagrees, which is a bug in the transition table.",
                live_set.display_name, exc,
            )

    def forget_loaded(self) -> None:
        """
        Nothing is loaded any more. Called when Ableton exits, so the pad for the set
        that was playing becomes pressable again instead of a silent no-op.
        """
        self._loaded = None

    def mark_loaded(self, path: Path) -> None:
        """Tell the control what boot already launched, so re-pressing it is a no-op."""
        self._loaded = path
