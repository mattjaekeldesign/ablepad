"""RuntimeStateStore: round-trip, atomicity mechanics, corrupt-file quarantine."""

from storage.runtime_state import RuntimeStateStore


def test_round_trip(tmp_path):
    store = RuntimeStateStore(tmp_path / "runtime_state.json")
    store.save({"last_set": "worship.als", "page": 2})
    assert store.load() == {"last_set": "worship.als", "page": 2}


def test_missing_file_loads_empty(tmp_path):
    assert RuntimeStateStore(tmp_path / "absent.json").load() == {}


def test_corrupt_file_quarantined_not_fatal(tmp_path, caplog):
    path = tmp_path / "runtime_state.json"
    path.write_text("{ half a json", encoding="utf-8")
    store = RuntimeStateStore(path)
    with caplog.at_level("WARNING"):
        assert store.load() == {}
    assert (tmp_path / "runtime_state.json.corrupt").exists()
    assert not path.exists()


def test_non_object_json_treated_as_corrupt(tmp_path):
    path = tmp_path / "runtime_state.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    assert RuntimeStateStore(path).load() == {}


def test_save_leaves_no_temp_files(tmp_path):
    store = RuntimeStateStore(tmp_path / "runtime_state.json")
    store.save({"a": 1})
    store.save({"a": 2})
    leftovers = [p for p in tmp_path.iterdir() if p.suffix == ".tmp"]
    assert leftovers == []
    assert store.load() == {"a": 2}


def test_save_creates_parent_dirs(tmp_path):
    store = RuntimeStateStore(tmp_path / "deep" / "nested" / "state.json")
    store.save({"ok": True})
    assert store.load() == {"ok": True}
