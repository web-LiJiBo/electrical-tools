"""Exercise the shipped browser scripts without adding a browser dependency."""
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.skipif(shutil.which('node') is None, reason='Frontend regression requires Node.js 18+')
def test_scene_linkage_javascript_behaviors():
    root = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [shutil.which('node'), '--test', 'tests/test_scenario_linkage_frontend.cjs'],
        cwd=root, capture_output=True, encoding='utf-8', timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
