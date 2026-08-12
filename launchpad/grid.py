"""
The Launchpad X surface map. MEASURED, not inferred.

LAYER: drivers. Pure data and arithmetic — no I/O, no mido, no state. Everything
above (renderer, mappings, modes) may import this; it imports nothing of ours.

PROVENANCE
    Method   : tools/launchpad_note_tester.py — lights an LED index, records what
               pressing that control actually sends. Never assumes the two agree.
    Device   : Novation Launchpad X, firmware 0.3.5.1
    Host     : Beelink "RIG", Windows 11 Home, driven over SSH
    Date     : 2026-08-12
    Evidence : tools/results/grid-frame.txt   (17 frame positions)
               tools/results/grid-8x8.txt     (64 interior pads)
               tools/results/grid-retest.txt  (11/12/13 re-run after a misplaced press)

RESULT
    All 81 positions swept. 80 pressable controls, every one reporting a number
    identical to the LED index that lit it. Zero unexplained mismatches.

    That is the important part: the manual claims (p.15) that LED indices always
    follow Programmer-mode numbering regardless of layout, and 80 independent data
    points agree. So the map is an EQUATION, not a lookup table.

        note_or_cc = (row * 10) + column        rows 1–9 bottom to top
                                                columns 1–9 left to right

    The three corners the manual names in prose (p.14) — 11 lower-left, 81 upper-left,
    18 lower-right — all landed where the equation predicts.
"""

from __future__ import annotations

# --- geometry ----------------------------------------------------------------

ROWS = range(1, 10)  # 1 = bottom, 9 = top
COLS = range(1, 10)  # 1 = left, 9 = right

PAD_ROWS = range(1, 9)  # the 8x8 note grid
PAD_COLS = range(1, 9)


def index(row: int, col: int) -> int:
    """The LED index / message number for a position. The whole map, in one line."""
    return row * 10 + col


def row_of(index_: int) -> int:
    return index_ // 10


def col_of(index_: int) -> int:
    return index_ % 10


# --- the surface -------------------------------------------------------------

#: Every addressable LED, including the logo. 81 entries — also the documented
#: ceiling for one LED Lighting SysEx (p.15), which is not a coincidence.
ALL_INDICES: tuple[int, ...] = tuple(index(r, c) for r in ROWS for c in COLS)

#: The 8x8 pad grid. Sends NOTE on press. MEASURED: all 64.
PAD_INDICES: tuple[int, ...] = tuple(index(r, c) for r in PAD_ROWS for c in PAD_COLS)

#: Top row of function buttons. Sends CC. MEASURED: 91–98, all 8.
TOP_ROW_INDICES: tuple[int, ...] = tuple(index(9, c) for c in PAD_COLS)

#: Right-hand scene-launch column. Sends CC. MEASURED: 19, 29 … 89, all 8.
RIGHT_COLUMN_INDICES: tuple[int, ...] = tuple(index(r, 9) for r in PAD_ROWS)

#: The Novation logo, top-right. It LIGHTS and it is NOT A BUTTON — confirmed on
#: the hardware 2026-08-12. Paint it if you like; never bind an action to it.
LOGO_INDEX: int = 99

#: Addressable but unpressable. mappings.py must reject any binding to these.
LED_ONLY_INDICES: frozenset[int] = frozenset({LOGO_INDEX})

#: What each control SENDS when pressed. Note the asymmetry with lighting: in
#: Programmer mode every control ACCEPTS either note or CC (p.10), so this governs
#: read_events(), not set_led().
SENDS_NOTE: frozenset[int] = frozenset(PAD_INDICES)
SENDS_CC: frozenset[int] = frozenset(TOP_ROW_INDICES + RIGHT_COLUMN_INDICES)

#: Everything a press can ever come from.
PRESSABLE_INDICES: frozenset[int] = SENDS_NOTE | SENDS_CC


# --- predicates --------------------------------------------------------------


def is_valid(index_: int) -> bool:
    """Is this a real position on the surface at all?"""
    return row_of(index_) in ROWS and col_of(index_) in COLS


def is_pad(index_: int) -> bool:
    """Inside the 8x8 note grid."""
    return index_ in SENDS_NOTE


def is_frame(index_: int) -> bool:
    """Top row or right column — the CC controls around the grid."""
    return index_ in SENDS_CC


def is_pressable(index_: int) -> bool:
    """False for the logo, which lights but has no switch under it."""
    return index_ in PRESSABLE_INDICES


def sanity_check() -> None:
    """
    Assert the file agrees with what was measured. Cheap, and it fails loudly if
    someone edits a constant without going back to the hardware.
    """
    assert len(ALL_INDICES) == 81, len(ALL_INDICES)
    assert len(PAD_INDICES) == 64, len(PAD_INDICES)
    assert len(SENDS_CC) == 16, len(SENDS_CC)
    assert len(PRESSABLE_INDICES) == 80, len(PRESSABLE_INDICES)
    assert set(ALL_INDICES) == PRESSABLE_INDICES | LED_ONLY_INDICES
    # The manual's own worked examples, p.14
    assert index(1, 1) == 11, "lower-left"
    assert index(8, 1) == 81, "upper-left"
    assert index(1, 8) == 18, "lower-right"
    assert index(8, 8) == 88, "upper-right"
    assert not is_pressable(LOGO_INDEX)


sanity_check()
