"""pylance dataset client: unified dataset open, storage option parsing, object-storage URI detection.

This is the single entry point the backend uses to access Lance datasets. To support S3 or
other object storage (or custom storage_options parsing) later, only this file needs to change.
"""
import os
from urllib.parse import urlsplit, urlunsplit

from .config import lance, LANCE_AVAILABLE
from .dataset_store import get_store

# Supported object-storage schemes.
_CLOUD_SCHEMES = ("s3", "oss")


def _bucket_of(path):
    return path.split("://", 1)[1].split("/")[0] if "://" in path else ""


def bucket_scoped_endpoint(endpoint, bucket):
    """Move the bucket into the endpoint's host, e.g.
    https://s3.us-east-1.amazonaws.com + my-bucket -> https://my-bucket.s3.us-east-1.amazonaws.com

    Needed because object_store does not compose the host itself when virtual-hosted style is on:
    it only drops the bucket from the request path, so a region endpoint ends up bucket-less. An
    endpoint that is already bucket-scoped is returned unchanged."""
    if not endpoint or not bucket:
        return endpoint
    parts = urlsplit(endpoint if "://" in endpoint else "https://" + endpoint)
    if parts.netloc.split(".")[0] == bucket:
        return endpoint
    scheme = parts.scheme or "https"
    return urlunsplit((scheme, bucket + "." + parts.netloc, parts.path, parts.query, parts.fragment))


def storage_option_set(path, opts):
    """s3:// always uses virtual-hosted addressing; every other scheme passes through untouched.

    Both S3 clients read the same key, so nothing is translated per client:
      - pylance forwards the dict to object_store, which reads `aws_virtual_hosted_style_request`;
      - OpenDAL declares it as a serde alias of its own `enable_virtual_host_style`
        (opendal-service-s3 config.rs) and strips a bucket-scoped host before re-adding the bucket
        (backend.rs), so the bucket-scoped endpoint below is accepted verbatim.

    oss:// needs no handling at all: opendal-service-oss resolves an absent `addressing_style` to
    `virtual`, which is already the modern form."""
    if not opts:
        return opts
    out = dict(opts)
    if path.split("://", 1)[0] != "s3":
        return out
    out["aws_virtual_hosted_style_request"] = "true"
    out["endpoint"] = bucket_scoped_endpoint(out.get("endpoint"), _bucket_of(path))
    return out


def storage_options(path):
    """Fetch the dataset's storage_options from the SQLite registry by path.
    Returns dict or None (when not registered). Used to pass through to lance.dataset when opening
    cloud datasets."""
    try:
        row = get_store().get_by_path(path)
    except Exception:
        return None
    if not row:
        return None
    opts = row.get("options") or {}
    return opts or None


def is_cloud(path):
    """Whether the path is an object-storage URI (s3:// oss:// ...)."""
    s = path.split("://", 1)[0] if "://" in path else ""
    return s in _CLOUD_SCHEMES


def open_dataset(path, version=None):
    """Open a dataset. Returns (ds, err); err is non-empty on failure.

    When version is given, opens a historical version (used for version diff)."""
    path = os.path.expanduser(path)
    if not is_cloud(path):
        if not os.path.isdir(path):
            return None, f"Path is not a valid Lance dataset directory: {path}"
    if not LANCE_AVAILABLE:
        return None, "pylance is not installed. Run `uv pip install pylance pyarrow`"
    try:
        kw = {"storage_options": storage_option_set(path, storage_options(path))}
        if version is not None:
            kw["version"] = version
        ds = lance.dataset(path, **kw)
        return ds, None
    except Exception as e:
        return None, f"Failed to open: {e}"
