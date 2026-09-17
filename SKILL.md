---
name: render-url
description: Render a URL in headless Chromium and extract structured JSON (title, headings, links, images, meta, text) from the rendered page. Use this whenever the task needs the post-JavaScript content of a web page — SPAs, JS-rendered content, or any page where a plain HTTP fetch would miss content added by client-side JS. Installs the `render-url` CLI from PyPI on first use. No LLM/AI is involved in the extraction itself — it is deterministic DOM parsing.
---

# render-url

A two-stage, deterministic CLI toolchain: render a URL in real Chromium (via Playwright), then extract structured data from the rendered HTML. No crawling, no LLM/AI-based interpretation — pure browser rendering + structural DOM parsing.

## Setup

Install the CLI from PyPI and the Chromium browser it drives. Do this once per environment; skip if `render-url --help` already succeeds.

```bash
pip install render-url
playwright install chromium
```

## Commands

### One-shot: render + extract in a single call (preferred for most tasks)

```bash
render-and-parse "https://example.com"
```

Prints one JSON object to stdout with the extracted structured data (title, headings, links, images, meta, text). Also writes `rendered_page_N.json` (raw render) and `parsed_page_N.json` (extracted data) to the current directory.

Useful flags:
- `--selector "<css>"` — scope extraction to one element (e.g. `--selector "article"`, `--selector "#main-content"`).
- `--timeout <ms>` — navigation timeout (default 30000).
- `--wait-until networkidle` — wait for network idle instead of the default `load` (use only if the page is known to settle onto a quiet network; SPAs with polling/websockets may hang).
- `--no-strip-whitespace` — preserve raw whitespace in extracted text instead of collapsing it.
- `--verbose` — log each pipeline step to stderr.
- `--log-json` — pretty-print the full result JSON to stderr as well.
- `--detect` — run deterministic page classification (see below) before rendering. Useful for job-application URLs, where the page may turn out to be a CAPTCHA, login wall, error page, closed job, or bot/security challenge instead of the actual application. If the page classifies as anything other than `APPLICATION`, parsing is skipped and the classification is returned instead of extracted page data.

### Application detection (`--detect`)

Runs entirely deterministic checks (no LLM/AI) against the rendered DOM and HTTP status: CAPTCHA, bot/security challenge (with a short navigate → wait → inspect → wait → inspect retry loop), login wall, HTTP/rendered error, closed/expired job, then an application-form evidence score. Output gains these fields:

```json
{
  "status": "APPLICATION",
  "reason": "application_form_detected",
  "detector": {
    "captcha": false,
    "login": false,
    "bot_challenge": false,
    "error": false,
    "closed_job": false,
    "form_detected": true
  },
  "form": {"count": 1, "inputs": 17, "textareas": 2, "selects": 3, "file_inputs": 1},
  "redirected": true
}
```

`status` is one of `APPLICATION`, `CAPTCHA`, `LOGIN`, `ERROR`, `CLOSED_JOB`, `BOT_CHALLENGE`, `NO_FORM`. When `status` is anything other than `APPLICATION`, `html`/`data` come back `null` — the page was never worth fully parsing. Thresholds, keyword lists, and challenge-wait timing are configurable via the `"detector"` section of `config.json` (see `config.example.json`).

### Two-stage: render and parse separately (when you need the raw HTML too)

```bash
render-url "https://example.com"              # -> rendered_page_1.json (includes raw "html" field)
parse-html rendered_page_1.json                # -> parsed_page_1.json (structured extraction)

# or piped, no intermediate file needed:
render-url "https://example.com" | parse-html -
```

`render-url` alone is useful when you need the raw post-JS HTML itself (e.g. to feed a different extraction step), not just the structured fields `parse-html` produces.

## Output schema (parse-html / render-and-parse)

```json
{
  "ok": true,
  "source_url": "https://example.com",
  "title": "Example Domain",
  "data": {
    "headings": [{"level": 1, "text": "Example Domain"}],
    "links": [{"text": "More information...", "href": "https://iana.org/domains/example"}],
    "images": [{"src": "...", "alt": "..."}],
    "meta": {"viewport": "width=device-width, initial-scale=1"},
    "text": "Example Domain This domain is for use in illustrative examples..."
  },
  "selector_matched": null,
  "error": null
}
```

On failure: `ok: false` and `error: {"type": "...", "message": "..."}`. Error types include `invalid_url`, `navigation_timeout`, `navigation_error`, `missing_html`, `invalid_config`, `parse_error`. Always check `ok` before reading `data`.

## Notes

- Exactly one URL per invocation — no crawling or link-following. To process multiple URLs, call the command once per URL.
- Output files (`rendered_page_N.json`, `parsed_page_N.json`) auto-increment and never overwrite existing files in the working directory — clean these up if not needed after use.
- All output is a single JSON object on stdout; diagnostics only ever go to stderr, so stdout is always safe to parse directly.
