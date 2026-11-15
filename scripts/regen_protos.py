#!/usr/bin/env python3
"""Recompile the protobuf bindings from the Lance repo, and record what they were built from.

Lance's metadata format is protobuf: manifest, transaction, data file, encodings. The generated
`*_pb2.py` files are checked in because users install the viewer without a Lance checkout — but
nothing in them says *which* Lance wrote them. That matters when a data file shows up as
`Unknown layout`: is the file newer than the bindings, or is something broken?

So every (re)generation also writes `protos/VERSION.json` with the Lance tag/commit, the protobuf
version the code was generated with, the source `.proto` hashes and the generated file hashes. A test
checks the last part, which catches hand-edited or half-committed bindings.

Usage:
    python3 regen_protos.py --lance-repo /path/to/lance     # recompile + stamp
    python3 regen_protos.py --stamp-only                    # stamp what is already checked in
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
# protos output to inside the package (src/lance_viewer/protos)
SRC = HERE.parent / "src"
OUT = SRC / "lance_viewer" / "protos"
STAMP_NAME = "VERSION.json"

# Protos to compile (including the dependency chain)
PROTO_FILES = [
    "table.proto", "fragment_metadata.proto", "file.proto",
    "clustering.proto", "transaction.proto", "index.proto",
    "index_old.proto", "ann.proto", "table_identifier.proto",
    "rowids.proto", "filtered_read.proto", "encodings_v2_0.proto",
    "encodings_v2_1.proto", "encodings_v2_3.proto", "file2.proto",
    "cache_diagnostics.proto",
]


def sha256(path):
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def git(lance_repo, *args):
    """Best-effort git metadata; a tarball checkout simply yields nulls."""
    try:
        out = subprocess.run(["git", "-C", str(lance_repo), *args],
                             capture_output=True, text=True, check=True)
        return out.stdout.strip() or None
    except (OSError, subprocess.CalledProcessError):
        return None


def generated_with():
    """The protobuf version recorded in the generated files' header (protoc writes it)."""
    for path in sorted(OUT.glob("*_pb2.py")):
        try:
            for line in path.read_text(encoding="utf-8").splitlines()[:12]:
                if line.startswith("# Protobuf Python Version:"):
                    return line.split(":", 1)[1].strip()
        except OSError:
            continue
    return None


def source_hashes(protos_dir):
    if not protos_dir or not protos_dir.is_dir():
        return None
    hashes = {}
    for name in PROTO_FILES:
        source = protos_dir / name
        if source.is_file():
            hashes[name] = sha256(source)
    return hashes or None


def write_stamp(protos_dir=None):
    bindings = {p.name: sha256(p) for p in sorted(OUT.glob("*_pb2.py"))}
    if not bindings:
        sys.exit(f"No generated bindings under {OUT}; nothing to stamp")

    lance_repo = protos_dir.parent if protos_dir else None
    stamp = {
        "lance": {
            "tag": git(lance_repo, "describe", "--tags", "--always") if lance_repo else None,
            "commit": git(lance_repo, "rev-parse", "HEAD") if lance_repo else None,
        },
        "python_protobuf": generated_with(),
        "sources": source_hashes(protos_dir),
        "bindings": bindings,
    }

    # Re-stamping an unchanged tree must not churn the timestamp: compare everything but
    # generated_at and keep the previous value when nothing else moved.
    try:
        previous = json.loads((OUT / STAMP_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        previous = {}
    unchanged = {k: v for k, v in previous.items() if k != "generated_at"} == stamp
    stamp = {
        "generated_at": (previous.get("generated_at")
                         or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        if unchanged else datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        **stamp,
    }
    (OUT / STAMP_NAME).write_text(json.dumps(stamp, indent=2) + "\n", encoding="utf-8")
    return stamp


def compile_protos(protos_dir):
    try:
        from grpc_tools import protoc
    except ImportError:
        sys.exit('Missing grpcio-tools: install the proto extra, e.g. pip install -e ".[proto]"')
    import grpc_tools

    stdout = os.path.join(grpc_tools.__path__[0], '_proto')

    # Compile into a temp dir (under src/lance_viewer, so generated files sit at the same level as the package)
    tmp = SRC / "lance_viewer" / "protos_new"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir()

    args_l = ["protoc", f"-I{protos_dir}", f"-I{stdout}",
              f"--python_out={tmp}", f"--descriptor_set_out={tmp}/lance.desc"] + PROTO_FILES
    rc = protoc.main(args_l)
    if rc != 0:
        sys.exit(f"protoc compile failed (rc={rc})")

    # Replace (keep __init__.py so protos is a package)
    shutil.rmtree(OUT)
    shutil.move(str(tmp), str(OUT))
    (OUT / "__init__.py").write_text(
        "\"\"\"Lance protobuf bindings (generated artifact; recompiled by scripts/regen_protos.py).\"\"\"\n"
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lance-repo", help="Lance source repo path (containing protos/)")
    ap.add_argument("--stamp-only", action="store_true",
                    help="do not compile; just write VERSION.json for the checked-in bindings")
    args = ap.parse_args()

    if args.stamp_only:
        if not OUT.is_dir():
            sys.exit(f"Bindings directory does not exist: {OUT}")
        protos_dir = Path(args.lance_repo) / "protos" if args.lance_repo else None
        stamp = write_stamp(protos_dir)
        print(f"✅ Stamped {OUT / STAMP_NAME}")
        print(f"   bindings: {len(stamp['bindings'])}, sources: {len(stamp['sources'] or {})}")
        return

    if not args.lance_repo:
        ap.error("--lance-repo is required unless --stamp-only is given")

    protos_dir = Path(args.lance_repo) / "protos"
    if not os.path.isdir(protos_dir):
        sys.exit(f"Lance protos directory does not exist: {protos_dir}")

    compile_protos(protos_dir)
    stamp = write_stamp(protos_dir)

    print(f"✅ Updated pb2 bindings under {OUT}")
    print(f"   Source proto: {protos_dir}")
    print(f"   Stamped: {OUT / STAMP_NAME} "
          f"(lance {stamp['lance']['tag'] or 'unknown'}, {len(stamp['bindings'])} bindings)")


if __name__ == "__main__":
    main()