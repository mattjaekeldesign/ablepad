"""
Set up the offline lifeline: make the Beelink auto-join a phone hotspot.

WHY THE PHONE MAKES THE NETWORK
    MEASURED 2026-08-13: this adapter reports "Hosted network supported: No", so the
    Beelink cannot be the access point without an internet connection to share.
    The phone can, and an iPhone Personal Hotspot gives a LAN with cellular data
    off -- which is all VNC and SSH need.

USAGE (on the rig)
    tools\\wifi_lifeline.py                 show status and stored profiles
    tools\\wifi_lifeline.py --auto "SSID"   make that network auto-join

THE ONE MANUAL STEP
    Join the hotspot once from Windows, with the password. This tool cannot do that
    and deliberately has no way to: a password typed into a script ends up in a shell
    history, a log, or a repo. After that one join Windows stores the profile and
    everything here works unattended.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="offline Wi-Fi lifeline")
    parser.add_argument("--auto", metavar="SSID", help="set this network to auto-connect")
    args = parser.parse_args(argv)

    from windows.wifi import WindowsWifi  # noqa: PLC0415 -- platform import

    wifi = WindowsWifi()
    status = wifi.status()

    print("connected :", status.ssid if status.connected else "no")
    print("profiles  :")
    for name in status.known:
        mark = " <- current" if name == status.ssid else ""
        print("   ", name + mark)
    if not status.known:
        print("    (none stored)")

    if not args.auto:
        print()
        print("To set the lifeline up:")
        print("  1. On the iPhone: Settings -> Personal Hotspot -> on")
        print("  2. On the Beelink: join it once from the Wi-Fi menu, with the password")
        print('  3. Run: tools\\\\wifi_lifeline.py --auto "<hotspot name>"')
        print()
        print("iOS turns Personal Hotspot off after a couple of minutes with nothing")
        print("connected, so switch it on and give the Beelink a few seconds to find")
        print("it. Once attached it stays up.")
        return 0

    ok = wifi.set_auto_connect(args.auto)
    if not ok:
        print()
        print("Could not set auto-connect. Join %r once from Windows first." % args.auto)
        return 1
    print()
    print("%r will now be joined automatically whenever it is in range." % args.auto)
    print("Test it: turn the hotspot off and on, and watch this command's output.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
