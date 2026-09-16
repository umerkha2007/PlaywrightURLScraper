"""
End-to-end integration test: render_url.py -> JSON file -> parse_html.py ->
structured JSON, both run as real subprocesses, proving the two stages
compose correctly.
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
PARSER_SCRIPT = ROOT / "parse_html.py"
FIXTURES = Path(__file__).resolve().parent / "fixtures"


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


def next_free_prefix_path(prefix):
    n = 1
    while (ROOT / f"{prefix}_{n}.json").exists():
        n += 1
    return ROOT / f"{prefix}_{n}.json"


def test_js_rendered_content_flows_through_pipeline(server):
    render_result, render_proc = run(
        [sys.executable, str(RENDER_SCRIPT), server.url("js_render.html")]
    )
    assert render_result["ok"] is True
    assert "INJECTED_BY_JS" in render_result["html"]

    step1_files = sorted(ROOT.glob("rendered_page_*.json"))
    assert step1_files, "render_url.py should have written a rendered_page_*.json file"
    step1_path = step1_files[-1]

    parse_result, parse_proc = run(
        [sys.executable, str(PARSER_SCRIPT), str(step1_path)]
    )
    assert parse_result["ok"] is True, parse_proc.stderr
    assert parse_result["source_url"] == server.url("js_render.html")
    assert "INJECTED_BY_JS" in parse_result["data"]["text"]


def test_static_page_headings_and_links_flow_through(server):
    render_result, _ = run([sys.executable, str(RENDER_SCRIPT), server.url("static.html")])
    assert render_result["ok"] is True

    step1_files = sorted(ROOT.glob("rendered_page_*.json"))
    step1_path = step1_files[-1]

    parse_result, _ = run([sys.executable, str(PARSER_SCRIPT), str(step1_path)])
    assert parse_result["ok"] is True
    assert parse_result["title"] == "Static Fixture Page"


def test_invalid_url_failure_boundary(server):
    render_result, _ = run([sys.executable, str(RENDER_SCRIPT), "not-a-url"])
    assert render_result["ok"] is False
    assert render_result["error"]["type"] == "invalid_url"

    step1_files = sorted(ROOT.glob("rendered_page_*.json"))
    step1_path = step1_files[-1]

    parse_result, _ = run([sys.executable, str(PARSER_SCRIPT), str(step1_path)])
    assert parse_result["ok"] is False
    assert parse_result["error"]["type"] == "missing_html"
