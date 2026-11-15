"""Session-scoped dataset cache: one handle per (session, path, version, credentials).

Lifetime has two independent signals:
  - heartbeat: silence beyond HEARTBEAT_GONE_SECONDS means the tab is gone;
  - activity: HEARTBEAT alive but no real request for IDLE_SECONDS releases the handles anyway.
"""
import os
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from lance_viewer import session_store  # noqa: E402

LOCAL = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "examples", "demo.lance"))


@pytest.fixture(autouse=True)
def _clean():
    session_store.clear()
    yield
    session_store.clear()


def test_same_session_reuses_one_handle():
    ds1, err1 = session_store.open_cached("s1", LOCAL)
    ds2, err2 = session_store.open_cached("s1", LOCAL)
    assert (err1, err2) == (None, None)
    assert ds1 is ds2


def test_different_sessions_get_different_handles():
    """Two pages must not share a handle: one may be reading with different credentials."""
    ds1, _ = session_store.open_cached("s1", LOCAL)
    ds2, _ = session_store.open_cached("s2", LOCAL)
    assert ds1 is not ds2


def test_no_session_means_no_caching():
    ds1, _ = session_store.open_cached(None, LOCAL)
    ds2, _ = session_store.open_cached(None, LOCAL)
    assert ds1 is not ds2
    assert session_store.stats()["entries"] == 0


def test_credential_change_is_a_different_entry(monkeypatch):
    """PUT can swap storage options; a cached handle from the old ones must not be reused."""
    opts = {"access_key_id": "A"}
    # Patch where it is looked up: session_store imports the function, so patching
    # lance_client.storage_options would not affect the already-bound name.
    monkeypatch.setattr(session_store, "storage_options", lambda p: opts)
    ds1, _ = session_store.open_cached("s1", LOCAL)
    opts["access_key_id"] = "B"
    ds2, _ = session_store.open_cached("s1", LOCAL)
    assert ds1 is not ds2
    assert session_store.stats()["entries"] == 2


def test_pinned_version_is_its_own_entry():
    """A historical version must never be served from the latest entry."""
    latest, _ = session_store.open_cached("s1", LOCAL)
    pinned, err = session_store.open_cached("s1", LOCAL, version=1)
    assert err is None
    assert pinned.version == 1
    assert pinned is not latest


# ── Heartbeat: silence means the tab is gone ─────────────────────────────────────────────────────
def test_missing_heartbeat_releases_the_session(monkeypatch):
    monkeypatch.setattr(session_store, "HEARTBEAT_GONE_SECONDS", 0.2)
    session_store.open_cached("s1", LOCAL)
    assert session_store.stats()["sessions"] == 1
    time.sleep(0.3)
    session_store.sweep_once()
    assert session_store.stats()["sessions"] == 0


def test_heartbeat_keeps_the_session_alive(monkeypatch):
    """A page that keeps pinging must not be reclaimed, even past the gone-window."""
    monkeypatch.setattr(session_store, "HEARTBEAT_GONE_SECONDS", 0.4)
    monkeypatch.setattr(session_store, "IDLE_SECONDS", 100)
    session_store.open_cached("s1", LOCAL)
    for _ in range(3):
        time.sleep(0.25)
        session_store.heartbeat("s1")
        session_store.sweep_once()
    assert session_store.stats()["sessions"] == 1


def test_bye_releases_immediately():
    session_store.open_cached("s1", LOCAL)
    session_store.heartbeat("s1", bye=True)
    assert session_store.stats()["sessions"] == 0


def test_heartbeat_for_an_unknown_session_creates_nothing():
    """Pings before any dataset is opened must not allocate a bucket."""
    session_store.heartbeat("ghost")
    assert session_store.stats()["sessions"] == 0


# ── Activity: alive but unused ───────────────────────────────────────────────────────────────────
def test_idle_page_is_released_even_while_pinging(monkeypatch):
    """Heartbeats keep a page 'alive'; a page left open and unused still releases its memory."""
    monkeypatch.setattr(session_store, "HEARTBEAT_GONE_SECONDS", 100)
    monkeypatch.setattr(session_store, "IDLE_SECONDS", 0.25)
    session_store.open_cached("s1", LOCAL)
    for _ in range(3):
        time.sleep(0.12)
        session_store.heartbeat("s1")  # alive the whole time
        session_store.sweep_once()
    time.sleep(0.2)
    session_store.heartbeat("s1")
    session_store.sweep_once()
    assert session_store.stats()["sessions"] == 0, "idle timeout must win over a live heartbeat"


def test_a_real_request_resets_the_idle_clock(monkeypatch):
    monkeypatch.setattr(session_store, "IDLE_SECONDS", 0.4)
    monkeypatch.setattr(session_store, "HEARTBEAT_GONE_SECONDS", 100)
    session_store.open_cached("s1", LOCAL)
    time.sleep(0.25)
    session_store.touch_activity("s1")
    time.sleep(0.25)
    session_store.sweep_once()
    assert session_store.stats()["sessions"] == 1


# ── Bounds ───────────────────────────────────────────────────────────────────────────────────────
def test_handle_cap_is_enforced(monkeypatch):
    monkeypatch.setattr(session_store, "MAX_ENTRIES", 4)
    monkeypatch.setattr(session_store, "HEARTBEAT_GONE_SECONDS", 100)
    monkeypatch.setattr(session_store, "IDLE_SECONDS", 100)
    for i in range(10):
        session_store.open_cached(f"s{i}", LOCAL)
    assert session_store.stats()["entries"] <= 4


def test_drop_path_forgets_only_that_path():
    """Invalidating one dataset must not evict an unrelated cached one."""
    session_store.open_cached("s1", LOCAL)
    pinned, err = session_store.open_cached("s1", LOCAL, version=1)
    assert err is None
    assert len(_keys("s1")) == 2

    session_store.drop_path(LOCAL)
    assert _keys("s1") == set(), "every entry for the path is dropped, across versions"

    session_store.open_cached("s1", LOCAL, version=1)
    session_store.drop_path("/some/other/table.lance")
    assert len(_keys("s1")) == 1


def test_sweeper_started_once():
    """The background reaper must not be spawned more than once per process."""
    assert session_store.start_sweeper(interval=3600) is True
    assert session_store.start_sweeper(interval=3600) is False


def test_concurrent_readers_share_one_handle():
    """Requests run on threads; a cached handle must serve them all without error."""
    ds, err = session_store.open_cached("s1", LOCAL)
    assert err is None
    errors = []

    def work():
        try:
            for _ in range(5):
                ds.count_rows()
                ds.to_table(offset=0, limit=2)
                list(ds.schema)
        except Exception as e:  # noqa: BLE001 - the assertion is that nothing raises
            errors.append(f"{type(e).__name__}: {e}")

    threads = [threading.Thread(target=work) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []


def _keys(session_id):
    with session_store._lock:
        return set(session_store._sessions.get(session_id, {}).get("entries", {}))