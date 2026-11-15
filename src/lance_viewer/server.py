#!/usr/bin/env python3
"""
lance-viewer - Lance dataset Web viewer
=======================================
Browse any Lance dataset - local or in object storage (S3, etc.) (binds to 127.0.0.1 by default).

Usage:
    python -m lance_viewer.server [--host 127.0.0.1] [--port 8770]
    # or after install: lance-viewer [--host ...] [--port ...]

Deps (installed together with `pip install -e .`): protobuf, opendal, pyarrow, pylance
(grpcio-tools is only needed by scripts/regen_protos.py, via the `proto` extra)

Layers:
    server.py             HTTP routing + dataset CRUD + startup (thin layer)
    handlers.py           API data-fetch functions
    lance_client.py       pylance client (_open/_storage_options/_is_cloud)
    util.py               pure helpers
    config.py             dependency availability flags + path constants
    dataset_store.py      SQLite dataset registry
    session_store.py      open-dataset handle cache (heartbeat + idle eviction)
    manifest_decoder.py   manifest/txn protobuf decode
    datafile_decoder.py   .lance file internals
    static/index.html     frontend (pure vanilla JS, self-contained)
"""

import argparse
import json
import mimetypes
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from .config import STATIC_DIR
from . import build_info, handlers, session_store
from .dataset_store import get_store

# Content types for the asset kinds we ship, pinned instead of looked up.
# mimetypes reads the OS mime database, so the same file gets a different Content-Type on macOS
# (image/x-icon, from /etc/apache2/mime.types) than in Linux CI (image/vnd.microsoft.icon, from
# Python's built-in table). A test that passes on one host and fails on the other is worse than a
# slightly unusual type, so the few types we actually serve are declared here.
STATIC_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".png": "image/png",
}


def _content_type(name):
    """Pinned type for known assets, OS lookup for anything else."""
    return (STATIC_CONTENT_TYPES.get(Path(name).suffix.lower())
            or mimetypes.guess_type(name)[0]
            or "application/octet-stream")


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path, content_type):
        try:
            data = path.read_bytes()
        except OSError:
            self._send_json({"error": "not found"}, 404)
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _path_param(self, parsed):
        q = parse_qs(parsed.query)
        p = (q.get("path") or [""])[0]
        if not p:
            self._send_json({"error": "Missing 'path' parameter"}, 400)
            return None
        return p

    def _file_param(self, parsed):
        q = parse_qs(parsed.query)
        f = (q.get("file") or [""])[0]
        if not f:
            self._send_json({"error": "Missing 'file' parameter"}, 400)
            return None
        return f

    def _reply(self, info, err):
        if err:
            self._send_json({"error": err}, 400)
        else:
            self._send_json(info)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/":
            self._send_file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
            return

        # Favicon (browsers and clients request /favicon.ico unconditionally)
        if path in ("/favicon.ico", "/favicon.svg", "/apple-touch-icon.png"):
            asset = STATIC_DIR / path.lstrip("/")
            self._send_file(asset, _content_type(asset.name))
            return

        # Static assets (css/js etc., subdirectories under static/)
        if path.startswith("/css/") or path.startswith("/js/") or path.startswith("/static/"):
            rel = path[1:].lstrip("/")  # drop leading /
            full = (STATIC_DIR / rel).resolve()
            # Path-traversal protection: must still be inside the static dir
            if not str(full).startswith(str(STATIC_DIR.resolve())):
                self._send_json({"error": "not found"}, 404)
                return
            if not full.is_file():
                self._send_json({"error": "not found"}, 404)
                return
            ctype = _content_type(full.name)
            self._send_file(full, ctype)
            return

        if path.startswith("/api/"):
            # Build provenance: package/dependency versions plus the Lance origin of the protobuf
            # bindings, so a bug report can say which format the viewer knows.
            if path == "/api/version":
                self._send_json(build_info.version_info())
                return

            # Dataset-list management endpoint (no path parameter needed)
            if path == "/api/datasets":
                self._send_json({"datasets": get_store().list_all()})
                return

            # Liveness: the page pings every 20s. Silence releases its cached datasets, so a killed
            # tab does not pin memory. `bye=1` is the closing beacon and releases immediately.
            if path == "/api/heartbeat":
                q = parse_qs(parsed.query)
                session_store.heartbeat(self._session_id(parsed),
                                        bye=(q.get("bye") or ["0"])[0] == "1")
                self._send_json({"ok": True})
                return

            p = self._path_param(parsed)
            if p is None:
                return

            session = self._session_id()
            # A real read counts as activity; the idle timeout is measured from these, not heartbeats.
            session_store.touch_activity(session)

            if path == "/api/dataset":
                q = parse_qs(parsed.query)
                try:
                    limit = int((q.get("limit") or ["200"])[0])
                except ValueError:
                    limit = 200
                try:
                    offset = int((q.get("offset") or ["0"])[0])
                except ValueError:
                    offset = 0
                version = self._version_param(q)
                # The Data tab asks for refs in the same request: one dataset open instead of two.
                include_refs = (q.get("refs") or [None])[0] == "1"
                # Repeated keys (cols=a&cols=b) rather than a comma join, so a column name
                # containing a comma cannot be split in half.
                columns = q.get("cols") or None
                filter_expr = (q.get("filter") or [""])[0].strip() or None
                info, err = handlers.dataset_info(p, limit, offset, version=version,
                                                  include_refs=include_refs, session=session,
                                                  columns=columns, filter=filter_expr)
            elif path == "/api/refs":
                info, err = handlers.refs_info(p, session=session)
            elif path == "/api/schema":
                info, err = handlers.schema_info(p, session=session)
            elif path == "/api/tree":
                info, err = handlers.tree_info(p)
            elif path == "/api/index":
                info, err = handlers.index_info(p, session=session)
            elif path == "/api/version_diff":
                q = parse_qs(parsed.query)
                def _v(k):
                    try:
                        return int(q.get(k, [None])[0]) if q.get(k, [None])[0] else None
                    except (TypeError, ValueError):
                        return None
                info, err = handlers.version_diff(p, from_v=_v('from'), to_v=_v('to'), session=session)
            elif path == "/api/storage":
                info, err = handlers.storage_info(p)
            elif path == "/api/health":
                info, err = handlers.health_info(p, session=session)
            elif path == "/api/transactions":
                # Paging: the timeline decodes the newest `limit` txns, skipping `offset` newest,
                # so a dataset with thousands of versions does not read every txn on tab open.
                q = parse_qs(parsed.query)
                try:
                    txn_limit = int((q.get("limit") or ["200"])[0])
                except ValueError:
                    txn_limit = 200
                try:
                    txn_offset = int((q.get("offset") or ["0"])[0])
                except ValueError:
                    txn_offset = 0
                info, err = handlers.transaction_timeline(p, session=session,
                                                          limit=txn_limit, offset=txn_offset)
            elif path in ("/api/manifest", "/api/txn", "/api/datafile", "/api/json", "/api/arrow"):
                f = self._file_param(parsed)
                if f is None:
                    return
                if path == "/api/manifest":
                    info, err = handlers.manifest_info(p, f)
                elif path == "/api/txn":
                    info, err = handlers.txn_info(p, f)
                elif path == "/api/datafile":
                    info, err = handlers.datafile_info(p, f)
                elif path == "/api/json":
                    info, err = handlers.json_info(p, f)
                else:
                    info, err = handlers.arrow_info(p, f)
            else:
                self._send_json({"error": "not found"}, 404)
                return
            self._reply(info, err)
            return

        self._send_json({"error": "not found"}, 404)

    def log_message(self, fmt, *args):
        sys.stderr.write("[lance-viewer] " + fmt % args + "\n")

    def _read_body(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    def _dataset_id(self, parsed):
        q = parse_qs(parsed.query)
        try:
            return int((q.get("id") or ["0"])[0])
        except (TypeError, ValueError):
            return 0

    def _version_param(self, q):
        """version may be an int snapshot number or a tag name; empty/missing means latest."""
        version = (q.get("version") or [None])[0]
        if not version:
            return None
        try:
            return int(version)
        except (TypeError, ValueError):
            return version

    def _session_id(self, parsed=None):
        """The page's session id, sent by the frontend as X-Lance-Session.

        It scopes the open-dataset cache: a reload gets a fresh id, so the first request reopens the
        dataset and picks up any new version. An absent header simply disables caching, which keeps
        curl and older clients on the previous behaviour.

        The closing beacon cannot set headers (navigator.sendBeacon), so the id may also arrive as
        ?sid=. Only a bounded, URL-safe token is accepted from either place.
        """
        raw = (self.headers.get("X-Lance-Session") or "").strip()
        if not raw and parsed is not None:
            raw = (parse_qs(parsed.query).get("sid") or [""])[0].strip()
        if not raw:
            return None
        if len(raw) > 64 or not all(c.isalnum() or c in "-_" for c in raw):
            return None
        return raw

    def do_POST(self):
        parsed = urlparse(self.path)
        # sendBeacon always POSTs, even for the closing 'bye' ping.
        if parsed.path == "/api/heartbeat":
            session_store.heartbeat(self._session_id(parsed), bye=True)
            self._send_json({"ok": True})
            return
        if parsed.path != "/api/datasets":
            self._send_json({"error": "not found"}, 404)
            return
        data = self._read_body()
        name = (data.get("name") or "").strip()
        path = (data.get("path") or "").strip()
        note = (data.get("note") or "").strip()
        if not path:
            self._send_json({"error": "Missing 'path' parameter"}, 400)
            return
        if not name:
            # Derive a default name from the path (last directory component or file name)
            name = path.rstrip("/").split("/")[-1] or path
        options = data.get("options")
        if options is not None and not isinstance(options, dict):
            self._send_json({"error": "options must be a JSON object"}, 400)
            return
        ds = get_store().add(name, path, note, options=options)
        self._send_json(ds, 201)

    def do_DELETE(self):
        parsed = urlparse(self.path)
        if parsed.path != "/api/datasets":
            self._send_json({"error": "not found"}, 404)
            return
        ds_id = self._dataset_id(parsed)
        if ds_id <= 0:
            self._send_json({"error": "Missing 'id' parameter"}, 400)
            return
        # Read the row first: after delete it is gone, and its path is what identifies cached handles.
        row = get_store().get(ds_id)
        if get_store().delete(ds_id):
            # The row is gone; any handle opened through it must not outlive it.
            if row and row.get("path"):
                session_store.drop_path(row["path"])
            self._send_json({"ok": True})
        else:
            self._send_json({"error": "not found"}, 404)

    def do_PUT(self):
        parsed = urlparse(self.path)
        if parsed.path != "/api/datasets":
            self._send_json({"error": "not found"}, 404)
            return
        ds_id = self._dataset_id(parsed)
        if ds_id <= 0:
            self._send_json({"error": "Missing 'id' parameter"}, 400)
            return
        data = self._read_body()
        name = (data.get("name") or "").strip() or None
        path = (data.get("path") or "").strip() or None
        note = data.get("note")  # allow clearing the note
        options = data.get("options")
        if options is not None and not isinstance(options, dict):
            self._send_json({"error": "options must be a JSON object"}, 400)
            return
        # Read the row first: update() returns the row as it is afterwards, so the pre-edit path
        # (whose cached handles must be dropped) is only available before the write.
        before = get_store().get(ds_id)
        ds = get_store().update(ds_id, name=name, path=path, note=note, options=options)
        if not ds:
            self._send_json({"error": "not found"}, 404)
            return
        # Only the path or the credentials affect which handle is valid; renaming or editing a note
        # must keep the session's already-open dataset. The cached key carries a credential
        # fingerprint, so a new options set already lands on a fresh entry — the old one is simply
        # dropped here to release its memory instead of lingering until the session expires.
        if before and (before.get("path") != ds.get("path")
                       or before.get("options") != ds.get("options")):
            for stale in {before.get("path"), ds.get("path")}:
                if stale:
                    session_store.drop_path(stale)
        self._send_json(ds)


def main():
    ap = argparse.ArgumentParser(description="Lance dataset Web viewer")
    ap.add_argument("--host", default="127.0.0.1", help="bind address (default 127.0.0.1)")
    ap.add_argument("--port", type=int, default=8770, help="port (default 8770)")
    # A plain flag, not argparse's version action: that one reflows the text through the help
    # formatter, which collapses the indented provenance block into one wrapped paragraph.
    ap.add_argument("--version", action="store_true",
                    help="print the version and the protobuf bindings' provenance, then exit")
    args = ap.parse_args()

    if args.version:
        print(build_info.version_text())
        return

    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    # Background reaper: once the last page closes there are no requests left to notice, so the
    # handles would otherwise sit in memory until something else happened.
    session_store.start_sweeper()
    print(f"\n  Lance Viewer started: http://{args.host}:{args.port}")
    print(f"  Bound {args.host} - only reachable locally (private memory data safe)\n")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
