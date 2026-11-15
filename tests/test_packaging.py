"""Packaging guard: every shipped static asset must be declared in package-data.

A missing glob here is invisible in development (tests and `-e .` installs read the source tree),
but a real `pip install` ships only what package-data lists, so favicons silently 404.
"""
from fnmatch import fnmatch
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_package_data_covers_every_static_asset():
    tomllib = pytest.importorskip("tomllib")  # stdlib on 3.11+; skipped on 3.10
    cfg = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    patterns = cfg["tool"]["setuptools"]["package-data"]["lance_viewer"]

    static = ROOT / "src" / "lance_viewer" / "static"
    missing = []
    for f in static.rglob("*"):
        if f.is_file():
            rel = "static/" + f.relative_to(static).as_posix()
            if not any(fnmatch(rel, pat) for pat in patterns):
                missing.append(rel)
    assert not missing, "not matched by [tool.setuptools.package-data]: " + ", ".join(missing)