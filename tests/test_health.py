"""Dataset health tab: fragment sizing, tombstones, index coverage and version churn.

All of it is metadata, so these tests can build small datasets with real deletions and multiple
versions and still run in well under a second.
"""
import pytest

from lance_viewer import handlers


def _lance():
    return pytest.importorskip("lance")


def _pa():
    return pytest.importorskip("pyarrow")


def _table(rows=30):
    pa = _pa()
    return pa.table({
        "id": pa.array(range(rows), type=pa.int64()),
        "name": pa.array([f"n{i}" for i in range(rows)], type=pa.string()),
        "vec": pa.array([[float(i)] * 4 for i in range(rows)], type=pa.list_(pa.float32(), 4)),
    })


@pytest.fixture
def health_dataset(tmp_path):
    """30 rows split into three 10-row fragments (every fragment counts as "small")."""
    path = tmp_path / "health.lance"
    _lance().write_dataset(_table(), str(path), max_rows_per_file=10)
    return path


def test_reports_structure_and_fragment_stats(health_dataset):
    info, err = handlers.health_info(str(health_dataset))
    assert err is None, err

    assert info["rows"] == 30
    assert info["fragments"] == 3
    assert info["data_files"] == 3
    assert info["versions"] == 1
    assert info["size_bytes"] > 0
    assert info["deleted_rows"] == 0

    assert info["fragment_stats"] == {"min": 10, "median": 10, "max": 10}
    assert info["format"]["data_storage_version"]
    assert [c["field"] for c in info["coverage"]] == ["id", "name", "vec"]
    assert all(c["index_types"] == [] for c in info["coverage"])


def test_flags_small_fragments_and_an_unindexed_vector_column(health_dataset):
    info, err = handlers.health_info(str(health_dataset))
    assert err is None, err

    codes = {issue["code"] for issue in info["issues"]}
    assert "small_fragments" in codes
    assert "no_vector_index" in codes
    assert "tombstones" not in codes

    small = next(i for i in info["issues"] if i["code"] == "small_fragments")
    assert small["params"] == {"n": 3, "total": 3, "threshold": handlers.HEALTH_SMALL_FRAGMENT_ROWS}
    # Every fragment is small here, so it is escalated rather than filed as a note.
    assert small["severity"] == "warn"


def test_deletions_are_reported_with_a_ratio(health_dataset):
    ds = _lance().dataset(str(health_dataset))
    ds.delete("id < 5")

    info, err = handlers.health_info(str(health_dataset))
    assert err is None, err

    assert info["rows"] == 25
    assert info["deleted_rows"] == 5

    tombstone = next(i for i in info["issues"] if i["code"] == "tombstones")
    assert tombstone["severity"] == "warn"
    assert tombstone["params"]["rows"] == 5
    assert tombstone["params"]["pct"] == pytest.approx(16.7)
    # Warnings sort ahead of informational findings.
    assert info["issues"][0]["code"] == "tombstones"


def test_index_coverage_reflects_created_indexes(health_dataset):
    ds = _lance().dataset(str(health_dataset))
    ds.create_scalar_index("name", "BTREE")

    info, err = handlers.health_info(str(health_dataset))
    assert err is None, err

    by_field = {c["field"]: c["index_types"] for c in info["coverage"]}
    assert by_field["name"] == ["BTree"]
    assert by_field["vec"] == []
    assert info["indexes"][0]["fields"] == ["name"]
    assert "no_vector_index" in {i["code"] for i in info["issues"]}


def test_version_churn_is_reported_for_a_heavily_appended_dataset(tmp_path):
    lance = _lance()
    path = tmp_path / "churn.lance"
    lance.write_dataset(_table(rows=30), str(path))
    for _ in range(20):
        lance.write_dataset(_table(rows=5), str(path), mode="append")

    info, err = handlers.health_info(str(path))
    assert err is None, err

    assert info["versions"] == 21
    churn = next(i for i in info["issues"] if i["code"] == "version_churn")
    assert churn["severity"] == "info"
    assert churn["params"]["versions"] == 21
    assert churn["params"]["ratio"] >= 3