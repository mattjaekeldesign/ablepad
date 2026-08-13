"""
Does the Launchpad send anything to the RIG's port while Ableton owns the device?

THE QUESTION
    Once the rig hands the surface to Ableton, the only way back to the launcher is
    quitting Live. If pressing the Launchpad's Custom button routes pads to
    interface 2 -- the rig's port, which Live does not hold -- then the rig can watch
    for that and take the surface back on demand. Set switching without quitting.

WHAT THE MANUAL SAYS, AND WHY THAT IS NOT ENOUGH
    docs/launchpad-x-sysex.md section 9: the Session/Note/Custom buttons cannot be
    CONTROLLED by the DAW but still SEND their CCs, so a host can observe
    user-driven layout changes. That is about interface 1, which Live owns. Whether
    a Custom layout's pad traffic reaches interface 2 is UNVERIFIED, and it is the
    whole question.

WHAT THIS DELIBERATELY DOES NOT DO
    It does not send. No Programmer Mode, no LED writes, no device settings. Live is
    driving the device and anything written here would fight it -- and would also
    invalidate the measurement, because the answer changes if the device is not in
    the state Live put it in.

RUN IT while Ableton is running with a set loaded and the rig controller STOPPED
(the controller would open this same port).
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

LISTEN_S = 90.0


def main() -> int:
    import mido  # noqa: PLC0415

    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass

    names = mido.get_input_names()
    print("input ports:")
    for n in names:
        print("   ", n)

    rig_port = next((n for n in names if "2 (LPX MIDI)" in n), None)
    daw_port = next((n for n in names if "LPX" in n and "MIDIIN2" not in n), None)
    print()
    print("rig port (interface 2, what we listen on):", rig_port)
    print("daw port (interface 1, Ableton's)        :", daw_port)
    if rig_port is None:
        print("\nthe rig's port is not present -- is the Launchpad plugged in?")
        return 1

    try:
        port = mido.open_input(rig_port)
    except Exception as exc:
        print("\ncould not open %s: %s" % (rig_port, exc))
        print("Something else holds it -- stop the rig controller first.")
        return 1

    # rtmidi drops SysEx by default, and a layout change may well BE SysEx.
    try:
        port._rt.ignore_types(False, False, False)
    except Exception:
        print("(could not clear ignore_types; SysEx may not be visible)")

    print()
    print("listening on interface 2 for %.0fs. Now, on the Launchpad:" % LISTEN_S)
    print("  1. press the CUSTOM button")
    print("  2. press several GRID PADS")
    print("  3. press SESSION to go back, then a few pads again")
    print()

    seen = 0
    end = time.monotonic() + LISTEN_S
    while time.monotonic() < end:
        for message in port.iter_pending():
            seen += 1
            print("  %6.2fs  %s" % (LISTEN_S - (end - time.monotonic()), message))
        time.sleep(0.005)

    port.close()
    print()
    if seen:
        print("RESULT: %d message(s) reached the rig's port while Ableton owned the" % seen)
        print("device. A Custom-layout escape hatch is possible -- the rig can watch")
        print("this port during a performance and take the surface back on demand.")
    else:
        print("RESULT: NOTHING reached the rig's port.")
        print("In Live Mode the device talks only to interface 1, which Ableton holds.")
        print("There is no escape hatch on this port: quitting Live stays the way back,")
        print("and any other route needs a second controller (the Ampero) or Bome.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
