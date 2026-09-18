"""
qa.py — LLM-based application-question extraction and answering (Step 3, optional).

Given a parsed page's extracted text (from parse_html.py) and a candidate's
resume (resume.md), asks an LLM (Anthropic Claude by default) to:

1. Identify the application/screening questions asked on the page.
2. Answer each one using the resume as the candidate's source of truth.

Unlike render_url.py and parse_html.py, this module DOES call out to an LLM
and DOES make network calls. It is only invoked when explicitly requested
(--answer-questions / config "answer_questions": true), so both other tools
remain deterministic and offline by default.

This mirrors QuestionsExtractor/extract_questions.py's approach (same model
aliases, same .env-based API key loading) but operates on a single already-
parsed page in-process, instead of batch-processing a links_applied_by_date.json
file of many jobs.
"""

import json
import os
import re
import time
from pathlib import Path


DEFAULT_RESUME_PATH = "resume.md"
DEFAULT_PROVIDER = "anthropic"
DEFAULT_MAX_CHARS = 8000
DEFAULT_MAX_RETRIES = 3

MODEL_ALIASES = {
    "opus5": "claude-opus-5",
    "sonnet5": "claude-sonnet-5",
    "fable5.1": "claude-fable-5-1",
    "fable5-1": "claude-fable-5-1",
    "haiku4.5": "claude-haiku-4-5-20251001",
    "haiku4-5": "claude-haiku-4-5-20251001",
    "sonnet4.5": "claude-sonnet-4-5-20250929",
    "sonnet4": "claude-sonnet-4-20250514",
    "opus4.1": "claude-opus-4-1-20250805",
    "opus4": "claude-opus-4-20250514",
    "sonnet3.7": "claude-3-7-sonnet-20250219",
    "sonnet3.5": "claude-3-5-sonnet-20241022",
    "haiku3.5": "claude-3-5-haiku-20241022",
    "opus3": "claude-3-opus-20240229",
    "haiku3": "claude-3-haiku-20240307",
}
DEFAULT_MODEL_SHORTNAME = "sonnet5"


def load_dotenv(path=".env"):
    """Minimal .env loader: sets os.environ from KEY=VALUE lines, without
    overriding variables already set in the real environment."""
    env_path = Path(path)
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def resolve_model(name):
    """Translate a short model name (e.g. "sonnet5") to its real Anthropic
    model ID. Values not found in the table are assumed to already be a
    full model ID and are returned unchanged."""
    key = (name or "").strip().lower()
    return MODEL_ALIASES.get(key, name)


PROMPT = """You are helping a job applicant answer the application/screening questions on a
scraped job-application web page, using their resume as ground truth.

The JSON object below has already been parsed from the page (fields shown in text form),
followed by the candidate's resume in Markdown.

1. Identify the exact application/screening questions asked on the page (e.g. "Where are you
   currently based?", "Are you legally authorized to work in Canada?", "Years of experience
   writing Python?"). Include ONLY real form questions posed to an applicant -- not rhetorical
   marketing questions from a job description. If none, return [].
2. For each question, write a concise, truthful answer grounded in the resume. If the resume
   does not contain enough information to answer confidently, set "answer" to null instead of
   guessing.

Return ONLY a JSON object of the form:
{{"application_questions": ["...", ...], "answers": [{{"question": "...", "answer": "..."}}, ...]}}
Do not include any prose outside the JSON.

Page JSON:
{page_json}

Resume (Markdown):
{resume}
"""


def load_resume(path):
    resume_path = Path(path)
    if not resume_path.exists():
        raise FileNotFoundError(
            f"resume file not found: {resume_path} (create it, or point --resume / \"resume_path\" "
            f"at your resume in Markdown)"
        )
    text = resume_path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"resume file is empty: {resume_path}")
    return text


def parse_llm_json(raw):
    raw = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", raw, re.S)
    if fence:
        raw = fence.group(1)
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        raw = raw[start : end + 1]
    return json.loads(raw)


def build_anthropic_client(api_key):
    import anthropic

    return anthropic.Anthropic(api_key=api_key)


def get_provider_client(provider, api_key, model):
    if provider == "anthropic":
        return {"client": build_anthropic_client(api_key), "model": model}
    raise ValueError(f"Unsupported provider: {provider}")


def answer_questions(page_title, source_url, page_text, resume_text, provider, max_chars=DEFAULT_MAX_CHARS,
                      max_retries=DEFAULT_MAX_RETRIES, backoff=5.0):
    """Ask the LLM to extract application questions from the page and answer them from
    the resume. Returns {"application_questions": [...], "answers": [{"question", "answer"}]}."""
    client, model = provider["client"], provider["model"]
    text = page_text or ""
    if max_chars and len(text) > max_chars:
        text = text[:max_chars]
    page_json = json.dumps({"title": page_title, "source_url": source_url, "text": text}, ensure_ascii=False)
    user_content = PROMPT.format(page_json=page_json, resume=resume_text)

    last = None
    for attempt in range(1, max_retries + 1):
        try:
            resp = client.messages.create(
                model=model,
                max_tokens=2000,
                system="You extract structured data from web pages and answer job-application questions "
                       "truthfully from a resume. Always respond with valid JSON only.",
                messages=[{"role": "user", "content": user_content}],
            )
            raw = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
            result = parse_llm_json(raw)
            if not isinstance(result.get("application_questions"), list) or not isinstance(result.get("answers"), list):
                raise ValueError("LLM response missing expected lists")
            return result
        except Exception as e:  # noqa: BLE001 - retry on any transient failure
            last = e
            if attempt < max_retries:
                time.sleep(backoff * attempt)
    raise RuntimeError(f"LLM question-answering failed after {max_retries} attempts: {last}")


def run(page_title, source_url, page_text, settings):
    """High-level entry point used by parse_html.py / render_and_parse.py.

    `settings` is a dict with keys: resume_path, provider, api_key, model, max_chars,
    max_retries. Returns the answer_questions() result dict, or raises on failure
    (missing resume, missing API key, LLM error) so the caller can decide how to report it.
    """
    load_dotenv()
    resume_text = load_resume(settings.get("resume_path") or DEFAULT_RESUME_PATH)

    provider_name = settings.get("provider") or os.environ.get("LLM_PROVIDER", DEFAULT_PROVIDER)
    if provider_name != "anthropic":
        raise ValueError(f"Unsupported qa provider: {provider_name} (only 'anthropic' is currently implemented)")

    api_key = settings.get("api_key") or os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise ValueError("Missing API key: pass --qa-api-key or set ANTHROPIC_API_KEY")

    model = resolve_model(settings.get("model") or os.environ.get("ANTHROPIC_MODEL", DEFAULT_MODEL_SHORTNAME))
    provider = get_provider_client(provider_name, api_key, model)

    return answer_questions(
        page_title,
        source_url,
        page_text,
        resume_text,
        provider,
        max_chars=settings.get("max_chars", DEFAULT_MAX_CHARS),
        max_retries=settings.get("max_retries", DEFAULT_MAX_RETRIES),
    )
