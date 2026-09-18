"""
CLI-level tests for render_and_parse.py's --answer-questions / --detect gate.

--answer-questions is only allowed to call the LLM on a page --detect classified as
APPLICATION (see parse_html.qa_gate_error). render_and_parse.py enforces this early,
before even launching Chromium, when --answer-questions is passed without --detect --
so these tests run as fast subprocess checks with no browser/network involved.
"""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "render_and_parse.py"


def run(args, cwd=None):
    cmd = [sys.executable, str(SCRIPT)] + args
    return subprocess.run(cmd, capture_output=True, text=True, timeout=30, cwd=cwd or ROOT)


def test_answer_questions_without_detect_is_rejected_before_rendering(tmp_path):
    # cwd=tmp_path, not ROOT: a local config.json with "detect": true would otherwise
    # supply --detect implicitly and mask what this test is checking.
    proc = run(["https://example.com", "--answer-questions"], cwd=tmp_path)
    assert proc.returncode == 1, proc.stdout
    result = json.loads(proc.stdout.strip())
    assert result["ok"] is False
    assert result["error"]["type"] == "invalid_input"
    assert "requires --detect" in result["error"]["message"]


def test_answer_questions_with_detect_passes_the_early_gate(tmp_path):
    """With --detect also passed, the early gate must not block -- any failure past this
    point (network, browser, resolving example.com) is unrelated to the gate itself."""
    proc = run(["https://example.com", "--answer-questions", "--detect"], cwd=tmp_path)
    if proc.returncode == 1:
        result = json.loads(proc.stdout.strip())
        assert "requires --detect" not in json.dumps(result)


def test_missing_url_error_takes_priority_over_gate(tmp_path):
    proc = run(["--answer-questions"], cwd=tmp_path)
    assert proc.returncode == 1, proc.stdout
    result = json.loads(proc.stdout.strip())
    assert result["ok"] is False
    assert result["error"]["type"] == "invalid_input"
    assert "No URL provided" in result["error"]["message"]
