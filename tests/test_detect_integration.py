"""
Integration tests for the --detect flag on render_url.py and render_and_parse.py.

Runs the real CLIs as subprocesses (Playwright + Chromium) against a local
HTTP server serving the detector fixture pages, using a low-latency detector
config (tests/fixtures/detector_config.json) so the BOT_CHALLENGE retry loop
stays fast.
"""

import glob
import http.server
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
RENDER_SCRIPT = ROOT / "render_url.py"
RENDER_AND_PARSE_SCRIPT = ROOT / "render_and_parse.py"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
DETECTOR_CONFIG = FIXTURES / "detector_config.json"


class _Server:
    def __init__(self, directory):
        self.directory = str(directory)
        handler = lambda *a, **kw: http.server.SimpleHTTPRequestHandler(
            *a, directory=self.directory, **kw
        )
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def url(self, path):
        return f"http://127.0.0.1:{self.port}/{path}"

    def stop(self):
        self.httpd.shutdown()


@pytest.fixture(scope="module")
def server():
    s = _Server(FIXTURES)
    yield s
    s.stop()


@pytest.fixture(autouse=True)
def cleanup_pipeline_files():
    yield
    for pattern in ("rendered_page_*.json", "parsed_page_*.json"):
        for f in glob.glob(str(ROOT / pattern)):
            os.remove(f)


def run(cmd):
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60, cwd=ROOT)
    assert proc.stdout.strip(), f"empty stdout; stderr={proc.stderr}"
    lines = [l for l in proc.stdout.strip().splitlines() if l.strip()]
    assert len(lines) == 1, f"expected exactly one stdout line, got: {proc.stdout!r}"
    return json.loads(lines[0]), proc


def run_render(url):
    return run([
        sys.executable, str(RENDER_SCRIPT), url,
        "--detect", "--config", str(DETECTOR_CONFIG),
    ])


def run_render_and_parse(url):
    return run([
        sys.executable, str(RENDER_AND_PARSE_SCRIPT), url,
        "--detect", "--config", str(DETECTOR_CONFIG),
    ])


def test_render_url_application_form(server):
    result, proc = run_render(server.url("application_form.html"))
    assert result["ok"] is True, proc.stderr
    assert result["status"] == "APPLICATION"
    assert result["detector"]["form_detected"] is True
    assert result["html"] is not None
    assert "application-form" in result["html"]
    assert result["form"]["file_inputs"] == 1


def test_render_url_captcha_skips_html(server):
    result, proc = run_render(server.url("captcha_page.html"))
    assert result["ok"] is True, proc.stderr
    assert result["status"] == "CAPTCHA"
    assert result["detector"]["captcha"] is True
    assert result["html"] is None


def test_render_url_login_wall(server):
    result, proc = run_render(server.url("login_page.html"))
    assert result["ok"] is True, proc.stderr
    assert result["status"] == "LOGIN"
    assert result["detector"]["login"] is True
    assert result["html"] is None


def test_render_url_closed_job(server):
    result, proc = run_render(server.url("closed_job.html"))
    assert result["ok"] is True, proc.stderr
    assert result["status"] == "CLOSED_JOB"
    assert result["detector"]["closed_job"] is True
    assert result["html"] is None


def test_render_url_bot_challenge(server):
    result, proc = run_render(server.url("bot_challenge.html"))
    assert result["ok"] is True, proc.stderr
    assert result["status"] == "BOT_CHALLENGE"
    assert result["detector"]["bot_challenge"] is True
    assert result["html"] is None


def test_render_url_static_page_is_no_form(server):
    result, proc = run_render(server.url("static.html"))
    assert result["ok"] is True, proc.stderr
    assert result["status"] == "NO_FORM"
    assert result["html"] is None


def test_render_url_without_detect_flag_is_unaffected(server):
    """--detect must be opt-in: default behavior stays exactly as before."""
    result, proc = run([sys.executable, str(RENDER_SCRIPT), server.url("captcha_page.html")])
    assert result["ok"] is True, proc.stderr
    assert "status" not in result
    assert result["html"] is not None


def test_render_and_parse_application_flows_through(server):
    result, proc = run_render_and_parse(server.url("application_form.html"))
    assert result["ok"] is True, proc.stderr
    assert result["status"] == "APPLICATION"
    assert result["data"] is not None
    assert "Senior Software Engineer" in result["data"]["text"]


def test_render_and_parse_captcha_skips_parsing(server):
    result, proc = run_render_and_parse(server.url("captcha_page.html"))
    assert result["ok"] is True, proc.stderr
    assert result["status"] == "CAPTCHA"
    assert result["data"] is None


def test_render_and_parse_login_skips_parsing(server):
    result, proc = run_render_and_parse(server.url("login_page.html"))
    assert result["ok"] is True, proc.stderr
    assert result["status"] == "LOGIN"
    assert result["data"] is None
