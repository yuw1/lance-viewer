"""Language switching must re-render the tab body, not only the static chrome.

The tab content is generated HTML without data-i18n markers, so it used to stay in the previous
language when the header and tab labels switched. The harness loads tools.js in a Node VM and
asserts setLang re-renders via loadCurrentTab once a dataset is open (and not at boot).
"""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "js" / "i18n_test.js"


def test_language_switch_rerenders_the_tab_body():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required for the i18n harness")

    proc = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, (
        "language switching no longer re-renders the tab body\n" + proc.stdout + proc.stderr
    )