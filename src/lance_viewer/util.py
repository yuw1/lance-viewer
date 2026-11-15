"""Pure helper functions: timestamp formatting / numbers / Arrow scalar to JSON / index-stat folding / file collection and categorization."""
from datetime import datetime, timezone


def fmt_timestamp(v):
    """Millisecond/second timestamp -> human-readable time. Non-timestamps are returned as-is (None)."""
    if not isinstance(v, (int, float)) or v != v:  # NaN check
        return None
    if 1e12 <= v <= 4e12:      # 2001~2096 millisecond-range
        dt = datetime.fromtimestamp(v / 1000, tz=timezone.utc)
        return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")
    if 1e9 <= v <= 4e9:        # 2001~2096 second-range
        dt = datetime.fromtimestamp(v, tz=timezone.utc)
        return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")
    return None


def num(x):
    if isinstance(x, float):
        return f"{x:.4f}"
    return str(x)


def cell_to_py(value):
    """Convert an Arrow scalar to a JSON-friendly value. Vectors/large arrays are folded."""
    if value is None:
        return None
    try:
        py = value.as_py()
    except Exception:
        py = value
    if isinstance(py, (list, tuple)):
        n = len(py)
        if n > 8:
            preview = ", ".join(num(py[i]) for i in range(4))
            return {"__vector__": True, "dims": n, "preview": f"[{preview}, ...]"}
        return py
    if isinstance(py, float):
        return round(py, 6)
    return py


def sanitize_index_stat(stats):
    """Strip oversized/low-value fields from index stats (e.g. HNSW centroids arrays) to avoid bloated responses."""
    if not isinstance(stats, dict):
        return stats
    out = {}
    for k, v in stats.items():
        if k == 'indices' and isinstance(v, list):
            out[k] = [sanitize_index_stat(item) for item in v]
        elif k == 'segments' and isinstance(v, list):
            out[k] = [sanitize_index_stat(item) for item in v]
        elif k == 'centroids':
            # Centroid arrays are large; fold to a count summary
            if isinstance(v, list):
                dim = len(v[0]) if v and isinstance(v[0], list) else 0
                out[k] = {"__folded__": True, "num_centroids": len(v), "dim": dim}
            else:
                out[k] = v
        elif isinstance(v, (list, dict)) and len(str(v)) > 4000:
            # Other oversized fields are folded
            if isinstance(v, list):
                out[k] = {"__folded__": True, "num_items": len(v)}
            else:
                out[k] = {"__folded__": True, "num_keys": len(v)}
        else:
            out[k] = v
    return out


def schema_field_set(ds):
    """Return the dataset's schema field list [(name, type), ...]."""
    try:
        return [(f.name, str(f.type)) for f in ds.schema]
    except Exception:
        return []


def collect_files(root):
    """Recursively collect all files under a directory: (relpath, size)."""
    import os
    out = []
    try:
        for dirpath, dirnames, filenames in os.walk(root):
            for fn in filenames:
                full = os.path.join(dirpath, fn)
                try:
                    size = os.path.getsize(full)
                except OSError:
                    size = 0
                rel = os.path.relpath(full, root)
                out.append((rel, size))
    except OSError:
        pass
    return out


def categorize(relpath):
    """Categorize a file by its path prefix. Returns (category, label)."""
    parts = relpath.split('/')
    if parts[0] == 'data':
        return ('data', 'Data files (.lance)')
    if parts[0] == '_versions':
        return ('versions', 'Version manifests')
    if parts[0] == '_indices':
        return ('indices', 'Index files')
    if parts[0] == '_deletions':
        return ('deletions', 'Deletion files')
    if parts[0] == '_transactions':
        return ('transactions', 'Transaction logs')
    return ('other', 'Other')
