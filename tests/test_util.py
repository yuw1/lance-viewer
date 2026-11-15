"""util.py pure-function unit tests (no external deps, runnable in CI directly)."""
import pytest

from lance_viewer import util


def test_fmt_timestamp_seconds():
    # second-range timestamp (2001~2096)
    assert util.fmt_timestamp(1_600_000_000) is not None


def test_fmt_timestamp_millis():
    # millisecond-range timestamp
    assert util.fmt_timestamp(1_600_000_000_000) is not None


def test_fmt_timestamp_non_timestamp():
    assert util.fmt_timestamp("abc") is None
    assert util.fmt_timestamp(42) is None
    assert util.fmt_timestamp(float("nan")) is None


def test_num_float_and_int():
    assert util.num(3.14159) == "3.1416"
    assert util.num(10) == "10"


def test_cell_to_py_short_list():
    # short lists returned as-is
    assert util.cell_to_py([1, 2, 3]) == [1, 2, 3]


def test_cell_to_py_long_list_folds():
    # vectors longer than 8 elements are folded into a __vector__ summary
    long_vec = list(range(20))
    out = util.cell_to_py(long_vec)
    assert out["__vector__"] is True
    assert out["dims"] == 20


def test_cell_to_py_none():
    assert util.cell_to_py(None) is None


def test_sanitize_index_stat_folds_centroids():
    stats = {"centroids": [[0.1, 0.2]] * 5, "num_rows": 100}
    out = util.sanitize_index_stat(stats)
    assert out["centroids"]["__folded__"] is True
    assert out["centroids"]["num_centroids"] == 5
    assert out["num_rows"] == 100


def test_sanitize_index_stat_non_dict():
    assert util.sanitize_index_stat("x") == "x"


def test_categorize():
    assert util.categorize("data/1.lance")[0] == "data"
    assert util.categorize("_versions/1.manifest")[0] == "versions"
    assert util.categorize("_indices/abc")[0] == "indices"
    assert util.categorize("_deletions/x.arrow")[0] == "deletions"
    assert util.categorize("_transactions/0.txn")[0] == "transactions"
    assert util.categorize("README.md")[0] == "other"


def test_collect_files(tmp_path):
    (tmp_path / "a.txt").write_text("hello")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.txt").write_text("world")
    files = util.collect_files(str(tmp_path))
    assert {f for f, _ in files} == {"a.txt", "sub/b.txt"}
