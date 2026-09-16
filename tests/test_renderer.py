"""
Tests for render_url.py.

Spins up a local HTTP server serving fixture pages so tests are
deterministic and don't depend on the public internet (except for the
optional WASM smoke test).
"""

import glob
import http.server
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
RENDER_SCRIPT = ROOT / "render_url.py"
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
def cleanup_rendered_files():
    """Remove the rendered_page_*.json files render_url.py writes to ROOT on every call."""
    yield
    for f in glob.glob(str(ROOT / "rendered_page_*.json")):
        os.remove(f)


def run_render(url, timeout=None, extra_args=None):
    cmd = [sys.executable, str(RENDER_SCRIPT), url]
    if timeout is not None:
        cmd += ["--timeout", str(timeout)]
    if extra_args:
        cmd += extra_args
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60, cwd=ROOT)
    assert proc.stdout.strip(), f"empty stdout; stderr={proc.stderr}"
    lines = [l for l in proc.stdout.strip().splitlines() if l.strip()]
    assert len(lines) == 1, f"expected exactly one stdout line, got: {proc.stdout!r}"
    return json.loads(lines[0])


def test_static_html(server):
    result = run_render(server.url("static.html"))
    assert result["ok"] is True
    assert "Static Fixture" in result["html"]
    assert result["title"] == "Static Fixture Page"
    assert result["status_code"] == 200


def test_js_rendered_page(server):
    result = run_render(server.url("js_render.html"))
    assert result["ok"] is True
    assert "INJECTED_BY_JS" in result["html"]


def test_redirect(server):
    result = run_render(server.url("redirect.html"))
    assert result["ok"] is True
    assert result["url"] == server.url("redirect.html")
    assert result["final_url"] != result["url"]
    assert "Redirect Target" in result["html"]


def test_invalid_url():
    result = run_render("not-a-url")
    assert result["ok"] is False
    assert result["error"]["type"] == "invalid_url"


def test_timeout():
    # Non-routable address, forces navigation to hang until timeout.
    result = run_render("http://10.255.255.1/", timeout=2000)
    assert result["ok"] is False
    assert result["error"]["type"] in ("navigation_timeout", "navigation_error")


@pytest.mark.skipif(
    True,
    reason="Optional: requires network access to a public WASM demo page; enable manually.",
)
def test_wasm_page():
    result = run_render("https://webassembly.org/")
    assert result["ok"] is True
    # Recorded observation only: WASM executing does not guarantee content
    # lands in the DOM (e.g. canvas-rendered output would not).
    assert isinstance(result["html"], str)
