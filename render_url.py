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

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError

import detector as detector_pkg


DEFAULT_TIMEOUT_MS = 30000
DEFAULT_STABILIZATION_MS = 1000
DEFAULT_OUTPUT_PREFIX = "rendered_page"
DEFAULT_OUTPUT_DIR = "."
DEFAULT_WAIT_UNTIL = "load"
DEFAULT_HEADLESS = True
DEFAULT_CONFIG_PATH = "config.json"

# wait_until values Playwright's page.wait_for_load_state() accepts.
VALID_WAIT_UNTIL = ("load", "domcontentloaded", "networkidle")

DEFAULT_VERBOSE = False
DEFAULT_LOG_JSON = False
DEFAULT_DETECT = False
DEFAULT_RAW_HTML = False

# Body-only, markup-only extraction used by --raw-html: drops <script>/<style>/<link>
# (and other non-content) elements plus inline style="" and on*="" attributes.
BODY_ONLY_JS = """() => {
  const body = document.body.cloneNode(true);
  body.querySelectorAll('script, style, link, noscript, template').forEach(e => e.remove());
  for (const el of [body, ...body.querySelectorAll('*')]) {
    for (const a of Array.from(el.attributes)) {
      if (a.name === 'style' || a.name.startsWith('on')) el.removeAttribute(a.name);
    }
  }
  return body.outerHTML;
}"""

DEFAULTS = {
    "url": None,
    "timeout_ms": DEFAULT_TIMEOUT_MS,
    "stabilization_ms": DEFAULT_STABILIZATION_MS,
    "wait_until": DEFAULT_WAIT_UNTIL,
    "headless": DEFAULT_HEADLESS,
    "output_prefix": DEFAULT_OUTPUT_PREFIX,
    "output_dir": DEFAULT_OUTPUT_DIR,
    "verbose": DEFAULT_VERBOSE,
    "log_json": DEFAULT_LOG_JSON,
    "detect": DEFAULT_DETECT,
    "raw_html": DEFAULT_RAW_HTML,
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
    # "parser" and "detector" are reserved for Step 2 (parse_html.py) and the
    # detector package respectively, which read the same config file but only
    # look at their own sub-key. Ignored here so all tools can share one
    # config.json without render_url.py rejecting them as typos.
    unknown = set(data) - set(DEFAULTS) - {"parser", "detector"}
    if unknown:
        raise SystemExit(f"error: unknown config key(s) in {path}: {', '.join(sorted(unknown))}")
    return {k: v for k, v in data.items() if k not in ("parser", "detector")}


def resolve_settings(args):
    """Merge defaults <- config file <- CLI args (CLI wins)."""
    settings = dict(DEFAULTS)
    settings.update(load_config_file(args.config))
    for key in DEFAULTS:
        cli_value = getattr(args, key, None)
        if cli_value is not None:
            settings[key] = cli_value
    return settings


def format_html(html):
    """Pretty-print HTML with one tag per line and consistent indentation."""
    return BeautifulSoup(html, "html.parser").prettify()


def next_output_path(prefix, directory=".", ext="json"):
    n = 1
    while True:
        candidate = Path(directory) / f"{prefix}_{n}.{ext}"
        if not candidate.exists():
            return candidate
        n += 1


def build_result(ok, url, final_url=None, status_code=None, title=None, html=None, error=None,
                  status=None, detector=None, reason=None, form=None, redirected=None):
    result = {
        "ok": ok,
        "url": url,
        "final_url": final_url,
        "status_code": status_code,
        "title": title,
        "html": html,
        "error": error,
    }
    # Only present when --detect was used, so non-detect output stays
    # byte-for-byte identical to before this feature existed.
    if status is not None:
        result["status"] = status
        result["redirected"] = redirected
        result["reason"] = reason
        result["detector"] = detector
        result["form"] = form
    return result


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


def _log(verbose, message):
    if verbose:
        print(f"[render-url] {message}", file=sys.stderr)


def _run_challenge_wait_loop(page, status_code, detector_config, verbose):
    """navigate -> wait -> inspect -> wait -> inspect, per the BOT_CHALLENGE spec.

    Returns the final classify() result once the page is no longer showing a
    bot/security challenge, or once challenge_max_checks is exhausted.
    """
    wait_ms = detector_config.get("challenge_wait_ms", 2000)
    max_checks = detector_config.get("challenge_max_checks", 2)

    result = None
    for attempt in range(max_checks + 1):
        html = page.evaluate("document.documentElement.outerHTML")
        result = detector_pkg.classify(html, status_code=status_code, config=detector_config)
        if not result["detector"]["bot_challenge"]:
            return result
        if attempt < max_checks:
            _log(verbose, f"bot challenge detected (attempt {attempt + 1}/{max_checks}); waiting {wait_ms}ms and re-inspecting")
            page.wait_for_timeout(wait_ms)
    return result


def render(url, timeout_ms, stabilization_ms=DEFAULT_STABILIZATION_MS,
           wait_until=DEFAULT_WAIT_UNTIL, headless=DEFAULT_HEADLESS, verbose=False,
           detect=False, detector_config=None, body_only=False):
    with sync_playwright() as p:
        browser = None
        try:
            _log(verbose, f"launching Chromium (headless={headless})")
            try:
                browser = p.chromium.launch(headless=headless)
            except PlaywrightError as e:
                _log(verbose, f"browser launch failed: {e}")
                return error_result(url, "browser_error", str(e))

            page = browser.new_page()
            page.set_default_timeout(timeout_ms)

            status_code = None
            _log(verbose, f"navigating to {url} (timeout={timeout_ms}ms)")
            try:
                response = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                if response is not None:
                    status_code = response.status
                _log(verbose, f"domcontentloaded (status={status_code})")
            except PlaywrightTimeoutError as e:
                _log(verbose, f"navigation timed out: {e}")
                return error_result(url, "navigation_timeout", str(e))
            except PlaywrightError as e:
                _log(verbose, f"navigation error: {e}")
                return error_result(url, "navigation_error", str(e))

            # Best-effort extra settle time beyond domcontentloaded, without
            # relying on networkidle by default (SPAs may keep long-lived
            # connections open and never reach it) — configurable via
            # wait_until for callers who do want it.
            _log(verbose, f"waiting for load state \"{wait_until}\"")
            try:
                page.wait_for_load_state(wait_until, timeout=timeout_ms)
            except PlaywrightTimeoutError:
                _log(verbose, f"load state \"{wait_until}\" timed out (continuing)")
            except PlaywrightError:
                pass

            _log(verbose, f"stabilizing for {stabilization_ms}ms")
            page.wait_for_timeout(stabilization_ms)

            detection = None
            if detect:
                detector_config = detector_config or detector_pkg.load_detector_config(DEFAULT_CONFIG_PATH)
                _log(verbose, "running application detector (redirect/CAPTCHA/login/error/closed-job/bot-challenge checks)")
                try:
                    detection = _run_challenge_wait_loop(page, status_code, detector_config, verbose)
                except PlaywrightError as e:
                    _log(verbose, f"detection failed: {e}")
                    return error_result(url, "detection_error", str(e))
                _log(verbose, f"classification: {detection['status']} (reason={detection['reason']})")

                if detection["status"] != detector_pkg.constants.STATUS_APPLICATION:
                    try:
                        final_url = page.url
                        title = page.title()
                    except PlaywrightError:
                        final_url, title = page.url, None
                    return build_result(
                        ok=True,
                        url=url,
                        final_url=final_url,
                        status_code=status_code,
                        title=title,
                        html=None,
                        error=None,
                        status=detection["status"],
                        detector=detection["detector"],
                        reason=detection["reason"],
                        form=detection["form"],
                        redirected=(final_url != url),
                    )

            _log(verbose, "extracting outerHTML, title, and final URL")
            try:
                html = page.evaluate(BODY_ONLY_JS if body_only else "document.documentElement.outerHTML")
                title = page.title()
                final_url = page.url
            except PlaywrightError as e:
                _log(verbose, f"HTML extraction failed: {e}")
                return error_result(url, "html_extraction_error", str(e))

            if body_only:
                html = format_html(html)

            _log(verbose, f"done: {len(html)} chars of HTML captured")
            return build_result(
                ok=True,
                url=url,
                final_url=final_url,
                status_code=status_code,
                title=title,
                html=html,
                error=None,
                status=detection["status"] if detection else None,
                detector=detection["detector"] if detection else None,
                reason=detection["reason"] if detection else None,
                form=detection["form"] if detection else None,
                redirected=(final_url != url) if detection else None,
            )
        finally:
            if browser is not None:
                _log(verbose, "closing Chromium")
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
    parser.add_argument(
        "--verbose", "-v",
        dest="verbose",
        action="store_const",
        const=True,
        default=None,
        help="Log rendering progress (navigation, waits, extraction, browser lifecycle) to stderr.",
    )
    parser.add_argument(
        "--log-json",
        dest="log_json",
        action="store_const",
        const=True,
        default=None,
        help="Additionally log the final result JSON, pretty-printed, to stderr.",
    )
    parser.add_argument(
        "--detect",
        dest="detect",
        action="store_const",
        const=True,
        default=None,
        help="Run deterministic page classification (CAPTCHA/login/error/closed-job/bot-challenge/"
             "application-form detection) before extracting HTML. If the page does not classify as "
             "APPLICATION, the result carries the classification instead of the rendered HTML. "
             "Configurable via the \"detector\" section of the config file.",
    )
    parser.add_argument(
        "--no-detect",
        dest="detect",
        action="store_const",
        const=False,
        help="Turn page classification off, overriding \"detect\": true in the config file.",
    )
    parser.add_argument(
        "--raw-html",
        dest="raw_html",
        action="store_const",
        const=True,
        default=None,
        help="Emit the rendered <body> markup only, pretty-printed (no scripts, styles, links, inline style/on* attributes; "
             "not JSON) to stdout and to <prefix>_N.html. All other "
             "options still apply. If no HTML was produced (error, or --detect classified the page "
             "as non-APPLICATION), the JSON result is emitted instead so the failure is visible.",
    )
    return parser.parse_args(argv)


def main():
    args = parse_args()
    settings = resolve_settings(args)
    verbose = settings["verbose"]
    log_json = settings["log_json"]

    url = settings["url"]
    if not url:
        print(json.dumps(error_result(None, "invalid_url", "No URL provided via argument or config file.")))
        sys.exit(1)

    if not is_valid_url(url):
        _log(verbose, f"invalid URL: {url!r}")
        result = error_result(url, "invalid_url", "URL must be an absolute http(s) URL.")
    else:
        try:
            result = render(
                url,
                timeout_ms=settings["timeout_ms"],
                stabilization_ms=settings["stabilization_ms"],
                wait_until=settings["wait_until"],
                headless=settings["headless"],
                verbose=verbose,
                detect=settings["detect"],
                detector_config=detector_pkg.load_detector_config(args.config) if settings["detect"] else None,
                body_only=settings["raw_html"],
            )
        except Exception as e:
            _log(verbose, f"unexpected error: {e}")
            result = error_result(url, "unknown_error", str(e))

    raw_html = settings["raw_html"] and result.get("html") is not None
    output_text = result["html"] if raw_html else json.dumps(result)
    print(output_text)

    if log_json:
        print(json.dumps(result, indent=2), file=sys.stderr)

    output_path = next_output_path(settings["output_prefix"], settings["output_dir"],
                                   "html" if raw_html else "json")
    _log(verbose, f"writing output to {output_path}")
    try:
        output_path.write_text(output_text, encoding="utf-8")
    except OSError as e:
        print(f"warning: failed to write output file {output_path}: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
