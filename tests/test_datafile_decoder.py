""".lance 数据文件解码器测试。

覆盖三块：
  - 文件级错误路径（长度、magic）；
  - 真实文件的 footer / 列 / 页 / schema 结构，以及"页布局必须落在已知集合里"这条底线；
  - SparseBytes：对象存储只按 range 取回若干段字节，解码结果必须和整文件读取一致。

另外固定住未知布局的降级行为：Lance 升到新格式时，界面要显示"这是新格式"，而不是空白或崩掉。
"""
import re
import struct

import pytest
from google.protobuf import any_pb2

from lance_viewer import datafile_decoder as dd
from lance_viewer.datafile_decoder import SparseBytes, decode_datafile

# Generated bindings; importing the decoder puts protos/ on sys.path.
import file2_pb2  # noqa: E402

KNOWN_LAYOUTS = set(dd.LAYOUT_LABELS.values()) | {
    "No encoding", "Indirect encoding (buffer)", "Unknown Any", "Parse failed", "Unknown layout",
}
COMPRESSION_RE = re.compile(r"(none|LZ4|ZSTD|scheme\d+)(\(lvl\d+\))?")

FOOTER_SIZE = 40


def _only_data_file(dataset_path):
    files = sorted((dataset_path / "data").glob("*.lance"))
    assert files, "dataset has no data files"
    return files[0]


# ---------- file-level errors ----------

def test_rejects_file_shorter_than_footer():
    out, err = decode_datafile(b"\x00" * (FOOTER_SIZE - 1))
    assert out is None
    assert "too small" in err


def test_rejects_magic_mismatch():
    out, err = decode_datafile(b"\x00" * (FOOTER_SIZE - 4) + b"LANX")
    assert out is None
    assert "magic mismatch" in err


# ---------- a real data file ----------

def test_real_datafile_structure(decoder_dataset):
    path = _only_data_file(decoder_dataset)
    info, err = decode_datafile(path.read_bytes())
    assert err is None

    footer = info["footer"]
    assert footer["file_size"] == path.stat().st_size
    assert footer["major_version"] == 2
    assert footer["columns"] == len(info["schema"]) == 3
    assert [c["name"] for c in info["schema"]] == ["id", "name", "vec"]

    assert len(info["columns"]) == 3
    for col in info["columns"]:
        assert col["num_pages"] >= 1
        assert len(col["pages"]) == col["num_pages"]
        for page in col["pages"]:
            assert page["layout"] in KNOWN_LAYOUTS, page["layout"]
            assert page["num_buffers"] == len(page["buffer_offsets"])
            for comp in page["compression"]:
                assert COMPRESSION_RE.fullmatch(comp), comp


def test_every_page_layout_is_known(decoder_dataset):
    info, err = decode_datafile(_only_data_file(decoder_dataset).read_bytes())
    assert err is None
    layouts = {page["layout"] for col in info["columns"] for page in col["pages"]}
    assert layouts, "no pages decoded"
    assert layouts <= KNOWN_LAYOUTS


# ---------- SparseBytes (object-storage range reads) ----------

def test_sparse_bytes_zero_fills_missing_ranges():
    sparse = SparseBytes(10, [(3, b"ab")])
    assert len(sparse) == 10
    assert sparse[3] == ord("a")
    assert sparse[9] == 0              # never fetched, reads as zero
    assert sparse[-1] == 0
    assert bytes(sparse[0:6]) == b"\x00\x00\x00ab\x00"
    assert bytes(sparse[8:20]) == b"\x00\x00"   # slices clamp to the file size
    assert bytes(sparse[9:4]) == b""
    assert sparse.ranges() == [(3, 2)]
    assert sparse.fetched() == 2
    with pytest.raises(IndexError):
        sparse[10]


def test_decode_from_spans_matches_a_full_read(decoder_dataset):
    """The cloud path only fetches metadata ranges; the result must equal reading the whole file."""
    raw = _only_data_file(decoder_dataset).read_bytes()
    full, err = decode_datafile(raw)
    assert err is None

    def span(offset, size):
        # SparseBytes takes the fetched bytes, not a length: this is what the range reader hands it.
        return offset, raw[offset:offset + size]

    n = len(raw)
    footer = full["footer"]
    spans = [
        span(n - FOOTER_SIZE, FOOTER_SIZE),
        span(footer["cmo_table_offset"], 16 * footer["columns"]),
    ]
    if footer["global_buffers"]:
        spans.append(span(footer["gbo_table_offset"], 16 * footer["global_buffers"]))
    spans += [span(c["metadata_offset"], c["metadata_size"]) for c in full["columns"]]
    # Only global buffer 0 (the FileDescriptor) is fetched in production, so mirror that.
    spans += [span(g["offset"], g["size"]) for g in full["global_buffers"][:1]]

    sparse, sparse_err = decode_datafile(SparseBytes(n, spans))
    assert sparse_err is None

    assert sparse["footer"] == full["footer"]
    assert sparse["columns"] == full["columns"]
    assert sparse["global_buffers"] == full["global_buffers"]
    assert sparse["schema"] == full["schema"]


def test_range_read_without_the_schema_buffer_reports_no_columns(decoder_dataset):
    raw = _only_data_file(decoder_dataset).read_bytes()
    full, _ = decode_datafile(raw)
    n = len(raw)
    footer = full["footer"]
    spans = [(n - FOOTER_SIZE, raw[n - FOOTER_SIZE:]),
             (footer["cmo_table_offset"],
              raw[footer["cmo_table_offset"]:footer["cmo_table_offset"] + 16 * footer["columns"]])]
    spans += [(c["metadata_offset"], raw[c["metadata_offset"]:c["metadata_offset"] + c["metadata_size"]])
              for c in full["columns"]]

    info, err = decode_datafile(SparseBytes(n, spans))
    assert err is None
    assert info["schema"] == []
    assert len(info["columns"]) == footer["columns"]


# ---------- unknown / future encodings ----------

def _file_with_page_encoding(encoding):
    """Build a minimal valid .lance buffer: one column, one page, the given page encoding."""
    column = file2_pb2.ColumnMetadata()
    page = column.pages.add()
    page.length = 1
    page.encoding.CopyFrom(encoding)
    column_bytes = column.SerializeToString()

    cmo_offset = len(column_bytes)
    table = struct.pack("<QQ", 0, len(column_bytes))          # one (pos, size) entry
    footer = (struct.pack("<QQQ", 0, cmo_offset, cmo_offset)  # cm0, cmo, gbo offsets
              + struct.pack("<II", 0, 1)                      # global buffers, columns
              + struct.pack("<HH", 2, 1)                      # major, minor
              + b"LANC")
    return column_bytes + table + footer


def test_unknown_page_layout_is_named_instead_of_blank():
    encoding = file2_pb2.Encoding()
    newer = any_pb2.Any(type_url="/lance.encodings99.PageLayout", value=b"\x08\x01")
    encoding.direct.encoding = newer.SerializeToString()

    info, err = decode_datafile(_file_with_page_encoding(encoding))
    assert err is None

    page = info["columns"][0]["pages"][0]
    assert page["layout"] == "Unknown layout"
    assert "encodings99" in page["encoding"], "the format name must reach the UI"
    assert page["compression"] == []


def test_indirect_encoding_is_labelled_as_a_buffer_reference():
    encoding = file2_pb2.Encoding()
    encoding.indirect.buffer_location = 3
    encoding.indirect.buffer_length = 99

    info, err = decode_datafile(_file_with_page_encoding(encoding))
    assert err is None

    page = info["columns"][0]["pages"][0]
    assert page["layout"] == "Indirect encoding (buffer)"
    assert "buf_loc=3" in page["encoding"]
    assert "len=99" in page["encoding"]


def test_page_without_encoding_is_reported_as_none():
    encoding = file2_pb2.Encoding()
    encoding.none.SetInParent()

    info, err = decode_datafile(_file_with_page_encoding(encoding))
    assert err is None

    assert info["columns"][0]["pages"][0]["layout"] == "No encoding"