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

# ---------- vector index partition health ----------

def test_vector_partition_issue_flags_a_lopsided_ivf_index():
    issue = handlers._vector_partition_issue("idx_hnsw", {
        "num_indexed_rows": 30_000,
        "indices": [{"num_partitions": 2}],
    })
    assert issue is not None
    assert issue["code"] == "vector_partitions"
    assert issue["severity"] == "warn"
    assert issue["params"] == {
        "index": "idx_hnsw",
        "rows_per_partition": 15_000,
        "indexed_rows": 30_000,
        "partitions": 2,
        "threshold": handlers.HEALTH_MAX_ROWS_PER_PARTITION,
    }


def test_vector_partition_issue_is_quiet_when_balanced():
    assert handlers._vector_partition_issue("idx", {
        "num_indexed_rows": 10_000, "indices": [{"num_partitions": 4}],
    }) is None


def test_vector_partition_issue_sums_partitions_across_segments():
    issue = handlers._vector_partition_issue("idx", {
        "num_indexed_rows": 60_000,
        "indices": [{"num_partitions": 2}, {"num_partitions": 3}],
    })
    assert issue is not None
    assert issue["params"]["partitions"] == 5
    assert issue["params"]["rows_per_partition"] == 12_000


def test_vector_partition_issue_ignores_missing_stat_fields():
    for stats in ({}, {"num_indexed_rows": 0}, {"num_indexed_rows": 10, "indices": [{"num_partitions": 0}]}):
        assert handlers._vector_partition_issue("idx", stats) is None


def test_health_info_emits_the_partition_finding(health_dataset, monkeypatch):
    """Only IVF indices are checked; the finding is threaded into the issues list."""
    calls = []

    def fake_describe(ds):
        return [{"name": "vec_idx", "type": "IVF_HNSW_FLAT", "fields": ["vec"]},
                {"name": "btree_idx", "type": "BTree", "fields": ["name"]}]

    def fake_stats(ds, name):
        calls.append(name)
        return {"num_indexed_rows": 30_000, "indices": [{"num_partitions": 2}]}

    monkeypatch.setattr(handlers, "_describe_indices", fake_describe)
    monkeypatch.setattr(handlers, "_index_stats", fake_stats)

    info, err = handlers.health_info(str(health_dataset))
    assert err is None, err

    codes = {i["code"] for i in info["issues"]}
    assert "vector_partitions" in codes
    finding = next(i for i in info["issues"] if i["code"] == "vector_partitions")
    assert finding["params"]["index"] == "vec_idx"
    assert finding["params"]["rows_per_partition"] == 15_000
    # Stats were fetched for the IVF index only, never the BTree.
    assert calls == ["vec_idx"]


def test_vector_partition_issue_at_production_scale():
    """A large table built into a single partition: rows-per-partition dwarfs the threshold."""
    issue = handlers._vector_partition_issue("idx_vec", {
        "num_indexed_rows": 10_000_000,
        "indices": [{"num_partitions": 1}],
    })
    assert issue is not None
    assert issue["params"]["rows_per_partition"] == 10_000_000
    assert issue["params"]["partitions"] == 1
    # Exactly three orders of magnitude past the threshold: decisively "too few partitions".
    assert issue["params"]["rows_per_partition"] >= 1000 * issue["params"]["threshold"]


def test_healthy_sqrt_scale_partitioning_is_not_flagged():
    """A large table partitioned at ~sqrt(n) stays comfortably under the threshold."""
    issue = handlers._vector_partition_issue("idx_vec", {
        "num_indexed_rows": 10_000_000,
        "indices": [{"num_partitions": 3_200}],
    })
    assert issue is None
