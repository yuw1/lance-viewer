"""Per-browser-session cache of open datasets.

A page keeps a session id (X-Lance-Session) on every API call. The server keeps one Dataset handle
per (session, path, version, credentials), so switching tabs reuses the already-open dataset.

Lifetime is driven by two independent signals, because "the page is gone" and "the page is open but
unused" are different problems with different answers:

  - heartbeat: the page posts /api/heartbeat every 20s. No heartbeat for HEARTBEAT_GONE_SECONDS
    means the tab is gone (killed browser, network loss, crash) and its handles are released. A
    closing page also fires one last "bye" beacon, releasing immediately instead of waiting.
  - activity: a real API request. A page can stay open and idle; after IDLE_SECONDS with no real
    request the handles are released even though the page is still alive.

The heartbeat grace window is deliberately much wider than the interval: browsers throttle timers in
background tabs to roughly one minute, so a 20s heartbeat can legitimately arrive 60s apart. A
window of one or two beats would evict the dataset of a user who merely switched windows.

Handles are only ever read here, never checked out: Dataset.checkout_latest() mutates the shared
object and raises `RuntimeError: Already borrowed` under concurrent requests (measured: 9 of 10
threads failed). Callers that need a different version get a different cache entry instead.
"""
import hashlib
import os
import threading
import time

from .lance_client import open_dataset, storage_options


def _env_seconds(name, default):
    try:
        value = float(os.environ.get(name, ""))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


# What the frontend sends (informational; the page owns this number).
HEARTBEAT_INTERVAL_SECONDS = 20
# Silence longer than this means the tab is gone. Wide enough to survive background-tab throttling.
HEARTBEAT_GONE_SECONDS = _env_seconds("LANCE_VIEWER_HEARTBEAT_GONE", 90)
# Alive but no real request for this long: release anyway.
IDLE_SECONDS = _env_seconds("LANCE_VIEWER_SESSION_IDLE", 120)
# How often the background sweeper looks for expired sessions.
SWEEP_INTERVAL_SECONDS = 10
# Upper bound on cached handles across all sessions (a guard, not an expected hit rate).
MAX_ENTRIES = 64

_lock = threading.Lock()
# session id -> {
#     "entries": {(path, version, cred_fingerprint): (ds, last_used_monotonic)},
#     "heartbeat": monotonic of the last heartbeat,
#     "activity": monotonic of the last real API request,
# }
_sessions = {}
_sweeper_started = False


def _now():
    return time.monotonic()


def _fingerprint(options):
    """Stable short hash of the storage options so credential changes get a new cache entry."""
    if not options:
        return "-"
    payload = repr(sorted((str(k), str(v)) for k, v in options.items())).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def _new_session(now):
    return {"entries": {}, "heartbeat": now, "activity": now}


def get(session_id, path, version, options):
    """Return the cached handle for this session/version, or None."""
    if not session_id:
        return None
    key = (path, version, _fingerprint(options))
    now = _now()
    with _lock:
        _sweep_locked(now)
        sess = _sessions.get(session_id)
        if sess is None:
            return None
        entry = sess["entries"].get(key)
        if entry is None:
            return None
        ds, _ = entry
        sess["entries"][key] = (ds, now)
        sess["activity"] = now  # a cache hit is still a real request
        return ds


def put(session_id, path, version, options, ds):
    """Cache an opened handle for this session."""
    if not session_id or ds is None:
        return
    key = (path, version, _fingerprint(options))
    now = _now()
    with _lock:
        _sweep_locked(now)
        sess = _sessions.get(session_id)
        if sess is None:
            sess = _sessions[session_id] = _new_session(now)
        sess["entries"][key] = (ds, now)
        sess["activity"] = now
        _evict_cold()


def heartbeat(session_id, bye=False):
    """Record a liveness ping, or release the session now when the page is closing."""
    if not session_id:
        return
    now = _now()
    with _lock:
        if bye:
            _sessions.pop(session_id, None)
            return
        sess = _sessions.get(session_id)
        if sess is None:
            # Nothing cached yet: no object to keep alive, and creating a bucket per ping would be
            # pure overhead. The first cached handle starts the clock.
            return
        sess["heartbeat"] = now


def touch_activity(session_id):
    """Mark a real API request. Heartbeats deliberately do not call this."""
    if not session_id:
        return
    now = _now()
    with _lock:
        sess = _sessions.get(session_id)
        if sess is not None:
            sess["activity"] = now


def drop_path(path):
    """Forget every cached handle for a path (used when its registry row changes)."""
    with _lock:
        for sess in _sessions.values():
            for key in [k for k in sess["entries"] if k[0] == path]:
                sess["entries"].pop(key, None)
        _drop_empty_locked()


def clear():
    with _lock:
        _sessions.clear()


def stats():
    """For diagnostics/tests: cached session and handle counts."""
    with _lock:
        return {"sessions": len(_sessions),
                "entries": sum(len(s["entries"]) for s in _sessions.values())}


def sweep_once():
    """Release expired sessions; returns how many were dropped. Safe to call from any thread."""
    with _lock:
        return _sweep_locked(_now())


def start_sweeper(interval=None):
    """Start the background reaper. Idempotent; returns whether this call started it.

    A lazy sweep on every request is not enough: once the last page closes there are no requests
    left to trigger one, so the handles would sit in memory until something else happened.
    """
    global _sweeper_started
    with _lock:
        if _sweeper_started:
            return False
        _sweeper_started = True

    def loop():
        while True:
            time.sleep(interval if interval is not None else SWEEP_INTERVAL_SECONDS)
            try:
                sweep_once()
            except Exception:  # noqa: BLE001 - the reaper must never take the server down
                pass

    threading.Thread(target=loop, name="session-sweeper", daemon=True).start()
    return True


def _sweep_locked(now):
    expired = [sid for sid, s in _sessions.items()
               if now - s["heartbeat"] > HEARTBEAT_GONE_SECONDS
               or now - s["activity"] > IDLE_SECONDS]
    for sid in expired:
        _sessions.pop(sid, None)
    return len(expired)


def _drop_empty_locked():
    for sid in [s for s, v in _sessions.items() if not v["entries"]]:
        _sessions.pop(sid, None)


def _evict_cold():
    """Drop least-recently-used handles until the total is back under the cap."""
    entries = [(t, sid, key)
               for sid, sess in _sessions.items()
               for key, (_, t) in sess["entries"].items()]
    total = len(entries)
    if total <= MAX_ENTRIES:
        return
    entries.sort()
    for _, sid, key in entries[: total - MAX_ENTRIES]:
        sess = _sessions.get(sid)
        if sess is not None:
            sess["entries"].pop(key, None)
    _drop_empty_locked()


def open_cached(session_id, path, version=None):
    """Open a dataset through the session cache.

    Same contract as lance_client.open_dataset: returns (ds, err). The handle is safe to read from
    multiple request threads; it must not be mutated (no checkout) by callers.
    """
    # The credentials are part of the cache key: a PUT can swap them, and a handle opened with the
    # old ones must never serve a request made with the new ones.
    options = storage_options(path)

    ds = get(session_id, path, version, options)
    if ds is not None:
        return ds, None

    ds, err = open_dataset(path, version=version)
    if err:
        return None, err
    put(session_id, path, version, options, ds)
    return ds, None