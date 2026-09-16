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


def test_selector_cli_flag(tmp_path):
    html = (FIXTURES / "scoped_content.html").read_text(encoding="utf-8")
    step1 = {"ok": True, "url": "https://example.com", "html": html, "error": None}
    input_file = write_step1_json(tmp_path, "step1.json", step1)

    proc = run_parser([str(input_file), "--selector", "#main-content"])
    result = json.loads(proc.stdout.strip())
    assert result["ok"] is True
    assert result["selector_matched"] is True
    assert result["data"]["headings"] == [{"level": 2, "text": "Main Content Heading"}]
