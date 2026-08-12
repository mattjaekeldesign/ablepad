"""
Record what Get-PnpDevice actually returns for the audio interface.

LAYER: none. Bench instrument. No Launchpad involved -- this one never opens MIDI.

ANSWERS
    The exact friendly-name strings AudioInterfaceDetector matches on, for the
    Audient EVO 8 — and, just as importantly, WHICH of its several endpoints is the
    one that means "the interface is present".

WHY THE STRINGS HAVE TO BE VERBATIM
    Phase 5's launcher refuses to start Ableton when the interface is absent. That
    check is only as good as its match. A guessed substring produces the worst
    possible failure: the rig refuses to launch at a gig, for a reason that looks
    like the interface is broken.

    Bome cannot help here at all. It sees MIDI devices only; the EVO 8 is a
    MEDIA-class audio device and is invisible to it. Detection stays in Python
    regardless of how Phase 8 lands.

THE EVO 8 IS NOT ONE DEVICE TO WINDOWS
    Its manual shows at least two distinct endpoint names in the Sound control panel
    — "EVO 8 Main Output 1+2" (p.14) and "Loop-back 1+2" (p.36) — plus inputs. Those
    are what Windows DISPLAYS; Get-PnpDevice FriendlyName is a different field and is
    not guaranteed to match. This tool records all of them so the choice is made from
    evidence rather than from the manual's screenshots.

    Loop-back is NOT the endpoint to gate on. It is a virtual routing channel; its
    presence says nothing useful about whether audio can reach a mixer.

PRESENCE IS NOT HEALTH
    The EVO 8 manual states that an electrostatic discharge can make the unit "cease
    to output sound", recoverable only by unplugging and re-connecting (p.10). A unit
    in that state may still enumerate perfectly. Everything this tool records answers
    "is it there?" — it cannot answer "is it working?". Do not let a green result from
    this tool become the rig's definition of a healthy audio path.
    See docs/audient-evo-8-reference.md §6.

RUN IT ONCE PER SETUP
    Pass --label to keep runs apart — e.g. before and after a driver install, or on
    USB-A vs USB-C (which changes how many phantom channels are available, p.22):
        python tools/interface_name_inspector.py --label evo8-usbc
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys

from _bench import Recorder, require_windows

# Present-only. A ghost entry for an interface that is currently unplugged is
# exactly the false positive the Phase 5 guard exists to prevent, so the query the
# detector eventually ships must filter on Status too.
PNP_QUERY = (
    "Get-PnpDevice -PresentOnly "
    "| Where-Object { $_.Class -in @('MEDIA','AudioEndpoint','USB','SoundVideoAndGameControllers') } "
    "| Select-Object FriendlyName, Class, Status, InstanceId "
    "| ConvertTo-Json -Depth 3"
)

INTERESTING = ("evo", "audient", "usb audio", "loop-back", "loopback")

# Endpoint names the EVO 8 manual shows in the Windows Sound control panel. These are
# HINTS for reading the output, not a match list — the manual is showing a different
# field from the one Get-PnpDevice reports. If the strings below never appear, that is
# a finding worth recording, not a bug to work around.
MANUAL_NAMES = {
    "EVO 8 Main Output 1+2": "manual p.14 — the main playback endpoint",
    "Loop-back 1+2": "manual p.36 — virtual routing, NOT a presence signal",
}


def run_powershell(query: str) -> list[dict]:
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", query],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "powershell exited non-zero")

    output = completed.stdout.strip()
    if not output:
        return []

    parsed = json.loads(output)
    # ConvertTo-Json emits a bare object, not a list, when there is one result.
    return parsed if isinstance(parsed, list) else [parsed]


def looks_relevant(device: dict) -> bool:
    name = (device.get("FriendlyName") or "").lower()
    return any(token in name for token in INTERESTING)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", default="run", help="tag for the output filename")
    parser.add_argument("--all", action="store_true", help="list every device, not just audio")
    args = parser.parse_args()

    print("\n=== Audio interface name inspector ===")
    print("Purpose: capture verbatim Get-PnpDevice friendly names")
    print("Answers: the match strings for AudioInterfaceDetector\n")

    require_windows("interface_name_inspector.py")

    rec = Recorder(tool="interface_name_inspector.py")
    rec.add(f"# Label: {args.label}")
    rec.add(f"# Query: {PNP_QUERY}")
    rec.add()

    try:
        devices = run_powershell(PNP_QUERY)
    except Exception as exc:  # noqa: BLE001
        print(f"  PowerShell query failed: {exc}")
        return 1

    rec.add(f"# --- {len(devices)} AUDIO-CLASS DEVICES PRESENT ---")
    for device in devices:
        name = device.get("FriendlyName") or "(no friendly name)"
        marker = " <<<" if looks_relevant(device) else ""
        rec.add(f"#   [{device.get('Status', '?'):>2}] {device.get('Class', '?'):<28} {name!r}{marker}")
    rec.add()

    relevant = [d for d in devices if looks_relevant(d)]

    if not relevant:
        rec.add("# No EVO 8 / Audient device matched. Either it is unplugged, the Windows")
        rec.add("# driver is not installed (the EVO 8 is NOT class-compliant on Windows,")
        rec.add("# manual p.13), or its friendly name uses wording this tool does not look")
        rec.add("# for. Check the full list above and widen INTERESTING rather than")
        rec.add("# guessing a match string.")
        rec.save(f"interface-names-{args.label}.txt")
        return 0

    rec.add(f"# --- {len(relevant)} MATCHING ENDPOINT(S), FULL DETAIL ---")
    for device in relevant:
        name = device.get("FriendlyName") or ""
        rec.add(f"#   FriendlyName : {name!r}")
        rec.add(f"#   Class        : {device.get('Class')!r}")
        rec.add(f"#   Status       : {device.get('Status')!r}")
        rec.add(f"#   InstanceId   : {device.get('InstanceId')!r}")
        for known, note in MANUAL_NAMES.items():
            if known.lower() in name.lower():
                rec.add(f"#   -> matches a name printed in the manual: {note}")
        rec.add("#")
    rec.add()

    # The manual's names are what the Sound control panel shows. Whether Get-PnpDevice
    # agrees is exactly what this run is for -- so say either way, explicitly.
    seen = " ".join((d.get("FriendlyName") or "").lower() for d in relevant)
    rec.add("# --- DOES Get-PnpDevice AGREE WITH THE MANUAL? ---")
    for known, note in MANUAL_NAMES.items():
        hit = known.lower() in seen
        rec.add(f"#   {'FOUND    ' if hit else 'NOT FOUND'} {known!r}  ({note})")
    if not any(k.lower() in seen for k in MANUAL_NAMES):
        rec.add("#   Neither manual name appears. That is a real finding: the control-panel")
        rec.add("#   name and the PnP FriendlyName are different fields. Use what is above.")
    rec.add()

    rec.add("# --- PASTE INTO config/rig.yaml ---")
    rec.add()
    rec.add("audio_interface:")
    rec.add("  # Substring match, not whole-string: friendly names can carry a trailing")
    rec.add("  # instance number that changes across re-enumeration. Verify by replugging")
    rec.add("  # and re-running this tool.")
    rec.add("  match_any:")
    rec.add("    - 'EVO 8'")
    rec.add("  require_status: OK")
    rec.add()
    rec.add("# Endpoints observed this run, for the record:")
    for device in relevant:
        rec.add(f"#     {device.get('FriendlyName')!r}  [{device.get('Status')}]")
    rec.add()
    rec.add("# CHOOSE THE PRESENCE ENDPOINT DELIBERATELY. The EVO 8 exposes several, and")
    rec.add("# Loop-back is a virtual routing channel -- its presence says nothing about")
    rec.add("# whether audio can reach a mixer. Gate on the main output, not on whatever")
    rec.add("# happens to sort first.")
    rec.add("#")
    rec.add("# AND: Status == OK is still only PRESENCE. An ESD event can leave the EVO 8")
    rec.add("# enumerated but silent, recoverable only by a physical replug (manual p.10).")
    rec.add("# Phase 5's guard prevents launching into a MISSING interface; it cannot")
    rec.add("# detect a wedged one. That needs a separate health check -- see")
    rec.add("# docs/audient-evo-8-reference.md section 6.")

    rec.save(f"interface-names-{args.label}.txt")

    print("\n  Re-run with a different --label after any driver install, and on both")
    print("  USB-A and USB-C -- the port changes how many phantom channels work (p.22),")
    print("  and may change enumeration.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
