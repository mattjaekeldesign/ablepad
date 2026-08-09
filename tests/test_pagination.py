"""pagination: pure math, the roadmap's past-48 boundary, clamping, empty case."""

import pytest

from set_browser.pagination import Page, page_count, paginate


def test_49_items_is_two_pages():
    items = list(range(49))
    assert page_count(49) == 2
    first = paginate(items, 0)
    second = paginate(items, 1)
    assert len(first.items) == 48 and len(second.items) == 1
    assert second.items == (48,)


def test_exactly_48_is_one_page():
    assert page_count(48) == 1
    page = paginate(list(range(48)), 0)
    assert page.is_first and page.is_last


def test_empty_list_yields_one_empty_page():
    page = paginate([], 0)
    assert page == Page(items=(), index=0, page_count=1, total_items=0)
    assert page.is_first and page.is_last


def test_index_clamped_both_ends():
    items = list(range(100))
    assert paginate(items, -5).index == 0
    assert paginate(items, 99).index == 2  # 100 items / 48 -> pages 0..2


def test_custom_page_size():
    page = paginate(list(range(10)), 1, page_size=4)
    assert page.items == (4, 5, 6, 7)
    assert page.page_count == 3


def test_invalid_page_size_rejected():
    with pytest.raises(ValueError):
        page_count(10, page_size=0)
