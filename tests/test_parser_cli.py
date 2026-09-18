"""
CLI/subprocess-level integration tests for parse_html.py.

Mirrors tests/test_renderer.py's subprocess-driven style: runs
parse_html.py as a real subprocess against JSON input files and asserts on
stdout/exit behavior, not the parse_html() function directly (see
tests/test_parser.py for that).
"""

import glob
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PARSER_SCRIPT = ROOT / "parse_html.py"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "parser"


@pytest.fixture(autouse=True)
def cleanup_parsed_files():
    yield
    for f in glob.glob(str(ROOT / "parsed_page_*.json")):
        os.remove(f)


def run_parser(args, cwd=None):
    cmd = [sys.executable, str(PARSER_SCRIPT)] + args
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30, cwd=cwd or ROOT)
    return proc


def write_step1_json(tmp_path, name, payload):
    p = tmp_path / name
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def test_valid_step1_input_produces_correct_output(tmp_path):
    html = (FIXTURES / "full_page.html").read_text(encoding="utf-8")
    step1 = {
        "ok": True,
        "url": "https://example.com/page",
        "final_url": "https://example.com/page",
        "status_code": 200,
        "title": "ignored",
        "html": html,
        "error": None,
    }
    input_file = write_step1_json(tmp_path, "step1.json", step1)

    proc = run_parser([str(input_file)])
    assert proc.returncode == 0, proc.stderr
    lines = [l for l in proc.stdout.strip().splitlines() if l.strip()]
    assert len(lines) == 1
    result = json.loads(lines[0])
    assert result["ok"] is True
    assert result["source_url"] == "https://example.com/page"
    assert result["title"] == "Full Page Fixture"


def test_step1_ok_false_yields_missing_html(tmp_path):
    step1 = {
        "ok": False,
        "url": "http://bad",
        "final_url": None,
        "status_code": None,
        "title": None,
        "html": None,
        "error": {"type": "invalid_url", "message": "bad"},
    }
    input_file = write_step1_json(tmp_path, "step1_fail.json", step1)

    proc = run_parser([str(input_file)])
    lines = [l for l in proc.stdout.strip().splitlines() if l.strip()]
    assert len(lines) == 1
    result = json.loads(lines[0])
    assert result["ok"] is False
    assert result["error"]["type"] == "missing_html"


def test_malformed_json_input_is_structured_error(tmp_path):
    bad_file = tmp_path / "bad.json"
    bad_file.write_text("{not valid json", encoding="utf-8")

    proc = run_parser([str(bad_file)])
    lines = [l for l in proc.stdout.strip().splitlines() if l.strip()]
    assert len(lines) == 1, f"stderr: {proc.stderr}"
    result = json.loads(lines[0])
    assert result["ok"] is False
    assert result["error"]["type"] == "invalid_input"
    assert "Traceback" not in proc.stdout


def test_missing_input_file(tmp_path):
    proc = run_parser([str(tmp_path / "does_not_exist.json")])
    lines = [l for l in proc.stdout.strip().splitlines() if l.strip()]
    assert len(lines) == 1
    result = json.loads(lines[0])
    assert result["ok"] is False
    assert result["error"]["type"] == "invalid_input"


def test_invalid_config_bad_parser_key(tmp_path):
    html = (FIXTURES / "full_page.html").read_text(encoding="utf-8")
    step1 = {"ok": True, "url": "https://example.com", "html": html, "error": None}
    input_file = write_step1_json(tmp_path, "step1.json", step1)

    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({"parser": {"not_a_real_key": True}}), encoding="utf-8")

    proc = run_parser([str(input_file), "--config", str(config_file)])
    assert proc.returncode != 0
    assert "unknown parser config key" in proc.stderr


def test_output_files_auto_increment_and_no_overwrite():
    html = (FIXTURES / "full_page.html").read_text(encoding="utf-8")
    step1 = {"ok": True, "url": "https://example.com", "html": html, "error": None}
    input_file = ROOT / "tests" / "fixtures" / "parser" / "_tmp_step1_for_cli_test.json"
    input_file.write_text(json.dumps(step1), encoding="utf-8")
    try:
        for f in glob.glob(str(ROOT / "parsed_page_*.json")):
            os.remove(f)
        proc1 = run_parser([str(input_file)])
        proc2 = run_parser([str(input_file)])
        assert proc1.returncode == 0 and proc2.returncode == 0
        assert (ROOT / "parsed_page_1.json").exists()
        assert (ROOT / "parsed_page_2.json").exists()
        content1 = (ROOT / "parsed_page_1.json").read_text(encoding="utf-8")
        content2 = (ROOT / "parsed_page_2.json").read_text(encoding="utf-8")
        assert content1 == content2
    finally:
        input_file.unlink(missing_ok=True)


# --- --answer-questions (CLI-level; qa.run() itself is unit-tested elsewhere) ---
# These run the real subprocess with no anthropic install / API key required.
# --answer-questions is gated on the input having gone through --detect and been
# classified APPLICATION (see parse_html.qa_gate_error); the resume/API-key checks
# below only run once that gate is satisfied, via a step1 JSON with "status": "APPLICATION"
# (mimicking render-url --detect's output). A QA failure must never crash the process or
# discard the deterministic parse.

def _detected_application_step1(html):
    return {
        "ok": True, "url": "https://example.com", "html": html, "error": None,
        "status": "APPLICATION", "reason": "application_form_detected",
    }


def test_answer_questions_missing_resume_sets_qa_error_not_crash(tmp_path):
    html = (FIXTURES / "full_page.html").read_text(encoding="utf-8")
    input_file = write_step1_json(tmp_path, "step1.json", _detected_application_step1(html))

    proc = run_parser([
        str(input_file),
        "--answer-questions",
        "--resume", str(tmp_path / "does_not_exist.md"),
        "--qa-api-key", "fake-key",
    ])
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout.strip())
    assert result["ok"] is True
    assert "resume file not found" in result["qa_error"]
    assert "application_questions" not in result["data"]


def test_answer_questions_missing_api_key_sets_qa_error(tmp_path):
    html = (FIXTURES / "full_page.html").read_text(encoding="utf-8")
    input_file = write_step1_json(tmp_path, "step1.json", _detected_application_step1(html))
    resume_file = tmp_path / "resume.md"
    resume_file.write_text("# Jane Doe", encoding="utf-8")

    env = os.environ.copy()
    env.pop("ANTHROPIC_API_KEY", None)
    cmd = [sys.executable, str(PARSER_SCRIPT), str(input_file), "--answer-questions", "--resume", str(resume_file)]
    # cwd=tmp_path (not ROOT): qa.run() calls load_dotenv(".env") relative to cwd, and a real
    # .env in the repo root (if present) must not leak an API key into this test.
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30, cwd=tmp_path, env=env)
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout.strip())
    assert result["ok"] is True
    assert "Missing API key" in result["qa_error"]


def test_answer_questions_off_by_default(tmp_path):
    html = (FIXTURES / "full_page.html").read_text(encoding="utf-8")
    input_file = write_step1_json(tmp_path, "step1.json", _detected_application_step1(html))

    proc = run_parser([str(input_file)])
    result = json.loads(proc.stdout.strip())
    assert "qa_error" not in result


def test_answer_questions_without_detect_status_is_blocked(tmp_path):
    """Input that was never run through --detect (no "status" field) must not reach the LLM,
    even with valid --resume/--qa-api-key -- --answer-questions requires --detect."""
    html = (FIXTURES / "full_page.html").read_text(encoding="utf-8")
    step1 = {"ok": True, "url": "https://example.com", "html": html, "error": None}
    input_file = write_step1_json(tmp_path, "step1.json", step1)
    resume_file = tmp_path / "resume.md"
    resume_file.write_text("# Jane Doe", encoding="utf-8")

    proc = run_parser([
        str(input_file), "--answer-questions", "--resume", str(resume_file), "--qa-api-key", "fake-key",
    ])
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout.strip())
    assert result["ok"] is True
    assert "requires --detect" in result["qa_error"]
    assert "application_questions" not in result["data"]


def test_answer_questions_skipped_when_parse_itself_failed(tmp_path):
    """ok=false (e.g. Step 1 had no html) must never trigger a QA call, regardless of status."""
    step1 = {
        "ok": False, "url": "http://bad", "html": None,
        "error": {"type": "invalid_url", "message": "bad"}, "status": "APPLICATION",
    }
    input_file = write_step1_json(tmp_path, "step1_fail.json", step1)

    proc = run_parser([str(input_file), "--answer-questions", "--qa-api-key", "fake-key"])
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout.strip())
    assert result["ok"] is False
    assert "qa_error" not in result


def test_answer_questions_non_application_status_is_blocked(tmp_path):
    """A page --detect classified as something other than APPLICATION must not reach the LLM
    even if (unusually) html/data are still present."""
    html = (FIXTURES / "full_page.html").read_text(encoding="utf-8")
    step1 = {
        "ok": True, "url": "https://example.com", "html": html, "error": None,
        "status": "CAPTCHA", "reason": "captcha_detected",
    }
    input_file = write_step1_json(tmp_path, "step1.json", step1)
    resume_file = tmp_path / "resume.md"
    resume_file.write_text("# Jane Doe", encoding="utf-8")

    proc = run_parser([
        str(input_file), "--answer-questions", "--resume", str(resume_file), "--qa-api-key", "fake-key",
    ])
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout.strip())
    assert result["ok"] is True
    assert "classified as CAPTCHA" in result["qa_error"]
    assert "application_questions" not in result["data"]
    assert "application_questions" not in result["data"]


def test_selector_cli_flag(tmp_path):
    html = (FIXTURES / "scoped_content.html").read_text(encoding="utf-8")
    step1 = {"ok": True, "url": "https://example.com", "html": html, "error": None}
    input_file = write_step1_json(tmp_path, "step1.json", step1)

    proc = run_parser([str(input_file), "--selector", "#main-content"])
    result = json.loads(proc.stdout.strip())
    assert result["ok"] is True
    assert result["selector_matched"] is True
    assert result["data"]["headings"] == [{"level": 2, "text": "Main Content Heading"}]
