"""Frontend list limits: manifest JSON tree, timeline window, storage cap, version dropdown.

The harness loads the real render modules in a Node VM with a DOM stub that can be clicked, so it
checks how many nodes get built rather than just what the HTML looks like. Skipped where Node is
missing; every GitHub runner ships it.
"""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "js" / "render_limits_test.js"


def test_frontend_caps_the_large_lists():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required for the frontend limits harness")

    proc = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, (
        "a list renderer stopped capping its output\n" + proc.stdout + proc.stderr
    )