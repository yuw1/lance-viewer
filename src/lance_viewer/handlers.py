"""API data-fetch functions (grouped by feature).

Depends on app.util (pure helpers), app.lance_client (pylance client), app.config (dependency availability flags).
"""
import os
from datetime import datetime, timezone

from .config import lance, ipc, pa, LANCE_AVAILABLE, PYARROW_AVAILABLE
from .lance_client import open_dataset, is_cloud, storage_option_set, storage_options
from .session_store import open_cached
from .util import (fmt_timestamp, num, cell_to_py, json_safe_value, sanitize_index_stat,
                   schema_field_set, collect_files, categorize)
from .manifest_decoder import decode_manifest_file, build_summary, decode_txn_file, build_txn_summary
from .datafile_decoder import decode_datafile


# ---------------------------------------------------------------------------
# Data reading
# ---------------------------------------------------------------------------

# OpenDAL Operator params per object-storage scheme. The frontend stores these
# under the same canonical field names (no prefix), so the backend maps them straight
# through. "required" must be present; "optional" are passed through when present.
_SCHEME_REQUIRED_PARAMS = {
    "s3": {
        "required": ["access_key_id", "secret_access_key", "endpoint"],
        "optional": ["region"],
    },
    "oss": {
        "required": ["access_key_id", "access_key_secret", "endpoint"],
        "optional": [],
    },
}

# Storage tab: decoding every data file of a many-file dataset costs one read (or one range-read
# batch) per file. The biggest files dominate the byte counts, so analyse those and report the rest
# as a count.
STORAGE_MAX_DATA_FILES = 15


def _preview_cell(value):
    """For the data-preview table: scalars convert normally, vector/list columns send full values
    (after paging each page has few rows, so the size is manageable)."""
    if value is None:
        return None
    try:
        py = value.as_py()
    except Exception:
        py = value
    if isinstance(py, (list, tuple)):
        # Vector/list columns: send full values (plain numbers, formatted by the frontend)
        return [float(x) if isinstance(x, (int, float)) else json_safe_value(x) for x in py]
    if isinstance(py, float):
        return round(py, 6)
    return json_safe_value(py)


def dataset_info(path, limit=200, offset=0, version=None, include_refs=False, session=None,
                 columns=None, filter=None):
    """Data tab: schema / stats / row data.
    offset/limit support paging; version reads the snapshot pointed to by a historical version/branch/tag
    (read-only).

    include_refs attaches the branches/tags/versions lists to the same response. The Data tab draws a
    refs bar above the rows, so without it the browser fetched /api/refs and /api/dataset separately
    and the dataset was opened twice (~297 ms each against a real S3 table) for one screen.

    columns projects the scan down to the named columns: only those are read off storage. Names are
    validated against the schema and rejected on a typo rather than dropped, because pylance raises on
    an unknown field and a silently narrowed table would be the worse failure. The returned order is
    schema order, not request order, so toggling one column does not reshuffle the table.

    filter is a Lance/SQL predicate pushed into the scan, so the row count and the page describe the
    same subset instead of filtering in the browser after reading everything.
    """
    ds, err = open_cached(session, path, version=version)
    if err:
        return None, err

    if columns:
        names = list(ds.schema.names)
        unknown = [c for c in columns if c not in names]
        if unknown:
            return None, f"Unknown column(s): {', '.join(unknown)}"
        order = {n: i for i, n in enumerate(names)}
        columns = sorted(set(columns), key=lambda c: order[c])
    else:
        # An empty selection means "no filter", not "no columns": to_table(columns=[]) returns zero
        # columns instead of failing, which would render as an empty table with no way back.
        columns = None

    refs = _refs_of(ds, path) if include_refs else None

    schema_fields = []
    for f in ds.schema:
        schema_fields.append({"name": f.name, "type": str(f.type), "nullable": f.nullable})

    # count_rows()/to_table() share the filter so the total and the page describe the same rows.
    try:
        count = ds.count_rows(filter=filter or None)
        tbl = ds.to_table(columns=columns, offset=offset, limit=limit, filter=filter or None)
    except Exception as e:
        return None, f"Filter failed: {e}" if filter else f"Read failed: {e}"
    columns = {}
    for col in tbl.column_names:
        arr = tbl.column(col)
        columns[col] = [_preview_cell(arr[i]) for i in range(arr.length())]

    display_cols = []
    for col in tbl.column_names:
        arr = tbl.column(col)
        # Real timestamp columns are flagged by Arrow type, so the flag is right even when the first
        # row is null; plain integer columns holding epoch values still use the range heuristic.
        is_ts = pa is not None and pa.types.is_timestamp(arr.type)
        sample = arr[0].as_py() if arr.length() else None
        display_cols.append({"name": col, "timestamp": is_ts or fmt_timestamp(sample) is not None})

    info = {
        "path": path,
        "count": count,
        "offset": offset,
        "limit": limit,
        "shown": tbl.num_rows,
        # Reuse the refs listing when it was already computed: ds.versions() is a separate ~187 ms call.
        "versions": len(refs["versions"]) if refs else len(ds.versions()),
        "version": ds.version,
        "filter": filter or None,
        "schema": schema_fields,
        "columns": columns,
        "display": display_cols,
    }
    if refs:
        info["refs"] = refs
    return info, None


def schema_info(path, session=None):
    """Schema tab: schema details."""
    ds, err = open_cached(session, path)
    if err:
        return None, err
    fields = []
    for f in ds.schema:
        fields.append({"name": f.name, "type": str(f.type), "nullable": f.nullable})
    return {"path": path, "fields": fields}, None


def index_info(path, session=None):
    """Index overview tab: list all indexes + per-index stats.
    Depends on pylance (describe_indices / index_statistics)."""
    path = os.path.expanduser(path)
    if not is_cloud(path) and not os.path.isdir(path):
        return None, f"Path is not a valid Lance dataset directory: {path}"
    if not LANCE_AVAILABLE:
        return None, "pylance is not installed, cannot read indexes. Run `uv pip install pylance pyarrow`"
    try:
        ds, err = open_cached(session, path)
        if err:
            return None, err
        result = []
        for idx in _describe_indices(ds):
            name = idx["name"]
            entry = {
                "name": name,
                "type": idx["type"],
                "fields": idx["fields"],
            }
            # Stats can be slow/fail; keep an independent try for fault tolerance
            try:
                stats = _index_stats(ds, name)
                entry["stats"] = sanitize_index_stat(stats)
            except Exception as e:
                entry["stats"] = None
                entry["stats_error"] = str(e)
            result.append(entry)
        return {"path": path, "indices": result}, None
    except Exception as e:
        return None, f"Failed to read indexes: {e}"


def version_diff(path, from_v=None, to_v=None, session=None):
    """Version-diff tab: compare data volume/schema/index between two versions.
    Depends on pylance. from_v/to_v are version numbers; when omitted, use latest."""
    path = os.path.expanduser(path)
    if not is_cloud(path) and not os.path.isdir(path):
        return None, f"Path is not a valid Lance dataset directory: {path}"
    if not LANCE_AVAILABLE:
        return None, "pylance is not installed, cannot compare versions. Run `uv pip install pylance pyarrow`"
    try:
        ds, _err = open_cached(session, path)
        if ds is None:
            return None, _err
        versions = ds.versions()
        if not versions:
            return {"path": path, "versions": [], "diff": None}, None
        vnums = [v['version'] for v in versions]
        # Resolve from/to
        to_v = to_v if to_v is not None else vnums[-1]
        from_v = from_v if from_v is not None else vnums[0]

        def _vmeta(vnum):
            for v in versions:
                if v['version'] == vnum:
                    m = v.get('metadata', {})
                    def _m(k):
                        try:
                            return int(m.get(k, 0))
                        except (TypeError, ValueError):
                            return 0
                    ts = v.get('timestamp')
                    return {
                        "version": vnum,
                        "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S") if hasattr(ts, 'strftime') else str(ts),
                        "rows": _m("total_rows"),
                        "data_files": _m("total_data_files"),
                        "deletion_files": _m("total_deletion_files"),
                        "deletion_rows": _m("total_deletion_file_rows"),
                        "fragments": _m("total_fragments"),
                        "size_bytes": _m("total_files_size"),
                    }
            return {"version": vnum}

        # Timeline: metadata of every version between from_v and to_v
        timeline = []
        idx_from = vnums.index(from_v) if from_v in vnums else 0
        idx_to = vnums.index(to_v) if to_v in vnums else len(vnums) - 1
        for vnum in vnums[idx_from:idx_to + 1]:
            timeline.append(_vmeta(vnum))

        # Read schema and indexes of the from/to versions
        def _v_snapshot(vnum):
            try:
                dsv, _ = open_cached(session, path, version=vnum)
                schema = schema_field_set(dsv)
                try:
                    indices = [(i["name"], i["type"], i["fields"]) for i in _describe_indices(dsv)]
                except Exception:
                    indices = []
                return schema, indices
            except Exception as e:
                return None, None

        from_schema, from_indices = _v_snapshot(from_v)
        to_schema, to_indices = _v_snapshot(to_v)

        # Schema diff
        from_map = dict(from_schema or [])
        to_map = dict(to_schema or [])
        schema_diff = {
            "added": [n for n in to_map if n not in from_map],
            "removed": [n for n in from_map if n not in to_map],
            "type_changed": [{"name": n, "from": from_map[n], "to": to_map[n]}
                             for n in to_map if n in from_map and from_map[n] != to_map[n]],
        }

        # Index diff
        def _idx_key(i): return i[0]
        from_idx_set = {_idx_key(i): i for i in (from_indices or [])}
        to_idx_set = {_idx_key(i): i for i in (to_indices or [])}
        idx_diff = {
            "added": [list(to_idx_set[n]) for n in to_idx_set if n not in from_idx_set],
            "removed": [list(from_idx_set[n]) for n in from_idx_set if n not in to_idx_set],
        }

        from_m = _vmeta(from_v)
        to_m = _vmeta(to_v)
        diff = {
            "from": from_m,
            "to": to_m,
            "delta": {
                "rows": to_m["rows"] - from_m["rows"],
                "data_files": to_m["data_files"] - from_m["data_files"],
                "deletion_files": to_m["deletion_files"] - from_m["deletion_files"],
                "fragments": to_m["fragments"] - from_m["fragments"],
                "size_bytes": to_m["size_bytes"] - from_m["size_bytes"],
            },
            "schema": schema_diff,
            "indices": idx_diff,
        }

        return {"path": path, "versions": vnums, "timeline": timeline, "diff": diff}, None
    except Exception as e:
        return None, f"Version diff failed: {e}"


def _refs_of(ds, path):
    """Branches / tags / versions of an already-open dataset.

    Split out so the Data tab can reuse one open dataset instead of opening it twice: the refs bar
    and the row preview both need the same snapshot, and open_dataset() is the expensive part
    (~297 ms against a real S3 table). Returns the same payload refs_info returns.
    """
    # Branches: name -> version currently pointed to
    branches = []
    try:
        for name, info in (ds.branches.list() or {}).items():
            # branch_identifier: [(version, uuid), ...] — the version the branch currently points to
            version = None
            try:
                if info.get("branch_identifier"):
                    version = info["branch_identifier"][0][0]
            except (TypeError, IndexError, KeyError):
                version = None
            branches.append({
                "name": name,
                "version": version,
                "parent_version": info.get("parent_version"),
                "metadata": info.get("metadata") or {},
            })
    except Exception:
        branches = []

    # Tags: name -> version pointed to
    tags = []
    try:
        for name, info in (ds.tags.list() or {}).items():
            tags.append({
                "name": name,
                "version": info.get("version"),
                "metadata": info.get("metadata") or {},
            })
    except Exception:
        tags = []

    # Versions: all version numbers + metadata
    versions = []
    try:
        for v in ds.versions():
            m = v.get("metadata", {})

            def _m(k):
                try:
                    return int(m.get(k, 0))
                except (TypeError, ValueError):
                    return 0

            ts = v.get("timestamp")
            versions.append({
                "version": v["version"],
                "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S") if hasattr(ts, "strftime") else str(ts),
                "rows": _m("total_rows"),
                "size_bytes": _m("total_files_size"),
            })
    except Exception:
        versions = []

    # Tags on each version (for the 🏷 marker in the version list)
    tag_by_version = {}
    for t in tags:
        if t["version"] is not None:
            tag_by_version.setdefault(t["version"], []).append(t["name"])

    return {
        "path": path,
        "branches": branches,
        "tags": tags,
        "versions": versions,
        "tag_by_version": tag_by_version,
    }


def refs_info(path, session=None):
    """Branch/Tag/Version bar: return the dataset's branches / tags / versions lists.
    Read-only: resolve each ref's target version with version_refs, and open snapshots via
    open_dataset(path, version=N); the dataset pointer is never changed (no checkout)."""
    path = os.path.expanduser(path)
    if not is_cloud(path) and not os.path.isdir(path):
        return None, f"Path is not a valid Lance dataset directory: {path}"
    if not LANCE_AVAILABLE:
        return None, "pylance is not installed, cannot read refs. Run `uv pip install pylance pyarrow`"
    try:
        ds, err = open_cached(session, path)
        if err:
            return None, err
        return _refs_of(ds, path), None
    except Exception as e:
        return None, f"Failed to read branches/tags/versions: {e}"


# ---------------------------------------------------------------------------
# Local file parsing (object storage not supported)
# ---------------------------------------------------------------------------

def tree_info(path):
    """File-tree tab: recursive directory structure.
    Local files use os.walk; object storage issues one prefixed LIST through OpenDAL."""
    path = os.path.expanduser(path)
    if is_cloud(path):
        return _cloud_tree_info(path)
    if not os.path.isdir(path):
        return None, f"Path is not a valid Lance dataset directory: {path}"

    def _mtime_str(ts):
        if not ts:
            return None
        try:
            dt = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone()
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except (OSError, ValueError, OverflowError):
            return None

    def walk(dirpath):
        entries = []
        for name in sorted(os.listdir(dirpath)):
            full = os.path.join(dirpath, name)
            try:
                st = os.stat(full)
            except OSError:
                st = None
            mtime = _mtime_str(st.st_mtime) if st else None
            if os.path.isdir(full):
                entries.append({"name": name, "type": "dir", "mtime": mtime,
                                "children": walk(full)})
            else:
                size = st.st_size if st else 0
                entries.append({"name": name, "type": "file", "size": size,
                                "mtime": mtime})
        return entries

    return {"path": path, "tree": walk(path)}, None


def _cloud_tree_info(path):
    """File tree of an object-storage dataset, built from the same listing the other views use.
    The returned structure matches local tree_info (dir has children, file has size/mtime),
    so the frontend renderTree can be reused directly."""
    entries, err = _dataset_files(path)
    if err:
        return None, err
    try:
        # Build directory tree: {dirpath: {name: entry}}
        root = {}
        for rel, size, mtime in entries:
            parts = [p for p in rel.split('/') if p]
            if not parts:
                continue
            node = root
            # Create directory levels
            for d in parts[:-1]:
                if d not in node:
                    node[d] = {"__dir": True, "__children": {}}
                node = node[d]["__children"]
            # File node
            name = parts[-1]
            node[name] = {
                "__dir": False,
                "size": size,
                "mtime": mtime,
            }

        def _to_entry(name, n):
            if n.get("__dir"):
                children = sorted(
                    [ _to_entry(k, v) for k, v in n["__children"].items() ],
                    key=lambda e: (e["type"] != 'dir', e["name"]),
                )
                return {"name": name, "type": "dir", "mtime": None, "children": children}
            return {"name": name, "type": "file", "size": n.get("size", 0), "mtime": n.get("mtime")}

        tree = sorted(
            [ _to_entry(k, v) for k, v in root.items() ],
            key=lambda e: (e["type"] != 'dir', e["name"]),
        )
        return {"path": path, "tree": tree}, None
    except Exception as e:
        return None, f"Failed to read object-storage file tree: {e}"


def _object_prefix(path):
    """The part of an object-storage path below the bucket, without leading/trailing slashes.
    Empty when the path points at the bucket root itself."""
    rest = path.split('://', 1)[-1]
    parts = [p for p in rest.split('/') if p]
    return '/'.join(parts[1:])


def _dataset_files(path):
    """List (relpath, size, mtime) for every file a dataset tracks, local or in object storage.

    Local walks the directory; object storage issues a single prefixed LIST through OpenDAL.
    Listing is a pure file operation, so it does not open the dataset: manifest parsing is not
    needed to know what objects exist, and it keeps the file tree readable when the dataset
    itself is what is broken. mtime is a formatted string or None. Returns (files, err).
    """
    if not is_cloud(path):
        if not os.path.isdir(path):
            return None, f"Path is not a valid Lance dataset directory: {path}"
        return [(rel, size, _mtime_str(_local_mtime(path, rel)))
                for rel, size in collect_files(path)], None

    # Checked before the client is built: a dataset at the bucket root has an empty prefix, and
    # scan("") lists the whole bucket, mixing unrelated objects into the tree. String-only, so the
    # message is the same whether or not storage options happen to be registered for the path.
    if not _object_prefix(path):
        return None, ("Cannot list an object-storage dataset at the bucket root; "
                      "use a path inside the bucket, e.g. s3://bucket/table.lance")

    op, prefix, err = _open_operator(path, '')
    if err:
        return None, err
    try:
        files = []
        for entry in op.scan(prefix):
            meta = entry.metadata
            if not meta.is_file:
                continue
            rel = entry.path[len(prefix):] if entry.path.startswith(prefix) else entry.path
            if not rel:
                continue
            files.append((rel, meta.content_length, _mtime_str(meta.last_modified)))
        return files, None
    except Exception as e:
        return None, f"Failed to list object-storage files: {e}"


def _local_mtime(root, rel):
    try:
        return datetime.fromtimestamp(os.path.getmtime(os.path.join(root, rel)), tz=timezone.utc).astimezone()
    except OSError:
        return None


def _mtime_str(ts):
    """Format a datetime (local mtime or pylance last_modified) as a local timestamp string."""
    if not ts:
        return None
    try:
        if hasattr(ts, 'astimezone') and ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts.astimezone().strftime("%Y-%m-%d %H:%M:%S") if hasattr(ts, 'astimezone') else str(ts)
    except Exception:
        return str(ts)


def _read_file_bytes(path, rel):
    """Read one dataset file by its relative path. Range-reads object storage when possible."""
    if is_cloud(path):
        # Only a data file has the v2 footer the range reader looks for. Trying it on a txn/json/
        # arrow file (timeline, JSON view) costs a wasted stat + footer GET and can hand a
        # SparseBytes stand-in to a decoder that expects real bytes.
        if rel.endswith(".lance"):
            buf, err = _read_datafile_range(path, rel)
            if not err:
                return buf, None
        return _read_dataset_file(path, rel)
    full = os.path.join(path, rel)
    try:
        with open(full, 'rb') as fh:
            return fh.read(), None
    except OSError as e:
        return None, str(e)


def storage_info(path):
    """Storage/compression analysis tab: per-type size stats + per-column storage/compression of data files.
    Works for local datasets and object storage; remote data-file metadata is range-read."""
    path = os.path.expanduser(path)
    try:
        files, ferr = _dataset_files(path)
        if ferr:
            return None, ferr
        total = sum(s for _, s, _ in files)

        # Categorize by type
        type_map = {}
        for rel, size, _ in files:
            key, label = categorize(rel)
            if key not in type_map:
                type_map[key] = {"key": key, "label": label, "count": 0, "size": 0}
            type_map[key]["count"] += 1
            type_map[key]["size"] += size
        file_types = sorted(type_map.values(), key=lambda x: -x["size"])

        # Top large files
        top_files = sorted(files, key=lambda x: -x[1])[:15]
        top_files = [{"path": rel, "size": size} for rel, size, _ in top_files]

        # Per-column analysis of data files. Only the largest few are decoded; see
        # STORAGE_MAX_DATA_FILES for why the rest are reported as a count instead.
        all_data_files = sorted(
            ((rel, size) for rel, size, _ in files
             if rel.startswith('data/') and rel.endswith('.lance')),
            key=lambda entry: -entry[1],
        )
        analysed = all_data_files[:STORAGE_MAX_DATA_FILES]
        data_files = []
        for rel, size in analysed:
            buf, rerr = _read_file_bytes(path, rel)
            if rerr:
                info, err = None, rerr
            else:
                info, err = decode_datafile(buf)
            if err:
                data_files.append({"file": rel, "size": size, "error": err})
                continue
            columns = []
            for c in info["columns"]:
                if c.get("error"):
                    continue
                total_buf = 0
                comp_set = set()
                pages = 0
                for p in c["pages"]:
                    total_buf += sum(p.get("buffer_sizes", []))
                    comp_set.update(p.get("compression", []))
                    pages += 1
                columns.append({
                    "index": c["index"],
                    "name": (info["schema"][c["index"]]["name"]
                             if c["index"] < len(info["schema"]) else f"col{c['index']}"),
                    "buffer_size": total_buf,
                    "compression": sorted(comp_set) if comp_set else [],
                    "pages": pages,
                })
            data_files.append({
                "file": rel,
                "size": size,
                "columns": columns,
                "columns_count": len(columns),
            })

        return {
            "path": path,
            "total_size": total,
            "file_types": file_types,
            "top_files": top_files,
            "data_files": data_files,
            "data_files_total": len(all_data_files),
            "data_files_analyzed": len(data_files),
        }, None
    except Exception as e:
        return None, f"Storage analysis failed: {e}"


HEALTH_SMALL_FRAGMENT_ROWS = 10_000
# An IVF partition should hold roughly this many vectors or fewer; past it, each probe scans too
# wide a group and query latency climbs. Lance's own guidance lands near sqrt(n) partitions, which
# keeps rows-per-partition close to sqrt(n) — for the sizes this tool is used on, a flat 10k cap is
# a conservative "definitely too few partitions" line.
HEALTH_MAX_ROWS_PER_PARTITION = 10_000

# The IVF family groups vectors by centroid, so rows-per-partition is meaningful for these only.
# HNSW/FLAT/Inverted/BTree have no such grouping and are skipped.
IVF_INDEX_TYPES = {
    "IVF_FLAT", "IVF_PQ", "IVF_SQ",
    "IVF_HNSW_FLAT", "IVF_HNSW_SQ", "IVF_HNSW_PQ",
}


def _index_stats(ds, name):
    """Per-index statistics across pylance versions: stats.index_stats() replaced index_statistics()."""
    try:
        return ds.stats.index_stats(name)
    except AttributeError:
        return ds.index_statistics(name)


def _describe_indices(ds):
    """Index name/type/fields across pylance versions: describe_indices() replaced list_indices()."""
    if hasattr(ds, "describe_indices"):
        return [{"name": d.name, "type": d.index_type,
                 "fields": [str(f) for f in (d.field_names or [])]}
                for d in ds.describe_indices()]
    return [{"name": idx.get("name"), "type": idx.get("type"),
             "fields": [str(f) for f in (idx.get("fields") or [])]}
            for idx in ds.list_indices() or []]


def _vector_partition_issue(name, stats):
    """Flag an IVF index whose vectors-per-partition exceeds the healthy target.

    Returns an issue dict, or None when the index is fine or the stats do not carry the needed
    fields. Threads the actual number through so the UI can show "30000 rows / 2 partitions =
    15000 per partition" instead of a bare verdict.
    """
    if not isinstance(stats, dict):
        return None
    indexed_rows = int(stats.get("num_indexed_rows") or 0)
    if not indexed_rows:
        return None

    entries = stats.get("indices") or []
    if entries:
        # Each entry is a segment of the index; sum its partitions so a multi-segment index is
        # judged on its total.
        partitions = sum(int(e.get("num_partitions") or 0)
                         for e in entries if isinstance(e, dict))
    else:
        partitions = int(stats.get("num_partitions") or 0)
    if not partitions:
        return None

    rows_per_partition = indexed_rows / partitions
    if rows_per_partition <= HEALTH_MAX_ROWS_PER_PARTITION:
        return None

    return {
        "code": "vector_partitions",
        "severity": "warn",
        "params": {
            "index": name,
            "rows_per_partition": int(rows_per_partition),
            "indexed_rows": indexed_rows,
            "partitions": partitions,
            "threshold": HEALTH_MAX_ROWS_PER_PARTITION,
        },
    }


def health_info(path, session=None):
    """Dataset health tab: fragment sizing, tombstones, index coverage and version churn.

    Everything here is metadata: one dataset open, one fragment listing, no column scan. The
    thresholds are heuristics (a Lance fragment is usually around a million rows), so each finding
    carries the number behind it instead of a verdict.
    """
    path = os.path.expanduser(path)
    ds, err = open_cached(session, path)
    if err:
        return None, err

    schema = [{"name": f.name, "type": str(f.type), "nullable": f.nullable} for f in ds.schema]
    rows = int(ds.count_rows())
    fragments = list(ds.get_fragments())

    frag_rows = []
    deleted_rows = 0
    data_files = 0
    size_bytes = 0
    for fragment in fragments:
        meta = fragment.metadata
        frag_rows.append(int(meta.num_rows))
        deletion = getattr(meta, "deletion_file", None)
        if deletion is not None:
            deleted_rows += int(getattr(deletion, "num_deleted_rows", 0) or 0)
        files = list(getattr(meta, "files", []) or [])
        data_files += len(files)
        size_bytes += sum(int(getattr(f, "file_size_bytes", 0) or 0) for f in files)

    stats = {"min": 0, "median": 0, "max": 0}
    if frag_rows:
        ordered = sorted(frag_rows)
        stats = {"min": ordered[0], "median": ordered[len(ordered) // 2], "max": ordered[-1]}

    indices = _describe_indices(ds)

    coverage = []
    for field in schema:
        types = sorted({i["type"] for i in indices if field["name"] in i["fields"]})
        coverage.append({"field": field["name"], "type": field["type"], "index_types": types})

    versions = list(ds.versions() or [])
    written_rows = 0
    for version in versions:
        try:
            written_rows += int((version.get("metadata") or {}).get("total_rows") or 0)
        except (TypeError, ValueError):
            pass

    issues = []
    if rows == 0:
        issues.append({"code": "empty", "severity": "info", "params": {}})

    if deleted_rows:
        pct = round(deleted_rows / (rows + deleted_rows) * 100, 1)
        issues.append({
            "code": "tombstones",
            "severity": "warn" if pct >= 5 else "info",
            "params": {"rows": deleted_rows, "pct": pct},
        })

    small = [n for n in frag_rows if n < HEALTH_SMALL_FRAGMENT_ROWS]
    if small:
        issues.append({
            "code": "small_fragments",
            "severity": "warn" if len(small) > max(1, len(frag_rows) // 2) else "info",
            "params": {"n": len(small), "total": len(frag_rows),
                       "threshold": HEALTH_SMALL_FRAGMENT_ROWS},
        })

    if len(frag_rows) >= 3 and stats["median"] > 0:
        ratio = round(stats["max"] / stats["median"], 1)
        if ratio >= 5:
            issues.append({"code": "fragment_skew", "severity": "info",
                           "params": {"ratio": ratio}})

    if len(versions) >= 20 and rows and written_rows:
        ratio = round(written_rows / rows, 1)
        if ratio >= 3:
            issues.append({"code": "version_churn", "severity": "info",
                           "params": {"versions": len(versions), "ratio": ratio}})

    for field in schema:
        if field["type"].startswith("fixed_size_list") and not any(
                field["name"] in i["fields"] for i in indices):
            issues.append({"code": "no_vector_index", "severity": "info",
                           "params": {"field": field["name"]}})

    for idx in indices:
        if idx["type"] not in IVF_INDEX_TYPES:
            continue
        try:
            stats = _index_stats(ds, idx["name"])
        except Exception:
            continue   # a stats hiccup must not sink the whole health tab
        issue = _vector_partition_issue(idx["name"], stats)
        if issue:
            issues.append(issue)

    severity_order = {"error": 0, "warn": 1, "info": 2}
    issues.sort(key=lambda issue: severity_order.get(issue["severity"], 3))

    return {
        "path": path,
        "rows": rows,
        "fragments": len(fragments),
        "versions": len(versions),
        "data_files": data_files,
        "size_bytes": size_bytes,
        "deleted_rows": deleted_rows,
        "fragment_stats": stats,
        "small_fragments": len(small),
        "format": {"data_storage_version": str(getattr(ds, "data_storage_version", "") or "")},
        "schema": schema,
        "indexes": indices,
        "coverage": coverage,
        "issues": issues,
    }, None


def _txn_file_version(name):
    """Version number encoded in a txn file name ("12-uuid.txn" -> 12).

    Names are parsed instead of compared as strings: lexicographic order would put "10-" before
    "2-", which breaks "newest N" slicing once a dataset passes ten versions. Unparseable names
    sort last rather than raising.
    """
    try:
        return int(name.split('-', 1)[0])
    except (ValueError, IndexError):
        return 1 << 62


def transaction_timeline(path, session=None, limit=200, offset=0):
    """Transaction-timeline tab: decode the newest `limit` _transactions/*.txn files, skipping the
    newest `offset` so the UI can page backwards.

    A dataset can accumulate thousands of versions; decoding every txn made opening this tab cost
    one object read per version. The window is applied to the file list *before* reading, and the
    response reports `total`/`has_more` so the UI can offer "load earlier".
    """
    path = os.path.expanduser(path)
    limit = max(1, min(int(limit), 1000))
    offset = max(0, int(offset))

    files, ferr = _dataset_files(path)
    if ferr:
        return None, ferr
    mt_by_rel = {rel: mt for rel, _, mt in files}
    txn_files = sorted((rel.split('/', 1)[1] for rel, _, _ in files
                        if rel.startswith('_transactions/') and rel.endswith('.txn')),
                       key=_txn_file_version)
    if not txn_files:
        return {"path": path, "transactions": [], "op_stats": {}, "has_snapshot": False,
                "total": 0, "limit": limit, "offset": offset, "has_more": False}, None

    total = len(txn_files)
    end = max(0, total - offset)
    start = max(0, end - limit)
    window = txn_files[start:end]
    has_more = start > 0

    try:
        # Read version snapshot metadata (merged from the snapshot-list tab), provided when pylance
        # is available. Only the versions inside the window are kept: a 5000-version dataset would
        # otherwise build 5000 dicts to use 200 of them.
        wanted = {_txn_file_version(f) + 1 for f in window}
        snapshots = {}
        has_snapshot = False
        if LANCE_AVAILABLE:
            try:
                ds, _ = open_cached(session, path)
                for v in ds.versions():
                    if v["version"] not in wanted:
                        continue
                    m = v.get("metadata", {})
                    def _m(k):
                        try:
                            return int(m.get(k, 0))
                        except (TypeError, ValueError):
                            return 0
                    ts = v.get("timestamp")
                    snapshots[v["version"]] = {
                        "rows": _m("total_rows"),
                        "data_files": _m("total_data_files"),
                        "deletion_files": _m("total_deletion_files"),
                        "deletion_rows": _m("total_deletion_file_rows"),
                        "fragments": _m("total_fragments"),
                        "size_bytes": _m("total_files_size"),
                        "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S") if hasattr(ts, "strftime") else str(ts),
                    }
                has_snapshot = True
            except Exception:
                has_snapshot = False
        txns = []
        for f in window:
            buf, rerr = _read_file_bytes(path, '_transactions/' + f)
            if rerr:
                txns.append({"file": f, "version": None, "error": rerr})
                continue
            data, err = decode_txn_file(buf)
            if err:
                txns.append({"file": f, "version": None, "error": err})
                continue
            summary = build_txn_summary(data["data"])
            # Version number from the file-name prefix
            try:
                version = int(f.split('-')[0])
            except (ValueError, IndexError):
                version = None
            # Timestamp from the file's mtime (already resolved per backend by _dataset_files)
            mtime = mt_by_rel.get('_transactions/' + f)
            txns.append({
                "file": f,
                "version": version,
                "operation": summary.get("operation"),
                "operation_label": summary.get("operation_label"),
                "read_version": summary.get("read_version"),
                "fragments": summary.get("fragments"),
                "physical_rows": summary.get("physical_rows"),
                "data_files": summary.get("data_files"),
                "uuid": summary.get("uuid"),
                "mtime": mtime,
                # txn file version is one less than the manifest version (txn v0 -> manifest v1)
                "snapshot": snapshots.get(version + 1) if version is not None else None,
            })
        # Sort by version (None last)
        txns.sort(key=lambda x: (x["version"] is None, x["version"] or 0))
        # Operation stats
        op_stats = {}
        for t in txns:
            if t.get("operation"):
                op_stats[t["operation"]] = op_stats.get(t["operation"], 0) + 1
        return {"path": path, "transactions": txns, "op_stats": op_stats,
                "has_snapshot": has_snapshot, "total": total, "limit": limit,
                "offset": offset, "has_more": has_more}, None
    except Exception as e:
        return None, f"Transaction timeline failed: {e}"


# ---------------------------------------------------------------------------
# File viewers (manifest / txn / datafile / json / arrow)
# ---------------------------------------------------------------------------

def _read_dataset_file(path, file):
    """Read one file's bytes from a dataset (local or object storage). Returns (data_bytes, err).
    - Local: read from disk directly
    - Object storage: read with OpenDAL (s3:// oss://), using the stored storage_options.
      Scheme determines the credential field name (s3 uses secret_access_key, oss uses access_key_secret)."""
    path = os.path.expanduser(path)
    resolved_file = os.path.normpath(file)
    if resolved_file.startswith(('..', '/')) or '..' in resolved_file.split('/'):
        return None, "Invalid file name"

    if not is_cloud(path):
        full = os.path.join(path, resolved_file)
        if not os.path.isfile(full):
            return None, f"File not found: {full}"
        try:
            with open(full, 'rb') as fh:
                return fh.read(), None
        except OSError as e:
            return None, f"Read failed: {e}"

    op, full_key, err = _open_operator(path, resolved_file)
    if err:
        return None, err
    try:
        return op.read(full_key), None
    except Exception as e:
        return None, f"Failed to read object-storage file: {e}"


def _open_operator(path, resolved_file):
    """For an object-storage path, build the OpenDAL Operator + full object key.
    Returns (op, full_key, err); err is None on success."""
    try:
        import opendal
    except ImportError:
        return None, None, "opendal is not installed, cannot read object-storage files. Run `uv pip install opendal`"

    scheme = path.split('://', 1)[0]
    spec = _SCHEME_REQUIRED_PARAMS.get(scheme)
    if spec is None:
        return None, None, f"Unsupported object-storage scheme: {scheme}"

    # storage_option_set turns on virtual-hosted addressing for s3:// and leaves other schemes
    # alone; OpenDAL reads the same dict, so no per-client translation is needed here.
    opts = storage_option_set(path, storage_options(path)) or {}
    missing = [p for p in spec["required"] if not opts.get(p)]
    if missing:
        return None, None, ("This dataset's storage options are missing: "
                            + ", ".join(missing) + " for scheme " + scheme)

    rest = path.split('://', 1)[1]
    parts = rest.split('/')
    bucket = parts[0]
    base = '/'.join(parts[1:])
    full_key = (base + '/' + resolved_file) if base else resolved_file

    params = {p: opts[p] for p in spec["required"]}
    params["bucket"] = bucket
    # optional params (e.g. s3 region) pass through when present
    params.update({p: opts[p] for p in spec["optional"] if opts.get(p)})
    # The virtual-hosted switch is neither scheme-required nor optional, so it is passed
    # explicitly; OpenDAL accepts the object_store spelling as a serde alias.
    for key in ("aws_virtual_hosted_style_request",):
        if opts.get(key):
            params[key] = opts[key]

    try:
        op = opendal.Operator(scheme, **params)
    except Exception as e:
        return None, None, f"Failed to build object-storage client: {e}"
    return op, full_key, None


def _range_read_datafile(op, full_key):
    """Fetch only a .lance data file's metadata by range, as a SparseBytes.

    The footer points at the CMO/GBO tables and each column's metadata blob, so the decoder needs
    those spans plus global buffer 0 (the FileDescriptor) and nothing else. Data buffers are never
    fetched. Returns (SparseBytes, err).
    """
    import struct
    from .datafile_decoder import FOOTER_SIZE, SparseBytes

    try:
        n = op.stat(full_key).content_length
    except Exception as e:
        return None, f"Failed to stat object-storage file: {e}"
    if n < FOOTER_SIZE:
        return None, f"File too small ({n} bytes)"

    def _range(offset, size):
        if offset < 0 or size <= 0:
            return b""
        if offset + size > n:
            raise RuntimeError(f"range {offset}+{size} runs past end of file ({n})")
        try:
            return op.read(full_key, offset=offset, size=size)
        except Exception as e:
            raise RuntimeError(f"range read failed at {offset}+{size}: {e}")

    try:
        footer = _range(n - FOOTER_SIZE, FOOTER_SIZE)
        off_cm0, off_cmo, off_gbo = struct.unpack_from('<QQQ', footer, 0)
        n_gbuf, n_cols = struct.unpack_from('<II', footer, 24)

        # CMO table: (pos, size) per column
        cmo = _range(off_cmo, n_cols * 16)
        cols = [struct.unpack_from('<QQ', cmo, i * 16) for i in range(n_cols)]

        # GBO table: (pos, size) per global buffer
        gbo = _range(off_gbo, n_gbuf * 16)
        gbufs = [struct.unpack_from('<QQ', gbo, i * 16) for i in range(n_gbuf)]

        spans = [(n - FOOTER_SIZE, footer), (off_cmo, cmo), (off_gbo, gbo)]
        # global buffer 0 (FileDescriptor) + every column-metadata blob
        for pos, size in ([gbufs[0]] if gbufs else []) + cols:
            if size > 0:
                spans.append((pos, _range(pos, size)))
    except Exception as e:
        return None, f"Failed to range-read object-storage file: {e}"

    return SparseBytes(n, spans), None


def _range_read_manifest(op, full_key):
    """Fetch only a manifest's header and payload by range.

    The manifest sits at a known offset recorded in the last 16 bytes: read those, then the u32
    length at manifest_pos, then the protobuf payload. A manifest can reach megabytes (length-
    prefixed fragment list), so this avoids pulling the whole thing. Returns (SparseBytes, err).
    """
    import struct
    from .datafile_decoder import SparseBytes

    try:
        n = op.stat(full_key).content_length
    except Exception as e:
        return None, f"Failed to stat object-storage file: {e}"
    if n < 16:
        return None, f"File too small ({n} bytes, minimum 16)"

    def _range(offset, size):
        if offset + size > n:
            raise RuntimeError(f"range {offset}+{size} runs past end of file ({n})")
        return op.read(full_key, offset=offset, size=size)

    try:
        footer = _range(n - 16, 16)
        manifest_pos = struct.unpack('<q', footer[:8])[0]
        if manifest_pos < 0 or manifest_pos + 4 > n:
            return None, f"manifest_pos ({manifest_pos}) out of range; file corrupt"
        head = _range(manifest_pos, 4)
        payload_len = struct.unpack('<I', head)[0]
        if manifest_pos + 4 + payload_len > n:
            return None, f"payload length ({payload_len}) runs past end of file"
        payload = _range(manifest_pos + 4, payload_len)
    except Exception as e:
        return None, f"Failed to range-read manifest: {e}"

    return SparseBytes(n, [(n - 16, footer), (manifest_pos, head), (manifest_pos + 4, payload)]), None


def _read_datafile_range(path, file):
    """Read only the metadata a .lance data file needs to be decoded, from object storage.

    Data buffers are never fetched; see _range_read_datafile for the spans that are.
    Returns (SparseBytes, err).
    """
    path = os.path.expanduser(path)
    resolved_file = os.path.normpath(file)
    if resolved_file.startswith(('..', '/')) or '..' in resolved_file.split('/'):
        return None, "Invalid file name"

    op, full_key, err = _open_operator(path, resolved_file)
    if err:
        return None, err
    return _range_read_datafile(op, full_key)


def manifest_info(path, file):
    """Decode a manifest file, return summary + full JSON. Supports local and object storage.
    For object storage the manifest is range-read: only the footer, the length prefix and the
    payload are fetched, not any other bytes in the file."""
    path = os.path.expanduser(path)
    buf = None
    if is_cloud(path):
        resolved = os.path.normpath(file)
        if not (resolved.startswith(('..', '/')) or '..' in resolved.split('/')):
            op, full_key, oerr = _open_operator(path, resolved)
            if not oerr:
                buf, rerr = _range_read_manifest(op, full_key)
    if buf is None:
        buf, err = _read_dataset_file(path, file)
        if err:
            return None, err
    data, err = decode_manifest_file(buf)
    if err:
        return None, err
    return {"path": os.path.expanduser(path), "file": file, "summary": build_summary(data), "full": data}, None


def txn_info(path, file):
    """Decode a txn (transaction) file, return summary + full JSON. Supports local and object storage."""
    buf, err = _read_dataset_file(path, file)
    if err:
        return None, err
    data, err = decode_txn_file(buf)
    if err:
        return None, err
    return {"path": os.path.expanduser(path), "file": file, "summary": build_txn_summary(data["data"]), "full": data}, None


def datafile_info(path, file):
    """Decode a .lance data file, return footer + column/page info. Supports local and object storage.
    For object storage, read only the metadata by range instead of the whole file."""
    if is_cloud(path):
        buf, err = _read_datafile_range(path, file)
        if not err:
            data, derr = decode_datafile(buf)
            if not derr:
                return {"path": os.path.expanduser(path), "file": file, "data": data}, None
        # fall back to whole-file read if range-read path fails
    buf, err = _read_dataset_file(path, file)
    if err:
        return None, err
    data, err = decode_datafile(buf)
    if err:
        return None, err
    return {"path": os.path.expanduser(path), "file": file, "data": data}, None


def json_info(path, file):
    """Read a JSON file (e.g. latest_version_hint.json), return parsed content. Supports local and object storage."""
    import json as _json
    buf, err = _read_dataset_file(path, file)
    if err:
        return None, err
    if not file.lower().endswith('.json'):
        return None, f"Not a JSON file: {file}"
    try:
        content = _json.loads(buf.decode('utf-8'))
    except _json.JSONDecodeError as e:
        return None, f"JSON parse failed: {e}"
    return {"path": os.path.expanduser(path), "file": file, "data": content}, None


def arrow_info(path, file):
    """Read an Arrow IPC file (e.g. _deletions/*.arrow deletion files), return schema + row data.
    Supports local and object storage. Read whole rather than by range: the caller renders every
    row, so all record-batch blocks are needed anyway; splitting the read would only trade one GET
    for several with no bytes saved (measured: 0.2% saved, 5x the requests)."""
    import io
    path = os.path.expanduser(path)
    buf, err = _read_dataset_file(path, file)
    if err:
        return None, err
    if not file.lower().endswith('.arrow'):
        return None, f"Not an Arrow IPC file: {file}"
    if not PYARROW_AVAILABLE:
        return None, "pyarrow is not installed, cannot read Arrow files. Run `uv pip install pyarrow`"
    try:
        reader = ipc.open_file(io.BytesIO(buf))
        schema = [
            {"name": f.name, "type": str(f.type), "nullable": f.nullable}
            for f in reader.schema
        ]
        rows = []
        for i in range(reader.num_record_batches):
            batch = reader.get_batch(i)
            cols = batch.column_names
            for r in range(batch.num_rows):
                row = {}
                for c in cols:
                    arr = batch.column(c)
                    row[c] = cell_to_py(arr[r])
                rows.append(row)
        return {
            "path": os.path.expanduser(path), "file": file,
            "schema": schema,
            "num_batches": reader.num_record_batches,
            "total_rows": len(rows),
            "rows": rows,
        }, None
    except Exception as e:
        return None, f"Arrow file parse failed: {e}"
