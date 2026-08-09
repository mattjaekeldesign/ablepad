"""
Find performable .als files; refuse to surface Ableton's own clutter.

LAYER: Services.

WHO CALLS IT
    set_browser/service.py, at startup and on every rescan.

WHAT COUNTS AS CLUTTER (and why each rule exists)
    Ableton keeps previous versions in a 'Backup' folder inside every project —
    loading one on stage means playing last week's edit. 'Ableton Project Info'
    holds project bookkeeping, never a performable set. Recovered/autosaved
    copies are crash artefacts. All three must be invisible to a performer.

HOW IT FAILS
    A missing or empty root returns an empty list and lets the caller decide —
    the roadmap requires an empty folder to become an error STATE, not a crash.

DETERMINISM
    Results are sorted case-insensitively by display path. Pad layouts must not
    reshuffle between two rescans of identical content.
"""

from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)

# Any .als whose path contains one of these directory names is not performable.
SKIP_DIRS = frozenset({"backup", "ableton project info", "$recycle.bin"})

# Filename fragments marking crash artefacts, matched case-insensitively.
SKIP_NAME_TOKENS = ("[recovered]", "autosave")


def is_performable(path: Path) -> bool:
    if any(part.lower() in SKIP_DIRS for part in path.parts):
        return False
    name = path.name.lower()
    return not any(token in name for token in SKIP_NAME_TOKENS)


def scan(root: Path) -> list[Path]:
    """Every performable .als under root, sorted, absolute."""
    if not root.is_dir():
        log.warning("sets root %s does not exist or is not a directory", root)
        return []
    found = sorted(
        (p.resolve() for p in root.rglob("*.als") if is_performable(p)),
        key=lambda p: str(p).lower(),
    )
    log.info("scan of %s found %d performable set(s)", root, len(found))
    return found
