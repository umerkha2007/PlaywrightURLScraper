"""
parse_html.py — deterministic HTML -> structured JSON extractor (Step 2).

Pipeline: Step 1 JSON (rendered_page_*.json) -> "html" field -> BeautifulSoup4
          (html.parser backend) -> deterministic structural extraction rules
          -> single JSON object on stdout.

No LLM, AI model, agent reasoning, or semantic HTML interpretation is used
anywhere in this script. No network access, no Playwright. This module is
fully independent of render_url.py (never imports it).

Extracted fields (see parse_html()):
  title    <title> text, whitespace-normalized. null if absent/empty.
  headings every h1-h6 in document order: {"level": int, "text": str}.
  links    every <a href=...> in document order: {"text": str, "href": str}.
           Anchors without an href attribute are excluded. Not deduped.
  images   every <img src=...> in document order: {"src": str, "alt": str}.
           alt defaults to "" if the attribute is absent. Images without a
           src attribute are excluded.
  meta     dict of {name_or_property: content} from <meta name=...> and
           <meta property=...> tags, collected in document order with the
           later tag winning on duplicate keys.
  text     visible text of <body> (or whole document if no body), with
           <script>/<style> contents excluded, whitespace-normalized.

`selector` (optional CSS selector, config key) scopes headings/links/images/
text extraction to the first element matched by BeautifulSoup's .select();
title/meta remain document-level. No match -> those fields come back empty
and `selector_matched` is false (not an error).

`strip_whitespace` (default true) controls whitespace normalization
(collapse runs of whitespace to a single space, strip ends) for text/
headings/links text. When false, raw tag text is used as-is.
"""

import argparse
import json
import re
import sys
from pathlib import Path

from bs4 import BeautifulSoup


DEFAULT_SELECTOR = None
DEFAULT_STRIP_WHITESPACE = True
DEFAULT_OUTPUT_PREFIX = "parsed_page"
DEFAULT_OUTPUT_DIR = "."
DEFAULT_CONFIG_PATH = "config.json"
DEFAULT_VERBOSE = False
DEFAULT_LOG_JSON = False

DEFAULTS = {
    "selector": DEFAULT_SELECTOR,
    "strip_whitespace": DEFAULT_STRIP_WHITESPACE,
    "output_prefix": DEFAULT_OUTPUT_PREFIX,
    "output_dir": DEFAULT_OUTPUT_DIR,
    "verbose": DEFAULT_VERBOSE,
    "log_json": DEFAULT_LOG_JSON,
}


def _log(verbose, message):
    if verbose:
        print(f"[parse-html] {message}", file=sys.stderr)

_WHITESPACE_RE = re.compile(r"\s+")


def load_config_file(path):
    """Read the shared config file and return only its "parser" sub-object.

    render_url.py owns the rest of the file (flat renderer keys); this
    reads the same file but scopes itself to the "parser" key so both
    tools can coexist in one config.json with no changes needed to
    render_url.py's own key handling beyond tolerating "parser" as known-but-
    ignored.
    """
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
    parser_section = data.get("parser", {})
    if not isinstance(parser_section, dict):
        raise SystemExit(f"error: \"parser\" section in {path} must be a JSON object.")
    unknown = set(parser_section) - set(DEFAULTS)
    if unknown:
        raise SystemExit(
            f"error: unknown parser config key(s) in {path}: {', '.join(sorted(unknown))}"
        )
    return parser_section


def resolve_settings(args):
    """Merge defaults <- config file's "parser" section <- CLI args (CLI wins)."""
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


def build_result(ok, source_url=None, title=None, data=None, selector_matched=None, error=None):
    return {
        "ok": ok,
        "source_url": source_url,
        "title": title,
        "data": data,
        "selector_matched": selector_matched,
        "error": error,
    }


def error_result(source_url, error_type, message):
    return build_result(ok=False, source_url=source_url, error={"type": error_type, "message": message})


def _norm(text, strip_whitespace):
    if strip_whitespace:
        return _WHITESPACE_RE.sub(" ", text).strip()
    return text


def _extract_title(soup, strip_whitespace):
    tag = soup.find("title")
    if tag is None:
        return None
    text = _norm(tag.get_text(), strip_whitespace)
    return text if text else None


def _extract_headings(scope, strip_whitespace):
    headings = []
    for tag in scope.find_all(re.compile(r"^h[1-6]$")):
        level = int(tag.name[1])
        headings.append({"level": level, "text": _norm(tag.get_text(), strip_whitespace)})
    return headings


def _extract_links(scope, strip_whitespace):
    links = []
    for tag in scope.find_all("a"):
        if not tag.has_attr("href"):
            continue
        text = _norm(tag.get_text(), strip_whitespace) if tag.get_text() else ""
        links.append({"text": text, "href": tag.get("href")})
    return links


def _extract_images(scope):
    images = []
    for tag in scope.find_all("img"):
        if not tag.has_attr("src"):
            continue
        images.append({"src": tag.get("src"), "alt": tag.get("alt", "")})
    return images


def _extract_meta(soup):
    meta = {}
    for tag in soup.find_all("meta"):
        key = tag.get("property") if tag.has_attr("property") else tag.get("name")
        if not key or not tag.has_attr("content"):
            continue
        meta[key] = tag.get("content")
    return meta


def _extract_text(scope, strip_whitespace):
    for tag in scope.find_all(["script", "style"]):
        tag.decompose()
    text = scope.get_text(separator=" ")
    return _norm(text, strip_whitespace)


def parse_html(html, config=None):
    """Parse raw HTML into the deterministic structured-extraction schema.

    Returns the same dict shape build_result() produces. No network access,
    no Playwright, no LLM/AI reasoning; pure structural DOM traversal.
    """
    config = config or {}
    source_url = config.get("source_url")
    strip_whitespace = config.get("strip_whitespace", DEFAULT_STRIP_WHITESPACE)
    selector = config.get("selector", DEFAULT_SELECTOR)
    verbose = config.get("verbose", DEFAULT_VERBOSE)

    if html is None or not isinstance(html, str):
        _log(verbose, "invalid input: html is missing or not a string")
        return error_result(source_url, "invalid_input", "html must be a non-empty string.")

    try:
        if not isinstance(strip_whitespace, bool):
            raise ValueError("strip_whitespace must be a boolean.")
        if selector is not None and not isinstance(selector, str):
            raise ValueError("selector must be a string or null.")
    except ValueError as e:
        _log(verbose, f"invalid config: {e}")
        return error_result(source_url, "invalid_config", str(e))

    _log(verbose, f"parsing {len(html)} chars of HTML with BeautifulSoup4 (html.parser)")
    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception as e:
        _log(verbose, f"parse error: {e}")
        return error_result(source_url, "parse_error", str(e))

    try:
        _log(verbose, "extracting title and meta tags")
        title = _extract_title(soup, strip_whitespace)
        meta = _extract_meta(soup)

        selector_matched = None
        scope = soup.body if soup.body is not None else soup

        if selector:
            _log(verbose, f"applying selector: {selector!r}")
            try:
                matches = soup.select(selector)
            except Exception as e:
                _log(verbose, f"invalid selector: {e}")
                return error_result(source_url, "invalid_config", f"invalid selector: {e}")
            if matches:
                scope = matches[0]
                selector_matched = True
                _log(verbose, "selector matched an element; scoping extraction to it")
            else:
                selector_matched = False
                _log(verbose, "selector matched nothing; returning empty scoped fields")
                return build_result(
                    ok=True,
                    source_url=source_url,
                    title=title,
                    data={"headings": [], "links": [], "images": [], "meta": meta, "text": ""},
                    selector_matched=False,
                    error=None,
                )

        _log(verbose, "extracting headings, links, images, and text")
        data = {
            "headings": _extract_headings(scope, strip_whitespace),
            "links": _extract_links(scope, strip_whitespace),
            "images": _extract_images(scope),
            "meta": meta,
            "text": _extract_text(scope, strip_whitespace),
        }
        _log(
            verbose,
            f"done: {len(data['headings'])} headings, {len(data['links'])} links, "
            f"{len(data['images'])} images extracted",
        )

        return build_result(
            ok=True,
            source_url=source_url,
            title=title,
            data=data,
            selector_matched=selector_matched,
            error=None,
        )
    except Exception as e:
        _log(verbose, f"unexpected error: {e}")
        return error_result(source_url, "unknown_error", str(e))


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Parse a Step 1 rendered-page JSON file's HTML into deterministic structured JSON."
    )
    parser.add_argument(
        "input",
        nargs="?",
        default=None,
        help="Path to a Step 1 JSON output file (or use --input). Use \"-\" to read from stdin.",
    )
    parser.add_argument(
        "--input",
        dest="input_opt",
        default=None,
        help="Path to a Step 1 JSON output file (alternative to the positional argument).",
    )
    parser.add_argument(
        "--config",
        default=DEFAULT_CONFIG_PATH,
        help=f"Path to a JSON config file (default: {DEFAULT_CONFIG_PATH}). Reads its \"parser\" section.",
    )
    parser.add_argument(
        "--selector",
        dest="selector",
        default=None,
        help="CSS selector to scope headings/links/images/text extraction to.",
    )
    parser.add_argument(
        "--no-strip-whitespace",
        dest="strip_whitespace",
        action="store_const",
        const=False,
        default=None,
        help="Preserve original whitespace in extracted text instead of collapsing it.",
    )
    parser.add_argument(
        "--output-prefix",
        dest="output_prefix",
        default=None,
        help=f"Prefix for the auto-incremented output file (default: {DEFAULT_OUTPUT_PREFIX}).",
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
        help="Log parsing progress (input loading, extraction steps, field counts) to stderr.",
    )
    parser.add_argument(
        "--log-json",
        dest="log_json",
        action="store_const",
        const=True,
        default=None,
        help="Additionally log the final result JSON, pretty-printed, to stderr.",
    )
    return parser.parse_args(argv)


def _print_result(result, log_json):
    print(json.dumps(result))
    if log_json:
        print(json.dumps(result, indent=2), file=sys.stderr)


def main():
    args = parse_args()
    settings = resolve_settings(args)
    verbose = settings["verbose"]
    log_json = settings["log_json"]

    input_path = args.input_opt or args.input

    if not input_path:
        _log(verbose, "no input file provided")
        result = error_result(None, "invalid_input", "No input file provided (positional argument, --input, or \"-\" for stdin).")
        _print_result(result, log_json)
        sys.exit(1)

    _log(verbose, f"reading input from {'stdin' if input_path == '-' else input_path}")
    try:
        if input_path == "-":
            raw_text = sys.stdin.read()
        else:
            raw_text = Path(input_path).read_text(encoding="utf-8")
    except OSError as e:
        _log(verbose, f"failed to read input: {e}")
        result = error_result(None, "invalid_input", f"failed to read input file {input_path}: {e}")
        _print_result(result, log_json)
        sys.exit(1)

    try:
        step1 = json.loads(raw_text)
    except json.JSONDecodeError as e:
        _log(verbose, f"input is not valid JSON: {e}")
        result = error_result(None, "invalid_input", f"input file is not valid JSON: {e}")
        _print_result(result, log_json)
        output_path = next_output_path(settings["output_prefix"], settings["output_dir"])
        _write_output(output_path, result, verbose)
        sys.exit(1)

    if not isinstance(step1, dict):
        _log(verbose, "input JSON is not an object")
        result = error_result(None, "invalid_input", "Step 1 JSON must be an object.")
        _print_result(result, log_json)
        output_path = next_output_path(settings["output_prefix"], settings["output_dir"])
        _write_output(output_path, result, verbose)
        sys.exit(1)

    source_url = step1.get("url")
    html = step1.get("html")

    if not step1.get("ok", False) or html is None:
        _log(verbose, "Step 1 result had ok=false or no html field; skipping parse")
        result = error_result(source_url, "missing_html", "Step 1 result had ok=false or a null html field.")
    else:
        config = {
            "source_url": source_url,
            "selector": settings["selector"],
            "strip_whitespace": settings["strip_whitespace"],
            "verbose": verbose,
        }
        try:
            result = parse_html(html, config=config)
        except Exception as e:
            _log(verbose, f"unexpected error: {e}")
            result = error_result(source_url, "unknown_error", str(e))

    _print_result(result, log_json)
    output_path = next_output_path(settings["output_prefix"], settings["output_dir"])
    _write_output(output_path, result, verbose)


def _write_output(path, result, verbose=False):
    _log(verbose, f"writing output to {path}")
    try:
        path.write_text(json.dumps(result), encoding="utf-8")
    except OSError as e:
        print(f"warning: failed to write output file {path}: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
