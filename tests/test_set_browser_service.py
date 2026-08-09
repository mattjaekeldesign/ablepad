"""SetBrowserService: the roadmap Phase 4 exit checklist, end to end on tmp dirs."""

from set_browser.service import SetBrowserService


def build_sets(root, count, prefix="set"):
    for i in range(count):
        (root / f"{prefix}{i:03}.als").write_text("stub", encoding="utf-8")


def test_scan_merge_and_page(tmp_path):
    build_sets(tmp_path, 3)
    (tmp_path / "sets.yaml").write_text(
        "sets:\n  set000.als: {name: Opener, color: green}\n", encoding="utf-8"
    )
    service = SetBrowserService(sets_dir=tmp_path)
    assert service.rescan() == 3
    page = service.current_page()
    assert page.items[0].display_name == "Opener"
    assert page.items[1].display_name == "set001"


def test_empty_folder_is_state_not_crash(tmp_path):
    service = SetBrowserService(sets_dir=tmp_path)
    assert service.rescan() == 0
    assert service.is_empty
    assert service.current_page().items == ()
    assert service.set_at(0) is None


def test_pagination_past_48(tmp_path):
    build_sets(tmp_path, 50)
    service = SetBrowserService(sets_dir=tmp_path)
    service.rescan()
    assert service.current_page().page_count == 2
    second = service.next_page()
    assert second.index == 1 and len(second.items) == 2
    assert service.next_page().index == 1  # clamped at the end, no wrap
    assert service.prev_page().index == 0


def test_set_at_maps_page_position_to_the_right_set(tmp_path):
    build_sets(tmp_path, 50)
    service = SetBrowserService(sets_dir=tmp_path)
    service.rescan()
    service.next_page()
    chosen = service.set_at(1)
    assert chosen is not None and chosen.path.name == "set049.als"
    assert service.set_at(2) is None  # past the end of a 2-item page


def test_rescan_without_restart_picks_up_changes(tmp_path):
    build_sets(tmp_path, 2)
    service = SetBrowserService(sets_dir=tmp_path)
    assert service.rescan() == 2
    (tmp_path / "new.als").write_text("stub", encoding="utf-8")
    assert service.rescan() == 3  # same object, no restart


def test_rescan_preserves_page_where_possible(tmp_path):
    build_sets(tmp_path, 96)  # exactly 2 pages
    service = SetBrowserService(sets_dir=tmp_path)
    service.rescan()
    service.next_page()
    assert service.rescan() == 96
    assert service.current_page().index == 1  # still on page 2


def test_rescan_clamps_page_when_sets_vanish(tmp_path):
    build_sets(tmp_path, 96)
    service = SetBrowserService(sets_dir=tmp_path)
    service.rescan()
    service.next_page()
    for i in range(48, 96):  # delete page 2's contents
        (tmp_path / f"set{i:03}.als").unlink()
    service.rescan()
    assert service.current_page().index == 0  # clamped, not out of range
