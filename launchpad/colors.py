"""
Launchpad X palette indices. The eight the rig uses are MEASURED; the rest are not.

LAYER: drivers. Pure constants — no I/O, no state.

WHAT THE DEVICE ACTUALLY WANTS
    A palette index, 0–127. Not a hex colour. The rig never converts to RGB, so no
    colour table is needed here — only the indices, named, so that renderer.py reads
    as intent rather than magic numbers.

    (Arbitrary RGB is possible via lighting type 3 in the LED SysEx, p.15. Nothing
    uses it, and it would bypass this file entirely if it did.)

PROVENANCE
    Method   : lit on the bottom row, left to right, and read off the device by eye
    Device   : Novation Launchpad X, firmware 0.3.5.1
    Host     : Beelink "RIG"
    Date     : 2026-08-12
    Result   : eight for eight, exactly as the manual's prose describes them

WHY ONLY EIGHT
    Page 12 of the Programmer's Reference is the full 128-entry table, and it is an
    IMAGE — no text to extract. The eight below are the only palette facts the manual
    states in prose (p.14–15, p.23), and they are the ones that were verified.

    That turned out to be enough: the five configs and three animations in this repo
    reference exactly these eight indices and no others. Every colour the rig paints
    has been seen on the real device. Phase 1's exit test is that no guess is
    load-bearing — and none is.

    That is a property of today's configs, not of the design. tools/palette_coverage.py
    fails when a config starts depending on an index nobody has seen lit.

THE OTHER 120
    docs/colour-palette-candidate.json holds a full table sampled from the Launchpad
    Mini MK3 manual — a DIFFERENT DEVICE (SysEx ID 0x0D, not 0x0C). All eight verified
    entries agree with it, which is encouraging and is not proof of the rest. It is a
    design aid for the Config Lab. Do not import it here.
"""

from __future__ import annotations

# --- verified on hardware, 2026-08-12 ----------------------------------------

OFF = 0
RED = 5
YELLOW = 13
GREEN = 19
GREEN_BRIGHT = 21
GREEN_DIM = 23
CYAN = 37
BLUE = 45

#: index -> what a human saw on the device. The whole verified set.
VERIFIED: dict[int, str] = {
    OFF: "off",
    RED: "red",
    YELLOW: "yellow",
    GREEN: "green",
    GREEN_BRIGHT: "bright green",
    GREEN_DIM: "dim green",
    CYAN: "cyan / turquoise",
    BLUE: "blue",
}

PALETTE_SIZE = 128  # p.12, indices 0-127

#: Semantic colour name -> verified index. set_browser/models.py stores colours as
#: NAMES precisely so an unmeasured palette index never becomes load-bearing there;
#: this is the seam where names become indices, and it can only produce verified ones.
_BY_NAME: dict[str, int] = {
    "off": OFF, "black": OFF,
    "red": RED,
    "yellow": YELLOW, "amber": YELLOW, "orange": YELLOW,
    "green": GREEN,
    "bright green": GREEN_BRIGHT, "green_bright": GREEN_BRIGHT, "lime": GREEN_BRIGHT,
    "dim green": GREEN_DIM, "green_dim": GREEN_DIM,
    "cyan": CYAN, "turquoise": CYAN, "teal": CYAN,
    "blue": BLUE,
}

#: What an unrecognised colour name becomes. Deliberately a real, verified colour
#: rather than OFF: a set whose metadata names a colour we cannot render should still
#: be VISIBLE and selectable. Losing a pad because someone wrote "puce" in sets.yaml
#: would be a silent, gig-night failure.
UNKNOWN_COLOR = GREEN_DIM

_warned: set[str] = set()


def by_name(name: str | None) -> int:
    """
    Resolve a semantic colour name to a VERIFIED palette index.

    Note that models.NEUTRAL_COLOR is "white", and white is NOT among the eight
    indices confirmed on hardware -- palette 3 looks like white in the candidate
    table sampled from a different device, and nobody has looked at it here. So it
    lands on UNKNOWN_COLOR like any other unverified name, and says so once.
    """
    if not name:
        return UNKNOWN_COLOR
    key = name.strip().lower()
    if key in _BY_NAME:
        return _BY_NAME[key]
    if key not in _warned:
        _warned.add(key)
        import logging

        logging.getLogger(__name__).warning(
            "colour %r is not one of the verified names %s — rendering it as %r. "
            "Verify the index with tools/led_color_tester.py before relying on it.",
            name, sorted(set(_BY_NAME)), UNKNOWN_COLOR,
        )
    return UNKNOWN_COLOR


def is_verified(index: int) -> bool:
    """Has a human actually seen this index lit on a Launchpad X?"""
    return index in VERIFIED


def describe(index: int) -> str:
    """Human name if verified, otherwise an honest label."""
    return VERIFIED.get(index, f"palette {index} (UNVERIFIED)")


def require_verified(index: int) -> int:
    """
    Use where an unseen colour would be a real problem — Error Mode, say, where the
    whole point is that a human can tell the states apart at a glance on a dark stage.

    Returns the index so it can be used inline.
    """
    if not is_verified(index):
        raise ValueError(
            f"palette index {index} has never been confirmed on hardware. "
            f"Verify it with tools/led_color_tester.py --index {index}, or pick one of "
            f"{sorted(VERIFIED)}."
        )
    return index


def sanity_check() -> None:
    assert len(VERIFIED) == 8, len(VERIFIED)
    assert all(0 <= i < PALETTE_SIZE for i in VERIFIED)
    assert OFF == 0, "palette 0 is 'off', not a colour (p.14)"


sanity_check()
