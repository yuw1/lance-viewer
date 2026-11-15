"""Provenance stamp: the checked-in bindings must be described by protos/VERSION.json.

The stamp is what answers "which Lance wrote these bindings?" when a file uses a format this build
does not know. Keeping it under test makes the answer trustworthy: a hand-edited or half-committed
binding shows up as a hash mismatch instead of drifting silently.
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from lance_viewer import build_info

ROOT = Path(__file__).resolve().parents[1]
PROTOS = ROOT / "src" / "lance_viewer" / "protos"
STAMP = PROTOS / "VERSION.json"


def _sha(path):
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _stamp():
    return json.loads(STAMP.read_text(encoding="utf-8"))


def test_stamp_lists_exactly_the_checked_in_bindings():
    checked_in = sorted(p.name for p in PROTOS.glob("*_pb2.py"))
    assert sorted(_stamp()["bindings"]) == checked_in


def test_stamp_hashes_match_the_files():
    stamp = _stamp()
    stale = [name for name, digest in stamp["bindings"].items()
             if _sha(PROTOS / name) != digest]
    assert not stale, (
        "protos/VERSION.json is stale for " + ", ".join(stale)
        + "; rerun scripts/regen_protos.py --stamp-only"
    )


def test_stamp_records_provenance_keys():
    stamp = _stamp()
    assert set(stamp) >= {"generated_at", "lance", "python_protobuf", "sources", "bindings"}
    assert set(stamp["lance"]) == {"tag", "commit"}


def test_version_info_surfaces_the_stamp():
    info = build_info.version_info()
    assert info["package"]
    assert info["protos"]["bindings"] == len(list(PROTOS.glob("*_pb2.py")))
    assert set(info["protos"]["lance"]) == {"tag", "commit"}


def test_version_flag_prints_the_binding_origin():
    proc = subprocess.run([sys.executable, "-m", "lance_viewer.server", "--version"],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    assert "proto bindings:" in proc.stdout
    assert "lance-viewer" in proc.stdout