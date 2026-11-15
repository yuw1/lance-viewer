"""SQLite persistence layer for the dataset list.

Data is stored in the platform-standard user data dir:
  - macOS / Linux: ~/.local/share/lance-viewer/datasets.db
  - Windows:       %APPDATA%\\lance-viewer\\datasets.db
It manages a registry of Lance dataset paths: name / path / note / created time / last-access time / storage options.

The options field stores JSON text holding object-storage connection params (e.g. S3 endpoint / access key / secret key),
passed through as storage_options to lance.dataset when server.py opens cloud datasets.

Note: the lance-viewer service uses ThreadingHTTPServer (multi-threaded request handling),
so a single sqlite3 connection cannot be shared across threads. Hence each operation here opens a new connection
(check_same_thread=False allows use from other threads), and closes it when done.
"""
import os
import json
import sqlite3
from datetime import datetime
from pathlib import Path


def _data_dir():
    """Return the platform-standard user data directory for lance-viewer."""
    if os.name == "nt":  # Windows
        base = Path(os.environ.get("APPDATA", str(Path.home())))
    else:  # macOS / Linux / other POSIX
        base = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share")))
    return base / "lance-viewer"


def _db_path():
    base = _data_dir()
    base.mkdir(parents=True, exist_ok=True)
    return base / "datasets.db"


class DatasetStore:
    def __init__(self, db_path=None):
        self.db_path = str(db_path or _db_path())
        # Initialize schema (created once)
        conn = self._connect()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS datasets (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    name        TEXT NOT NULL,
                    path        TEXT NOT NULL UNIQUE,
                    note        TEXT DEFAULT '',
                    created_at  TEXT NOT NULL,
                    last_access TEXT,
                    options     TEXT DEFAULT '{}'
                )
            """)
            conn.commit()
            # Backward compat: if the options column is missing, ALTER it in
            cols = [r[1] for r in conn.execute("PRAGMA table_info(datasets)").fetchall()]
            if "options" not in cols:
                conn.execute("ALTER TABLE datasets ADD COLUMN options TEXT DEFAULT '{}'")
                conn.commit()
        finally:
            conn.close()

    def _connect(self):
        # check_same_thread=False: the connection may be used from other threads; each call opens a fresh connection to avoid cross-thread reuse
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _now(self):
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def _opts_dict(row):
        """Parse the options TEXT into a dict; give an empty dict on parse failure."""
        raw = row["options"] or "{}"
        try:
            d = json.loads(raw)
            return d if isinstance(d, dict) else {}
        except Exception:
            return {}

    def _to_out(self, row):
        """Row -> frontend-visible dict (options parsed to a dict)."""
        d = dict(row)
        d["options"] = self._opts_dict(row)
        return d

    def list_all(self):
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM datasets ORDER BY last_access DESC NULLS LAST, created_at DESC"
            ).fetchall()
            return [self._to_out(r) for r in rows]
        finally:
            conn.close()

    def add(self, name, path, note="", options=None):
        opts_json = json.dumps(options or {}, ensure_ascii=False)
        conn = self._connect()
        try:
            existing = conn.execute(
                "SELECT id FROM datasets WHERE path = ?", (path,)
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE datasets SET name = ?, note = ?, last_access = ?, options = ? WHERE id = ?",
                    (name, note, self._now(), opts_json, existing["id"]),
                )
                conn.commit()
                return self._get(conn, existing["id"])
            cur = conn.execute(
                "INSERT INTO datasets (name, path, note, created_at, last_access, options) VALUES (?, ?, ?, ?, ?, ?)",
                (name, path, note, self._now(), self._now(), opts_json),
            )
            conn.commit()
            return self._get(conn, cur.lastrowid)
        finally:
            conn.close()

    def _get(self, conn, ds_id):
        r = conn.execute(
            "SELECT * FROM datasets WHERE id = ?", (ds_id,)
        ).fetchone()
        return self._to_out(r) if r else None

    def get(self, ds_id):
        conn = self._connect()
        try:
            return self._get(conn, ds_id)
        finally:
            conn.close()

    def get_by_path(self, path):
        """Look up by path (used by server to fetch storage_options when opening a dataset)."""
        conn = self._connect()
        try:
            r = conn.execute(
                "SELECT * FROM datasets WHERE path = ?", (path,)
            ).fetchone()
            return self._to_out(r) if r else None
        finally:
            conn.close()

    def delete(self, ds_id):
        conn = self._connect()
        try:
            cur = conn.execute("DELETE FROM datasets WHERE id = ?", (ds_id,))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def update(self, ds_id, name=None, path=None, note=None, options=None):
        conn = self._connect()
        try:
            row = self._get(conn, ds_id)
            if not row:
                return None
            new_name = name if name is not None else row["name"]
            new_path = path if path is not None else row["path"]
            new_note = note if note is not None else row["note"]
            new_opts = json.dumps(options if options is not None else row["options"], ensure_ascii=False)
            conn.execute(
                "UPDATE datasets SET name = ?, path = ?, note = ?, options = ? WHERE id = ?",
                (new_name, new_path, new_note, new_opts, ds_id),
            )
            conn.commit()
            return self._get(conn, ds_id)
        finally:
            conn.close()

    def touch(self, ds_id):
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE datasets SET last_access = ? WHERE id = ?", (self._now(), ds_id)
            )
            conn.commit()
        finally:
            conn.close()


# Global singleton: reused within the service process (internally each op opens a fresh connection; itself thread-safe)
_store = None


def get_store():
    global _store
    if _store is None:
        _store = DatasetStore()
    return _store
