"""
A few seconds to pick a set before the rig picks one for you.

LAYER: Controller policy. Pure -- injected clock, no device, no process.

WHY IT EXISTS
    OBSERVED on the first cold boot, 2026-08-13: the rig launched boot_set the
    instant it started, and by the time a human was looking the surface already
    belonged to Ableton. So the Set Browser existed at boot and was unreachable at
    boot -- "ableton auto boots so i never had the chance to choose a set".

WHAT IT DOES
    Shows the Set Browser at startup so a set can be chosen before anything loads.

    Two behaviours, and the default CHANGED on 2026-08-13 after the first real use:
    originally it auto-loaded boot_set when the window expired, on the reasoning
    that an unattended rig must reach a playable state on its own. Matt's verdict on
    seeing it: "live launched auto which is a big no... i must be able to choose the
    set i want to boot into". Launching the WRONG set is worse than launching
    nothing, so rig.boot_requires_choice now defaults true and the rig waits.

    The cost is real and accepted: a rig powering up unattended sits here forever.
    That is the right trade for an instrument somebody stands in front of, and
    boot_requires_choice=false restores the timeout for one that is not.

    Pressing a set during the window cancels it -- the press IS the choice, and
    counting down afterwards would either load two sets or ignore the one you asked
    for.

WHY IT SITS IN BOOT AND NOT BEFORE IT
    The boot gate is already running and already has its own timeout, so a few
    seconds here comes out of that budget rather than adding to it. Set
    rig.boot_choice_s to 0 to restore the old behaviour exactly.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable

from rig.events import ActionRequested, EventBus
from rig.exceptions import IllegalTransition
from rig.state import RigState, StateMachine

log = logging.getLogger(__name__)

__all__ = ["BootChoice"]


@dataclass
class BootChoice:
    seconds: float
    clock: Callable[[], float]
    machine: StateMachine
    bus: EventBus
    #: Wait until a set is chosen rather than loading the default when the window
    #: expires. `seconds` is then only the point at which the log says so.
    require_choice: bool = False
    #: True when the rig could actually launch a set right now -- Launchpad attached,
    #: audio interface present. Until it is, the browser is NOT shown and Boot Mode's
    #: animation keeps playing.
    #:
    #: OBSERVED 2026-08-13: without this the bank appeared immediately, before the
    #: rig could act on it, and pressing a pad did nothing. "this is where i wanted
    #: the rain animation before the bank because then i know when its truly ready to
    #: launch live". A surface offering choices it cannot honour is worse than one
    #: that plainly says "not yet".
    ready: "Callable[[], bool]" = lambda: True

    _started_at: float | None = field(default=None, init=False)
    _done: bool = field(default=False, init=False)
    _nagged: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        self.bus.subscribe(ActionRequested, self._on_action)

    def waiting(self, now: float) -> bool:
        """
        True while boot should hold off launching. Safe to call every tick.

        Also performs the transition into the browser on the first call, because
        the window is only meaningful if the surface is showing the sets.
        """
        if self._done or self.seconds <= 0:
            return False

        if self._started_at is None:
            # Not ready to launch anything yet: stay in Boot Mode, keep its animation
            # running, and do not offer a choice that cannot be acted on.
            try:
                if not self.ready():
                    return True
            except Exception:  # noqa: BLE001 -- a broken probe must not stall boot
                log.exception("readiness check failed — showing the browser anyway")
            self._started_at = now
            try:
                self.machine.transition(RigState.SET_BROWSER, "BOOT_CHOICE")
            except IllegalTransition as exc:
                # Not worth stalling boot over. Skip the window and carry on.
                log.warning("cannot show the browser at boot (%s) — loading the default", exc)
                self._done = True
                return False
            log.info(
                "choose a set%s",
                ""
                if self.require_choice
                else " — the default loads on its own in %.0fs" % self.seconds,
            )
            return True

        if now - self._started_at >= self.seconds:
            if self.require_choice:
                # Nothing loads until a human picks. Said once, not every tick.
                if not self._nagged:
                    self._nagged = True
                    log.info(
                        "waiting for a set to be chosen — nothing loads until a pad "
                        "is held (rig.boot_requires_choice)"
                    )
                return True
            log.info("no set chosen — loading the default")
            self._finish()
            return False
        return True

    def _on_action(self, event: ActionRequested) -> None:
        if event.action == "LOAD_SET" and not self._done:
            # The press IS the choice. Counting down afterwards would either load two
            # sets or ignore the one that was asked for.
            log.info("set chosen during the boot window — cancelling the default")
            self._finish(chosen=True)

    def _finish(self, chosen: bool = False) -> None:
        """
        Close the window. Deliberately does NOT move the rig back to BOOT.

        SET_BROWSER -> BOOT is not in the transition table and should not be: going
        backwards is not a thing this rig does. Nothing needs it either -- the boot
        gate is latched rather than keyed on state, so it keeps evaluating from
        wherever we are, and the handover rules take the surface once Ableton is up.
        """
        self._done = True
        self.chosen = chosen

    chosen: bool = field(default=False, init=False)
