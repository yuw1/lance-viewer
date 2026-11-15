"""dataset_store.py SQLite registry CRUD unit tests (temp DB; does not touch real data)."""
import tempfile

from lance_viewer.dataset_store import DatasetStore


def _fresh_store():
    """Each test uses an independent temp DB to avoid cross-talk."""
    return DatasetStore(db_path=tempfile.mktemp(suffix=".db"))


def test_add_and_get_by_path():
    s = _fresh_store()
    row = s.add("demo", "/data/demo", "note")
    assert row["id"] > 0
    got = s.get_by_path("/data/demo")
    assert got is not None
    assert got["name"] == "demo"
    assert got["note"] == "note"


def test_add_duplicate_path_updates():
    s = _fresh_store()
    s.add("a", "/data/x")
    s.add("b", "/data/x")
    rows = [r for r in s.list_all() if r["path"] == "/data/x"]
    # UNIQUE(path) -> should be a single row, name updated to b
    assert len(rows) == 1
    assert rows[0]["name"] == "b"


def test_add_with_options():
    s = _fresh_store()
    s.add("s3", "s3://bucket/ds", options={"aws_access_key_id": "x"})
    got = s.get_by_path("s3://bucket/ds")
    assert got["options"] == {"aws_access_key_id": "x"}


def test_update_fields():
    s = _fresh_store()
    row = s.add("old", "/data/p")
    updated = s.update(row["id"], name="new", note="")
    assert updated["name"] == "new"
    assert updated["note"] == ""


def test_delete():
    s = _fresh_store()
    row = s.add("del", "/data/d")
    assert s.delete(row["id"]) is True
    assert s.delete(row["id"]) is False  # second delete returns False
    assert s.get_by_path("/data/d") is None


def test_list_all_empty_then_with_items():
    s = _fresh_store()
    assert s.list_all() == []
    s.add("one", "/data/1")
    assert len(s.list_all()) == 1
