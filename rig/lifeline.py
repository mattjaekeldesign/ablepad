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

    That also makes the failure mode benign: the worst this can do is ask an absent
    network for a connection every 20 seconds, which costs nothing and logs once.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable

log = logging.getLogger(__name__)

__all__ = ["WifiLifeline"]

#: Seconds between attempts while disconnected. Short enough that switching the
#: hotspot on and putting the phone in a pocket is enough, long enough that it is
#: not hammering the radio -- each attempt is a real association attempt, not a scan.
RETRY_INTERVAL_S = 20.0


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

    _next_attempt_at: float = field(default=0.0, init=False)
    _announced_down: bool = field(default=False, init=False)
    _attempts: int = field(default=0, init=False)

    def poll(self) -> None:
        """Cheap, and safe to call every tick. Never raises into the loop."""
        if not self.ssid:
            return
        now = self.clock()
        if now < self._next_attempt_at:
            return
        self._next_attempt_at = now + self.retry_interval_s

        try:
            status = self.wifi.status()
        except Exception as exc:  # noqa: BLE001 -- no radio, no netsh, off-Windows
            log.debug("cannot read wifi status (%s)", exc)
            return

        if status.connected:
            if self._announced_down:
                log.info("network back: on %r after %d attempt(s)", status.ssid, self._attempts)
                self._announced_down = False
                self._attempts = 0
            return

        if not self._announced_down:
            # Once, then quietly. Being off-network is the NORMAL state of this rig
            # -- it is offline by design -- so this must not fill the log.
            log.info(
                "no network; will keep asking for %r every %.0fs so the lifeline is "
                "there when it is needed",
                self.ssid, self.retry_interval_s,
            )
            self._announced_down = True

        self._attempts += 1
        try:
            self.wifi.connect(self.ssid)
        except Exception as exc:  # noqa: BLE001
            log.debug("connect attempt failed (%s)", exc)

    @property
    def attempts(self) -> int:
        """Attempts since the last successful connection. For the health check."""
        return self._attempts
