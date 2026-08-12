"""
Sweep the 128-entry colour palette and record what the hardware actually emits.

LAYER: none. Bench instrument.

ANSWERS
    launchpad/colors.py -- the palette index to colour mapping.

WHY THIS IS STILL OPEN
    The Programmer's Reference prints the palette as a table on p.12, but the page is
    an image. Text extraction cannot read it. Eight indices are recoverable from the
    manual's prose and worked examples:

        0 blank/off, 5 red, 13 yellow, 19 green, 21 bright green,
        23 dim green, 37 turquoise, 45 blue

    docs/colour-palette-candidate.json holds a full 128-entry table copied from
    Launchpad Mini MK3 research. All eight agree with it. That is suggestive and
    nothing more -- it is a different device, and this tool exists to replace it.

WHAT "VERIFIED" MEANS HERE
    Not "matches the candidate". It means someone looked at the hardware and wrote
    down what they saw. The candidate values are printed alongside so disagreements
    are obvious, but agreement is not proof and the tool never auto-accepts.

    Two things the candidate cannot tell you either way, and the photographs can:
      - the table's own values bottom out at 0x61 (97) rather than 0, which looks
        like a rendering floor in the printed swatches rather than real LED output
      - index 0 samples as grey #616161 but MEANS off (p.14)

MODES
    --pages   (default) 64 pads at a time, two pages, photograph each
    --single  one index at a time on the whole grid, for close inspection
    --index N one specific index, held until you press Enter
"""

from __future__ import annotations

import argparse
import sys

from _bench import (
    PALETTE_SIZE,
    PAD_GRID_INDICES,
    Recorder,
    banner,
    bench,
    clear_all,
    led_batch,
    load_candidate_palette,
    prompt,
)

PADS_PER_PAGE = len(PAD_GRID_INDICES)  # 64


def visual_rows() -> list[list[int]]:
    """
    The 8x8 pad indices in the order a person sees them: top row first.

    PAD_GRID_INDICES is generated bottom-to-top because that is how the note
    numbering runs. A photograph is read top-to-bottom, so the printed map has to
    be flipped or every recorded value lands one row out.
    """
    return [[row * 10 + col for col in range(1, 9)] for row in range(8, 0, -1)]


def print_page_map(first_index: int) -> None:
    """Print which palette index sits on which pad, oriented as the photo will be."""
    print(f"\n  Palette indices {first_index}-{first_index + PADS_PER_PAGE - 1},")
    print("  laid out as you are looking at the device:\n")
    for visual_row, pads in enumerate(visual_rows()):
        cells = []
        for column, _pad in enumerate(pads):
            offset = visual_row * 8 + column
            cells.append(f"{first_index + offset:>4}")
        print("     " + " ".join(cells))
    print()


def show_page(session, first_index: int) -> None:
    """
    One batched write per page.

    64 entries is inside the documented 81-entry ceiling (p.15), so the whole page
    lands in a single SysEx and every pad changes in the same instant. That matters
    for a photograph -- pads lit in sequence would expose at different times.
    """
    pairs = [
        (pad, (first_index + offset) % PALETTE_SIZE)
        for offset, pad in enumerate(PAD_GRID_INDICES)
    ]
    session.send(led_batch(pairs))


def pages_mode(session, rec: Recorder) -> None:
    candidate = load_candidate_palette()

    for page, first_index in enumerate(range(0, PALETTE_SIZE, PADS_PER_PAGE), start=1):
        session.send(clear_all())
        show_page(session, first_index)
        print(f"\n  --- PAGE {page}: indices {first_index}-{first_index + PADS_PER_PAGE - 1} ---")
        print_page_map(first_index)
        print("  Photograph the surface now.")
        print("  Shoot square-on, fixed exposure, no flash. Flash washes out the")
        print("  difference between neighbouring entries, which is the whole point.")
        prompt("\n  Enter when photographed: ", wait_s=30.0)

    session.send(clear_all())

    rec.add("# --- PALETTE WORKSHEET ---")
    rec.add("#")
    rec.add("# Fill in OBSERVED from the photographs. The candidate column is from a")
    rec.add("# DIFFERENT DEVICE (Launchpad Mini MK3) and is here only so disagreements")
    rec.add("# stand out. Do not copy it across because it looks close.")
    rec.add("#")
    rec.add("# index | candidate | observed")
    rec.add("# ------|-----------|----------------------------------")
    for index in range(PALETTE_SIZE):
        guess = candidate.get(index, "?")
        confirmed = CONFIRMED_BY_MANUAL.get(index)
        note = f"   <- manual says {confirmed}" if confirmed else ""
        rec.lines.append(f"# {index:>5} | {guess:>9} |{note}")
    rec.add()
    print(f"  worksheet written with {PALETTE_SIZE} rows to fill in")


# Recoverable from the Programmer's Reference prose and worked examples, p.14-15,
# p.23. These are the only palette facts the manual states in text.
CONFIRMED_BY_MANUAL: dict[int, str] = {
    0: "blank/off",
    5: "red",
    13: "yellow",
    19: "green",
    21: "bright green",
    23: "dim green",
    37: "turquoise",
    45: "blue",
}


def single_mode(session, rec: Recorder, only: int | None) -> None:
    candidate = load_candidate_palette()
    indices = [only] if only is not None else list(range(PALETTE_SIZE))

    print("\n  Whole grid set to one index at a time. Enter advances, Ctrl+C stops.\n")
    observed: dict[int, str] = {}

    try:
        for index in indices:
            session.send(led_batch([(pad, index) for pad in PAD_GRID_INDICES]))
            guess = candidate.get(index, "?")
            confirmed = CONFIRMED_BY_MANUAL.get(index)
            suffix = f"   manual: {confirmed}" if confirmed else ""
            answer = prompt(
                f"  index {index:>3}  (candidate {guess}){suffix}\n"
                "    what do you see? (blank to skip): "
            ).strip()
            if answer:
                observed[index] = answer
    except (KeyboardInterrupt, SystemExit):
        print(f"\n  stopped -- {len(observed)} indices recorded")

    session.send(clear_all())

    if not observed:
        rec.add("# No observations recorded.")
        return

    rec.add("# --- OBSERVED PALETTE ENTRIES ---")
    rec.add("PALETTE_OBSERVED: dict[int, str] = {")
    for index in sorted(observed):
        rec.add(f"    {index}: {observed[index]!r},")
    rec.add("}")
    rec.add()

    disagreements = [
        (index, candidate.get(index, "?"), value)
        for index, value in sorted(observed.items())
        if candidate.get(index, "?").lower() not in value.lower()
    ]
    rec.add(f"# {len(observed)} recorded, {len(disagreements)} differ from the candidate.")
    if disagreements:
        rec.add("# Differences -- the candidate table is from a different device, so")
        rec.add("# these are expected findings, not errors:")
        for index, guess, actual in disagreements:
            rec.add(f"#   {index:>3}: candidate {guess}  observed {actual!r}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--pages", action="store_true", help="two 64-pad pages (default)")
    group.add_argument("--single", action="store_true", help="one index at a time")
    parser.add_argument("--index", type=int, help="hold one specific index")
    args = parser.parse_args()

    if args.index is not None and not (0 <= args.index < PALETTE_SIZE):
        print(f"  --index must be 0-{PALETTE_SIZE - 1}")
        return 1

    banner(
        "LED colour palette tester",
        "record what each of the 128 palette indices actually looks like",
        "launchpad/colors.py",
    )

    rec = Recorder(tool="led_color_tester.py")

    with bench() as session:
        if args.single or args.index is not None:
            single_mode(session, rec, args.index)
            rec.save("palette-observed.txt")
        else:
            pages_mode(session, rec)
            rec.save("palette-worksheet.txt")

    print("\n  Keep the photographs. Commit them next to the worksheet -- a palette")
    print("  reading that nobody can re-check is barely better than a guess.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
