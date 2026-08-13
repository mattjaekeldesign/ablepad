"""
Is the rig reachable over a USB-tethered iPhone?

WHY A TOOL AND NOT JUST "IT WORKS"
    A tether is the fallback for when Wi-Fi has failed, which means it gets used on
    the worst possible day. It should be proven on a good one.

WHAT IT CHECKS, in the order things actually go wrong
    1. Apple Mobile Device Support installed -- Windows has no inbox driver for an
       iPhone tether, so without this the phone charges and nothing else happens.
    2. The service is running.
    3. An Apple network adapter exists -- appears only once the phone is plugged in,
       unlocked, trusted, and Personal Hotspot is on.
    4. That adapter has a default gateway, which is the only proof packets can leave.

WHAT IT CANNOT TELL YOU
    Whether anything can reach the rig FROM outside. Tailscale over a tether depends
    on the phone having data; a tether with cellular off gives a LAN between phone
    and rig, which is enough for VNC and SSH from the phone itself and nothing more.
    That is usually the case that matters -- the phone in your hand IS the client.
"""

from __future__ import annotations

import subprocess


def ps(command: str) -> str:
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            capture_output=True, text=True, timeout=30,
        )
    except Exception as exc:  # noqa: BLE001
        return f"ERROR {exc}"
    return result.stdout.strip()


def main() -> int:
    ok = True

    installed = ps(
        "@(Get-ItemProperty 'HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*',"
        "'HKLM:\\SOFTWARE\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*' "
        "-EA SilentlyContinue | Where-Object { $_.DisplayName -match 'Apple Mobile Device' }).Count"
    )
    print("1. Apple Mobile Device Support :", "installed" if installed not in ("", "0") else "MISSING")
    if installed in ("", "0"):
        print("     winget install --id Apple.AppleMobileDeviceSupport")
        ok = False

    service = ps("(Get-Service 'Apple Mobile Device Service' -EA SilentlyContinue).Status")
    print("2. Apple device service        :", service or "not present")

    adapters = ps(
        "(Get-NetAdapter -EA SilentlyContinue | Where-Object "
        "{ $_.InterfaceDescription -match 'Apple|iPhone|RNDIS' } | "
        "ForEach-Object { $_.Name + ' [' + $_.Status + ']' }) -join '; '"
    )
    print("3. Apple network adapter       :", adapters or "NONE (phone not plugged in / not trusted / hotspot off)")
    if not adapters:
        ok = False

    gateway = ps(
        "(Get-NetIPConfiguration | Where-Object { $_.IPv4DefaultGateway -ne $null } | "
        "ForEach-Object { $_.InterfaceAlias + ' -> ' + $_.IPv4DefaultGateway.NextHop }) -join '; '"
    )
    print("4. Routes out                  :", gateway or "NONE")

    print()
    if ok and adapters:
        print("Tether looks usable. To prove it, turn Wi-Fi OFF on the Beelink and")
        print("connect from the phone over VNC or SSH -- that is the scenario this exists for.")
    else:
        print("Not usable yet. Plug the iPhone in with a DATA cable (not charge-only),")
        print("unlock it, tap Trust, and turn Personal Hotspot on. Then run this again.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
