"""
Slice an ordered set list into pad-grid-sized pages.

LAYER: Services (pure functions, no state, no I/O).

PAGE SIZE
    Default 48 — the roadmap's own boundary ('pagination works past 48 sets').
    DESIGN CONSTANT, UNVERIFIED against Start_DOCS (§ not in repo): believed to
    be 8 columns x 6 rows, leaving the top rows for navigation/status. The
    number is a parameter everywhere precisely so that finding produces a
    one-line change.

HOW IT FAILS
    It cannot: a page index is clamped into range, and an empty list yields one
    empty page rather than zero pages, so 'current page' is always meaningful.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence, TypeVar

T = TypeVar("T")

DEFAULT_PAGE_SIZE = 48  # UNVERIFIED design constant — see module docstring


@dataclass(frozen=True)
class Page:
    items: tuple
    index: int  # zero-based, already clamped
    page_count: int
    total_items: int

    @property
    def is_first(self) -> bool:
        return self.index == 0

    @property
    def is_last(self) -> bool:
        return self.index >= self.page_count - 1


def page_count(total: int, page_size: int = DEFAULT_PAGE_SIZE) -> int:
    if page_size < 1:
        raise ValueError(f"page_size must be >= 1, got {page_size}")
    return max(1, -(-total // page_size))  # ceil-div; empty list still has page 0


def paginate(items: Sequence[T], index: int, page_size: int = DEFAULT_PAGE_SIZE) -> Page:
    count = page_count(len(items), page_size)
    clamped = min(max(index, 0), count - 1)
    start = clamped * page_size
    return Page(
        items=tuple(items[start : start + page_size]),
        index=clamped,
        page_count=count,
        total_items=len(items),
    )
