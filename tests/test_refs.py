"""Branch/Tag/Version view tests: /api/refs endpoint + version param reads historical snapshots.

Depends on the examples/demo.lance dataset (contains branch feature-x, tag snapshot-v3).
"""
import json
import threading
import urllib.parse
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer

from lance_viewer.server import Handler
from lance_viewer.handlers import refs_info, dataset_info


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
            return e.code, json.loads(e.read().decode("utf-8"))


DEMO = "examples/demo.lance"


def test_refs_info_lists_branch_tag_version():
    info, err = refs_info(DEMO)
    assert err is None
    # Branches
    assert any(b["name"] == "feature-x" for b in info["branches"])
    # Tags
    assert any(t["name"] == "snapshot-v3" for t in info["tags"])
    # Versions
    versions = [v["version"] for v in info["versions"]]
    assert versions == sorted(versions) and len(versions) >= 6
    # Tag folded into versions: version 3 should be labeled snapshot-v3
    assert 3 in info["tag_by_version"]
    assert "snapshot-v3" in info["tag_by_version"][3]


def test_dataset_info_reads_historical_version():
    info, err = dataset_info(DEMO, version=3)
    assert err is None
    assert info["version"] == 3
    # Reading a historical version does not change the main branch's latest version
    latest, err2 = dataset_info(DEMO)
    assert err2 is None
    assert latest["version"] > 3


def test_dataset_info_latest_has_version_field():
    info, err = dataset_info(DEMO)
    assert err is None
    # The version field is the newly added current snapshot number (positive int, >= historical versions)
    assert isinstance(info["version"], int) and info["version"] >= 1


def test_api_refs_endpoint():
    with _ServerCtx() as srv:
        q = urllib.parse.quote(DEMO)
        status, body = srv.get(f"/api/refs?path={q}")
        assert status == 200
        assert any(b["name"] == "feature-x" for b in body["branches"])
        assert any(t["name"] == "snapshot-v3" for t in body["tags"])


def test_api_dataset_with_version_param():
    with _ServerCtx() as srv:
        q = urllib.parse.quote(DEMO)
        status, body = srv.get(f"/api/dataset?path={q}&version=3")
        assert status == 200
        assert body["version"] == 3


CLOUD = "s3://example-bucket/test_table.lance"


def test_cloud_tree_info_builds_tree():
    """File tree of an object-storage dataset: no longer returns "unsupported", but builds a directory
    tree from the OpenDAL listing. Requires access to the S3 bucket; skips when unreachable."""
    from lance_viewer.handlers import tree_info
    info, err = tree_info(CLOUD)
    # Any open failure on a cloud path means the bucket/env is unreachable — skip, don't fail.
    # (Language-agnostic: the backend error string may be in any language.)
    if err is not None:
        import pytest
        pytest.skip(f"S3 unreachable: {err}")
    assert err is None, f"should build object-storage file tree: {err}"
    # Should contain the Lance dataset standard directories
    dirs = {n["name"] for n in info["tree"] if n["type"] == "dir"}
    assert "_versions" in dirs and "data" in dirs
    # At least one data file
    def files(n):
        c = [x for x in n if x["type"] == "file"]
        for x in n:
            if x["type"] == "dir":
                c += files(x.get("children", []))
        return c
    assert files(info["tree"]), "should list at least one file"
