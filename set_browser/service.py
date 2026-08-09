"""
The set browser facade — the one object the controller talks to.

LAYER: Services.

WHO CALLS IT
    rig/controller.py (Phase 3 wiring): page navigation on frame-button events,
    set selection on pad events, rescan from System Mode. The Launchpad renderer
    reads current_page() to paint; the Ableton launcher (Phase 5) receives the
    LiveSet a selection resolves to.

STATE IT OWNS
    The scanned+merged set list and the current page index — nothing else.
    Selection/hold-to-confirm is controller state, not browser state.

HOW IT FAILS
    An empty scan leaves is_empty True; the CALLER must surface Error Mode.
    Rescan preserves the current page index where possible (clamped), so a
    mid-show rescan does not teleport the performer to page one.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from set_browser.metadata import load_metadata, merge
from set_browser.models import LiveSet
from set_browser.pagination import DEFAULT_PAGE_SIZE, Page, paginate
from set_browser.scanner import scan

log = logging.getLogger(__name__)

METADATA_FILENAME = "sets.yaml"


@dataclass
class SetBrowserService:
    sets_dir: Path
    page_size: int = DEFAULT_PAGE_SIZE

    _sets: list[LiveSet] = field(default_factory=list, init=False)
    _page_index: int = field(default=0, init=False)

    def rescan(self) -> int:
        """(Re)load from disk + sets.yaml. Returns the number of sets found."""
        files = scan(self.sets_dir)
        metadata = load_metadata(self.sets_dir / METADATA_FILENAME)
        self._sets = merge(files, metadata, self.sets_dir)
        self._page_index = paginate(self._sets, self._page_index, self.page_size).index
        log.info("rescan: %d set(s), now on page %d", len(self._sets), self._page_index)
        return len(self._sets)

    @property
    def is_empty(self) -> bool:
        return not self._sets

    @property
    def sets(self) -> tuple[LiveSet, ...]:
        return tuple(self._sets)

    def current_page(self) -> Page:
        return paginate(self._sets, self._page_index, self.page_size)

    def next_page(self) -> Page:
        self._page_index = paginate(self._sets, self._page_index + 1, self.page_size).index
        return self.current_page()

    def prev_page(self) -> Page:
        self._page_index = paginate(self._sets, self._page_index - 1, self.page_size).index
        return self.current_page()

    def set_at(self, position: int) -> LiveSet | None:
        """
        The set at a position on the CURRENT page (0-based), or None if the
        position is past the end — pressing an unlit pad selects nothing.
        """
        page = self.current_page()
        if 0 <= position < len(page.items):
            return page.items[position]
        return None
