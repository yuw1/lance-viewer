"""server.py HTTP routing integration tests (start a real server; test routes + error paths; no Lance data needed)."""
import json
import threading
import urllib.request
import urllib.parse
import urllib.error
from http.server import ThreadingHTTPServer

from lance_viewer.server import Handler


class _ServerCtx:
    def __init__(self):
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.srv.server_address[1]
        self.thread = threading.Thread(target=self.srv.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.srv.shutdown()
        self.srv.server_close()

    def get(self, path):
        url = f"http://127.0.0.1:{self.port}{path}"
        try:
            with urllib.request.urlopen(url) as r:
                return r.status, json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            # Non-200 responses (e.g. 400/404) also carry a JSON body; return normally
            return e.code, json.loads(e.read().decode("utf-8"))

    def get_session(self, path, session):
        """GET carrying the page session header, like the browser does."""
        url = f"http://127.0.0.1:{self.port}{path}"
        req = urllib.request.Request(url, headers={"X-Lance-Session": session})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    def put(self, path, payload):
        url = f"http://127.0.0.1:{self.port}{path}"
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"), method="PUT",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    def post_raw(self, path):
        """POST with no body: the shape navigator.sendBeacon produces for the closing ping."""
        url = f"http://127.0.0.1:{self.port}{path}"
        req = urllib.request.Request(url, data=b"", method="POST")
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    def get_raw(self, path):
        """Return the raw text body (for non-JSON responses like the HTML home page)."""
        url = f"http://127.0.0.1:{self.port}{path}"
        try:
            with urllib.request.urlopen(url) as r:
                return r.status, r.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8")

    def get_bytes(self, path):
        """Return (status, body bytes, content-type) for binary assets like the favicon."""
        url = f"http://127.0.0.1:{self.port}{path}"
        try:
            with urllib.request.urlopen(url) as r:
                return r.status, r.read(), r.headers.get("Content-Type")
        except urllib.error.HTTPError as e:
            return e.code, e.read(), e.headers.get("Content-Type")


def test_index_html_served():
    with _ServerCtx() as srv:
        status, body = srv.get_raw("/")
        assert status == 200
        assert "<!DOCTYPE" in body or "<html" in body


def test_index_html_declares_favicons():
    # Browsers silently request /favicon.ico otherwise; assert the links are declared.
    with _ServerCtx() as srv:
        status, body = srv.get_raw("/")
        assert status == 200
        assert 'rel="icon"' in body
        assert "favicon.svg" in body
        assert "apple-touch-icon" in body


def test_favicon_ico_served():
    with _ServerCtx() as srv:
        status, body, ctype = srv.get_bytes("/favicon.ico")
        assert status == 200
        assert ctype == "image/x-icon"
        # ICO header: reserved=0, type=1 (icon), count>=1
        assert body[:4] == b"\x00\x00\x01\x00"
        assert len(body) > 100


def test_static_content_types_do_not_follow_the_host_mime_database(monkeypatch):
    """The Content-Type must not depend on the OS mime database.

    mimetypes consults /etc/apache2/mime.types and friends, which disagree between hosts: on macOS
    .ico resolves to image/x-icon while Python's own table says image/vnd.microsoft.icon (what a
    plain Linux runner reports). Pinning the types we ship keeps the answer identical everywhere.
    """
    from lance_viewer import server

    monkeypatch.setattr(server.mimetypes, "guess_type", lambda name: ("application/x-host-specific", None))
    assert server._content_type("favicon.ico") == "image/x-icon"
    assert server._content_type("style.css").startswith("text/css")
    assert server._content_type("render.js").startswith("text/javascript")
    assert server._content_type("favicon.svg") == "image/svg+xml"
    # Unknown suffixes still defer to the OS lookup, then to the generic type.
    assert server._content_type("thing.weird") == "application/x-host-specific"
    monkeypatch.setattr(server.mimetypes, "guess_type", lambda name: (None, None))
    assert server._content_type("thing.weird") == "application/octet-stream"


def test_favicon_svg_served():
    with _ServerCtx() as srv:
        status, body, ctype = srv.get_bytes("/favicon.svg")
        assert status == 200
        assert ctype == "image/svg+xml"
        assert b"<svg" in body


def test_apple_touch_icon_served():
    with _ServerCtx() as srv:
        status, body, ctype = srv.get_bytes("/apple-touch-icon.png")
        assert status == 200
        assert ctype == "image/png"
        assert body[:8] == b"\x89PNG\r\n\x1a\n"


def test_datasets_list_ok():
    with _ServerCtx() as srv:
        status, body = srv.get("/api/datasets")
        assert status == 200
        assert "datasets" in body


def test_unknown_api_404():
    with _ServerCtx() as srv:
        status, body = srv.get("/api/nonexistent?path=x")
        assert status == 404


def test_tree_on_plain_dir(tmp_path):
    # tree_info works on a plain directory too (does not require it be a lance dataset)
    with _ServerCtx() as srv:
        q = urllib.parse.quote(str(tmp_path))
        status, body = srv.get(f"/api/tree?path={q}")
        assert status == 200
        assert "tree" in body


def test_missing_path_400():
    with _ServerCtx() as srv:
        status, body = srv.get("/api/tree")
        assert status == 400
        assert "path" in body.get("error", "")


def test_path_traversal_blocked(tmp_path):
    with _ServerCtx() as srv:
        q = urllib.parse.quote(str(tmp_path))
        status, body = srv.get(f"/api/manifest?path={q}&file=../../etc/passwd")
        assert status == 400
        assert "Invalid" in body.get("error", "")


def test_manifest_missing_file(tmp_path):
    with _ServerCtx() as srv:
        q = urllib.parse.quote(str(tmp_path))
        status, body = srv.get(f"/api/manifest?path={q}&file=nope.manifest")
        assert status == 400
        assert "not found" in body.get("error", "").lower()


def test_static_css_served():
    with _ServerCtx() as srv:
        status, body = srv.get_raw("/css/style.css")
        assert status == 200
        assert ":root" in body or "body" in body


def test_static_js_served():
    with _ServerCtx() as srv:
        for js in ("tools.js", "files.js", "render.js", "sidebar.js"):
            status, body = srv.get_raw(f"/js/{js}")
            assert status == 200, f"{js} should return 200"


def test_static_missing_404():
    with _ServerCtx() as srv:
        status, body = srv.get_raw("/js/nope.js")
        assert status == 404


def test_static_path_traversal_blocked():
    with _ServerCtx() as srv:
        status, body = srv.get_raw("/css/../../etc/passwd")
        assert status == 404


def test_dataset_offset_param_accepted(tmp_path):
    # /api/dataset accepts the offset paging param: an invalid path returns a 400 JSON error, not a 500 crash
    with _ServerCtx() as srv:
        q = urllib.parse.quote(str(tmp_path))
        status, body = srv.get(f"/api/dataset?path={q}&limit=100&offset=200")
        assert status == 400
        assert "error" in body  # non-lance dataset -> 400 error object, but routing parses offset without crashing


def test_render_js_has_pagination():
    # Frontend render.js should contain pagination rendering (pagination) and page-switch function
    with _ServerCtx() as srv:
        _, body = srv.get_raw("/js/render.js")
        assert "renderPagination" in body
        assert "setDataPage" in body
        assert "DATA_PAGE_SIZES" in body
        # Tieba-style controls: page size, first/last, and a jump box.
        assert "setPageSize" in body
        assert "jumpToDataPage" in body
        assert "pageWindow" in body
        assert "firstPage" in body and "lastPage" in body


def test_pager_controls_are_rendered_and_translated():
    """The bar is built in JS with t() keys: both languages must define every one of them."""
    with _ServerCtx() as srv:
        _, js = srv.get_raw("/js/tools.js")
        for key in ("pageSize", "firstPage", "lastPage", "jumpTo", "pageUnit", "jump"):
            # One definition in zh and one in en.
            assert js.count(f"    {key}:") == 2, f"{key} must exist in both dictionaries"


def test_page_size_choices_are_the_supported_set():
    with _ServerCtx() as srv:
        _, body = srv.get_raw("/js/render.js")
        assert "const DATA_PAGE_SIZES = [20, 50, 100, 200];" in body


def test_no_stale_page_size_constant_references():
    """DATA_PAGE_SIZE (singular) was replaced by a mutable dataPageSize.

    A leftover reference is a ReferenceError at runtime that the tab's try/catch swallows into an
    empty view, which is exactly what happened once already: render.js was moved to the new name
    while sidebar.js kept the old one and the Data tab rendered blank.
    """
    import re
    from pathlib import Path
    js_dir = Path(__file__).parent.parent / "src" / "lance_viewer" / "static" / "js"
    bad = []
    for f in js_dir.glob("*.js"):
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            # Matches the old symbol but not DATA_PAGE_SIZES.
            if re.search(r"\bDATA_PAGE_SIZE\b(?!S)", line):
                bad.append(f"{f.name}:{i}: {line.strip()}")
    assert not bad, "stale DATA_PAGE_SIZE reference:\n" + "\n".join(bad)


def test_page_size_reaches_the_request():
    """Both the tab loader and the pager must send the selected size, not a literal."""
    with _ServerCtx() as srv:
        _, render = srv.get_raw("/js/render.js")
        _, sidebar = srv.get_raw("/js/sidebar.js")
        assert "limit: dataPageSize" in render
        assert "limit: dataPageSize" in sidebar
        assert "offset: dataPage * dataPageSize" in sidebar


def test_column_projection_keeps_the_current_page():
    """Hiding a column changes neither the row count nor the row order, so the offset stays valid.

    Resetting here yanks the user back to page 1 for no reason, which is the bug this pins down.
    """
    from pathlib import Path
    js = Path(__file__).parent.parent / "src" / "lance_viewer" / "static" / "js"
    render = (js / "render.js").read_text(encoding="utf-8")
    for fn in ("function toggleDataColumn", "function selectAllDataColumns"):
        start = render.index(fn)
        body = render[start:render.index("\n}", start)]
        assert "dataPage = 0" not in body, f"{fn} must not reset the page"


def test_dataset_and_version_switches_do_reset_the_page():
    """The inverse: these change the row count, so page 1 is the only safe landing spot."""
    from pathlib import Path
    js = Path(__file__).parent.parent / "src" / "lance_viewer" / "static" / "js"
    render = (js / "render.js").read_text(encoding="utf-8")
    sidebar = (js / "sidebar.js").read_text(encoding="utf-8")
    assert "dataPage = 0; // switching dataset resets to first page" in sidebar
    for fn in ("function onRefBranchChange", "function onRefVersionChange"):
        start = render.index(fn)
        assert "dataPage = 0" in render[start:render.index("\n}", start)], f"{fn} must reset"


def test_switching_tabs_keeps_the_page():
    with _ServerCtx() as srv:
        _, sidebar = srv.get_raw("/js/sidebar.js")
        assert "if (activeTab !== 'data') dataPage = 0" not in sidebar


# ── Session-scoped dataset cache over HTTP ───────────────────────────────────────────────────────
def _demo():
    from pathlib import Path
    return str((Path(__file__).parent.parent / "examples" / "demo.lance").resolve())


def _register(srv, path):
    """Add a dataset row so PUT has something to edit; returns its id."""
    body = json.dumps({"name": "cache-test", "path": path}).encode("utf-8")
    req = urllib.request.Request(
        f"http://127.0.0.1:{srv.port}/api/datasets", data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read().decode("utf-8"))["id"]


def test_session_requests_are_served_from_one_handle():
    """Same session, repeated request: the second must reuse the cached dataset."""
    from lance_viewer import session_store
    session_store.clear()
    path = _demo()
    q = urllib.parse.urlencode({"path": path})
    with _ServerCtx() as srv:
        s1, b1 = srv.get_session(f"/api/dataset?{q}", "httpsess")
        s2, b2 = srv.get_session(f"/api/dataset?{q}", "httpsess")
        assert (s1, s2) == (200, 200)
        assert b1["count"] == b2["count"]
        assert session_store.stats()["entries"] == 1, "one handle for one session"
    session_store.clear()


def test_requests_without_a_session_header_are_not_cached():
    from lance_viewer import session_store
    session_store.clear()
    q = urllib.parse.urlencode({"path": _demo()})
    with _ServerCtx() as srv:
        assert srv.get(f"/api/dataset?{q}")[0] == 200
        assert srv.get(f"/api/dataset?{q}")[0] == 200
        assert session_store.stats()["entries"] == 0
    session_store.clear()


def test_a_rejected_session_header_disables_caching():
    """Only a bounded URL-safe token is accepted; anything else must not become a cache bucket."""
    from lance_viewer import session_store
    session_store.clear()
    q = urllib.parse.urlencode({"path": _demo()})
    with _ServerCtx() as srv:
        bad = "x" * 200  # over the 64-char cap
        assert srv.get_session(f"/api/dataset?{q}", bad)[0] == 200
        assert session_store.stats()["entries"] == 0
    session_store.clear()


def test_put_evicts_the_cached_handle_for_the_old_path():
    """Editing a row can repoint its path/credentials, so its cached handles must be dropped.

    Regression: update() returns the row as it stands afterwards, so reading the pre-edit path
    after the write handed drop_path() only the new value and left the old entry alive.
    """
    from lance_viewer import session_store
    session_store.clear()
    path = _demo()
    q = urllib.parse.urlencode({"path": path})
    with _ServerCtx() as srv:
        ds_id = _register(srv, path)
        assert srv.get_session(f"/api/dataset?{q}", "putsess")[0] == 200
        assert session_store.stats()["entries"] == 1

        status, _ = srv.put(f"/api/datasets?id={ds_id}", {"note": "cache test"})
        assert status == 200
        assert session_store.stats()["entries"] == 1, "a note edit must not evict the handle"

        status, _ = srv.put(f"/api/datasets?id={ds_id}", {"path": path + "/"})
        assert status == 200
        assert session_store.stats()["entries"] == 0, "the old path's handle must be dropped"

        # Restore and clean up the registry row
        srv.put(f"/api/datasets?id={ds_id}", {"path": path, "note": ""})
        urllib.request.urlopen(
            urllib.request.Request(f"http://127.0.0.1:{srv.port}/api/datasets?id={ds_id}",
                                   method="DELETE")).read()
    session_store.clear()


def test_delete_evicts_the_cached_handle():
    from lance_viewer import session_store
    session_store.clear()
    path = _demo()
    q = urllib.parse.urlencode({"path": path})
    with _ServerCtx() as srv:
        ds_id = _register(srv, path)
        assert srv.get_session(f"/api/dataset?{q}", "delsess")[0] == 200
        assert session_store.stats()["entries"] == 1
        urllib.request.urlopen(
            urllib.request.Request(f"http://127.0.0.1:{srv.port}/api/datasets?id={ds_id}",
                                   method="DELETE")).read()
        assert session_store.stats()["entries"] == 0
    session_store.clear()


def test_lifetime_windows_are_configurable_and_default_to_90s_and_2min():
    import importlib
    import os
    from lance_viewer import session_store
    # The heartbeat window must be several 20s beats wide: background tabs throttle timers to ~60s.
    assert session_store.HEARTBEAT_INTERVAL_SECONDS == 20
    assert session_store.HEARTBEAT_GONE_SECONDS == 90
    assert session_store.IDLE_SECONDS == 120
    os.environ["LANCE_VIEWER_HEARTBEAT_GONE"] = "45"
    os.environ["LANCE_VIEWER_SESSION_IDLE"] = "300"
    try:
        importlib.reload(session_store)
        assert session_store.HEARTBEAT_GONE_SECONDS == 45
        assert session_store.IDLE_SECONDS == 300
    finally:
        os.environ.pop("LANCE_VIEWER_HEARTBEAT_GONE", None)
        os.environ.pop("LANCE_VIEWER_SESSION_IDLE", None)
        importlib.reload(session_store)


def test_heartbeat_route_keeps_a_session_cached():
    """The page pings /api/heartbeat; that must not be treated as a real request or drop state."""
    from lance_viewer import session_store
    session_store.clear()
    q = urllib.parse.urlencode({"path": _demo()})
    with _ServerCtx() as srv:
        assert srv.get_session(f"/api/dataset?{q}", "beatsess")[0] == 200
        assert session_store.stats()["entries"] == 1
        status, body = srv.get_session("/api/heartbeat", "beatsess")
        assert (status, body) == (200, {"ok": True})
        assert session_store.stats()["entries"] == 1, "a ping must not evict anything"
    session_store.clear()


def test_bye_beacon_releases_the_session_without_a_header():
    """sendBeacon cannot set headers, so the closing ping carries ?sid= in the query."""
    from lance_viewer import session_store
    session_store.clear()
    q = urllib.parse.urlencode({"path": _demo()})
    with _ServerCtx() as srv:
        assert srv.get_session(f"/api/dataset?{q}", "byesess")[0] == 200
        assert session_store.stats()["entries"] == 1
        status, body = srv.post_raw("/api/heartbeat?sid=byesess&bye=1")
        assert (status, body) == (200, {"ok": True})
        assert session_store.stats()["entries"] == 0, "the closing beacon releases immediately"
    session_store.clear()


def test_bye_without_a_session_id_is_harmless():
    from lance_viewer import session_store
    session_store.clear()
    with _ServerCtx() as srv:
        assert srv.post_raw("/api/heartbeat?bye=1")[0] == 200
        assert session_store.stats()["sessions"] == 0
    session_store.clear()


# ── Column projection on the Data tab (cols= repeated key) ──────────────────────────────────────
def _data(srv, cols, extra=None):
    q = f"path={urllib.parse.quote(_demo())}"
    for c in cols:
        q += f"&cols={urllib.parse.quote(c)}"
    if extra:
        q += "&" + extra
    return srv.get("/api/dataset?" + q)


def test_cols_projects_to_only_the_requested_columns():
    with _ServerCtx() as srv:
        status, body = _data(srv, ["name", "score"])
        assert status == 200
        assert list(body["columns"].keys()) == ["name", "score"]
        assert [d["name"] for d in body["display"]] == ["name", "score"]
        # The total is a metadata read, so it stays the whole-table count under any projection.
        assert body["count"] > 0
        assert body["schema"], "schema stays complete so the chips can list every column"


def test_cols_returns_schema_order_not_request_order():
    """Toggling one column must not reshuffle the table."""
    with _ServerCtx() as srv:
        _, body = _data(srv, ["score", "id"])
        assert list(body["columns"].keys()) == ["id", "score"]


def test_cols_rejects_an_unknown_column():
    """A typo must be an error, not a silently narrowed table."""
    with _ServerCtx() as srv:
        status, body = _data(srv, ["id", "nope"])
        assert status == 400
        assert "nope" in body["error"]


def test_cols_deduplicates_a_repeated_name():
    """pylance raises on duplicate columns; the handler must not pass the repeat through."""
    with _ServerCtx() as srv:
        status, body = _data(srv, ["id", "id"])
        assert status == 200
        assert list(body["columns"].keys()) == ["id"]


def test_no_cols_param_reads_every_column():
    with _ServerCtx() as srv:
        _, body = srv.get(f"/api/dataset?path={urllib.parse.quote(_demo())}")
        assert list(body["columns"].keys()) == [f["name"] for f in body["schema"]]


def test_cols_combines_with_paging():
    """Projection and offset/limit must compose: page 2 of one column still has rows."""
    with _ServerCtx() as srv:
        _, page1 = _data(srv, ["id"], extra="limit=5&offset=0")
        _, page2 = _data(srv, ["id"], extra="limit=5&offset=5")
        assert list(page2["columns"].keys()) == ["id"]
        assert page2["offset"] == 5
        assert page2["columns"]["id"] and page1["columns"]["id"]
        assert page1["columns"]["id"] != page2["columns"]["id"]


# ── Arbitrary page sizes (the pager offers 20/50/100/200) ──────────────────────────────────────
def test_page_size_is_honoured_end_to_end():
    with _ServerCtx() as srv:
        for size in (20, 50, 100, 200):
            _, body = _data(srv, ["id"], extra=f"limit={size}&offset=0")
            assert body["shown"] == size, f"limit={size} should show {size} rows"
            assert len(body["columns"]["id"]) == size


def test_offset_with_a_larger_page_size_stays_consistent():
    """A custom page size must page on its own boundaries, not on the default 20."""
    with _ServerCtx() as srv:
        # Derive the page size from the real table size: CI builds a 200-row dataset while a local
        # one holds 5000, so a hard-coded offset would step past the end on CI and show nothing.
        _, probe = _data(srv, ["id"], extra="limit=1&offset=0")
        size = probe["count"] // 4
        assert size > 20, "dataset too small to distinguish a custom page size from the default"
        _, p1 = _data(srv, ["id"], extra=f"limit={size}&offset=0")
        _, p3 = _data(srv, ["id"], extra=f"limit={size}&offset={size * 2}")
        assert p1["shown"] == size
        assert p3["offset"] == size * 2
        assert p3["shown"] > 0, "page 3 of a 4-page table must have rows"
        # The two windows must not overlap.
        assert set(p1["columns"]["id"]).isdisjoint(set(p3["columns"]["id"]))


def test_offset_past_the_end_returns_no_rows_instead_of_failing():
    with _ServerCtx() as srv:
        status, body = _data(srv, ["id"], extra="limit=20&offset=999999")
        assert status == 200
        assert body["shown"] == 0
        assert body["count"] > 0, "the total must still describe the whole table"


def test_transactions_accept_limit_and_offset():
    """The timeline is paged over the wire: newest `limit` txns, skipping the newest `offset`."""
    with _ServerCtx() as srv:
        q = urllib.parse.urlencode({"path": _demo(), "limit": 2, "offset": 1})
        status, body = srv.get(f"/api/transactions?{q}")

    assert status == 200
    assert body["total"] == 6
    assert body["limit"] == 2 and body["offset"] == 1
    assert [t["version"] for t in body["transactions"]] == [3, 4]
    assert body["has_more"] is True


def test_transactions_ignore_a_non_numeric_limit():
    with _ServerCtx() as srv:
        q = urllib.parse.urlencode({"path": _demo(), "limit": "abc", "offset": "xyz"})
        status, body = srv.get(f"/api/transactions?{q}")

    assert status == 200
    assert body["limit"] == 200 and body["offset"] == 0
    assert body["has_more"] is False


def test_version_endpoint_reports_binding_provenance():
    with _ServerCtx() as srv:
        status, body = srv.get("/api/version")

    assert status == 200
    assert body["package"]
    assert body["protos"]["bindings"] > 0
    assert set(body["protos"]["lance"]) == {"tag", "commit"}


def test_health_endpoint_reports_the_dataset():
    q = urllib.parse.urlencode({"path": _demo()})
    with _ServerCtx() as srv:
        status, body = srv.get(f"/api/health?{q}")

    assert status == 200
    assert body["rows"] > 0
    assert body["fragments"] >= 1
    assert body["format"]["data_storage_version"]
    assert isinstance(body["issues"], list)


def test_dataset_filter_reaches_the_scan():
    q = urllib.parse.urlencode({"path": _demo(), "filter": "id < 3", "limit": 10})
    with _ServerCtx() as srv:
        status, body = srv.get(f"/api/dataset?{q}")

    assert status == 200
    assert body["count"] == 3
    assert body["columns"]["id"] == [0, 1, 2]
    assert body["filter"] == "id < 3"


def test_invalid_filter_is_a_400_with_the_parser_message():
    q = urllib.parse.urlencode({"path": _demo(), "filter": "id <<<"})
    with _ServerCtx() as srv:
        status, body = srv.get(f"/api/dataset?{q}")

    assert status == 400
    assert "Filter failed" in body["error"]
