#!/usr/bin/env python3
"""
Lance manifest file decoder
===========================
Parse a Lance dataset `_versions/*.manifest` file (protobuf-encoded) into readable JSON.

Format (see lance-table/src/io/manifest.rs):
    [4 bytes LE u32: payload_len][protobuf Manifest payload]...[16-byte footer]
    footer = [8 bytes LE i64: manifest_pos][8 bytes MAGIC ('LANC' prefix)]

Deps: the *_pb2.py generated in this dir (compiled from Lance repo protos/*.proto)
"""

import struct
import sys
import json
from pathlib import Path

try:
    from google.protobuf import json_format
except ImportError:
    sys.exit("Missing dependency: run `uv pip install protobuf`")

# The generated *_pb2.py modules use bare imports to reference each other (a protobuf generated-code
# constraint), so the protos dir must be on sys.path to load them as top-level modules. protos/ is a
# package-internal artifact, shipped with the package.
sys.path.insert(0, str(Path(__file__).resolve().parent / "protos"))
# Key: import these pb2 modules so that Any-referenced messages (index details, etc.) register in the default pool
import table_pb2  # noqa: E402
import transaction_pb2  # noqa: E402
import index_pb2  # noqa: E402
import index_old_pb2  # noqa: E402
import ann_pb2  # noqa: E402
import fragment_metadata_pb2  # noqa: E402
import file_pb2  # noqa: E402
import clustering_pb2  # noqa: E402


def decode_manifest_file(buf):
    """Decode a manifest file's bytes, returning (data dict, err or None).
    buf is the already-read bytes (Path.read_bytes for local, object store read for cloud)."""
    n = len(buf)
    if n < 16:
        return None, f"File too small ({n} bytes, minimum 16)"

    footer = buf[n - 16:]
    manifest_pos = struct.unpack('<q', footer[:8])[0]
    magic = footer[8:]

    # The last four footer bytes are 'LANC'; the four before them carry the manifest version, so
    # check the suffix rather than exact equality. Without this any file whose last 8 bytes happen
    # to parse as a small offset (a JSON file, a random blob) decodes to an empty manifest.
    if not magic.endswith(b"LANC"):
        return None, f"magic mismatch: {magic!r}"

    if manifest_pos < 0 or manifest_pos >= n:
        return None, f"manifest_pos ({manifest_pos}) out of range; file corrupt"

    payload_len = struct.unpack('<I', buf[manifest_pos:manifest_pos + 4])[0]
    payload = buf[manifest_pos + 4: manifest_pos + 4 + payload_len]
    if len(payload) != payload_len:
        return None, f"payload length mismatch: expected {payload_len}, got {len(payload)}"

    try:
        m = table_pb2.Manifest()
        m.ParseFromString(payload)
    except Exception as e:
        return None, f"protobuf decode failed: {e}"

    js = json_format.MessageToDict(
        m, preserving_proto_field_name=True, use_integers_for_enums=False
    )
    return {"manifest_pos": manifest_pos, "magic": magic.decode('latin-1'), "data": js}, None


def decode_txn_file(buf):
    """Decode a txn (transaction) file's bytes, returning (data dict, err or None).
    A txn is plain protobuf (no framing). buf is the already-read bytes."""
    if len(buf) < 2:
        return None, "File too small"
    try:
        m = transaction_pb2.Transaction()
        m.ParseFromString(buf)
    except Exception as e:
        return None, f"protobuf decode failed: {e}"
    js = json_format.MessageToDict(
        m, preserving_proto_field_name=True, use_integers_for_enums=False
    )
    return {"data": js}, None


# Transaction operation type -> label
def txn_operation_label(js):
    """Determine the operation type from Transaction content, returning (english key, label)."""
    op_keys = [
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
    ]
    for key, label in op_keys:
        if key in js:
            return key, label
    return None, "Unknown operation"


def build_txn_summary(js):
    """Build a condensed summary from the full txn JSON."""
    op, op_label = txn_operation_label(js)
    frag_count = 0
    rows = None
    files_count = 0
    if op == "append" and js.get("append", {}).get("fragments"):
        frags = js["append"]["fragments"]
        frag_count = len(frags)
        for f in frags:
            rows = f.get("physical_rows", rows)
            files_count += len(f.get("files", []))
    elif op == "delete" and js.get("delete"):
        pass
    return {
        "uuid": js.get("uuid"),
        "read_version": js.get("read_version"),
        "operation": op,
        "operation_label": op_label,
        "fragments": frag_count,
        "physical_rows": rows,
        "data_files": files_count,
    }


def build_summary(js):
    """Build a condensed summary from the full manifest JSON."""
    data = js.get("data", {})
    fields = data.get("fields", [])
    fragments = data.get("fragments", [])

    schema_cols = []
    for f in fields:
        schema_cols.append({
            "name": f.get("name", ""),
            "logical_type": f.get("logical_type", ""),
            "encoding": f.get("encoding", ""),
            "nullable": f.get("nullable", False),
        })

    frag_list = []
    for fr in fragments:
        files = []
        for df in fr.get("files", []):
            files.append({
                "path": df.get("path", ""),
                "file_major_version": df.get("file_major_version"),
                "columns": len(df.get("column_indices", [])),
            })
        frag_list.append({
            "id": fr.get("id"),
            "physical_rows": fr.get("physical_rows"),
            "files": files,
        })

    return {
        "version": data.get("version"),
        "schema_cols": schema_cols,
        "fragments": frag_list,
        "max_fragment_id": data.get("max_fragment_id"),
        "reader_feature_flags": data.get("reader_feature_flags"),
        "writer_feature_flags": data.get("writer_feature_flags"),
        "writer_version": data.get("writer_version"),
        "data_format": data.get("data_format"),
        "transaction_file": data.get("transaction_file"),
    }


if __name__ == "__main__":
    # CLI test
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("manifest", help="path to the manifest file")
    ap.add_argument("--summary", action="store_true", help="output only the condensed summary")
    args = ap.parse_args()

    out, err = decode_manifest_file(Path(args.manifest).read_bytes())
    if err:
        print("Error:", err)
        sys.exit(1)
    if args.summary:
        print(json.dumps(build_summary(out), ensure_ascii=False, indent=2))
    else:
        print(json.dumps(out, ensure_ascii=False, indent=2))
