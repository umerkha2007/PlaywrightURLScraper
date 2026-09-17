"""detector/config.py — loads the "detector" section of the shared config.json.

Mirrors parse_html.py's "parser" section pattern: render_url.py owns the
top-level flat keys, parse_html.py owns "parser", this owns "detector". All
three tools can share one config.json.
"""

import json
from pathlib import Path

from . import constants

DEFAULTS = {
    "threshold": constants.APPLICATION_SCORE_THRESHOLD_DEFAULT,
    "challenge_wait_ms": constants.CHALLENGE_WAIT_MS_DEFAULT,
    "challenge_max_checks": constants.CHALLENGE_MAX_CHECKS_DEFAULT,
    "captcha_text_patterns": constants.CAPTCHA_TEXT_PATTERNS,
    "captcha_iframe_src_patterns": constants.CAPTCHA_IFRAME_SRC_PATTERNS,
    "bot_challenge_text_patterns": constants.BOT_CHALLENGE_TEXT_PATTERNS,
    "bot_challenge_provider_hints": constants.BOT_CHALLENGE_PROVIDER_HINTS,
    "login_keyword_patterns": constants.LOGIN_KEYWORD_PATTERNS,
    "error_http_status_codes": constants.ERROR_HTTP_STATUS_CODES,
    "error_text_patterns": constants.ERROR_TEXT_PATTERNS,
    "closed_job_text_patterns": constants.CLOSED_JOB_TEXT_PATTERNS,
    "application_form_keywords": constants.APPLICATION_FORM_KEYWORDS,
    "resume_field_keywords": constants.RESUME_FIELD_KEYWORDS,
    "cover_letter_field_keywords": constants.COVER_LETTER_FIELD_KEYWORDS,
    "first_name_field_keywords": constants.FIRST_NAME_FIELD_KEYWORDS,
    "last_name_field_keywords": constants.LAST_NAME_FIELD_KEYWORDS,
    "work_auth_text_patterns": constants.WORK_AUTH_TEXT_PATTERNS,
    "linkedin_field_keywords": constants.LINKEDIN_FIELD_KEYWORDS,
    "phone_field_keywords": constants.PHONE_FIELD_KEYWORDS,
    "application_score_weights": constants.APPLICATION_SCORE_WEIGHTS,
}


def load_detector_config(path):
    """Read the shared config file's "detector" section, defaults for anything absent."""
    settings = dict(DEFAULTS)

    p = Path(path)
    if not p.exists():
        return settings

    try:
        with p.open(encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise SystemExit(f"error: failed to read config file {path}: {e}")
    if not isinstance(data, dict):
        raise SystemExit(f"error: config file {path} must contain a JSON object.")

    section = data.get("detector", {})
    if not isinstance(section, dict):
        raise SystemExit(f"error: \"detector\" section in {path} must be a JSON object.")

    unknown = set(section) - set(DEFAULTS)
    if unknown:
        raise SystemExit(
            f"error: unknown detector config key(s) in {path}: {', '.join(sorted(unknown))}"
        )

    settings.update(section)
    return settings
