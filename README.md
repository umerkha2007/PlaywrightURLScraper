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
| Detect | `--detect` | off | Check what kind of page this actually is before returning HTML. See [Detecting what kind of page you got](#detecting-what-kind-of-page-you-got) below. |

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
| Detect | `--detect` | off | Check what kind of page this actually is before parsing it. See [Detecting what kind of page you got](#detecting-what-kind-of-page-you-got) below. |

### Detecting what kind of page you got

Some URLs — job application links especially — don't lead where you expect. You might land on a CAPTCHA, a login screen, a "this job is closed" page, an error page, or a bot-blocking screen like Cloudflare's "Checking your browser..." interstitial, instead of the actual page you wanted.

Passing `--detect` tells the tool to figure out which of these it landed on **before** handing you back the page content — using simple, predictable rules (checking for password fields, CAPTCHA widgets, known error/closed-job wording, and so on). No AI is involved; it's the same kind of exact, repeatable checking as everything else in this project.

```bash
render-url "https://example.com/job/123" --detect
render-and-parse "https://example.com/job/123" --detect
```

The result gets a `status` field telling you what was found:

| `status` | Meaning |
|---|---|
| `APPLICATION` | Looks like a real application form. The page's HTML (or parsed data, for `render-and-parse`) is included as usual. |
| `CAPTCHA` | Blocked by a CAPTCHA. |
| `LOGIN` | You'd need to sign in first. |
| `ERROR` | An error page (404, 500, "something went wrong", etc). |
| `CLOSED_JOB` | The job posting says it's closed, filled, or expired. |
| `BOT_CHALLENGE` | A bot-protection screen (e.g. Cloudflare) that didn't clear after a short wait. |
| `NO_FORM` | The page loaded fine, but nothing that looks like an application form was found. |

For anything other than `APPLICATION`, the HTML/parsed data comes back empty (`null`) — there was no point extracting it. You also get a `detector` object showing exactly which checks fired (`captcha`, `login`, `bot_challenge`, `error`, `closed_job`, `form_detected`), and a plain-text `reason` for the classification. This means downstream automation (or a human) can tell at a glance whether it's worth doing anything further with this URL, without having to read the page.

`--detect` is entirely optional — leave it off and both tools behave exactly as before.

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
  "detect": false,
  "parser": {
    "selector": null,
    "strip_whitespace": true,
    "output_prefix": "parsed_page",
    "output_dir": ".",
    "verbose": false,
    "log_json": false
  },
  "detector": {
    "threshold": 10,
    "challenge_wait_ms": 2000,
    "challenge_max_checks": 2
  }
}
```

The `"detector"` section only matters if you use `--detect`. `challenge_wait_ms`/`challenge_max_checks` control how long it waits and re-checks a page that looks like a bot-blocking screen before giving up. You can leave this section out entirely to use the sensible defaults shown above.

**About `threshold`:** every page gets a score built from evidence found in its form fields (an email input is worth 5 points, a resume upload 5, a "first name" field 2, and so on — see `detector/constants.py` for the full list). `threshold` is the minimum score a page needs to be called `APPLICATION` instead of `NO_FORM`.

- **Minimum useful value: `1`.** Anything this low means almost any form on the page (even a simple newsletter signup with just an email field) gets called an application — too loose to trust.
- **Maximum meaningful value: `45`.** That's the total score a page could ever get if it had every single positive signal the scorer looks for. Setting the threshold at or above this makes `APPLICATION` nearly impossible to reach, even for real, complete application forms — too strict to be useful.
- **Ideal / default: `10`.** In practice, a real job application form easily scores 20–30+ (email + text fields + textarea + file upload alone is already 20), while a stray contact form or newsletter box scores well under 10. `10` gives enough headroom to reject those false positives while still catching applications that are missing a field or two.

If you're seeing real application pages misclassified as `NO_FORM`, lower the threshold a bit (e.g. `7`–`8`). If unrelated forms (contact forms, search bars, sign-up boxes) are being misclassified as `APPLICATION`, raise it (e.g. `12`–`15`). Going far outside the `1`–`45` range defeats the point of having a threshold at all.

## Output schemas

**`render-url` success:**
```json
{"ok": true, "url": "...", "final_url": "...", "status_code": 200, "title": "...", "html": "...", "error": null}
```
Errors: `invalid_url`, `navigation_error`, `navigation_timeout`, `browser_error`, `html_extraction_error`, `unknown_error`, `detection_error`.

**`render-url` with `--detect`** adds these fields (see [Detecting what kind of page you got](#detecting-what-kind-of-page-you-got)):
```json
{
  "ok": true, "url": "...", "final_url": "...", "status_code": 200, "title": "...",
  "html": "...",
  "status": "APPLICATION",
  "reason": "application_form_detected",
  "redirected": false,
  "detector": {"captcha": false, "login": false, "bot_challenge": false, "error": false, "closed_job": false, "form_detected": true},
  "form": {"count": 1, "inputs": 17, "textareas": 2, "selects": 3, "file_inputs": 1},
  "error": null
}
```
`html` is `null` whenever `status` isn't `APPLICATION`.

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

When `render-and-parse` is run with `--detect` and the page isn't classified as `APPLICATION`, `data` comes back `null` and the same `status`/`reason`/`detector`/`form`/`redirected` fields as above are included instead.

Both tools always print exactly one JSON object to stdout (success or failure) — diagnostics go to stderr only.

## What this project intentionally does NOT do

- No crawling, link-following, or multi-URL batching.
- No DOM mutation, clicking, form submission, or authentication.
- No LLM, AI, embeddings, or semantic interpretation — structural extraction and rule-based classification only.
- No solving or bypassing CAPTCHAs or bot-protection challenges — `--detect` only tells you one is there.
- `parse-html` makes no network calls and never launches a browser.
