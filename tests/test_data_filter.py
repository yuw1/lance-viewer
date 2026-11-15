"""Data tab: row filtering, pushed into the scan rather than applied in the browser."""
import pytest

from lance_viewer import handlers


# ---------- row filter ----------

def test_filter_limits_rows_and_count(decoder_dataset):
    info, err = handlers.dataset_info(str(decoder_dataset), limit=10, filter="id < 5")
    assert err is None, err

    assert info["count"] == 5              # the total describes the filtered set, not the table
    assert info["shown"] == 5
    assert info["columns"]["id"] == [0, 1, 2, 3, 4]
    assert info["filter"] == "id < 5"


def test_filter_paginates_within_the_filtered_set(decoder_dataset):
    info, err = handlers.dataset_info(str(decoder_dataset), limit=3, offset=2, filter="id >= 10")
    assert err is None, err

    assert info["count"] == 14
    assert info["columns"]["id"] == [12, 13, 14]


def test_filter_combines_with_column_projection(decoder_dataset):
    info, err = handlers.dataset_info(str(decoder_dataset), limit=5, columns=["id"],
                                      filter="id < 3")
    assert err is None, err

    assert list(info["columns"]) == ["id"]
    assert info["columns"]["id"] == [0, 1, 2]


def test_no_filter_means_no_echo(decoder_dataset):
    info, err = handlers.dataset_info(str(decoder_dataset), limit=1)
    assert err is None, err
    assert info["filter"] is None
    assert info["count"] == 24


def test_invalid_filter_is_reported_instead_of_raising(decoder_dataset):
    info, err = handlers.dataset_info(str(decoder_dataset), filter="id <<<")
    assert info is None
    assert err and "Filter failed" in err
