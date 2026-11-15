"""manifest / transaction 解码器测试。

两层：

  - 纯字节：手工拼出 Lance 的 framing，覆盖截断、越界、长度不符、坏 protobuf 等错误路径。不需要
    数据集，跑得极快，这是解码器出错时最先该亮的地方。
  - 真实文件：用当前安装的 Lance 现场写一个小数据集，断言字段级结构。

数据集现场生成而不是提交固定字节，是因为 Lance 升级后旧文件永远不会再产生，钉住它只能证明"我们
还认识旧格式"，恰好测不到新格式。
"""
import struct

import pytest

from lance_viewer.datafile_decoder import SparseBytes
from lance_viewer.manifest_decoder import (
    build_summary,
    build_txn_summary,
    decode_manifest_file,
    decode_txn_file,
    txn_operation_label,
)

# Generated bindings. Importing manifest_decoder above puts protos/ on sys.path, which is how the
# generated modules import each other.
import table_pb2  # noqa: E402
import transaction_pb2  # noqa: E402

MAGIC = b"LANC"


def _frame(payload, pos=None, magic=MAGIC):
    """[u32 payload_len][payload][i64 manifest_pos][8-byte magic], as a `.manifest` file."""
    body = struct.pack("<I", len(payload)) + payload
    return body + struct.pack("<q", 0 if pos is None else pos) + magic.rjust(8, b"\x00")


# ---------- framing / error paths ----------

def test_rejects_file_shorter_than_footer():
    out, err = decode_manifest_file(b"\x00" * 8)
    assert out is None
    assert "too small" in err


def test_rejects_manifest_pos_past_end_of_file():
    out, err = decode_manifest_file(_frame(b"", pos=10 ** 6))
    assert out is None
    assert "out of range" in err


def test_rejects_negative_manifest_pos():
    out, err = decode_manifest_file(_frame(b"", pos=-1))
    assert out is None
    assert "out of range" in err


def test_rejects_payload_length_past_end_of_file():
    buf = struct.pack("<I", 50) + b"abc" + struct.pack("<q", 0) + MAGIC.rjust(8, b"\x00")
    out, err = decode_manifest_file(buf)
    assert out is None
    assert "mismatch" in err


def test_rejects_invalid_protobuf_payload():
    # 0x0f is wire type 7, which does not exist: ParseFromString must fail rather than half-parse.
    out, err = decode_manifest_file(_frame(b"\x0f"))
    assert out is None
    assert "decode failed" in err


def test_rejects_magic_mismatch():
    out, err = decode_manifest_file(_frame(b"", magic=b"LANX"))
    assert out is None
    assert "magic mismatch" in err


def test_accepts_a_versioned_magic_prefix():
    # Real files end in "\x00\x00\x02\x00LANC": the version bytes must not be treated as part of
    # the magic, or every manifest would be rejected the moment Lance bumps them.
    out, err = decode_manifest_file(_frame(b"", magic=b"\x00\x00\x02\x00LANC"))
    assert err is None
    assert out["magic"] == "\x00\x00\x02\x00LANC"


def test_decodes_from_sparse_range_spans():
    """The cloud path fetches footer + length + payload by range; that must decode identically."""
    manifest = table_pb2.Manifest(version=3)
    field = manifest.fields.add()
    field.name = "id"
    field.logical_type = "int64"
    field.encoding = "PLAIN"
    manifest.fragments.add().physical_rows = 5

    payload = manifest.SerializeToString()
    buf = _frame(payload)
    n = len(buf)
    manifest_pos = struct.unpack("<q", buf[-16:-8])[0]

    spans = [
        (n - 16, buf[n - 16:]),
        (manifest_pos, buf[manifest_pos:manifest_pos + 4]),
        (manifest_pos + 4, payload),
    ]
    sparse, err = decode_manifest_file(SparseBytes(n, spans))
    assert err is None

    summary = build_summary(sparse)
    assert summary["version"] == "3"
    assert [c["name"] for c in summary["schema_cols"]] == ["id"]
    assert int(summary["fragments"][0]["physical_rows"]) == 5


def test_decodes_an_empty_manifest():
    out, err = decode_manifest_file(_frame(table_pb2.Manifest().SerializeToString()))
    assert err is None
    assert out["manifest_pos"] == 0
    assert out["magic"].endswith("LANC")
    assert out["data"] == {}


def test_summary_of_an_empty_manifest_is_empty_not_an_error():
    summary = build_summary({"data": {}})
    assert summary["schema_cols"] == []
    assert summary["fragments"] == []
    assert summary["version"] is None


# ---------- transactions ----------

def test_txn_rejects_tiny_file():
    for buf in (b"", b"\xff"):
        out, err = decode_txn_file(buf)
        assert out is None
        assert "too small" in err


def test_txn_rejects_invalid_protobuf():
    # 0x0f is wire type 7 (invalid); two bytes so it clears the "too small" guard first.
    out, err = decode_txn_file(b"\x0f\x00")
    assert out is None
    assert "decode failed" in err


def test_txn_append_roundtrip():
    txn = transaction_pb2.Transaction(uuid="u-1", read_version=2)
    frag = txn.append.fragments.add()
    frag.id = 7
    frag.physical_rows = 5
    data_file = frag.files.add()
    data_file.path = "data/a.lance"
    data_file.file_major_version = 2

    out, err = decode_txn_file(txn.SerializeToString())
    assert err is None

    summary = build_txn_summary(out["data"])
    # protobuf's JSON mapping renders 64-bit integers as strings; the summary keeps them as-is.
    assert summary == {
        "uuid": "u-1",
        "read_version": "2",
        "operation": "append",
        "operation_label": "Append",
        "fragments": 1,
        "physical_rows": "5",
        "data_files": 1,
    }


@pytest.mark.parametrize("key,label", [
    ("append", "Append"),
    ("delete", "Delete"),
    ("overwrite", "Overwrite"),
    ("create_index", "CreateIndex"),
    ("rewrite", "Rewrite"),
    ("merge", "Merge"),
    ("project", "Project"),
    ("restore", "Restore"),
    ("reserve_fragments", "ReserveFragments"),
    ("clone", "Clone"),
    ("update", "Update"),
    ("update_config", "UpdateConfig"),
    ("data_replacement", "DataReplacement"),
    ("data_overlay", "DataOverlay"),
    ("update_mem_wal_state", "UpdateMemWalState"),
])
def test_operation_labels(key, label):
    assert txn_operation_label({key: {}}) == (key, label)


def test_unknown_operation_is_reported_not_guessed():
    assert txn_operation_label({"some_future_op": {}}) == (None, "Unknown operation")


def test_delete_txn_has_no_fragment_counts():
    txn = transaction_pb2.Transaction(uuid="u-2", read_version=1)
    txn.delete.SetInParent()
    out, err = decode_txn_file(txn.SerializeToString())
    assert err is None

    summary = build_txn_summary(out["data"])
    assert summary["operation"] == "delete"
    assert summary["fragments"] == 0
    assert summary["physical_rows"] is None


# ---------- a real dataset ----------

def _latest_manifest(dataset_path):
    return max((dataset_path / "_versions").glob("*.manifest"),
               key=lambda p: int(p.stem))


def test_real_manifest_matches_the_dataset(decoder_dataset):
    lance = pytest.importorskip("lance")

    out, err = decode_manifest_file(_latest_manifest(decoder_dataset).read_bytes())
    assert err is None

    summary = build_summary(out)
    ds = lance.dataset(str(decoder_dataset))

    assert int(summary["version"]) == ds.version
    assert [c["name"] for c in summary["schema_cols"]] == ["id", "name", "vec"]
    assert summary["schema_cols"][0]["logical_type"] == "int64"
    assert summary["schema_cols"][1]["logical_type"] == "string"
    assert summary["schema_cols"][2]["logical_type"].startswith("fixed_size_list")

    assert len(summary["fragments"]) == 1
    fragment = summary["fragments"][0]
    assert int(fragment["physical_rows"]) == 24
    assert fragment["files"], "a fragment with rows must reference at least one data file"
    for f in fragment["files"]:
        assert f["path"].endswith(".lance")
        assert f["file_major_version"] == 2
        assert f["columns"] == 3


def test_every_transaction_file_decodes(decoder_dataset):
    txns = sorted((decoder_dataset / "_transactions").glob("*.txn"))
    assert txns, "writing a dataset should leave at least one transaction file"

    known = {"append", "delete", "overwrite", "create_index", "rewrite", "merge", "project",
             "restore", "reserve_fragments", "clone", "update", "update_config",
             "data_replacement", "data_overlay", "update_mem_wal_state"}
    for path in txns:
        out, err = decode_txn_file(path.read_bytes())
        assert err is None, f"{path.name}: {err}"
        summary = build_txn_summary(out["data"])
        assert summary["operation"] in known, f"{path.name}: {summary['operation']}"
        assert summary["uuid"], f"{path.name}: no uuid"