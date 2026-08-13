"""
Keep trying to reach the phone's hotspot, so the rig is reachable when it matters.

LAYER: Controller policy. Pure — an injected Wi-Fi controller and clock, so the
whole retry rule is testable with no radio.

WHY ACTIVE RETRY AND NOT WINDOWS AUTO-CONNECT
    The profile is already set to connect automatically and it is first in the
    preference order. OBSERVED 2026-08-13: the hotspot was switched off and on, and
    the Beelink -- disconnected at the time, so nothing was holding it back -- did
    not rejoin.

    Two reasons passive auto-join is the wrong mechanism here, and neither is
    fixable in a profile:

      * Windows rescans on its own schedule when idle, of the order of a minute. A
        rig you are trying to reach because something is wrong should not make you
        wait out a scan interval.
      * iOS puts Personal Hotspot to sleep when nothing is attached. It responds to
        a device trying to associate, so something has to KNOCK. Waiting politely
        for a beacon can wait a long time.

    So this asks, repeatedly, whenever it is not connected. That is all it does.

WHAT IT WILL NOT DO
    Touch a working connection. If the rig is on any network, this does nothing at
    all -- no switching, no preference enforcement, no opinion. Matt joining a venue
    wifi by hand must not be undone by a watchdog, and a rig that hops networks
    mid-set to satisfy a policy is worse than one that stays put.

    THE FAILURE MODE THIS ALMOST HAD
        The first version knocked every 20 s forever, from the moment it saw no
        network. A connect attempt aimed at an absent SSID occupies the radio, and
        Windows reassociating with a network it already knows is a process that must
        not be interrupted -- so a watchdog meant to keep the rig reachable could
        instead stop it recovering on its own. SUSPECTED of doing exactly that on
        2026-08-13, when the Beelink went off-network and stayed there.

        Hence the grace period and the backoff. A watchdog must never leave the rig
        LESS reachable than no watchdog at all; if it cannot guarantee that, it
        should not run -- which is why it ships disabled until the fix is verified
        on hardware.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable

log = logging.getLogger(__name__)

__all__ = ["WifiLifeline"]

#: First gap between attempts. Doubles from here -- see MAX_INTERVAL_S.
RETRY_INTERVAL_S = 20.0

#: The ceiling on backoff. A rig that has been away from its hotspot for an hour
#: should be knocking every few minutes, not three times a minute forever.
MAX_INTERVAL_S = 300.0

#: How long the rig must have been off-network before the FIRST knock.
#:
#: This is the important one. A connect attempt aimed at an absent network occupies
#: the radio, and Windows reassociating with a network it already knows is a process
#: that must not be interrupted. Left to itself the adapter recovers; knocked at
#: every 20 seconds it may not. So: let Windows try first, and only start asking
#: once it has clearly failed on its own.
GRACE_S = 60.0


@dataclass
class WifiLifeline:
    """
    Polled from the controller's tick loop; acts at most every retry_interval_s.

    `ssid` empty disables it entirely, which is the right default for a rig that has
    never been told which network is its lifeline.
    """

    wifi: object  # windows.wifi.WifiController
    ssid: str
    clock: Callable[[], float]
    retry_interval_s: float = RETRY_INTERVAL_S
    max_interval_s: float = MAX_INTERVAL_S
    grace_s: float = GRACE_S

    #: Two cadences on purpose. Status is checked at the FIXED interval so a
    #: restored connection is noticed promptly; knocks back off, because they cost
    #: radio time and a status read does not. Sharing one clock meant a rig that had
    #: been away an hour would not notice it was back for another five minutes.
    _next_status_at: float = field(default=0.0, init=False)
    _next_knock_at: float = field(default=0.0, init=False)
    _down_since: float | None = field(default=None, init=False)
    _interval: float = field(default=RETRY_INTERVAL_S, init=False)
    _announced_down: bool = field(default=False, init=False)
    _attempts: int = field(default=0, init=False)

    def poll(self) -> None:
        """Cheap, and safe to call every tick. Never raises into the loop."""
        if not self.ssid:
            return
        now = self.clock()
        if now < self._next_status_at:
            return
        self._next_status_at = now + self.retry_interval_s

        try:
            status = self.wifi.status()
        except Exception as exc:  # noqa: BLE001 -- no radio, no netsh, off-Windows
            log.debug("cannot read wifi status (%s)", exc)
            return

        # ANY route out counts, not just Wi-Fi. A tethered iPhone presents as an
        # ordinary network adapter, and a Wi-Fi-only check would see "no wifi",
        # start knocking, and occupy the radio while the rig was already reachable
        # over the cable.
        if not status.connected and self._has_other_route():
            if self._announced_down:
                log.info("network back over another adapter (tether or ethernet)")
            self._reset()
            return

        if status.connected:
            if self._announced_down:
                log.info("network back: on %r after %d attempt(s)", status.ssid, self._attempts)
            self._reset()
            return

        if self._down_since is None:
            self._down_since = now

        # Let Windows recover on its own first. Knocking during that window is how a
        # watchdog stops the very reassociation it is supposed to help.
        if now - self._down_since < self.grace_s:
            return

        if now < self._next_knock_at:
            return  # backed off; still watching, just not asking yet

        if not self._announced_down:
            # Once, then quietly. Being off-network is this rig's NORMAL state.
            log.info(
                "off-network for %.0fs; asking for %r, backing off up to %.0fs "
                "between attempts",
                self.grace_s, self.ssid, self.max_interval_s,
            )
            self._announced_down = True

        self._attempts += 1
        try:
            self.wifi.connect(self.ssid)
        except Exception as exc:  # noqa: BLE001
            log.debug("connect attempt failed (%s)", exc)

        # Back off. The target may be a hotspot in a bag two towns away, and a rig
        # that never widens its interval is a rig holding the radio hostage.
        self._interval = min(self._interval * 2, self.max_interval_s)
        self._next_knock_at = now + self._interval

    def _has_other_route(self) -> bool:
        """A default gateway on any adapter. False if the check is unavailable."""
        probe = getattr(self.wifi, "has_any_network", None)
        if probe is None:
            return False
        try:
            return bool(probe())
        except Exception:  # noqa: BLE001
            return False

    def _reset(self) -> None:
        self._announced_down = False
        self._attempts = 0
        self._down_since = None
        self._interval = self.retry_interval_s
        self._next_knock_at = 0.0

    @property
    def attempts(self) -> int:
        """Attempts since the last successful connection. For the health check."""
        return self._attempts
