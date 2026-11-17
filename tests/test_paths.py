from datetime import datetime

from omni_recorder.paths import call_id_for, list_call_ids, new_call_id

T = datetime(2026, 11, 17, 9, 5)


def test_call_id_format():
    assert call_id_for(T) == "2026-11-17_0905"


def test_first_id_is_plain(tmp_path):
    assert new_call_id(tmp_path, T) == "2026-11-17_0905"


def test_collisions_get_suffix(tmp_path):
    (tmp_path / "2026-11-17_0905").mkdir()
    assert new_call_id(tmp_path, T) == "2026-11-17_0905_2"
    (tmp_path / "2026-11-17_0905_2").mkdir()
    assert new_call_id(tmp_path, T) == "2026-11-17_0905_3"


def test_missing_records_dir_ok(tmp_path):
    assert new_call_id(tmp_path / "nope", T) == "2026-11-17_0905"
    assert list_call_ids(tmp_path / "nope") == []


def test_list_call_ids_sorted(tmp_path):
    for n in ("b", "a"):
        (tmp_path / n).mkdir()
    (tmp_path / "file.txt").write_text("x")
    assert list_call_ids(tmp_path) == ["a", "b"]
