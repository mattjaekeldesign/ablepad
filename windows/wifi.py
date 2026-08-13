"""
Joining a known Wi-Fi network automatically — the offline lifeline.

LAYER: Drivers (OS). Windows-specific; everything above is written against the
Protocol so the rig stays testable off-rig.

WHY THIS AND NOT A HOTSPOT ON THE BEELINK
    The plan was for the Beelink to BE the access point, so a phone could join it
    with no internet anywhere. MEASURED 2026-08-13:

        netsh wlan show drivers -> "Hosted network supported : No"

    The Intel AX101's driver has dropped the legacy SoftAP, which was the only mode
    that runs an access point with nothing to share. What remains is Windows Mobile
    Hotspot, built around sharing an internet connection and generally refusing
    without one — useless for a rig that is offline by design.

    So the direction reverses: the PHONE makes the network and the Beelink joins it.
    An iPhone Personal Hotspot provides a LAN even with cellular data off, which is
    all VNC and SSH need.

WHAT AUTO-CONNECT ACTUALLY REQUIRES
    A stored profile with connectionMode=auto. Windows then joins whenever the SSID
    appears, with no interaction — which is the whole requirement, because on a
    headless rig there is nobody to click "connect".

THE iOS BEHAVIOUR TO DESIGN AROUND
    Personal Hotspot stops advertising after a couple of minutes with nothing
    connected, unless the Settings screen is open. This is not a bug to fix here and
    cannot be fixed here: it means the phone should be turned on and then given a
    few seconds, and the Beelink -- which is always scanning -- will find it. Once a
    device is attached the hotspot stays up.

A PERMISSION THAT LOOKS LIKE A BUG
    MEASURED 2026-08-13: `netsh wlan show interfaces` refuses to report the SSID
    unless Location Services is on -- "Network shell commands need location
    permission", WlanQueryInterface error 5. It is not an elevation problem; the rig
    runs elevated and still gets it, and netsh reports it on stdout with exit code
    ZERO, so a returncode check reads it as success.

    Only the SSID read is affected. Listing profiles and setting connectionmode --
    the two calls auto-connect actually needs -- work regardless, which is why the
    lifeline does not depend on turning Location on. Status falls back to
    Get-NetConnectionProfile, which answers "am I on the hotspot" without it.

WHAT THIS MODULE WILL NOT DO
    Store a password. add_profile() takes one and hands it to netsh; nothing here
    writes it to disk or logs it. The profile then lives in Windows' own store,
    which is where a Wi-Fi credential belongs.
"""

from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass

log = logging.getLogger(__name__)

__all__ = ["WifiController", "WindowsWifi", "NetworkStatus"]


@dataclass(frozen=True)
class NetworkStatus:
    connected: bool
    ssid: str | None
    #: Profiles stored on the machine, in Windows' own preference order.
    known: tuple[str, ...] = ()


class WifiController:
    """The seam. Faked in tests."""

    def status(self) -> NetworkStatus: ...

    def known_profiles(self) -> tuple[str, ...]: ...

    def set_auto_connect(self, ssid: str) -> bool: ...


@dataclass
class WindowsWifi:
    """
    netsh, because it is present on every Windows, needs no dependency, and its
    output has been stable for a decade. The WinRT Wi-Fi API is richer and needs
    packaging work that buys nothing for "join this one network automatically".
    """

    interface: str = "Wi-Fi"

    def status(self) -> NetworkStatus:
        """
        What we are on, and what we know how to join.

        The profile list is gathered even when the SSID cannot be read, because the
        two need different permissions and the profiles are the half that matters:
        auto-connect is configured from them.
        """
        known = self.known_profiles()
        out = self._netsh(["wlan", "show", "interfaces"])
        if out is None or "Access is denied" in out:
            # MEASURED 2026-08-13: modern Windows gates SSID reads behind Location
            # Services -- "Network shell commands need location permission ...
            # WlanQueryInterface returns error 5". Nothing to do with elevation; the
            # rig runs elevated and still gets it.
            ssid = self._ssid_without_location()
            return NetworkStatus(connected=ssid is not None, ssid=ssid, known=known)
        state = self._field(out, "State")
        ssid = self._field(out, "SSID")
        connected = bool(state and state.lower().startswith("connected"))
        return NetworkStatus(
            connected=connected, ssid=ssid if connected else None, known=known
        )

    @staticmethod
    def _ssid_without_location() -> str | None:
        """
        The connected network's name via Get-NetConnectionProfile, which does not
        need Location permission. For a Wi-Fi adapter its Name IS the SSID.

        Less precise than netsh, in a way worth knowing. MEASURED 2026-08-13: this
        returned "Verizon_Monk 2" while the stored PROFILE is named "Verizon_Monk" --
        Windows suffixes a connection profile when it has seen the same network more
        than once. So do NOT compare this against known_profiles() for equality; it
        answers "roughly where am I", not "which stored profile is in use".
        """
        try:
            result = subprocess.run(
                [
                    "powershell", "-NoProfile", "-Command",
                    "(Get-NetConnectionProfile | Where-Object "
                    "{ $_.InterfaceAlias -like 'Wi-Fi*' } | "
                    "Select-Object -First 1 -ExpandProperty Name)",
                ],
                capture_output=True, text=True, timeout=20,
            )
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
            return None
        name = result.stdout.strip()
        return name or None

    def known_profiles(self) -> tuple[str, ...]:
        out = self._netsh(["wlan", "show", "profiles"])
        if out is None:
            return ()
        # "    All User Profile     : <name>" -- the name can contain colons and
        # spaces, so split once from the left and keep the rest.
        found = []
        for line in out.splitlines():
            if "All User Profile" in line and ":" in line:
                found.append(line.split(":", 1)[1].strip())
        return tuple(found)

    def set_auto_connect(self, ssid: str) -> bool:
        """
        Make Windows join this network whenever it appears. Idempotent.

        Returns False if the profile does not exist -- the password has to be
        entered once, by a human, and this module deliberately has no way to do
        that unattended.
        """
        if ssid not in self.known_profiles():
            log.error(
                "no stored profile for %r, so it cannot be set to auto-connect. "
                "Join it once from Windows (with the password) and run this again.",
                ssid,
            )
            return False
        out = self._netsh(
            ["wlan", "set", "profileparameter", f'name={ssid}', "connectionmode=auto"]
        )
        if out is None:
            return False
        log.info("%r will now be joined automatically whenever it is in range", ssid)
        return True

    def has_any_network(self) -> bool:
        """
        Is this machine on ANY network -- Wi-Fi, Ethernet, or a tethered phone?

        Asked because the lifeline must not knock at a hotspot while the rig is
        perfectly reachable over a USB tether. An iPhone tether presents as an
        ordinary network adapter, so a Wi-Fi-only check would see "no wifi", start
        knocking, and occupy the radio for nothing.

        Judged on having a DEFAULT GATEWAY rather than on adapter state: an adapter
        can be Up and connected to nothing useful, and "can packets leave" is the
        question that actually matters.
        """
        try:
            result = subprocess.run(
                [
                    "powershell", "-NoProfile", "-Command",
                    "@(Get-NetIPConfiguration | Where-Object "
                    "{ $_.IPv4DefaultGateway -ne $null }).Count",
                ],
                capture_output=True, text=True, timeout=20,
            )
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
            return False
        try:
            return int(result.stdout.strip() or "0") > 0
        except ValueError:
            return False

    def connect(self, ssid: str) -> bool:
        """Join now, rather than waiting for the scan. Used by the bench tools."""
        out = self._netsh(["wlan", "connect", f'name={ssid}'])
        return out is not None

    # -- internals --------------------------------------------------------

    @staticmethod
    def _field(text: str, label: str) -> str | None:
        """
        First `label : value` line. Deliberately anchored on the label at the START
        of a stripped line: "SSID" also appears inside "BSSID", and matching that
        would report the access point's MAC as the network name.
        """
        pattern = re.compile(rf"^{re.escape(label)}\s*:\s*(.+)$", re.M)
        for line in text.splitlines():
            match = pattern.match(line.strip())
            if match:
                return match.group(1).strip()
        return None

    def _netsh(self, args: list[str]) -> str | None:
        try:
            result = subprocess.run(
                ["netsh", *args], capture_output=True, text=True, timeout=20
            )
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired) as exc:
            log.debug("netsh %s failed: %s", " ".join(args), exc)
            return None
        if result.returncode != 0:
            log.debug("netsh %s returned %d: %s", " ".join(args), result.returncode,
                      result.stderr.strip())
            return None
        # netsh reports the Location-permission refusal on STDOUT with a zero exit
        # code, so a returncode check alone reads it as success and then parses a
        # help message for an SSID.
        return result.stdout
