"""
List every MIDI port Windows exposes, and probe which ones can actually be opened.

LAYER: none. Bench instrument.

ANSWERS
    1. The exact port-name strings for both Launchpad interfaces. launchpad/ports.py
       matches on these, so an approximation is worthless -- they must be verbatim.
    2. Whether the Launchpad X really presents two independent input ports on this
       machine, as the manual says it does (p.6).
    3. Which ports are already held by another process.

WHY (3) MATTERS MORE THAN IT LOOKS
    On Windows a MIDI input port can be opened by exactly one process. That single
    fact is the whole reason the Bome decision exists (ROADMAP.md S1). This tool is
    the cheapest way to see the constraint directly: run it with Ableton closed, then
    again with Ableton open, and diff.

    Two ports existing does NOT mean two programs can observe the same pad press.
    Do not let a clean run here be read as "exclusivity solved".

RUN IT TWICE
    Pass --label to tag the run, e.g.
        python tools/midi_port_inspector.py --label ableton-closed
        python tools/midi_port_inspector.py --label ableton-open
"""

from __future__ import annotations

import argparse
import sys

import mido

from _bench import Port, PortRole, Recorder, find_ports, require_windows


def probe_open(name: str, direction: str) -> tuple[bool, str]:
    """
    Try to open a port and immediately close it.

    A failure here is a finding, not an error: on Windows the usual cause is that
    another process already holds the input.
    """
    opener = mido.open_input if direction == "input" else mido.open_output
    try:
        port = opener(name)
    except Exception as exc:  # noqa: BLE001 -- the exception text IS the result
        return False, type(exc).__name__ + ": " + str(exc)
    try:
        port.close()
    except Exception:  # noqa: BLE001
        pass
    return True, "opened and closed cleanly"


def report(rec: Recorder, direction: str, names: list[str]) -> list[Port]:
    rec.add(f"# --- {direction.upper()} PORTS ({len(names)}) ---")
    if not names:
        rec.add("#   none reported by the backend")
        rec.add()
        return []

    for index, name in enumerate(names):
        ok, detail = probe_open(name, direction)
        mark = "OK  " if ok else "HELD"
        rec.add(f"#   [{index}] {mark} {name!r}")
        if not ok:
            rec.add(f"#        -> {detail}")

    launchpad = find_ports(names)
    rec.add()
    if launchpad:
        rec.add(f"#   Launchpad {direction} ports: {len(launchpad)}")
        for port in launchpad:
            note = "" if port.classified_by == "name" else "  <- classified by POSITION"
            rec.add(f"#     {port.role.value:>7} : {port.name!r}{note}")
    else:
        rec.add("#   No Launchpad ports found. Is it plugged in and out of MSD mode?")
    rec.add()
    return launchpad


def verdict(rec: Recorder, ins: list[Port], outs: list[Port]) -> None:
    rec.add("# --- VERDICT ---")

    in_roles = {p.role for p in ins}
    if {PortRole.DAW, PortRole.MIDI} <= in_roles:
        rec.add("#   Two distinct Launchpad INPUT interfaces present, as the manual")
        rec.add("#   describes (p.6). Strategy A in ROADMAP.md S1 is topologically")
        rec.add("#   possible.")
        rec.add("#")
        rec.add("#   This does NOT settle MIDI input exclusivity. Two ports means two")
        rec.add("#   processes can hold one each -- not that both can see the same pad")
        rec.add("#   press. That is still the Phase 8 question.")
    elif in_roles:
        rec.add(f"#   Only these input roles found: {sorted(r.value for r in in_roles)}")
        rec.add("#   The manual says there should be two (p.6). Record the discrepancy;")
        rec.add("#   do not work around it silently.")
    else:
        rec.add("#   No Launchpad input ports at all.")

    if any(p.classified_by == "ordinal" for p in [*ins, *outs]):
        rec.add("#")
        rec.add("#   Some ports were classified by POSITION because their names do not")
        rec.add("#   contain 'daw' or 'midi'. The manual's ordinal rule is: first")
        rec.add("#   interface = DAW, second = MIDI. Confirm by behaviour before")
        rec.add("#   hardcoding either into launchpad/ports.py.")
    rec.add()


def emit_literal(rec: Recorder, ins: list[Port], outs: list[Port]) -> None:
    """Pasteable into launchpad/ports.py. Verbatim names, no normalisation."""
    rec.add("# --- PASTE INTO launchpad/ports.py ---")
    rec.add()
    rec.add("PORT_NAMES: dict[str, dict[str, str]] = {")
    for role in (PortRole.DAW, PortRole.MIDI):
        entry_in = next((p.name for p in ins if p.role is role), None)
        entry_out = next((p.name for p in outs if p.role is role), None)
        rec.add(f'    "{role.value}": {{')
        rec.add(f'        "in":  {entry_in!r},')
        rec.add(f'        "out": {entry_out!r},')
        rec.add("    },")
    rec.add("}")
    rec.add()
    rec.add("# Match on these EXACTLY. Windows appends an index to MIDI port names and")
    rec.add("# it can change across re-enumeration -- if that turns out to happen here,")
    rec.add("# switch to a prefix match and record why.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--label",
        default="run",
        help="tag for the output filename, e.g. ableton-closed",
    )
    parser.add_argument(
        "--allow-non-windows",
        action="store_true",
        help="run anyway off-rig. Results are NOT valid for the build.",
    )
    args = parser.parse_args()

    print("\n=== MIDI port inspector ===")
    print("Purpose: record verbatim port names and probe open-ability")
    print("Answers: launchpad/ports.py constants; the exclusivity constraint\n")

    if not args.allow_non_windows:
        require_windows("midi_port_inspector.py")
    else:
        print("  ! --allow-non-windows: results are illustrative only.\n")

    rec = Recorder(tool="midi_port_inspector.py")
    rec.add(f"# Label: {args.label}")
    rec.add(f"# Backend: {mido.backend.name if mido.backend else 'unknown'}")
    rec.add()

    ins = report(rec, "input", list(mido.get_input_names()))
    outs = report(rec, "output", list(mido.get_output_names()))

    verdict(rec, ins, outs)
    emit_literal(rec, ins, outs)

    rec.save(f"midi-ports-{args.label}.txt")

    print("\n  Now run this again with Ableton open and diff the two files.")
    print("  A port that reads OK in one and HELD in the other is the exclusivity")
    print("  constraint made visible.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
