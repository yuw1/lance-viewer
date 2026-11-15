#!/usr/bin/env python3
"""
Lance .lance data-file decoder
===============================
Parse the internals of a Lance v2 data file: footer, column metadata, pages, encoding, compression.

File layout (v2, see protos/file2.proto header comment):
    [Data Buffers][Column Metadatas][CMO Table][GBO Table][Footer]
    Footer (40 bytes, at the end):
        u64: cm0 offset | u64: CMO table offset | u64: GBO table offset
        u32: #global buffers | u32: #columns
        u16: major version | u16: minor version | "LANC"

    CMO Table: a (position, size) u64 pair per column, pointing to the ColumnMetadata protobuf
    ColumnMetadata (file2.proto): encoding + pages[] + buffer_offsets/sizes
        Page: buffer_offsets[] | buffer_sizes[] | length | encoding | priority
    Page encoding: oneof direct/indirect/none
        direct.encoding = bytes is an Any(type_url=/lance.encodings21.PageLayout, value=PageLayout)
    PageLayout (encodings_v2_1.proto):
        oneof mini_block_layout / constant_layout / full_zip_layout / blob_layout
"""

import struct
import sys
from pathlib import Path

try:
    from google.protobuf import json_format
    from google.protobuf import any_pb2
except ImportError:
    sys.exit("Missing dependency: run `uv pip install protobuf`")

# The generated *_pb2.py modules use bare imports to reference each other (a protobuf generated-code
# constraint), so the protos dir must be on sys.path to load them as top-level modules. protos/ is a
# package-internal artifact, shipped with the package.
sys.path.insert(0, str(Path(__file__).resolve().parent / "protos"))
import file2_pb2
import encodings_v2_1_pb2 as e1
import file_pb2

FOOTER_SIZE = 40


class SparseBytes:
    """A read-only stand-in for a file's bytes where only some ranges were actually fetched.

    Object storage is read by range, so only the footer, the CMO/GBO tables and the column
    metadata are in memory. Materialising those into a bytearray(n) would allocate the whole file
    just to leave it empty, so instead the fetched spans are kept in a sorted list and slices are
    assembled on demand (only the ~15 small metadata reads the decoder performs).

    Implements just enough of the bytes protocol for decode_datafile: len(), slicing, and
    struct.unpack_from on a slice result (a real bytes object). Missing bytes read as zeros, which
    matches the old sparse-bytearray behaviour the range reader relied on.
    """

    __slots__ = ("size", "_spans")

    def __init__(self, size, spans=()):
        self.size = size
        self._spans = sorted(((o, bytes(b)) for o, b in spans if b), key=lambda s: s[0])

    def __len__(self):
        return self.size

    def __getitem__(self, key):
        if isinstance(key, int):
            if key < 0:
                key += self.size
            if not 0 <= key < self.size:
                raise IndexError("index out of range")
            for off, data in self._spans:
                if off <= key < off + len(data):
                    return data[key - off]
            return 0
        start, stop, _ = key.indices(self.size)
        if stop <= start:
            return b""
        out = bytearray(stop - start)
        for off, data in self._spans:
            lo = max(off, start)
            hi = min(off + len(data), stop)
            if lo < hi:
                out[lo - start:hi - start] = data[lo - off:hi - off]
        return bytes(out)

    def ranges(self):
        """The fetched spans as (offset, length), for diagnostics and tests."""
        return [(off, len(data)) for off, data in self._spans]

    def __repr__(self):
        return f"SparseBytes(size={self.size}, spans={len(self._spans)}, fetched={self.fetched()})"

    def fetched(self):
        return sum(len(d) for _, d in self._spans)


# Compression algorithm names
COMPRESSION_NAMES = {
    0: "none",
    1: "LZ4",
    2: "ZSTD",
}

# Encoding oneof field -> label
ENCODING_LABELS = {
    "flat": "Flat",
    "variable": "Variable",
    "constant": "Constant",
    "nullable": "Nullable",
    "fixed_size_list": "FixedSizeList",
    "list": "List",
    "struct": "Struct",
    "binary": "Binary",
    "dictionary": "Dictionary",
    "fsst": "FSST",
    "packed_struct": "PackedStruct",
    "bitpacked": "BitPacking",
    "inline_bitpacking": "InlineBitPacking",
    "out_of_line_bitpacking": "OutOfLineBitPacking",
    "fixed_size_binary": "FixedSizeBinary",
    "bitpacked_for_non_neg": "BitPacking(non-negative)",
    "packed_struct_fixed_width_mini_block": "PackedStructMiniBlock",
    "block": "Block",
    "rle": "RLE",
    "general_mini_block": "GeneralMiniBlock",
    "byte_stream_split": "ByteStreamSplit",
}

# PageLayout oneof -> label
LAYOUT_LABELS = {
    "mini_block_layout": "MiniBlock",
    "constant_layout": "Constant",
    "full_zip_layout": "FullZip",
    "blob_layout": "Blob",
}


def _extract_compression(compressive, depth=0):
    """Extract the compression algorithm name(s) from a CompressiveEncoding. Returns list[str]."""
    results = []
    if compressive is None:
        return results
    which = compressive.WhichOneof("compression")
    if not which:
        return results
    comp = getattr(compressive, which)
    results.extend(_extract_from_object(comp, set(), 0))
    return list(dict.fromkeys(results))


def _extract_from_object(obj, _seen=None, _depth=0):
    """Recursively walk an object's fields, extracting BufferCompression schemes. Cycle detection and depth limit included."""
    if _depth > 12:
        return []
    if _seen is None:
        _seen = set()
    oid = id(obj)
    if oid in _seen:
        return []
    _seen.add(oid)
    results = []
    try:
        fields = obj.DESCRIPTOR.fields
    except AttributeError:
        return results
    for field_desc in fields:
        if field_desc.type != field_desc.TYPE_MESSAGE:
            continue
        is_rep = getattr(field_desc, 'is_repeated', False)
        if is_rep:
            for item in getattr(obj, field_desc.name):
                results.extend(_collect(item, _seen, _depth + 1))
        else:
            sub = getattr(obj, field_desc.name)
            results.extend(_collect(sub, _seen, _depth + 1))
    return results


def _collect(sub, _seen, _depth):
    """Determine whether a child is a BufferCompression or another message, and recurse to extract."""
    if sub is None or _depth > 12:
        return []
    # Exact BufferCompression check (message full_name is lance.encodings21.BufferCompression)
    try:
        fname = sub.DESCRIPTOR.full_name
    except AttributeError:
        fname = None
    if fname == 'lance.encodings21.BufferCompression':
        scheme = sub.scheme
        if not scheme:
            return []
        name = COMPRESSION_NAMES.get(scheme, f"scheme{scheme}")
        level = sub.level
        return [name + (f"(lvl{level})" if level else "")]
    if hasattr(sub, 'DESCRIPTOR'):
        return _extract_from_object(sub, _seen, _depth)
    return []


def _extract_compression_attr(obj):
    """Extract from any object that has a compression field."""
    results = _extract_from_object(obj, set(), 0)
    return list(dict.fromkeys(results))


def _page_layout_summary(page_encoding):
    """Extract a layout summary from a page's encoding.
    Returns (layout_label, encoding_desc, compression_list).
    """
    field = page_encoding.WhichOneof("location")
    if field == "none" or field is None:
        return "No encoding", "", []
    if field == "indirect":
        # Indirect encoding (in another buffer), cannot be read directly
        ind = page_encoding.indirect
        return "Indirect encoding (buffer)", f"buf_loc={ind.buffer_location} len={ind.buffer_length}", []
    # direct
    raw = page_encoding.direct.encoding
    type_url = ""
    try:
        anym = any_pb2.Any()
        anym.ParseFromString(raw)
        type_url = anym.type_url
        if not type_url.endswith("PageLayout"):
            return "Unknown Any", type_url, []
        pl = e1.PageLayout()
        pl.ParseFromString(anym.value)
    except Exception:
        # Try parsing directly as PageLayout
        try:
            pl = e1.PageLayout()
            pl.ParseFromString(raw)
        except Exception:
            return "Parse failed", "", []

    which = pl.WhichOneof("layout")
    if which is None:
        # A PageLayout from a newer Lance: the Any parses (unknown fields are ignored) but no layout
        # arm this build knows about is set. Naming the format is the difference between "the viewer
        # is broken" and "this file is newer than the viewer".
        return "Unknown layout", f"{type_url or 'bare PageLayout'} (unsupported by this build)", []
    layout_label = LAYOUT_LABELS.get(which, which)
    compressions = []
    encoding_desc = ""

    if which == "mini_block_layout":
        mb = pl.mini_block_layout
        compressions = _extract_compression_attr(mb)
        encoding_desc = (f"items={mb.num_items} buffers={mb.num_buffers}"
                         + (f" dict_items={mb.num_dictionary_items}" if mb.num_dictionary_items else "")
                         + (f" large_chunk" if mb.has_large_chunk else ""))
    elif which == "constant_layout":
        cl = pl.constant_layout
        compressions = _extract_compression_attr(cl)
        iv = cl.inline_value
        if hasattr(iv, 'WhichOneof'):
            encoding_desc = f"inline_value={iv.WhichOneof('value') or 'none'}"
        else:
            encoding_desc = "constant"
    elif which == "full_zip_layout":
        fz = pl.full_zip_layout
        compressions = _extract_compression_attr(fz)
        encoding_desc = f"bits_per_value={fz.bits_per_value} num_items={fz.num_items}"
    elif which == "blob_layout":
        encoding_desc = "blob external descriptor"

    return layout_label, encoding_desc, compressions


def _decode_file_schema(buf, gbo_off, n_gbuf):
    """Decode the FileDescriptor from global buffer 0 to extract the column schema.
    Returns (columns_schema list, err or None).
    """
    if n_gbuf == 0:
        return [], None
    try:
        gpos, gsize = struct.unpack('<QQ', buf[gbo_off:gbo_off + 16])
    except struct.error:
        return [], None
    if gpos + gsize > len(buf):
        return [], None
    try:
        fd = file_pb2.FileDescriptor()
        fd.ParseFromString(buf[gpos:gpos + gsize])
    except Exception:
        return [], None
    cols = []
    for fld in fd.schema.fields:
        cols.append({
            "name": fld.name,
            "logical_type": fld.logical_type,
            "parent_id": fld.parent_id,
            "encoding": fld.encoding,
            "nullable": fld.nullable,
        })
    return cols, None


def decode_datafile(buf):
    """Decode a .lance data file's bytes. Returns (info dict, err or None).
    buf is the already-read bytes."""
    n = len(buf)
    if n < FOOTER_SIZE:
        return None, f"File too small ({n} bytes)"

    # ---- footer ----
    # Everything below slices buf before unpacking so that a SparseBytes stand-in (range-read
    # object storage) works unchanged: struct.unpack_from would need a real buffer.
    try:
        off_cm0, off_cmo, off_gbo = struct.unpack('<QQQ', buf[n - FOOTER_SIZE:n - FOOTER_SIZE + 24])
        n_gbuf, n_cols = struct.unpack('<II', buf[n - FOOTER_SIZE + 24:n - FOOTER_SIZE + 32])
        major, minor = struct.unpack('<HH', buf[n - FOOTER_SIZE + 32:n - FOOTER_SIZE + 36])
        magic = buf[n - 4:n]
    except struct.error:
        return None, "Footer parse failed"
    if magic != b"LANC":
        return None, f"magic mismatch: {magic!r}"

    footer_info = {
        "column0_offset": off_cm0,
        "cmo_table_offset": off_cmo,
        "gbo_table_offset": off_gbo,
        "global_buffers": n_gbuf,
        "columns": n_cols,
        "major_version": major,
        "minor_version": minor,
        "file_size": n,
    }

    # ---- column metadata ----
    columns = []
    for i in range(n_cols):
        try:
            pos, size = struct.unpack('<QQ', buf[off_cmo + i * 16:off_cmo + i * 16 + 16])
        except struct.error:
            columns.append({"error": "CMO table out of range"})
            continue
        cm_raw = buf[pos:pos + size]
        try:
            cm = file2_pb2.ColumnMetadata()
            cm.ParseFromString(cm_raw)
        except Exception as e:
            columns.append({"error": f"column {i} parse failed: {e}"})
            continue

        pages = []
        for pi, pg in enumerate(cm.pages):
            layout_label, enc_desc, comp = _page_layout_summary(pg.encoding)
            page_info = {
                "index": pi,
                "length": pg.length,
                "priority": pg.priority,
                "num_buffers": len(pg.buffer_offsets),
                "buffer_offsets": list(pg.buffer_offsets),
                "buffer_sizes": list(pg.buffer_sizes),
                "layout": layout_label,
                "encoding": enc_desc,
                "compression": comp,
            }
            pages.append(page_info)

        columns.append({
            "index": i,
            "metadata_offset": pos,
            "metadata_size": size,
            "num_pages": len(cm.pages),
            "pages": pages,
        })

    # ---- global buffer table ----
    gbufs = []
    if n_gbuf > 0 and off_gbo + n_gbuf * 16 <= n:
        for i in range(n_gbuf):
            gpos, gsize = struct.unpack('<QQ', buf[off_gbo + i * 16:off_gbo + i * 16 + 16])
            gbufs.append({"index": i, "offset": gpos, "size": gsize})

    schema, _ = _decode_file_schema(buf, off_gbo, n_gbuf)

    return {
        "footer": footer_info,
        "columns": columns,
        "global_buffers": gbufs,
        "schema": schema,
    }, None


if __name__ == "__main__":
    import json
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("datafile", help="path to the .lance data file")
    args = ap.parse_args()
    info, err = decode_datafile(Path(args.datafile).read_bytes())
    if err:
        print("Error:", err)
        sys.exit(1)
    print(json.dumps(info, ensure_ascii=False, indent=2))
