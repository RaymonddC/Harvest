import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_capture_worklet_keeps_posting_chunks_after_the_first():
    # Regression: the buffer was re-created with the length of the one just sent (now 0), so the
    # microphone produced a single chunk and the agent never heard the farmer.
    out = subprocess.run(["node", str(pathlib.Path(__file__).with_name("worklet_check.mjs")),
                          str(ROOT / "web/js/audio-worklets.js")],
                         capture_output=True, text=True, check=True).stdout
    assert int(out.strip()) >= 90  # 4 s at 25 chunks a second
