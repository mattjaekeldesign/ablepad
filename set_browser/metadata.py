"""
Overlay sets.yaml onto scanned files.

LAYER: Services.

THE MERGE RULE
    Disk is the source of WHICH sets exist; sets.yaml is the source of what they
    are CALLED and how they look. A set on disk but not in the file still
    appears — neutral colour, stem for a name — because a set that vanishes
    from the browser after a rename-in-yaml-only is a gig-night trap. A
    sets.yaml entry with no matching file is logged and dropped, never shown:
    a pad that maps to a missing file is worse than no pad.

KEY MATCHING
    Keys are matched against the filename ('worship.als'). A key containing a
    slash is matched against the path relative to the sets root instead, for
    projects holding several .als files with the same name. If one plain key
    matches several files, ALL of them get the metadata and a warning is
    logged — surfacing the ambiguity beats silently picking one.

HOW IT FAILS
    An unreadable or malformed sets.yaml disables overrides for the run (logged,
    defaults used). Metadata is cosmetic; the show can go on without it.
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

from set_browser.models import DEFAULT_CATEGORY, NEUTRAL_COLOR, LiveSet

log = logging.getLogger(__name__)


def load_metadata(path: Path) -> dict[str, dict]:
    """The 'sets' mapping from sets.yaml, or {} if absent/unusable."""
    if not path.exists():
        log.info("no metadata file at %s — all sets will use defaults", path)
        return {}
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (yaml.YAMLError, OSError) as exc:
        log.warning("sets.yaml unusable (%s) — using defaults for this run", exc)
        return {}
    sets = raw.get("sets")
    if not isinstance(sets, dict):
        if sets is not None:
            log.warning("sets.yaml 'sets' must be a mapping; ignoring it")
        return {}
    return {str(k): v for k, v in sets.items() if isinstance(v, dict)}


def merge(files: list[Path], metadata: dict[str, dict], root: Path) -> list[LiveSet]:
    matched_keys: set[str] = set()
    filename_hits: dict[str, int] = {}
    results: list[LiveSet] = []

    for file in files:
        try:
            rel = str(file.relative_to(root.resolve())).replace("\\", "/")
        except ValueError:
            rel = file.name
        entry = None
        for key in (rel, file.name):
            if key in metadata:
                entry = metadata[key]
                matched_keys.add(key)
                if "/" not in key:
                    filename_hits[key] = filename_hits.get(key, 0) + 1
                break
        if entry is None:
            results.append(LiveSet(path=file, display_name=file.stem))
            continue
        results.append(
            LiveSet(
                path=file,
                display_name=str(entry.get("name", file.stem)),
                color=str(entry.get("color", NEUTRAL_COLOR)),
                category=str(entry.get("category", DEFAULT_CATEGORY)),
                has_metadata=True,
            )
        )

    for key, hits in filename_hits.items():
        if hits > 1:
            log.warning(
                "sets.yaml key %r matched %d files — use a path key ('folder/%s') "
                "to disambiguate",
                key,
                hits,
                key,
            )
    for key in metadata.keys() - matched_keys:
        log.warning("sets.yaml entry %r matches no file on disk — not shown", key)

    return results
