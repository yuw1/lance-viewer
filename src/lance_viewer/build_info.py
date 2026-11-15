"""Build provenance: the package version and where the protobuf bindings came from.

The bindings are generated artifacts (see scripts/regen_protos.py). `protos/VERSION.json` records the
Lance tag/commit, the protobuf version used for generation and the hashes of every generated file.
This module turns that into something a user can quote in a bug report: `lance-viewer --version`
or `GET /api/version`.
"""
import json
import platform
from pathlib import Path

from . import __version__

STAMP_PATH = Path(__file__).resolve().parent / "protos" / "VERSION.json"


def proto_stamp():
    """The recorded provenance, or None for a checkout that predates stamping."""
    try:
        return json.loads(STAMP_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _pylance_version():
    try:
        import importlib.metadata as metadata
        return metadata.version("pylance")
    except Exception:
        return None


def version_info():
    """A JSON-serialisable description of this install, safe to expose over the local API."""
    import google.protobuf

    stamp = proto_stamp() or {}
    lance = stamp.get("lance") or {}
    return {
        "package": __version__,
        "python": platform.python_version(),
        "protobuf": google.protobuf.__version__,
        "pylance": _pylance_version(),
        "protos": {
            "generated_at": stamp.get("generated_at"),
            "lance": {"tag": lance.get("tag"), "commit": lance.get("commit")},
            "python_protobuf": stamp.get("python_protobuf"),
            "bindings": len(stamp.get("bindings") or {}),
        },
    }


def version_text():
    """Human-readable form for `--version`."""
    info = version_info()
    protos = info["protos"]
    lance = protos["lance"]
    origin = lance["tag"] or "unknown"
    if lance["commit"]:
        origin += f" @ {lance['commit'][:8]}"
    return (
        f"lance-viewer {info['package']}\n"
        f"  python {info['python']}, protobuf {info['protobuf']}, "
        f"pylance {info['pylance'] or 'n/a'}\n"
        f"  proto bindings: lance {origin}, "
        f"generated {protos['generated_at'] or 'unknown'} "
        f"({protos['bindings']} files, protobuf {protos['python_protobuf'] or 'unknown'})"
    )