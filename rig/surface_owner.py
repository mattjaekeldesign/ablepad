"""
Who should be driving the Launchpad right now: this rig, or Ableton.

LAYER: Controller policy. Pure — takes facts, returns a decision. Touches no
device, opens no port, so every rule below is testable off-rig.

THE POINT OF THE WHOLE THING
    The Launchpad is the rig's operating system interface, and it is also a Live
    controller. Those are different jobs and they cannot both be happening: the rig
    drives the device in Programmer Mode on interface 2, while Live's Launchpad X
    script drives DAW mode on interface 1, and Programmer Mode is DEVICE-WIDE. One
    of them has to let go.

    Matt's requirement, and it is the right one: the Launchpad is a launcher until
    a set is open, then it becomes a normal Live controller and the system stuff
    gets out of the way.

WHY OWNERSHIP FOLLOWS ABLETON AND NOT THE MODE TREE
    Live's control surface does not wait to be handed anything. From the moment
    Live starts with Launchpad X enabled, its script owns interface 1 and will put
    the device into DAW mode -- knocking it out of Programmer Mode underneath the
    rig. So "rig paints while Ableton runs" is not a state we can be in, whatever
    the mode tree says.

    That is why the Set Browser cannot coexist with a running Ableton, and why
    quitting Live is what brings the launcher back.

THE ONE OVERRIDE
    ERROR always takes the surface back, even mid-set. If the EVO has gone silent
    -- and an ESD-wedged EVO enumerates perfectly while outputting nothing -- then
    a Launchpad still showing Ableton's session view is a rig that looks healthy
    and makes no sound. That is the single worst thing this surface can do on
    stage. Stealing it back to show a fault is not a discourtesy to Ableton; it is
    the only moment the surface has something urgent to say.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from rig.state import RigState

log = logging.getLogger(__name__)

__all__ = ["SurfaceOwner", "Owner"]


class Owner:
    """Not an Enum on purpose -- two values, used as booleans at every call site."""

    RIG = "rig"
    ABLETON = "ableton"


#: States in which the rig hands the surface to Ableton, PROVIDED Ableton is
#: actually up. A table rather than `state is PERFORMANCE` so that adding a state
#: later is a decision someone has to make explicitly rather than inherit.
_HANDS_OVER: dict[RigState, bool] = {
    RigState.BOOT: False,  # nothing is loaded yet; the rig is the only UI there is
    RigState.SET_BROWSER: True,  # only reachable with Ableton down, but see below
    RigState.PERFORMANCE: True,  # the whole point
    RigState.SYSTEM: False,  # system controls are the rig's own screen
    RigState.ERROR: False,  # THE override -- see the module docstring
    RigState.SHUTDOWN: False,  # going down; a dark rig-owned surface is honest
}


@dataclass
class SurfaceOwner:
    """
    Decides ownership from rig state plus whether Ableton is up.

    `enabled` False keeps the rig on the surface always, which is the behaviour
    every phase before this had. Kept as a switch because handover depends on
    Ableton being configured with the Launchpad X control surface -- a manual step
    in Live's Preferences that this rig cannot verify or perform.
    """

    enabled: bool = True

    _last: str | None = field(default=None, init=False)

    def owner(self, state: RigState, ableton_ready: bool) -> str:
        """
        Who should have the surface. Logs only when the answer CHANGES -- this is
        called every tick, 30 times a second.
        """
        decision = self._decide(state, ableton_ready)
        if decision != self._last:
            if self._last is not None:
                log.info(
                    "launchpad handover: %s -> %s (state=%s, ableton_ready=%s)",
                    self._last, decision, state.value, ableton_ready,
                )
            self._last = decision
        return decision

    def rig_owns(self, state: RigState, ableton_ready: bool) -> bool:
        return self.owner(state, ableton_ready) == Owner.RIG

    # -- internals --------------------------------------------------------

    def _decide(self, state: RigState, ableton_ready: bool) -> str:
        if not self.enabled:
            return Owner.RIG
        if not _HANDS_OVER.get(state, False):
            return Owner.RIG
        if not ableton_ready:
            # Handing over to a process that is not there would leave the surface
            # dark and unresponsive with nothing driving it -- the rig would look
            # dead while working perfectly.
            return Owner.RIG
        return Owner.ABLETON
