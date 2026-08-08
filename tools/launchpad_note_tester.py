"""
Record the real 9x9 note/CC map by lighting each position and capturing what it sends.

LAYER: none. Bench instrument.

ANSWERS
    launchpad/grid.py -- which message arrives when each physical control is pressed,
    and which LED index lights that same control.

WHY THE GUIDED SWEEP, NOT JUST A CAPTURE LOOP
    A capture loop ("press things, I'll log them") tells you which numbers exist. It
    cannot tell you which number belongs to which physical position without the human
    reporting that separately, which is where transcription errors come from.

    So the sweep drives the LED first: light index i, ask for the pad that just lit,
    record what that press sends. One pass yields a verified pairing

        LED index  <->  physical position  <->  input message

    without assuming either numbering is correct. That matters because the manual
    says LED indices always follow Programmer-mode numbering regardless of layout
    (p.15) -- so if the two ever disagree, this is the tool that would show it.

WHAT IS ALREADY KNOWN
    The 8x8 pad grid is inferred as note = (row * 10) + column, rows 1-9 bottom to
    top. Three corners are confirmed in the manual's own prose (p.14): 11 lower left,
    81 upper left, 18 lower right. Those pin the origin and both strides.

    UNCONFIRMED, and the actual reason this tool exists: the CC frame. The top row
    is believed to be CC 91-98, the right column CC 19/29/.../89, the logo CC 99.
    The Set Browser's pagination and System Mode access depend on those. p.10 renders
    the layout as an image, so nothing in the manual's text confirms them.

MODES
    --sweep  (default) guided, one position at a time, full provenance
    --free   freeform capture; press anything, everything is logged
    --frame  sweep only the 17 outer controls -- the actual unknowns, ~2 minutes
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

from _bench import (
    ALL_LED_INDICES,
    PAD_GRID_INDICES,
    Recorder,
    bench,
    banner,
    led_static,
    prompt,
)

# Palette 3 is white in every reading of the table we have, and it is the entry
# least likely to be confused with a neighbour under stage lighting.
CUE_COLOUR = 3

# The outer ring: top row, right column, logo. These are the unverified ones.
FRAME_INDICES: tuple[int, ...] = tuple(
    i for i in ALL_LED_INDICES if i not in PAD_GRID_INDICES
)


@dataclass
class Observation:
    led_index: int
    message_type: str  # "note_on" | "control_change" | "none"
    number: int | None
    velocity: int | None

    @property
    def agrees(self) -> bool:
        """Does the input number match the LED index we lit?"""
        return self.number == self.led_index

    def describe(self) -> str:
        if self.message_type == "none":
            return f"  LED {self.led_index:>2} -> (nothing captured)"
        kind = "note" if self.message_type == "note_on" else "CC  "
        flag = "" if self.agrees else f"   <- MISMATCH, LED index is {self.led_index}"
        return (
            f"  LED {self.led_index:>2} -> {kind} {self.number:>3} "
            f"vel/val {self.velocity:>3}{flag}"
        )


def sweep(session, indices: tuple[int, ...], observations: list[Observation]) -> None:
    """
    Appends into `observations` as it goes, rather than returning at the end, so a
    Ctrl+C partway through still leaves the caller holding everything captured so far.
    A sweep of 81 positions is several minutes of someone's attention; losing it to an
    early exit would be its own bug.
    """
    total = len(indices)

    print(f"\n  {total} positions. Press the LIT control each time.")
    print("  Press Enter with nothing lit-and-pressed to skip a position.")
    print("  Ctrl+C stops early and still saves what you have.\n")

    for count, index in enumerate(indices, start=1):
        session.send(led_static(index, CUE_COLOUR))
        print(f"  [{count}/{total}] lit LED index {index} -- press it", end="", flush=True)

        message = session.wait_for_event(timeout_s=30.0)
        session.send(led_static(index, 0))

        if message is None:
            print("  ... timeout, skipped")
            observations.append(Observation(index, "none", None, None))
            continue

        if message.type == "control_change":
            observation = Observation(index, "control_change", message.control, message.value)
        else:
            observation = Observation(index, "note_on", message.note, message.velocity)

        print()
        print(observation.describe())
        observations.append(observation)

        # The device sends note-on velocity 0 for release (p.6). Swallow it so the
        # next position does not capture the previous release as its press.
        session.wait_for_event(timeout_s=0.4)


def free_capture(session, rec: Recorder) -> None:
    print("\n  Freeform capture. Press anything. Ctrl+C to stop.\n")
    seen: set[tuple[str, int]] = set()
    try:
        while True:
            message = session.wait_for_event(timeout_s=None)
            if message is None:
                continue
            if message.type == "control_change":
                key, value = ("control_change", message.control), message.value
            else:
                key, value = ("note_on", message.note), message.velocity
            marker = "" if key in seen else "  (new)"
            seen.add(key)
            print(f"  {key[0]:<15} {key[1]:>3}   value {value:>3}{marker}")
    except (KeyboardInterrupt, SystemExit):
        pass

    rec.add("# --- FREEFORM CAPTURE ---")
    for kind, number in sorted(seen):
        rec.add(f"#   {kind:<15} {number}")
    rec.add()


def analyse(rec: Recorder, observations: list[Observation]) -> None:
    captured = [o for o in observations if o.message_type != "none"]
    skipped = [o for o in observations if o.message_type == "none"]
    mismatched = [o for o in captured if not o.agrees]

    rec.add("# --- ANALYSIS ---")
    rec.add(f"#   positions swept:  {len(observations)}")
    rec.add(f"#   captured:         {len(captured)}")
    rec.add(f"#   skipped/timeout:  {len(skipped)}")
    rec.add(f"#   index mismatches: {len(mismatched)}")
    rec.add()

    if mismatched:
        rec.add("#   MISMATCHES -- the LED index and the input number differ. This")
        rec.add("#   contradicts p.15's claim that LED indices always follow")
        rec.add("#   Programmer-mode numbering. Record it, do not resolve it silently:")
        for observation in mismatched:
            rec.add(f"#     {observation.describe().strip()}")
        rec.add()

    notes = sorted(o.number for o in captured if o.message_type == "note_on")
    ccs = sorted(o.number for o in captured if o.message_type == "control_change")

    rec.add(f"#   sends NOTE ({len(notes)}): {notes}")
    rec.add(f"#   sends CC   ({len(ccs)}): {ccs}")
    rec.add()

    expected_cc = sorted(FRAME_INDICES)
    if ccs and ccs == expected_cc:
        rec.add("#   The CC frame matches the inferred layout exactly:")
        rec.add("#     top row 91-98, right column 19..89, logo 99.")
        rec.add("#   This was the main open question. Consider it closed.")
    elif ccs:
        rec.add("#   CC frame does NOT match the inferred layout.")
        rec.add(f"#     expected: {expected_cc}")
        rec.add(f"#     actual:   {ccs}")
        rec.add("#   The inferred CC frame was wrong. grid.py must use the actual set.")
    rec.add()


def emit_literal(rec: Recorder, observations: list[Observation]) -> None:
    captured = [o for o in observations if o.message_type != "none"]
    if not captured:
        rec.add("# Nothing captured -- no literal emitted.")
        return

    notes = sorted(o.number for o in captured if o.message_type == "note_on")
    ccs = sorted(o.number for o in captured if o.message_type == "control_change")

    rec.add("# --- PASTE INTO launchpad/grid.py ---")
    rec.add()
    rec.add("# Measured, not inferred. Every value below was produced by lighting an")
    rec.add("# LED index and recording what pressing that control actually sent.")
    rec.add()
    rec.add("SENDS_NOTE: frozenset[int] = frozenset({")
    rec.add("    " + ", ".join(str(n) for n in notes))
    rec.add("})")
    rec.add()
    rec.add("SENDS_CC: frozenset[int] = frozenset({")
    rec.add("    " + ", ".join(str(c) for c in ccs))
    rec.add("})")
    rec.add()
    rec.add("# LED index -> (message type, number). Identical in every verified case")
    rec.add("# means the (row * 10) + column rule holds and grid.py can compute it.")
    rec.add("OBSERVED: dict[int, tuple[str, int]] = {")
    for observation in captured:
        rec.add(f"    {observation.led_index}: ({observation.message_type!r}, {observation.number}),")
    rec.add("}")
    rec.add()
    rec.add("# In Programmer mode every control ACCEPTS either note or CC; the split")
    rec.add("# above is only what the device SENDS on press (p.10). read_events() must")
    rec.add("# handle both. set_led() may use either.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--sweep", action="store_true", help="guided sweep, all 81 (default)")
    group.add_argument("--frame", action="store_true", help="sweep only the 17 outer controls")
    group.add_argument("--free", action="store_true", help="freeform capture")
    args = parser.parse_args()

    banner(
        "Launchpad note/CC map tester",
        "pair every LED index with the message its control sends",
        "launchpad/grid.py -- especially the unverified CC frame",
    )

    rec = Recorder(tool="launchpad_note_tester.py")

    with bench() as session:
        if args.free:
            free_capture(session, rec)
            rec.save("grid-freeform.txt")
            return 0

        indices = FRAME_INDICES if args.frame else ALL_LED_INDICES
        scope = "outer frame only" if args.frame else "full 9x9"
        rec.add(f"# Scope: {scope} ({len(indices)} positions)")
        rec.add()

        prompt("  Ready? Enter to start, Ctrl+C to abort: ")

        observations: list[Observation] = []
        try:
            sweep(session, indices, observations)
        except (KeyboardInterrupt, SystemExit):
            print(f"\n  stopped early -- saving {len(observations)} captured positions")

    if observations:
        analyse(rec, observations)
        emit_literal(rec, observations)
        rec.save("grid-frame.txt" if args.frame else "grid-full.txt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
