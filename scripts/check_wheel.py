#!/usr/bin/env python3
"""Assert a built wheel actually carries everything the viewer serves at runtime.

Package-data globs fail in a way no ordinary test notices: `pip install -e .` and the test suite
both read the source tree, so an asset left out of the wheel only breaks a real install. This script
inspects the artifact itself — what `pip install lance-viewer` unpacks — instead of pyproject.

Usage:
    python scripts/check_wheel.py dist/lance_viewer-*.whl

Build from a clean tree: a leftover `src/*.egg-info/SOURCES.txt` makes setuptools re-include files
the current config no longer lists, so a stale build can hide exactly the bug this checks for.
"""
import argparse
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src" / "lance_viewer"


def expected_assets():
    """Every file under the package that must be in the wheel, as wheel paths."""
    out = set()
    for sub in ("static", "protos"):
        for path in (PACKAGE / sub).rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts:
                out.add("lance_viewer/" + path.relative_to(PACKAGE).as_posix())
    return out


def main():
    ap = argparse.ArgumentParser(description="verify a built wheel ships every runtime asset")
    ap.add_argument("wheels", nargs="+", help="wheel file(s) to inspect")
    args = ap.parse_args()

    names = set()
    entry_points = ""
    for wheel in args.wheels:
        with zipfile.ZipFile(wheel) as zf:
            wheel_names = zf.namelist()
            names |= set(wheel_names)
            for name in wheel_names:
                if name.endswith(".dist-info/entry_points.txt"):
                    entry_points += zf.read(name).decode("utf-8")

    problems = []

    missing = sorted(expected_assets() - names)
    if missing:
        problems.append("missing from the wheel:\n    " + "\n    ".join(missing))

    leaked = sorted(n for n in names if n.startswith(("tests/", "screenshots/", "examples/")))
    if leaked:
        problems.append("development-only paths shipped in the wheel: " + ", ".join(leaked))

    if "lance-viewer" not in entry_points:
        problems.append("the lance-viewer console script is not declared")

    if not any(n.startswith("lance_viewer/") and n.endswith(".py") for n in names):
        problems.append("no python modules found in the wheel")

    if problems:
        print("wheel check failed:", file=sys.stderr)
        for problem in problems:
            print("  - " + problem, file=sys.stderr)
        return 1

    print(f"ok: {len(names)} entries; static/protos assets and the console script are present")
    print(f"    inspected: {', '.join(str(Path(w).name) for w in args.wheels)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())