# PlaywrightURLJsonExtractor

Two independent, deterministic CLI tools — no LLM/AI, no crawling:

- **`render-url`** — renders one URL in headless Chromium (via Playwright) and outputs the post-JS DOM as JSON.
- **`parse-html`** — parses the `html` field from `render-url`'s output into structured JSON (via BeautifulSoup4).

```
URL -> render-url -> rendered JSON (html field) -> parse-html -> structured JSON
```

## Install

```bash
pip install -e .
playwright install chromium
```

This puts `render-url` and `parse-html` on your `PATH`.

## Commands

### `render-url` — render a URL to JSON

```bash
render-url "https://example.com"
```

Prints one JSON object to stdout and writes it to an auto-incremented file (`rendered_page_1.json`, `rendered_page_2.json`, ...). Never overwrites existing files.

| Parameter | Flag | Default | Description |
|---|---|---|---|
| URL | positional, or `url` in config | *(none)* | The single URL to render. Required (from CLI or config). |
| Config file | `--config <path>` | `config.json` | Path to the JSON config file. |
| Timeout | `--timeout <ms>` | `30000` | Overall navigation timeout in milliseconds. |
| Stabilization | `--stabilization <ms>` | `1000` | Fixed settle time (ms) after load, before capturing the DOM. |
| Wait condition | `--wait-until <state>` | `load` | `load`, `domcontentloaded`, or `networkidle`. |
| Headless | `--headless` / `--no-headless` | `--headless` | Run Chromium headless or with a visible window. |
| Output prefix | `--output-prefix <name>` | `rendered_page` | Base name for the output JSON file. |
| Output dir | `--output-dir <dir>` | `.` | Directory the output file is written into. |
| Verbose | `--verbose` / `-v` | off | Log progress (navigation, waits, extraction, browser lifecycle) to stderr. Stdout still carries only the final JSON. |
| Log JSON | `--log-json` | off | Additionally pretty-print the final result JSON to stderr. |

### `parse-html` — extract structured data from rendered HTML

```bash
parse-html rendered_page_1.json
```

Reads a `render-url` JSON file (or stdin via `-`), extracts fields from its `html`, prints one JSON object to stdout, and writes it to an auto-incremented file (`parsed_page_1.json`, `parsed_page_2.json`, ...).

| Parameter | Flag | Default | Description |
|---|---|---|---|
| Input file | positional, or `--input <path>` | *(none)* | `render-url` JSON file to read. Use `-` for stdin. |
| Config file | `--config <path>` | `config.json` | Path to the JSON config file (reads its `"parser"` section). |
| CSS selector | `--selector <css>` | `null` | Scopes `headings`/`links`/`images`/`text` to the first matching element. No match -> those fields come back empty, not an error. |
| Whitespace | `--no-strip-whitespace` | strip on | Disable whitespace collapsing in extracted text. |
| Output prefix | `--output-prefix <name>` | `parsed_page` | Base name for the output JSON file. |
| Output dir | `--output-dir <dir>` | `.` | Directory the output file is written into. |
| Verbose | `--verbose` / `-v` | off | Log progress (input loading, extraction steps, field counts) to stderr. Stdout still carries only the final JSON. |
| Log JSON | `--log-json` | off | Additionally pretty-print the final result JSON to stderr. |

### Extracted fields

| Field | What it is | Fallback |
|---|---|---|
| `title` | `<title>` text | `null` if absent/empty |
| `headings` | `<h1>`–`<h6>`, in order | `[]` if none |
| `links` | `<a href>` text + href, in order (duplicates kept) | anchors without `href` excluded |
| `images` | `<img src>` + `alt`, in order | `alt` defaults to `""`; no `src` excluded |
| `meta` | `<meta name/property>` -> `content` | later tag wins on duplicate keys |
| `text` | visible body text (scripts/styles excluded) | `""` if none |

### `render-and-parse` — do both in one command

```bash
render-and-parse "https://example.com"
```

Runs `render-url` then `parse-html` in a single process and prints the final structured JSON. Writes both `rendered_page_N.json` and `parsed_page_N.json`.

| Parameter | Flag | Default | Description |
|---|---|---|---|
| URL | positional | *(none)* | The URL to render and parse. |
| Config file | `--config <path>` | `config.json` | Shared config file for both stages. |
| Timeout | `--timeout <ms>` | `30000` | Render-stage navigation timeout. |
| Stabilization | `--stabilization <ms>` | `1000` | Render-stage settle time. |
| Wait condition | `--wait-until <state>` | `load` | Render-stage load state. |
| Headless | `--headless` / `--no-headless` | `--headless` | Render-stage Chromium visibility. |
| CSS selector | `--selector <css>` | `null` | Parse-stage extraction scope. |
| Whitespace | `--no-strip-whitespace` | strip on | Parse-stage whitespace handling. |
| Output dir | `--output-dir <dir>` | `.` | Directory for both output files. |
| Verbose | `--verbose` / `-v` | off | Log progress from both stages to stderr. |
| Log JSON | `--log-json` | off | Additionally pretty-print the render stage and final result JSON to stderr. |

### Full pipeline manually (two commands)

```bash
render-url "https://example.com"
parse-html rendered_page_1.json

# or piped:
render-url "https://example.com" | parse-html -
```

### Tests

```bash
python -m pytest tests/ -v
```

### Publishing to PyPI

```bash
pip install build twine

# bump "version" in pyproject.toml first, then:
rm -rf dist build render_url.egg-info    # PowerShell: Remove-Item -Recurse -Force dist, build, render_url.egg-info -ErrorAction SilentlyContinue
python -m build                # builds dist/*.whl and dist/*.tar.gz
python -m twine check dist/*   # validates metadata before upload
python -m twine upload dist/*  # uploads to PyPI (prompts for credentials/token)
```

Use `python -m twine upload --repository testpypi dist/*` to publish to [TestPyPI](https://test.pypi.org/) first if you want to verify the package before a real release.

## Configuration

Precedence: **built-in defaults < `config.json` < CLI flags**. Both tools share one `config.json` (`parse-html` only reads its `"parser"` key). Copy [config.example.json](config.example.json) to get started — `config.json` is gitignored (local/per-environment). Unknown keys are rejected as typos.

```json
{
  "url": "https://example.com",
  "timeout_ms": 30000,
  "stabilization_ms": 1000,
  "wait_until": "load",
  "headless": true,
  "output_prefix": "rendered_page",
  "output_dir": ".",
  "verbose": false,
  "log_json": false,
  "parser": {
    "selector": null,
    "strip_whitespace": true,
    "output_prefix": "parsed_page",
    "output_dir": ".",
    "verbose": false,
    "log_json": false
  }
}
```

## Output schemas

**`render-url` success:**
```json
{"ok": true, "url": "...", "final_url": "...", "status_code": 200, "title": "...", "html": "...", "error": null}
```
Errors: `invalid_url`, `navigation_error`, `navigation_timeout`, `browser_error`, `html_extraction_error`, `unknown_error`.

**`parse-html` success:**
```json
{
  "ok": true,
  "source_url": "...",
  "title": "...",
  "data": {"headings": [...], "links": [...], "images": [...], "meta": {...}, "text": "..."},
  "selector_matched": null,
  "error": null
}
```
Errors: `invalid_input`, `missing_html` (Step 1 failed or had no `html`), `invalid_config`, `parse_error`, `unknown_error`.

Both tools always print exactly one JSON object to stdout (success or failure) — diagnostics go to stderr only.

## What this project intentionally does NOT do

- No crawling, link-following, or multi-URL batching.
- No DOM mutation, clicking, form submission, or authentication.
- No LLM, AI, embeddings, or semantic interpretation — structural extraction only.
- `parse-html` makes no network calls and never launches a browser.
