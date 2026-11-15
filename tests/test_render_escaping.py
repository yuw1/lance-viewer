"""Frontend escaping: dataset-controlled text must never reach the page as live HTML.

The harness loads the real render modules in a Node VM and feeds them hostile names/values. It is
skipped where Node is unavailable; every GitHub runner ships it.
"""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "js" / "render_escape_test.js"


def test_frontend_escapes_dataset_controlled_text():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required for the frontend escaping harness")

    proc = subprocess.run(
        [node, str(HARNESS)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, (
        "a renderer emitted dataset-controlled text unescaped\n"
        + proc.stdout + proc.stderr
    )