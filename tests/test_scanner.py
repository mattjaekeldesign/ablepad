"""scanner: finds .als, refuses Ableton clutter, deterministic, no-crash on empty."""

from set_browser.scanner import is_performable, scan


def make(root, *rel_paths):
    for rel in rel_paths:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("stub", encoding="utf-8")


def test_finds_als_recursively(tmp_path):
    make(tmp_path, "worship.als", "sunday/opener.als", "notes.txt")
    found = scan(tmp_path)
    assert [p.name for p in found] == ["opener.als", "worship.als"]


def test_ignores_backup_folders(tmp_path):
    make(tmp_path, "song.als", "song Project/Backup/song [2026-08-01].als")
    assert [p.name for p in scan(tmp_path)] == ["song.als"]


def test_ignores_project_info_and_recovered_and_autosave(tmp_path):
    make(
        tmp_path,
        "good.als",
        "p/Ableton Project Info/whatever.als",
        "crash [Recovered].als",
        "thing.autosave.als",
    )
    assert [p.name for p in scan(tmp_path)] == ["good.als"]


def test_skip_rules_case_insensitive(tmp_path):
    make(tmp_path, "keep.als", "BACKUP/old.als", "loud [RECOVERED].als")
    assert [p.name for p in scan(tmp_path)] == ["keep.als"]


def test_missing_root_returns_empty_not_crash(tmp_path):
    assert scan(tmp_path / "nope") == []


def test_empty_root_returns_empty(tmp_path):
    assert scan(tmp_path) == []


def test_order_is_deterministic_and_case_insensitive(tmp_path):
    make(tmp_path, "b.als", "A.als", "c.als")
    assert [p.name for p in scan(tmp_path)] == ["A.als", "b.als", "c.als"]


def test_is_performable_unit():
    from pathlib import Path

    assert is_performable(Path("sets/worship.als"))
    assert not is_performable(Path("sets/Backup/worship.als"))
    assert not is_performable(Path("worship autosave.als"))
