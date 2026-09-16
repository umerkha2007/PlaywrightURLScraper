"""
render_url.py — deterministic URL -> rendered HTML JSON utility.

Pipeline: URL -> Playwright (Chromium) -> JS/WASM execution -> rendered DOM
          -> HTML -> single JSON object on stdout.

No LLM, AI model, agent reasoning, or semantic HTML interpretation is used
anywhere in this script. It is a renderer, not a scraper.
"""

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright, Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError


DEFAULT_TIMEOUT_MS = 30000
DEFAULT_STABILIZATION_MS = 1000
DEFAULT_OUTPUT_PREFIX = "rendered_page"
DEFAULT_OUTPUT_DIR = "."
DEFAULT_WAIT_UNTIL = "load"
DEFAULT_HEADLESS = True
DEFAULT_CONFIG_PATH = "config.json"

# wait_until values Playwright's page.wait_for_load_state() accepts.
VALID_WAIT_UNTIL = ("load", "domcontentloaded", "networkidle")

DEFAULTS = {
    "url": None,
    "timeout_ms": DEFAULT_TIMEOUT_MS,
    "stabilization_ms": DEFAULT_STABILIZATION_MS,
    "wait_until": DEFAULT_WAIT_UNTIL,
    "headless": DEFAULT_HEADLESS,
    "output_prefix": DEFAULT_OUTPUT_PREFIX,
    "output_dir": DEFAULT_OUTPUT_DIR,
}


def load_config_file(path):
    """Read a JSON config file. Returns {} if the file doesn't exist."""
    p = Path(path)
    if not p.exists():
        return {}
    try:
        with p.open(encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise SystemExit(f"error: failed to read config file {path}: {e}")
    if not isinstance(data, dict):
        raise SystemExit(f"error: config file {path} must contain a JSON object.")
    unknown = set(data) - set(DEFAULTS)
    if unknown:
        raise SystemExit(f"error: unknown config key(s) in {path}: {', '.join(sorted(unknown))}")
    return data


def resolve_settings(args):
    """Merge defaults <- config file <- CLI args (CLI wins)."""
    settings = dict(DEFAULTS)
    settings.update(load_config_file(args.config))
    for key in DEFAULTS:
        cli_value = getattr(args, key, None)
        if cli_value is not None:
            settings[key] = cli_value
    return settings


def next_output_path(prefix, directory="."):
    n = 1
    while True:
        candidate = Path(directory) / f"{prefix}_{n}.json"
        if not candidate.exists():
            return candidate
        n += 1


def build_result(ok, url, final_url=None, status_code=None, title=None, html=None, error=None):
    return {
        "ok": ok,
        "url": url,
        "final_url": final_url,
        "status_code": status_code,
        "title": title,
        "html": html,
        "error": error,
    }


def error_result(url, error_type, message):
    return build_result(
        ok=False,
        url=url,
        error={"type": error_type, "message": message},
    )


def is_valid_url(url):
    try:
        parsed = urlparse(url)
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except Exception:
        return False


def render(url, timeout_ms, stabilization_ms=DEFAULT_STABILIZATION_MS,
           wait_until=DEFAULT_WAIT_UNTIL, headless=DEFAULT_HEADLESS):
    with sync_playwright() as p:
        browser = None
        try:
            try:
                browser = p.chromium.launch(headless=headless)
            except PlaywrightError as e:
                return error_result(url, "browser_error", str(e))

            page = browser.new_page()
            page.set_default_timeout(timeout_ms)

            status_code = None
            try:
                response = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                if response is not None:
                    status_code = response.status
            except PlaywrightTimeoutError as e:
                return error_result(url, "navigation_timeout", str(e))
            except PlaywrightError as e:
                return error_result(url, "navigation_error", str(e))

            # Best-effort extra settle time beyond domcontentloaded, without
            # relying on networkidle by default (SPAs may keep long-lived
            # connections open and never reach it) — configurable via
            # wait_until for callers who do want it.
            try:
                page.wait_for_load_state(wait_until, timeout=timeout_ms)
            except PlaywrightTimeoutError:
                pass
            except PlaywrightError:
                pass

            page.wait_for_timeout(stabilization_ms)

            try:
                html = page.evaluate("document.documentElement.outerHTML")
                title = page.title()
                final_url = page.url
            except PlaywrightError as e:
                return error_result(url, "html_extraction_error", str(e))

            return build_result(
                ok=True,
                url=url,
                final_url=final_url,
                status_code=status_code,
                title=title,
                html=html,
                error=None,
            )
        finally:
            if browser is not None:
                try:
                    browser.close()
                except PlaywrightError:
                    pass


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Render a single URL with Chromium (via Playwright) and emit the post-JS DOM as JSON."
    )
    parser.add_argument(
        "url",
        nargs="?",
        default=None,
        help="Exactly one URL to render. Falls back to \"url\" in the config file if omitted.",
    )
    parser.add_argument(
        "--config",
        default=DEFAULT_CONFIG_PATH,
        help=f"Path to a JSON config file (default: {DEFAULT_CONFIG_PATH}; ignored if it doesn't exist). "
             "CLI flags override values from this file.",
    )
    parser.add_argument(
        "--timeout",
        dest="timeout_ms",
        type=int,
        default=None,
        help=f"Overall navigation timeout in milliseconds (default: {DEFAULT_TIMEOUT_MS}).",
    )
    parser.add_argument(
        "--stabilization",
        dest="stabilization_ms",
        type=int,
        default=None,
        help=f"Fixed settle time after load, in milliseconds, before capturing the DOM "
             f"(default: {DEFAULT_STABILIZATION_MS}).",
    )
    parser.add_argument(
        "--wait-until",
        dest="wait_until",
        choices=VALID_WAIT_UNTIL,
        default=None,
        help=f"Load state to wait for after navigation (default: {DEFAULT_WAIT_UNTIL}). "
             "\"networkidle\" is not recommended for SPAs that keep long-lived connections open.",
    )
    parser.add_argument(
        "--headless",
        dest="headless",
        action="store_const",
        const=True,
        default=None,
        help=f"Run Chromium headless (default: {DEFAULT_HEADLESS}).",
    )
    parser.add_argument(
        "--no-headless",
        dest="headless",
        action="store_const",
        const=False,
        help="Run Chromium with a visible browser window.",
    )
    parser.add_argument(
        "--output-prefix",
        dest="output_prefix",
        default=None,
        help=f"Prefix for the auto-incremented output file, e.g. <prefix>_1.json, <prefix>_2.json, ... "
             f"(default: {DEFAULT_OUTPUT_PREFIX}).",
    )
    parser.add_argument(
        "--output-dir",
        dest="output_dir",
        default=None,
        help=f"Directory to write the output file into (default: {DEFAULT_OUTPUT_DIR}).",
    )
    return parser.parse_args(argv)


def main():
    args = parse_args()
    settings = resolve_settings(args)

    url = settings["url"]
    if not url:
        print(json.dumps(error_result(None, "invalid_url", "No URL provided via argument or config file.")))
        sys.exit(1)

    if not is_valid_url(url):
        result = error_result(url, "invalid_url", "URL must be an absolute http(s) URL.")
    else:
        try:
            result = render(
                url,
                timeout_ms=settings["timeout_ms"],
                stabilization_ms=settings["stabilization_ms"],
                wait_until=settings["wait_until"],
                headless=settings["headless"],
            )
        except Exception as e:
            result = error_result(url, "unknown_error", str(e))

    output_text = json.dumps(result)
    print(output_text)

    output_path = next_output_path(settings["output_prefix"], settings["output_dir"])
    try:
        output_path.write_text(output_text, encoding="utf-8")
    except OSError as e:
        print(f"warning: failed to write output file {output_path}: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
