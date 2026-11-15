"""The Data tab needs refs and rows; both come from one dataset open."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from lance_viewer import handlers  # noqa: E402

LOCAL = os.path.join(os.path.dirname(__file__), "..", "examples", "demo.lance")


def _dataset(path=LOCAL):
    info, err = handlers.dataset_info(path, limit=5, offset=0, include_refs=True)
    if err is not None:
        pytest.skip(err)
    return info


def test_dataset_info_can_carry_refs():
    """include_refs attaches the whole refs payload, identical to calling refs_info."""
    info = _dataset()
    refs, err = handlers.refs_info(LOCAL)
    assert err is None
    assert info["refs"] == refs


def test_dataset_info_omits_refs_by_default():
    """Paging callers (reloadDataTab) must not pay for refs they do not render."""
    info, err = handlers.dataset_info(LOCAL, limit=5, offset=0)
    assert err is None
    assert "refs" not in info


def test_merged_version_count_matches_refs_length():
    info = _dataset()
    assert info["versions"] == len(info["refs"]["versions"])


def test_rows_are_unaffected_by_refs():
    """Attaching refs must not change the row payload."""
    plain, err1 = handlers.dataset_info(LOCAL, limit=5, offset=0)
    merged = _dataset()
    assert err1 is None
    for key in ("count", "offset", "limit", "shown", "version", "schema", "columns", "display"):
        assert merged[key] == plain[key], key


def test_refs_of_reuses_the_open_dataset(monkeypatch):
    """_refs_of must not open the dataset itself; dataset_info already holds it.

    Counts real opens at the client, so the assertion fails if the helper ever starts opening its
    own copy (which is what merging the two endpoints is meant to prevent). A session id is passed
    so the count also proves the second call is served from the cache rather than reopened.
    """
    from lance_viewer import session_store

    opened = []
    original = session_store.open_dataset

    def _counting(*a, **k):
        opened.append(a)
        return original(*a, **k)

    session_store.clear()
    monkeypatch.setattr(session_store, "open_dataset", _counting)
    try:
        handlers.dataset_info(LOCAL, limit=5, offset=0, include_refs=True, session="t1")
        assert len(opened) == 1, f"expected exactly one open, got {len(opened)}"
        handlers.dataset_info(LOCAL, limit=5, offset=0, include_refs=True, session="t1")
        assert len(opened) == 1, "second call in the same session must hit the cache"
    finally:
        session_store.clear()
