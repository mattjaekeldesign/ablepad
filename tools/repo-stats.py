#!/usr/bin/env python3
"""Print a small, dependency-free progress report for the ablepad repo.

Mermaid is the project tracking surface: node classes such as :::done and
:::partial are counted from both architecture trees. ROADMAP.md checkboxes are
reported separately because they represent the finer-grained execution work.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TREES = sorted((ROOT / "viz" / "trees").glob("*.mmd"))
ROADMAP = ROOT / "docs" / "ROADMAP.md"

# Partial work contributes half credit. The remaining classes are tracked but
# do not count as completed evidence.
WEIGHTS = {"done": 1.0, "verified": 1.0, "partial": 0.5}
STATUS_RE = re.compile(r":::(done|verified|partial|todo|unverified|riskhigh|decision|next|branch)\b")
CHECK_RE = re.compile(r"^\s*(□|■|✅|✗|⚠️?)\s", re.MULTILINE)


def percent(value: float) -> str:
    return f"{value * 100:.0f}%"


def tree_stats(path: Path) -> tuple[dict[str, int], float, int]:
    counts: dict[str, int] = {}
    for status in STATUS_RE.findall(path.read_text(encoding="utf-8")):
        counts[status] = counts.get(status, 0) + 1
    tracked = sum(counts.values())
    earned = sum(counts.get(status, 0) * weight for status, weight in WEIGHTS.items())
    return counts, earned / tracked if tracked else 0.0, tracked


def roadmap_stats() -> tuple[int, int]:
    text = ROADMAP.read_text(encoding="utf-8")
    marks = CHECK_RE.findall(text)
    complete = sum(mark in {"■", "✅"} for mark in marks)
    return complete, len(marks)


def main() -> None:
    print("ablepad progress")
    print("================")

    scores: list[float] = []
    for tree in TREES:
        counts, score, tracked = tree_stats(tree)
        scores.append(score)
        summary = " ".join(
            f"{status}={counts[status]}"
            for status in ("done", "verified", "partial", "todo", "unverified", "riskhigh", "decision")
            if counts.get(status)
        )
        print(f"{tree.stem:9} {percent(score):>4} evidence  ({tracked} tracked nodes; {summary})")

    complete, total = roadmap_stats()
    roadmap_score = complete / total if total else 0.0
    print(f"roadmap   {percent(roadmap_score):>4} checked    ({complete}/{total} checklist items complete)")

    overall = (sum(scores) / len(scores) + roadmap_score) / 2 if scores else roadmap_score
    print(f"overall   {percent(overall):>4} tracked progress")
    print()
    print("Current state: documentation and bench tooling are ahead; rig application code is not started.")
    print("Next focus: Phase 1 hardware verification, then Phase 2 skeleton.")
    print("Open risks: full Launchpad map, colour palette, hotspot support, Ableton path, and real hardware access.")


if __name__ == "__main__":
    main()
