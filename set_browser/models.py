"""
The LiveSet model — one performable Ableton set as the browser sees it.

LAYER: Services (data only).

WHY color IS A NAME, NOT A PALETTE INDEX
    The Launchpad palette is Phase 1 UNVERIFIED (manual p.12 is a page image).
    Storing an index here would make an unmeasured constant load-bearing. The
    renderer (Phase 3) owns name -> index resolution against the measured
    colors.py; this package stays correct even if every index changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

NEUTRAL_COLOR = "white"  # sets without metadata still appear, in this
DEFAULT_CATEGORY = "uncategorised"


@dataclass(frozen=True)
class LiveSet:
    """
    path          absolute path to the .als — what the launcher (Phase 5) receives
    display_name  what a human calls it; file stem unless sets.yaml overrides
    color         semantic colour name; resolved to a palette index in Phase 3
    category      grouping label from sets.yaml, free-form
    has_metadata  False = discovered on disk but absent from sets.yaml
    """

    path: Path
    display_name: str
    color: str = NEUTRAL_COLOR
    category: str = DEFAULT_CATEGORY
    has_metadata: bool = False
