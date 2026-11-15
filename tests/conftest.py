"""Shared test setup.

The registry lives in a platform data directory by default (e.g. ~/.local/share/lance-viewer) and
holds the user's datasets, including their object-storage credentials. Two things follow:

  - Tests that go through the HTTP layer POST/PUT/DELETE /api/datasets, which write there. Writing
    must never touch the real list, so the session runs against a throwaway directory.
  - The optional cloud tests (LANCE_VIEWER_TEST_CLOUD=1) do need those registered credentials to
    reach a real bucket. So the real registry is *copied* into the throwaway directory instead of
    being ignored: reads see the user's datasets, writes stay local.
"""
import atexit
import os
import shutil
import tempfile
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def decoder_dataset(tmp_path_factory):
    """A small real dataset written by the installed Lance, for the decoder tests.

    Deliberately built at test time instead of checked in as bytes: a pinned old file can only prove
    "we still read the old format", while a dataset written by the current Lance is what a format
    upgrade actually changes. The assertions stay structural (columns, pages, encodings) so a normal
    version bump does not need new expected output.
    """
    lance = pytest.importorskip("lance")
    pa = pytest.importorskip("pyarrow")

    path = tmp_path_factory.mktemp("decoder") / "table.lance"
    rows = 24
    lance.write_dataset(pa.table({
        "id": pa.array(range(rows), type=pa.int64()),
        "name": pa.array([f"name_{i}" for i in range(rows)], type=pa.string()),
        "vec": pa.array([[float(i)] * 8 for i in range(rows)],
                        type=pa.list_(pa.float32(), 8)),
    }), str(path))
    return path


def _real_db():
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", str(Path.home())))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share")))
    return base / "lance-viewer" / "datasets.db"


_real = _real_db()
_tmp_home = tempfile.mkdtemp(prefix="lance-viewer-tests-")
os.environ["XDG_DATA_HOME"] = _tmp_home

# Copy the real registry so the cloud tests keep their credentials; never copy back.
if _real.is_file():
    target = Path(_tmp_home) / "lance-viewer"
    target.mkdir(parents=True, exist_ok=True)
    shutil.copy2(_real, target / "datasets.db")

atexit.register(lambda: shutil.rmtree(_tmp_home, ignore_errors=True))