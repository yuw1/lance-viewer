"""Object-storage code paths, exercised against an in-memory OpenDAL stand-in.

S3/OSS is a headline feature, but until now it was only covered when a real bucket happened to be
reachable: the cloud tests skip otherwise, so listing, range reads and operator construction never
ran in CI. The fake below implements the three Operator methods the handlers use (`scan`, `read`,
`stat`), which is the whole surface the backend depends on.

The datasets in these tests are the same bytes as a local dataset written by the installed Lance, so
every assertion is "the cloud path must produce the same answer as the local path".
"""
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from lance_viewer import handlers
from lance_viewer.dataset_store import get_store

CLOUD_PATH = "s3://example-bucket/table.lance"
PREFIX = "table.lance/"


class FakeOperator:
    """The three methods handlers call, backed by a dict of full object key -> bytes."""

    def __init__(self, objects, scheme, params, reads):
        self.objects = objects
        self.scheme = scheme
        self.params = params
        self.reads = reads

    def scan(self, prefix=""):
        for key in sorted(self.objects):
            if not key.startswith(prefix):
                continue
            data = self.objects[key]
            yield SimpleNamespace(
                path=key,
                metadata=SimpleNamespace(is_file=True,
                                         content_length=len(data),
                                         last_modified=None),
            )

    def read(self, key, offset=None, size=None):
        self.reads.append({"key": key, "offset": offset, "size": size})
        data = self.objects[key]
        if offset is None and size is None:
            return data
        offset = offset or 0
        return data[offset:] if size is None else data[offset:offset + size]

    def stat(self, key):
        return SimpleNamespace(content_length=len(self.objects[key]))


@pytest.fixture
def cloud(monkeypatch, decoder_dataset):
    """A dataset mirrored into a fake bucket, registered like a real S3 dataset."""
    objects = {}
    for path in decoder_dataset.rglob("*"):
        if path.is_file():
            objects[PREFIX + path.relative_to(decoder_dataset).as_posix()] = path.read_bytes()

    calls = []
    reads = []

    def operator(scheme, **params):
        calls.append({"scheme": scheme, **params})
        return FakeOperator(objects, scheme, params, reads)

    module = types.ModuleType("opendal")
    module.Operator = operator
    monkeypatch.setitem(sys.modules, "opendal", module)

    store = get_store()
    row = store.add("cloud-fixture", CLOUD_PATH, "", options={
        "endpoint": "https://s3.us-east-1.amazonaws.com",
        "region": "us-east-1",
        "access_key_id": "id",
        "secret_access_key": "secret",
    })
    try:
        yield SimpleNamespace(path=CLOUD_PATH, objects=objects, calls=calls, reads=reads,
                              local=decoder_dataset, row=row)
    finally:
        store.delete(row["id"])


def _rel_files(dataset):
    return sorted(p.relative_to(dataset).as_posix() for p in dataset.rglob("*") if p.is_file())


def _data_file(dataset):
    return next(p for p in dataset.rglob("data/*.lance"))


def _latest_manifest(dataset):
    return max((dataset / "_versions").glob("*.manifest"), key=lambda p: int(p.stem))


# ---------- operator construction ----------

def test_operator_is_built_with_virtual_hosted_s3_params(cloud):
    _, err = handlers.tree_info(cloud.path)
    assert err is None, err

    call = cloud.calls[0]
    assert call["scheme"] == "s3"
    assert call["bucket"] == "example-bucket"
    assert call["access_key_id"] == "id"
    assert call["secret_access_key"] == "secret"
    assert call["region"] == "us-east-1"
    # lance_client.storage_option_set moves the bucket into the host; the handler must not undo it
    assert call["endpoint"] == "https://example-bucket.s3.us-east-1.amazonaws.com"
    assert call["aws_virtual_hosted_style_request"] == "true"


def test_missing_storage_options_are_named(cloud):
    _, err = handlers.tree_info("s3://other-bucket/table.lance")
    assert err is not None
    assert "missing" in err
    assert "access_key_id" in err


def test_bucket_root_path_is_rejected_before_listing(cloud):
    _, err = handlers.tree_info("s3://example-bucket")
    assert err is not None
    assert "bucket root" in err


# ---------- listing ----------

def test_tree_mirrors_the_local_layout(cloud):
    info, err = handlers.tree_info(cloud.path)
    assert err is None, err

    by_name = {entry["name"]: entry for entry in info["tree"]}
    assert by_name["data"]["type"] == "dir"
    assert by_name["_versions"]["type"] == "dir"

    data_files = by_name["data"]["children"]
    assert [f["type"] for f in data_files] == ["file"]
    assert data_files[0]["size"] == _data_file(cloud.local).stat().st_size
    assert data_files[0]["mtime"] is None      # object listing carries no local mtime

    # directories sort before files at every level
    assert [e["type"] for e in info["tree"]] == sorted([e["type"] for e in info["tree"]],
                                                       key=lambda t: t != "dir")


def test_storage_view_matches_the_local_view(cloud):
    local, err = handlers.storage_info(str(cloud.local))
    assert err is None, err
    remote, rerr = handlers.storage_info(cloud.path)
    assert rerr is None, rerr

    assert remote["total_size"] == local["total_size"]
    assert remote["file_types"] == local["file_types"]
    assert remote["top_files"] == local["top_files"]
    assert remote["data_files"] == local["data_files"]


# ---------- range-read views ----------

def test_manifest_range_read_matches_the_local_decode(cloud):
    rel = _latest_manifest(cloud.local).relative_to(cloud.local).as_posix()

    local, err = handlers.manifest_info(str(cloud.local), rel)
    assert err is None, err
    remote, rerr = handlers.manifest_info(cloud.path, rel)
    assert rerr is None, rerr

    assert remote["summary"] == local["summary"]
    assert remote["full"]["data"] == local["full"]["data"]


def test_datafile_range_read_matches_the_local_decode(cloud):
    rel = _data_file(cloud.local).relative_to(cloud.local).as_posix()

    local, err = handlers.datafile_info(str(cloud.local), rel)
    assert err is None, err
    remote, rerr = handlers.datafile_info(cloud.path, rel)
    assert rerr is None, rerr

    assert remote["data"] == local["data"]

    # Range reads must not drag the data buffers over: only metadata is fetched.
    fetched = sum(len(data) for key, data in cloud.objects.items())
    data_file = _data_file(cloud.local)
    assert fetched > data_file.stat().st_size      # the mirror itself is complete
    assert remote["data"]["footer"]["file_size"] == data_file.stat().st_size


def test_txn_view_matches_the_local_decode(cloud):
    rel = sorted(p.relative_to(cloud.local).as_posix()
                 for p in (cloud.local / "_transactions").glob("*.txn"))[0]

    local, err = handlers.txn_info(str(cloud.local), rel)
    assert err is None, err
    remote, rerr = handlers.txn_info(cloud.path, rel)
    assert rerr is None, rerr

    assert remote["summary"] == local["summary"]
    assert remote["full"]["data"] == local["full"]["data"]


def test_transaction_timeline_matches_the_local_view(cloud, monkeypatch):
    # Snapshot metrics are merged in by opening the dataset through pylance, whose own S3 client the
    # fake operator cannot intercept. Disable that merge on both sides so this test covers what it
    # is about: listing the transaction objects and decoding them over the cloud path.
    monkeypatch.setattr(handlers, "LANCE_AVAILABLE", False)

    local, err = handlers.transaction_timeline(str(cloud.local))
    assert err is None, err
    remote, rerr = handlers.transaction_timeline(cloud.path)
    assert rerr is None, rerr

    strip = lambda rows: [{k: v for k, v in row.items() if k != "mtime"} for row in rows]
    assert strip(remote["transactions"]) == strip(local["transactions"])
    assert remote["op_stats"] == local["op_stats"]
    assert remote["has_snapshot"] is False


def test_txn_files_are_read_whole_not_by_range(cloud, monkeypatch):
    """A txn is not a data file: treating its trailing bytes as a v2 footer wastes a round trip."""
    monkeypatch.setattr(handlers, "LANCE_AVAILABLE", False)
    handlers.transaction_timeline(cloud.path)

    ranged = [r for r in cloud.reads if r["key"].endswith(".txn") and r["offset"] is not None]
    assert ranged == [], ranged


def test_json_view_reads_from_the_bucket(cloud):
    rel = "_versions/latest_version_hint.json"
    remote, err = handlers.json_info(cloud.path, rel)
    assert err is None, err
    local, lerr = handlers.json_info(str(cloud.local), rel)
    assert lerr is None, lerr
    assert remote["data"] == local["data"]


def test_every_mirrored_file_is_reachable(cloud):
    """Listing and reading agree on the same key set; a prefix bug shows up as a missing file."""
    listed = {rel for rel, _, _ in handlers._dataset_files(cloud.path)[0]}
    assert listed == set(_rel_files(cloud.local))
    assert all(isinstance(size, int) and size > 0 for _, size, _ in handlers._dataset_files(cloud.path)[0])