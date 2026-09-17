"""
render_and_parse.py — convenience wrapper chaining Step 1 and Step 2.

Pipeline: URL -> render_url.render() -> Step 1 JSON -> parse_html.parse_html()
          -> Step 2 JSON on stdout.

This is a thin orchestration layer only. It imports both render_url and
parse_html and calls their public functions directly (no subprocesses); it
adds no rendering or parsing logic of its own. render_url.py and
parse_html.py remain independently usable and parse_html.py still does not
import render_url.
"""

import argparse
import json
import sys
from types import SimpleNamespace

import render_url
import parse_html
import detector as detector_pkg


def _log(verbose, message):
    if verbose:
        print(f"[render-and-parse] {message}", file=sys.stderr)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Render a URL with Chromium and parse the result into structured JSON, in one step."
    )
    parser.add_argument("url", nargs="?", default=None, help="URL to render and parse.")
    parser.add_argument("--config", default=render_url.DEFAULT_CONFIG_PATH,
                         help=f"Path to a JSON config file (default: {render_url.DEFAULT_CONFIG_PATH}).")
    parser.add_argument("--timeout", dest="timeout_ms", type=int, default=None,
                         help="Overall navigation timeout in milliseconds (render stage).")
    parser.add_argument("--stabilization", dest="stabilization_ms", type=int, default=None,
                         help="Settle time in milliseconds after load (render stage).")
    parser.add_argument("--wait-until", dest="wait_until", choices=render_url.VALID_WAIT_UNTIL, default=None,
                         help="Load state to wait for after navigation (render stage).")
    parser.add_argument("--headless", dest="headless", action="store_const", const=True, default=None,
                         help="Run Chromium headless (render stage).")
    parser.add_argument("--no-headless", dest="headless", action="store_const", const=False,
                         help="Run Chromium with a visible window (render stage).")
    parser.add_argument("--selector", dest="selector", default=None,
                         help="CSS selector to scope extraction to (parse stage).")
    parser.add_argument("--no-strip-whitespace", dest="strip_whitespace", action="store_const",
                         const=False, default=None, help="Preserve raw whitespace (parse stage).")
    parser.add_argument("--output-dir", dest="output_dir", default=None,
                         help="Directory for both the rendered_page_*.json and parsed_page_*.json files.")
    parser.add_argument("--verbose", "-v", dest="verbose", action="store_const", const=True, default=None,
                         help="Log progress from both the render and parse stages to stderr.")
    parser.add_argument("--log-json", dest="log_json", action="store_const", const=True, default=None,
                         help="Additionally log the render stage and final parse stage JSON, pretty-printed, to stderr.")
    parser.add_argument("--detect", dest="detect", action="store_const", const=True, default=None,
                         help="Run deterministic page classification (CAPTCHA/login/error/closed-job/"
                              "bot-challenge/application-form detection) before rendering. If the page "
                              "does not classify as APPLICATION, parsing is skipped and the classification "
                              "is returned instead. Configurable via the \"detector\" section of the config file.")
    return parser.parse_args(argv)


def _log_json(log_json, label, result):
    if log_json:
        print(f"[render-and-parse] {label}:", file=sys.stderr)
        print(json.dumps(result, indent=2), file=sys.stderr)


def main():
    args = parse_args()

    render_args = SimpleNamespace(
        config=args.config,
        url=args.url,
        timeout_ms=args.timeout_ms,
        stabilization_ms=args.stabilization_ms,
        wait_until=args.wait_until,
        headless=args.headless,
        output_prefix=None,
        output_dir=args.output_dir,
        verbose=args.verbose,
        log_json=args.log_json,
        detect=args.detect,
    )
    render_settings = render_url.resolve_settings(render_args)
    verbose = render_settings["verbose"]
    log_json = render_settings["log_json"]

    url = render_settings["url"]
    if not url:
        result = parse_html.error_result(None, "invalid_input", "No URL provided via argument or config file.")
        print(json.dumps(result))
        _log_json(log_json, "final result", result)
        sys.exit(1)

    _log(verbose, f"stage 1/2: rendering {url}")
    if not render_url.is_valid_url(url):
        render_result = render_url.error_result(url, "invalid_url", "URL must be an absolute http(s) URL.")
    else:
        try:
            render_result = render_url.render(
                url,
                timeout_ms=render_settings["timeout_ms"],
                stabilization_ms=render_settings["stabilization_ms"],
                wait_until=render_settings["wait_until"],
                headless=render_settings["headless"],
                verbose=verbose,
                detect=render_settings["detect"],
                detector_config=detector_pkg.load_detector_config(args.config) if render_settings["detect"] else None,
            )
        except Exception as e:
            render_result = render_url.error_result(url, "unknown_error", str(e))

    render_output_path = render_url.next_output_path(render_settings["output_prefix"], render_settings["output_dir"])
    _log(verbose, f"writing render stage output to {render_output_path}")
    _log_json(log_json, "render stage result", render_result)
    try:
        render_output_path.write_text(json.dumps(render_result), encoding="utf-8")
    except OSError as e:
        print(f"warning: failed to write output file {render_output_path}: {e}", file=sys.stderr)

    parse_args_ns = SimpleNamespace(
        config=args.config,
        input=None,
        input_opt=None,
        selector=args.selector,
        strip_whitespace=args.strip_whitespace,
        output_prefix=None,
        output_dir=args.output_dir,
        verbose=args.verbose,
        log_json=args.log_json,
    )
    parse_settings = parse_html.resolve_settings(parse_args_ns)

    _log(verbose, "stage 2/2: parsing rendered HTML")
    html = render_result.get("html")
    detected_status = render_result.get("status")
    if detected_status is not None and detected_status != "APPLICATION":
        _log(verbose, f"detector classified page as {detected_status}; skipping parse")
        parse_result = parse_html.build_result(
            ok=True,
            source_url=render_result.get("final_url") or render_result.get("url"),
            title=render_result.get("title"),
            data=None,
            selector_matched=None,
            error=None,
        )
        parse_result["status"] = detected_status
        parse_result["reason"] = render_result.get("reason")
        parse_result["detector"] = render_result.get("detector")
        parse_result["form"] = render_result.get("form")
        parse_result["redirected"] = render_result.get("redirected")
    elif not render_result.get("ok", False) or html is None:
        _log(verbose, "render stage failed or produced no html; skipping parse")
        parse_result = parse_html.error_result(url, "missing_html", "Step 1 result had ok=false or a null html field.")
    else:
        parse_config = {
            "source_url": render_result.get("url"),
            "selector": parse_settings["selector"],
            "strip_whitespace": parse_settings["strip_whitespace"],
            "verbose": verbose,
        }
        try:
            parse_result = parse_html.parse_html(html, config=parse_config)
        except Exception as e:
            parse_result = parse_html.error_result(url, "unknown_error", str(e))
        if detected_status is not None:
            parse_result["status"] = detected_status
            parse_result["reason"] = render_result.get("reason")
            parse_result["detector"] = render_result.get("detector")
            parse_result["form"] = render_result.get("form")
            parse_result["redirected"] = render_result.get("redirected")

    parse_output_path = parse_html.next_output_path(parse_settings["output_prefix"], parse_settings["output_dir"])
    _log(verbose, f"writing parse stage output to {parse_output_path}")
    try:
        parse_output_path.write_text(json.dumps(parse_result), encoding="utf-8")
    except OSError as e:
        print(f"warning: failed to write output file {parse_output_path}: {e}", file=sys.stderr)

    print(json.dumps(parse_result))
    _log_json(log_json, "final result", parse_result)


if __name__ == "__main__":
    main()
