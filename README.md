# PlaywrightURLJsonExtractor — Step 1: URL → Rendered HTML JSON

A small, deterministic utility that renders **one URL** in a real Chromium
browser (via Playwright) and emits **one JSON object** containing the
post-JavaScript DOM as HTML.

```
URL -> Playwright -> Chromium -> JS/WASM execution -> rendered DOM -> HTML -> JSON
```

There is **no LLM, AI model, agent reasoning, or semantic HTML
interpretation** anywhere in this component. It captures the DOM; it does
not understand it.

## Why the Playwright Python library instead of a shell CLI command

The installed `playwright` CLI (`playwright --help`) only exposes
`open`, `codegen`, `install`, `screenshot`, `pdf`, `show-trace`, etc. There
is no built-in CLI subcommand that navigates a URL, waits deterministically,
evaluates JS to pull `outerHTML`, and prints structured JSON. Per the task
constraints (no `requests`/`urllib`/`curl`/BeautifulSoup-on-raw-HTTP), the
official Playwright *library* (same package the CLI ships from,
`playwright==1.58.0` here) is used to script Chromium directly — this is
the officially supported way to drive the actual rendering operation
(`page.goto`, `page.evaluate("document.documentElement.outerHTML")`,
`browser.close()`), not a workaround.

## Install

```bash
pip install -r requirements.txt
playwright install chromium
```

## Usage

```bash
python render_url.py "https://example.com"
python render_url.py "https://example.com" --timeout 45000
python render_url.py "https://example.com" --output-prefix page --output-dir out/
python render_url.py --config my_config.json
```

Exactly one URL per invocation. No crawling, no link-following, no
multi-URL batching.

Every invocation, success or failure, writes the same JSON object to a new
auto-incremented file — `rendered_page_1.json`, `rendered_page_2.json`, ...
— in the current directory by default, in addition to printing it to
stdout. Existing files are never overwritten; the number keeps advancing
across runs. Use `--output-prefix` to change the base name and
`--output-dir` to change the directory.

## Configuration

Every setting can come from three places, in increasing priority:

```text
built-in defaults  <  config.json  <  command-line flags
```

i.e. a CLI flag always wins over the config file, and the config file always
wins over the built-in default.

### Config file

By default the tool looks for `config.json` next to `render_url.py` (use
`--config <path>` to point at a different file). It's optional — if it
doesn't exist, built-in defaults are used. All keys are optional; unknown
keys cause the tool to exit with an error (to catch typos).

`config.json` is gitignored since it's local/per-environment. Copy the
tracked [config.example.json](config.example.json) to get started:

```bash
cp config.example.json config.json
```

```json
{
  "url": "https://example.com",
  "timeout_ms": 30000,
  "stabilization_ms": 1000,
  "wait_until": "load",
  "headless": true,
  "output_prefix": "rendered_page",
  "output_dir": "."
}
```

| Key                | Type          | Default          | Meaning                                                                 |
|--------------------|---------------|------------------|--------------------------------------------------------------------------|
| `url`              | string        | *(none)*         | URL to render if none is given on the command line.                     |
| `timeout_ms`       | integer       | `30000`          | Overall navigation timeout in milliseconds.                             |
| `stabilization_ms` | integer       | `1000`           | Fixed settle time (ms) after load, before the DOM is captured.          |
| `wait_until`       | string        | `"load"`         | Load state to wait for: `"load"`, `"domcontentloaded"`, or `"networkidle"`. |
| `headless`         | boolean       | `true`           | Run Chromium headless (`false` opens a visible window).                 |
| `output_prefix`    | string        | `"rendered_page"`| Base name for the auto-incremented output file.                         |
| `output_dir`       | string        | `"."`            | Directory the output file is written into.                              |

### Command-line flags

| Flag               | Overrides config key | Example                          |
|---------------------|----------------------|-----------------------------------|
| `url` (positional)  | `url`                | `python render_url.py "https://example.com"` |
| `--config <path>`   | *(selects which config file is read)* | `--config staging.json` |
| `--timeout <ms>`    | `timeout_ms`         | `--timeout 45000`                 |
| `--stabilization <ms>` | `stabilization_ms` | `--stabilization 2000`          |
| `--wait-until <state>` | `wait_until`       | `--wait-until networkidle`        |
| `--headless` / `--no-headless` | `headless` | `--no-headless`                   |
| `--output-prefix <name>` | `output_prefix`  | `--output-prefix page`            |
| `--output-dir <dir>`| `output_dir`         | `--output-dir out/`               |

The `url` positional argument is optional on the command line only because
it can instead come from the config file's `"url"` key; if neither is
supplied, the tool returns a structured `invalid_url` error.

`--wait-until networkidle` is available for pages known to settle onto a
quiet network, but is not the default — see [Waiting strategy](#waiting-strategy)
for why.

### Piping into another program

```bash
python render_url.py "https://example.com" | python -c "import sys,json; print(json.load(sys.stdin)['title'])"
python render_url.py "https://example.com"   # also writes rendered_page_1.json
python -c "import json; x=json.load(open('rendered_page_1.json')); print(len(x['html']))"
```

## Waiting strategy

1. Navigate with `wait_until="domcontentloaded"`.
2. Additionally wait for the `load` event (best-effort, does not fail the
   run if it times out).
3. Allow a fixed 1000ms stabilization period for post-load JS (SPA
   hydration, async rendering) to settle.
4. Capture `document.documentElement.outerHTML` via `page.evaluate`.
5. The entire navigation is bounded by `--timeout` (default 30000ms,
   configurable). `networkidle` is deliberately **not** used as the primary
   wait condition — SPAs with polling/websockets/long-lived connections may
   never reach network idle, which would hang the run indefinitely.
6. On timeout, a structured `navigation_timeout` error is returned instead
   of hanging.

## Output schema

Success:

```json
{
  "ok": true,
  "url": "https://example.com",
  "final_url": "https://example.com/",
  "status_code": 200,
  "title": "Example Domain",
  "html": "<html>...</html>",
  "error": null
}
```

Failure:

```json
{
  "ok": false,
  "url": "https://bad-url",
  "final_url": null,
  "status_code": null,
  "title": null,
  "html": null,
  "error": {
    "type": "invalid_url",
    "message": "URL must be an absolute http(s) URL."
  }
}
```

Error `type` values: `invalid_url`, `navigation_error`,
`navigation_timeout`, `browser_error`, `html_extraction_error`,
`unknown_error`.

Exactly one JSON object is printed to stdout, on both success and failure —
never a traceback, never log lines mixed into stdout. Diagnostic output (if
any) goes to stderr only.

## Session lifecycle

Each invocation launches its own Chromium instance and page, and closes the
browser in a `finally` block before the process exits — no session reuse,
no orphaned processes.

## What this project intentionally does NOT do

- No crawling or link-following.
- No DOM mutation, clicking, scrolling-for-extraction, form submission,
  authentication, or CAPTCHA solving.
- No HTML parsing/structuring (that is Step 2's job, operating on the
  `html` field of this tool's output — kept fully independent).
- No LLM or AI usage of any kind.

## Tests

```bash
python -m pytest tests/ -v
```

See `tests/test_renderer.py` for the covered cases: static HTML, JS-rendered
content, redirects, invalid URLs, timeouts, and a WASM page (recorded
behavior, not assumed).
