"""detector/classify.py — orchestrates the deterministic page-classification checks.

Pure function over already-fetched HTML (no Playwright dependency here; the
navigate -> wait -> inspect -> wait -> inspect challenge-resolution loop
lives in render_url.py, which calls classify() once per inspection).

Priority order (first match wins), matching the priority a human triaging
these pages would use: a CAPTCHA or bot challenge blocks everything else
from being visible, a login wall blocks the application, then error/closed
job, then the application-form score decides APPLICATION vs NO_FORM.
"""

from bs4 import BeautifulSoup

from . import constants
from .application import score_application
from .bot_challenge import detect_bot_challenge
from .captcha import detect_captcha
from .closed_job import detect_closed_job
from .errors import detect_error
from .login import detect_login
from .signals import normalized_text


def classify(html, status_code=None, config=None):
    """Classify rendered HTML into one ApplicationStatus value.

    Returns a dict:
      {
        "status": one of constants.ALL_STATUSES,
        "reason": short machine-readable reason string or None,
        "detector": {"captcha": bool, "login": bool, "bot_challenge": bool,
                      "error": bool, "closed_job": bool, "form_detected": bool},
        "provider": bot-challenge provider name or None,
        "score": application score (int),
        "form": {"count", "inputs", "textareas", "selects", "file_inputs"},
      }
    """
    config = config or {}
    soup = BeautifulSoup(html, "html.parser")
    text = normalized_text(soup)

    captcha, captcha_reason = detect_captcha(soup, text, config)
    bot_challenge, provider = detect_bot_challenge(soup, text, config)
    login, login_reason = detect_login(soup, text, config)
    error, error_reason = detect_error(status_code, text, config)
    closed_job, closed_job_reason = detect_closed_job(text, config)

    score, evidence, form_stats = score_application(
        soup, text,
        penalties={"login": login, "captcha": captcha, "error": error, "closed_job": closed_job},
        config=config,
    )

    threshold = config.get("threshold", constants.APPLICATION_SCORE_THRESHOLD_DEFAULT)
    form_detected = score >= threshold

    detector = {
        "captcha": captcha,
        "login": login,
        "bot_challenge": bot_challenge,
        "error": error,
        "closed_job": closed_job,
        "form_detected": form_detected,
    }

    if captcha:
        status, reason = constants.STATUS_CAPTCHA, captcha_reason
    elif bot_challenge:
        status, reason = constants.STATUS_BOT_CHALLENGE, "security_challenge_detected"
    elif login:
        status, reason = constants.STATUS_LOGIN, login_reason
    elif error:
        status, reason = constants.STATUS_ERROR, error_reason
    elif closed_job:
        status, reason = constants.STATUS_CLOSED_JOB, closed_job_reason
    elif form_detected:
        status, reason = constants.STATUS_APPLICATION, "application_form_detected"
    else:
        status, reason = constants.STATUS_NO_FORM, "no_application_form_detected"

    return {
        "status": status,
        "reason": reason,
        "detector": detector,
        "provider": provider,
        "score": score,
        "evidence": evidence,
        "form": form_stats,
    }
