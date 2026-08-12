"""
Check that every palette index the rig actually paints has been verified on hardware.

LAYER: none. A repo check, not a bench instrument -- it needs no Launchpad and runs
anywhere, unlike its siblings here.

WHY IT EXISTS
    The 128-colour palette will probably never be fully verified, because p.12 of the
    Programmer's Reference is an image and photographing 128 swatches is a bad use of
    an evening. It does not need to be. What matters is a much smaller question:

        is every index the configs and animations REFERENCE one we have actually
        seen on the device?

    On 2026-08-12 the answer was yes, exactly -- the five configs and three animations
    referenced 8 indices, and they were the same 8 the manual names in prose and that
    were confirmed by eye on the hardware that day. Coverage was 100% by accident.

    It will not stay that way. The moment someone picks a nice-looking colour in the
    Config Lab, the rig depends on an index nobody has ever seen lit. This tool is how
    that gets noticed then, rather than at a gig.

EXIT CODE
    0  every referenced index is verified
    1  at least one is not -- the list is printed

    Wired into a pre-commit hook or `just check`, that turns a silent drift into a
    loud one.
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Confirmed by eye on Launchpad X firmware 0.3.5.1, Beelink RIG, 2026-08-12.
# Each is also named in the manual's PROSE (p.14-15, p.23) -- these are the only
# palette facts the manual states in text rather than in the image on p.12.
# Read back from the device left to right and matched exactly.
VERIFIED: dict[int, str] = {
    0: "off",
    5: "red",
    13: "yellow",
    19: "green",
    21: "bright green",
    23: "dim green",
    37: "cyan / turquoise",
    45: "blue",
}

# Everything else lives in docs/colour-palette-candidate.json, which was sampled from
# the Launchpad Mini MK3 manual -- a DIFFERENT DEVICE. All 8 verified indices agree
# with it, which is encouraging and is not proof of the other 120.
CANDIDATE = REPO / "docs" / "colour-palette-candidate.json"

PALETTE_KEYS = ("palette", "paletteB")


def collect(root: Path) -> tuple[Counter, dict[int, set[str]]]:
    """Every palette index referenced under `root`, and which file used it."""
    counts: Counter = Counter()
    sources: dict[int, set[str]] = defaultdict(set)

    def walk(node, src: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in PALETTE_KEYS and isinstance(value, int):
                    counts[value] += 1
                    sources[value].add(src)
                else:
                    walk(value, src)
        elif isinstance(node, list):
            for value in node:
                walk(value, src)

    for path in sorted(root.glob("*.json")):
        try:
            walk(json.loads(path.read_text()), f"{root.name}/{path.stem}")
        except json.JSONDecodeError as exc:
            print(f"  ! {path} is not valid JSON: {exc}")
    return counts, sources


def main() -> int:
    counts: Counter = Counter()
    sources: dict[int, set[str]] = defaultdict(set)
    for folder in ("configs", "animations"):
        directory = REPO / folder
        if not directory.is_dir():
            continue
        c, s = collect(directory)
        counts.update(c)
        for index, names in s.items():
            sources[index] |= names

    if not counts:
        print("No palette references found. Nothing to check.")
        return 0

    candidate = {}
    if CANDIDATE.exists():
        candidate = {int(k): v for k, v in json.loads(CANDIDATE.read_text()).items()}

    print(f"\n  {len(counts)} distinct palette indices referenced by the rig\n")
    unverified = []
    for index in sorted(counts):
        mark = "OK " if index in VERIFIED else "?? "
        desc = VERIFIED.get(index) or f"candidate {candidate.get(index, 'unknown')}"
        print(f"  {mark} {index:>3}  x{counts[index]:<3} {desc:<22} {', '.join(sorted(sources[index]))}")
        if index not in VERIFIED:
            unverified.append(index)

    print(f"\n  verified on hardware : {len(counts) - len(unverified)}/{len(counts)}")
    if not unverified:
        print("  Every colour the rig paints has been seen on the real device.")
        return 0

    print(f"\n  NOT VERIFIED: {unverified}")
    print("  These come from a table sampled off a DIFFERENT DEVICE (Mini MK3).")
    print("  Confirm them with tools/led_color_tester.py --index N before a gig")
    print("  depends on telling them apart.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
