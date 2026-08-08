"""
Record what Get-PnpDevice actually returns for the audio interface.

LAYER: none. Bench instrument. No Launchpad involved -- this one never opens MIDI.

ANSWERS
    The exact friendly-name strings AudioInterfaceDetector matches on, for every
    Scarlett you own.

WHY THE STRINGS HAVE TO BE VERBATIM
    Phase 5's launcher refuses to start Ableton when the interface is absent. That
    check is only as good as its match. A guessed substring that happens to work on
    one Scarlett and not another produces the worst possible failure: the rig refuses
    to launch at a gig, for a reason that looks like the interface is broken.

    Bome cannot help here at all. It sees MIDI devices only; the Scarlett is a
    MEDIA-class audio device and is invisible to it. Detection stays in Python
    regardless of how Phase 8 lands.

RUN IT ONCE PER INTERFACE
    Plug in one Scarlett, run, then swap and run again. Pass --label to keep the
    results apart:
        python tools/interface_name_inspector.py --label scarlett-2i2
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

INTERESTING = ("focusrite", "scarlett", "usb audio", "motu")


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
        rec.add("# No Focusrite/Scarlett device matched. Either it is unplugged, or its")
        rec.add("# friendly name uses wording this tool does not look for. Check the full")
        rec.add("# list above and widen INTERESTING rather than guessing a match string.")
        rec.save(f"interface-names-{args.label}.txt")
        return 0

    rec.add(f"# --- {len(relevant)} MATCHING DEVICE(S), FULL DETAIL ---")
    for device in relevant:
        rec.add(f"#   FriendlyName : {device.get('FriendlyName')!r}")
        rec.add(f"#   Class        : {device.get('Class')!r}")
        rec.add(f"#   Status       : {device.get('Status')!r}")
        rec.add(f"#   InstanceId   : {device.get('InstanceId')!r}")
        rec.add("#")
    rec.add()

    rec.add("# --- PASTE INTO config/rig.yaml ---")
    rec.add()
    rec.add("audio_interface:")
    rec.add("  # Match on a substring, not the whole string: the friendly name can")
    rec.add("  # carry a trailing instance number that changes across re-enumeration.")
    rec.add("  # Verify that claim by replugging and re-running this tool.")
    rec.add("  match_any:")
    for device in relevant:
        rec.add(f"    - {device.get('FriendlyName')!r}")
    rec.add("  require_status: OK")
    rec.add()
    rec.add("# Status must be checked, not just presence. A device in an error state")
    rec.add("# still appears in this list, and launching Ableton against one gives a")
    rec.add("# silent rig -- the failure Phase 5's guard exists to prevent.")

    rec.save(f"interface-names-{args.label}.txt")

    print("\n  Swap Scarletts and run again with a different --label.")
    print("  Every interface that will ever be plugged into the rig needs an entry.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
