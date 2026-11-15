"""Storage-analysis and transaction-timeline tabs.

Both used to bail out early on object storage ("do not support the local ... view") even though the
underlying reads already worked — the guards dated from the first commit, before cloud reads existed.
These tests pin that the two views now share one file listing and work for both backends.
"""
import os

import pyarrow as pa
import pytest

from lance_viewer import handlers


@pytest.fixture(scope="module")
def local_ds(tmp_path_factory):
    import lance
    path = str(tmp_path_factory.mktemp("ds") / "table.lance")
    lance.write_dataset(pa.table({"id": [1, 2, 3], "name": ["a", "b", "c"]}), path)
    lance.write_dataset(pa.table({"id": [4, 5], "name": ["d", "e"]}), path, mode="append")
    return path


def test_dataset_files_lists_local_files_with_mtime(local_ds):
    files, err = handlers._dataset_files(local_ds)
    assert err is None
    rels = {rel for rel, _, _ in files}
    assert any(r.startswith("data/") and r.endswith(".lance") for r in rels)
    assert any(r.startswith("_versions/") for r in rels)
    # mtime is a formatted local timestamp, not a raw float
    assert all(mt is None or (isinstance(mt, str) and len(mt) == 19) for _, _, mt in files)


def test_dataset_files_rejects_a_missing_path(tmp_path):
    files, err = handlers._dataset_files(str(tmp_path / "nope"))
    assert files is None and "not a valid Lance dataset directory" in err


def test_dataset_files_accepts_an_empty_directory(tmp_path):
    # Matches the pre-existing contract: only "is this a directory" is validated, the walk may find
    # nothing. storage_info then reports a zero total rather than an error.
    files, err = handlers._dataset_files(str(tmp_path))
    assert (files, err) == ([], None)
    info, err = handlers.storage_info(str(tmp_path))
    assert err is None and info["total_size"] == 0 and info["data_files"] == []


def test_storage_info_works_on_a_local_dataset(local_ds):
    info, err = handlers.storage_info(local_ds)
    assert err is None
    assert info["total_size"] > 0
    keys = {t["key"] for t in info["file_types"]}
    assert {"data", "versions"} <= keys
    # per-column decode ran on both data files
    assert len(info["data_files"]) == 2
    for df in info["data_files"]:
        assert "error" not in df
        assert [c["name"] for c in df["columns"]] == ["id", "name"]
        assert all(c["pages"] >= 1 for c in df["columns"])


def test_transaction_timeline_works_on_a_local_dataset(local_ds):
    info, err = handlers.transaction_timeline(local_ds)
    assert err is None
    ops = [t["operation"] for t in info["transactions"]]
    assert ops == ["overwrite", "append"]
    assert info["op_stats"] == {"overwrite": 1, "append": 1}
    assert info["has_snapshot"] is True
    # txn file version is one less than the manifest it produces
    assert [t["snapshot"]["rows"] for t in info["transactions"]] == [3, 5]
    assert all(t["mtime"] for t in info["transactions"])


def test_read_file_bytes_reads_local_files(local_ds):
    rel = next(r for r, _, _ in handlers._dataset_files(local_ds)[0]
               if r.startswith("data/") and r.endswith(".lance"))
    buf, err = handlers._read_file_bytes(local_ds, rel)
    assert err is None and len(buf) > 0


def test_mtime_str_normalises_timezones():
    from datetime import datetime, timezone, timedelta
    utc = datetime(2026, 11, 12, 14, 38, 35, tzinfo=timezone.utc)
    # Same instant expressed in UTC+8 formats identically once converted
    plus8 = utc.astimezone(timezone(timedelta(hours=8)))
    assert handlers._mtime_str(utc) == handlers._mtime_str(plus8)
    # Naive datetimes are treated as UTC rather than silently shifted twice
    assert handlers._mtime_str(utc.replace(tzinfo=None)) == handlers._mtime_str(utc)
    assert handlers._mtime_str(None) is None


CLOUD = os.environ.get("LANCE_VIEWER_TEST_CLOUD_PATH", "s3://example-bucket/test_table.lance")


def _cloud_or_skip():
    if os.environ.get("LANCE_VIEWER_TEST_CLOUD") != "1":
        pytest.skip("set LANCE_VIEWER_TEST_CLOUD=1 (optional LANCE_VIEWER_TEST_CLOUD_PATH) "
                    "to run object-storage tests")


def test_storage_info_works_on_object_storage():
    """Cloud branch: listing comes from a prefixed OpenDAL LIST, data-file metadata from a range read."""
    _cloud_or_skip()
    info, err = handlers.storage_info(CLOUD)
    if err is not None:
        pytest.skip(f"S3 unreachable: {err}")
    assert info["total_size"] > 0
    assert info["data_files"], "should decode at least one data file"
    for df in info["data_files"]:
        assert "error" not in df


def test_transaction_timeline_works_on_object_storage():
    _cloud_or_skip()
    info, err = handlers.transaction_timeline(CLOUD)
    if err is not None:
        pytest.skip(f"S3 unreachable: {err}")
    assert info["transactions"], "should decode at least one txn file"
    assert all(t.get("operation") for t in info["transactions"])

def test_object_storage_listing_does_not_open_the_dataset():
    """Listing is a pure file operation: it must not open the dataset.

    The listing used to go through ds.all_files(), which paid a full dataset open (manifest
    parse, schema decode) just to run a LIST. A working file tree must survive a dataset that
    cannot be opened, so this pins the backend split: one LIST, no dataset.
    """
    _cloud_or_skip()
    import lance_viewer.lance_client as lc

    opened = []
    original = lc.open_dataset

    def _tracking(*a, **k):
        opened.append(a)
        return original(*a, **k)

    lc.open_dataset = _tracking
    try:
        files, err = handlers._dataset_files(CLOUD)
    finally:
        lc.open_dataset = original
    if err is not None:
        pytest.skip(f"S3 unreachable: {err}")
    assert files, "should list at least one file"
    assert opened == [], "listing must not open the dataset"


def test_object_storage_listing_returns_size_and_mtime():
    _cloud_or_skip()
    files, err = handlers._dataset_files(CLOUD)
    if err is not None:
        pytest.skip(f"S3 unreachable: {err}")
    assert all(isinstance(rel, str) and rel for rel, _, _ in files)
    assert all(isinstance(size, int) and size >= 0 for _, size, _ in files)
    # Object storage reports last_modified, so mtime should be present as a local timestamp
    assert all(mt is None or len(mt) == 19 for _, _, mt in files)
    assert any(mt is not None for _, _, mt in files)


def test_listing_a_bucket_root_is_rejected(monkeypatch):
    """A dataset path at the bucket root has an empty prefix, and scan("") lists the whole bucket.

    That would mix every unrelated object in the bucket into the file tree, so the listing
    refuses it. Checked from the path alone (before the client is built), so the message does not
    depend on whether storage options happen to be registered. No network.
    """
    monkeypatch.setattr(handlers, "is_cloud", lambda p: True)

    def _must_not_build(path, rel):
        raise AssertionError("must refuse before building the client")

    monkeypatch.setattr(handlers, "_open_operator", _must_not_build)
    for root in ("s3://example-bucket", "s3://example-bucket/"):
        files, err = handlers._dataset_files(root)
        assert files is None
        assert "bucket root" in err


def test_object_prefix_returns_the_key_below_the_bucket():
    assert handlers._object_prefix("s3://b/table.lance") == "table.lance"
    assert handlers._object_prefix("s3://b/a/b/table.lance") == "a/b/table.lance"
    assert handlers._object_prefix("oss://b/t.lance") == "t.lance"
    assert handlers._object_prefix("s3://b") == ""
    assert handlers._object_prefix("s3://b/") == ""
