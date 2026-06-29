from clinic_monitor.state import load_seen, save_seen


def test_roundtrip(tmp_path):
    path = tmp_path / "state.json"
    assert load_seen(path) == set()  # missing file -> empty

    save_seen(path, {"a", "b", "c"})
    assert load_seen(path) == {"a", "b", "c"}


def test_corrupt_file_is_ignored(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("not json {", encoding="utf-8")
    assert load_seen(path) == set()
