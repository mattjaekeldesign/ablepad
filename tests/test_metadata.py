"""metadata: overlay semantics — disk decides existence, yaml decides looks."""

from pathlib import Path

from set_browser.metadata import load_metadata, merge
from set_browser.models import NEUTRAL_COLOR


def touch(root, rel):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("stub", encoding="utf-8")
    return path.resolve()


def test_metadata_overrides_defaults(tmp_path):
    file = touch(tmp_path, "worship.als")
    merged = merge(
        [file],
        {"worship.als": {"name": "Worship", "color": "green", "category": "sunday"}},
        tmp_path,
    )
    (result,) = merged
    assert result.display_name == "Worship"
    assert result.color == "green"
    assert result.category == "sunday"
    assert result.has_metadata


def test_unknown_file_still_appears_neutral(tmp_path):
    file = touch(tmp_path, "mystery.als")
    (result,) = merge([file], {}, tmp_path)
    assert result.display_name == "mystery"
    assert result.color == NEUTRAL_COLOR
    assert not result.has_metadata


def test_yaml_entry_without_file_is_dropped_and_logged(tmp_path, caplog):
    file = touch(tmp_path, "real.als")
    with caplog.at_level("WARNING"):
        merged = merge([file], {"ghost.als": {"name": "Ghost"}}, tmp_path)
    assert [s.display_name for s in merged] == ["real"]
    assert any("ghost.als" in r.message for r in caplog.records)


def test_path_key_disambiguates_duplicate_filenames(tmp_path):
    a = touch(tmp_path, "sunday/set.als")
    b = touch(tmp_path, "praise/set.als")
    merged = merge([a, b], {"sunday/set.als": {"name": "Sunday"}}, tmp_path)
    by_path = {s.path: s for s in merged}
    assert by_path[a].display_name == "Sunday"
    assert by_path[b].display_name == "set"


def test_plain_key_matching_many_files_warns_but_applies(tmp_path, caplog):
    a = touch(tmp_path, "sunday/set.als")
    b = touch(tmp_path, "praise/set.als")
    with caplog.at_level("WARNING"):
        merged = merge([a, b], {"set.als": {"name": "Both"}}, tmp_path)
    assert [s.display_name for s in merged] == ["Both", "Both"]
    assert any("matched 2 files" in r.message for r in caplog.records)


def test_missing_metadata_file_is_fine(tmp_path):
    assert load_metadata(tmp_path / "sets.yaml") == {}


def test_malformed_metadata_file_disables_overrides(tmp_path, caplog):
    path = tmp_path / "sets.yaml"
    path.write_text("sets: [not, a, mapping", encoding="utf-8")
    with caplog.at_level("WARNING"):
        assert load_metadata(path) == {}


def test_partial_entry_keeps_defaults_for_the_rest(tmp_path):
    file = touch(tmp_path, "half.als")
    (result,) = merge([file], {"half.als": {"color": "red"}}, tmp_path)
    assert result.color == "red"
    assert result.display_name == "half"  # not overridden, falls back to stem
