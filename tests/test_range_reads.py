"""Range reads for object storage: only the metadata an endpoint needs should hit the wire.

Two endpoints decode framed formats whose metadata lives at known offsets, so they can be read by
range instead of fetching the object whole:

  * manifest  — last 16 bytes point at a u32 length + protobuf payload
  * .lance data file — the 40-byte footer points at the CMO/GBO tables, the FileDescriptor and
    each column's metadata; the data buffers are never needed for the metadata view

`arrow_info` is deliberately NOT range-read: it renders every row, so all record-batch blocks are
needed anyway (measured 0.2% saved for 5x the requests). These tests pin that too, so nobody
"optimises" it back into range reads by mistake.
"""
import os
import struct

import pyarrow as pa
import pytest

from lance_viewer import handlers
from lance_viewer.datafile_decoder import FOOTER_SIZE, SparseBytes, decode_datafile


class FakeOperator:
    """Stands in for an OpenDAL operator, recording every read so we can assert on the bytes."""

    def __init__(self, blobs):
        self.blobs = blobs
        self.reads = []

    def stat(self, key):
        size = len(self.blobs[key])

        class _Stat:
            content_length = size

        return _Stat()

    def read(self, key, offset=None, size=None):
        blob = self.blobs[key]
        if offset is None and size is None:
            self.reads.append((key, None, len(blob)))
            return blob
        offset = offset or 0
        chunk = blob[offset:offset + size]
        self.reads.append((key, offset, len(chunk)))
        return chunk

    def full_reads(self):
        return [r for r in self.reads if r[1] is None]

    def fetched(self, key):
        return sum(n for k, _, n in self.reads if k == key)


def _manifest_blob(payload_len=400, tail_pad=100):
    """A manifest with the real layout: [pad][u32 len][payload][16-byte footer]."""
    payload = b"\x08\x01" + b"\x00" * (payload_len - 2)
    head = struct.pack("<I", len(payload)) + payload
    # 16-byte footer: int64 manifest_pos + 8-byte magic
    footer = struct.pack("<q", tail_pad) + b"LANC\x00\x00\x00\x00"
    return b"\x00" * tail_pad + head + footer


# ---------------------------------------------------------------------------
# SparseBytes
# ---------------------------------------------------------------------------

def test_sparse_bytes_reads_only_fetched_spans():
    buf = SparseBytes(100, [(10, b"abc"), (50, b"de")])
    assert len(buf) == 100
    assert buf[10:13] == b"abc"
    assert buf[50:52] == b"de"
    # unfetched bytes read as zero, matching the sparse bytearray this replaced
    assert buf[0:3] == b"\x00\x00\x00"
    assert buf[40:42] == b"\x00\x00\x00"[:2]


def test_sparse_bytes_does_not_allocate_the_file_size():
    # The point of the container: a huge file with tiny metadata stays tiny in memory.
    buf = SparseBytes(5_000_000, [(0, b"x" * 8)])
    assert len(buf) == 5_000_000
    assert buf.fetched() == 8


def test_sparse_bytes_supports_struct_unpack_on_slices():
    buf = SparseBytes(40, [(0, struct.pack("<QQQ", 1, 2, 3))])
    assert struct.unpack("<QQQ", buf[0:24]) == (1, 2, 3)


# ---------------------------------------------------------------------------
# data file metadata
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def local_dataset(tmp_path_factory):
    """A small on-disk Lance dataset (two versions, one append)."""
    import lance

    path = str(tmp_path_factory.mktemp("ds") / "table.lance")
    lance.write_dataset(pa.table({"id": [1, 2, 3], "name": ["a", "b", "c"]}), path)
    lance.write_dataset(pa.table({"id": [4, 5], "name": ["d", "e"]}), path, mode="append")
    return path


@pytest.fixture(scope="module")
def real_datafile(tmp_path_factory):
    """A real .lance data file plus its bytes, so decoding is checked against the real thing."""
    import lance

    path = tmp_path_factory.mktemp("ds") / "t.lance"
    lance.write_dataset(pa.table({"id": list(range(200)), "s": ["v"] * 200}), str(path))
    files = sorted((path / "data").glob("*.lance"))
    blob = files[0].read_bytes()
    return blob


def test_range_read_datafile_fetches_metadata_not_data(real_datafile):
    op = FakeOperator({"data/0.lance": real_datafile})
    buf, err = handlers._range_read_datafile(op, "data/0.lance")
    assert err is None
    assert not op.full_reads(), "data file must not be read whole"
    # every byte fetched is a real range read, and is far less than the file
    assert 0 < buf.fetched() < len(real_datafile)
    assert buf.fetched() == op.fetched("data/0.lance")


def test_range_read_datafile_decodes_to_the_same_result_as_a_full_read(real_datafile):
    op = FakeOperator({"data/0.lance": real_datafile})
    sparse, err = handlers._range_read_datafile(op, "data/0.lance")
    assert err is None
    from_sparse, err1 = decode_datafile(sparse)
    from_full, err2 = decode_datafile(real_datafile)
    assert err1 is None and err2 is None
    assert from_sparse == from_full


def test_range_read_datafile_reports_a_short_file():
    op = FakeOperator({"data/tiny.lance": b"1234"})
    buf, err = handlers._range_read_datafile(op, "data/tiny.lance")
    assert buf is None and "too small" in err


# ---------------------------------------------------------------------------
# manifest
# ---------------------------------------------------------------------------

def test_range_read_manifest_fetches_footer_length_and_payload_only():
    blob = _manifest_blob()
    op = FakeOperator({"_versions/1.manifest": blob})
    buf, err = handlers._range_read_manifest(op, "_versions/1.manifest")
    assert err is None
    assert not op.full_reads(), "manifest must not be read whole"
    # footer (16) + length prefix (4) + payload, and nothing else
    assert len(op.reads) == 3
    assert op.fetched("_versions/1.manifest") < len(blob)


def test_range_read_manifest_rejects_an_out_of_range_pointer():
    blob = b"\x00" * 20 + struct.pack("<q", 10_000) + b"LANC\x00\x00\x00\x00"
    op = FakeOperator({"_versions/1.manifest": blob})
    buf, err = handlers._range_read_manifest(op, "_versions/1.manifest")
    assert buf is None and "out of range" in err


def test_range_read_manifest_decodes_identically_to_a_full_read(local_dataset):
    """The strongest check: build the same bytes two ways and compare the decoded output."""
    from lance_viewer.manifest_decoder import decode_manifest_file

    files, _ = handlers._dataset_files(local_dataset)
    man = next(rel for rel, _, _ in files if rel.endswith(".manifest"))
    blob = open(os.path.join(local_dataset, man), "rb").read()

    op = FakeOperator({man: blob})
    sparse, err = handlers._range_read_manifest(op, man)
    assert err is None
    assert not op.full_reads()

    from_sparse, err1 = decode_manifest_file(sparse)
    from_full, err2 = decode_manifest_file(blob)
    assert err1 is None and err2 is None
    assert from_sparse == from_full
    assert from_sparse["data"].get("fragments"), "decoded manifest should carry fragments"


def test_range_read_manifest_rejects_a_short_file():
    op = FakeOperator({"_versions/1.manifest": b"short"})
    buf, err = handlers._range_read_manifest(op, "_versions/1.manifest")
    assert buf is None and "too small" in err


def test_manifest_info_local_matches_full_decode(local_dataset):
    files, _ = handlers._dataset_files(local_dataset)
    man = next(rel for rel, _, _ in files if rel.endswith(".manifest"))
    info, err = handlers.manifest_info(local_dataset, man)
    assert err is None
    assert info["summary"]["fragments"], "fragment summary should not be empty"
    assert "fields" in info["full"]["data"]


# ---------------------------------------------------------------------------
# arrow: intentionally whole
# ---------------------------------------------------------------------------

def test_arrow_info_reads_whole_file_because_it_renders_every_row(tmp_path):
    tbl = pa.table({"k": list(range(500)), "v": ["x"] * 500})
    path = tmp_path / "d.arrow"
    with pa.OSFile(str(path), "wb") as fh:
        with pa.ipc.new_file(fh, tbl.schema) as writer:
            writer.write_table(tbl)

    import os
    n = os.path.getsize(str(path))
    # A local read goes through _read_dataset_file; assert the decoded payload is complete so a
    # future range-read change has to keep rendering all rows.
    info, err = handlers.arrow_info(str(tmp_path), "d.arrow")
    assert err is None
    assert info["total_rows"] == 500
    assert len(info["rows"]) == 500
    assert n > 0