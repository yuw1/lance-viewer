"""Large-dataset boundaries: the timeline window and the storage-tab analysis cap.

Both tabs used to touch every record a dataset had: the timeline decoded every `_transactions/*.txn`
(one object read each, on cloud) and the storage tab decoded every data file. These tests pin the
windows and the ordering (a 12-version dataset is where a lexicographic sort starts to lie).
"""
import pytest

from lance_viewer import handlers


@pytest.fixture(scope="module")
def versioned_dataset(tmp_path_factory):
    """12 versions, i.e. txn files 0..11 — past the point where string sorting breaks."""
    lance = pytest.importorskip("lance")
    pa = pytest.importorskip("pyarrow")

    path = tmp_path_factory.mktemp("versions") / "table.lance"
    lance.write_dataset(pa.table({"id": pa.array([0], type=pa.int64())}), str(path))
    for n in range(1, 12):
        lance.write_dataset(pa.table({"id": pa.array([n], type=pa.int64())}), str(path),
                            mode="append")
    return path


# ---------- timeline ----------

def test_newest_window_is_returned(versioned_dataset):
    info, err = handlers.transaction_timeline(str(versioned_dataset), limit=2)
    assert err is None, err

    assert info["total"] == 12
    assert [t["version"] for t in info["transactions"]] == [10, 11]
    assert info["offset"] == 0 and info["limit"] == 2
    assert info["has_more"] is True
    assert info["op_stats"] == {"append": 2}


def test_offset_pages_backwards(versioned_dataset):
    info, err = handlers.transaction_timeline(str(versioned_dataset), limit=2, offset=2)
    assert err is None, err

    assert [t["version"] for t in info["transactions"]] == [8, 9]
    assert info["has_more"] is True


def test_last_page_reports_no_more(versioned_dataset):
    info, err = handlers.transaction_timeline(str(versioned_dataset), limit=2, offset=10)
    assert err is None, err

    assert [t["version"] for t in info["transactions"]] == [0, 1]
    assert info["has_more"] is False


def test_offset_past_the_end_returns_no_rows(versioned_dataset):
    info, err = handlers.transaction_timeline(str(versioned_dataset), limit=5, offset=99)
    assert err is None, err

    assert info["transactions"] == []
    assert info["total"] == 12
    assert info["has_more"] is False


def test_window_is_ordered_numerically_not_lexicographically(versioned_dataset):
    # "10-" sorts before "2-" as a string; the newest three must still be 9, 10, 11.
    info, err = handlers.transaction_timeline(str(versioned_dataset), limit=3)
    assert err is None, err
    assert [t["version"] for t in info["transactions"]] == [9, 10, 11]


def test_limits_are_clamped(versioned_dataset):
    info, _ = handlers.transaction_timeline(str(versioned_dataset), limit=0)
    assert info["limit"] == 1
    assert len(info["transactions"]) == 1

    info, _ = handlers.transaction_timeline(str(versioned_dataset), limit=10 ** 6)
    assert info["limit"] == 1000


def test_txn_file_version_parses_names():
    assert handlers._txn_file_version("12-uuid.txn") == 12
    assert handlers._txn_file_version("0-uuid.txn") == 0
    assert handlers._txn_file_version("not-a-version.txn") == 1 << 62   # sorts last


# ---------- storage ----------

def test_storage_analyses_only_the_largest_files(monkeypatch):
    """20 data files in, 15 analysed: the cap and "largest first" are both asserted."""
    files = [(f"data/f{i:02d}.lance", 100 + i, None) for i in range(20)]
    monkeypatch.setattr(handlers, "_dataset_files", lambda path: (files, None))

    decoded = []
    monkeypatch.setattr(handlers, "_read_file_bytes",
                        lambda path, rel: (decoded.append(rel) or b"x", None))
    monkeypatch.setattr(handlers, "decode_datafile",
                        lambda buf: ({"columns": [], "schema": []}, None))

    info, err = handlers.storage_info("/fake/dataset")
    assert err is None, err

    assert info["data_files_total"] == 20
    assert info["data_files_analyzed"] == 15
    assert len(info["data_files"]) == 15
    assert sorted(decoded) == [f"data/f{i:02d}.lance" for i in range(5, 20)]
    assert info["top_files"][0]["path"].endswith("f19.lance")


def test_storage_counts_match_a_small_dataset(decoder_dataset):
    info, err = handlers.storage_info(str(decoder_dataset))
    assert err is None, err

    assert info["data_files_total"] == 1
    assert info["data_files_analyzed"] == 1
    assert len(info["data_files"]) == 1
    # Nothing was left unanalysed, so the UI has no note to show.
    assert info["data_files_total"] == info["data_files_analyzed"]