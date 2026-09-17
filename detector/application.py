"""detector/application.py — deterministic application-form scoring.

Builds a positive/negative evidence score from DOM shape, then subtracts
penalties for signals owned by the other detectors (login/captcha/error/
closed_job), which the caller passes in as booleans it already computed.
"""

from . import constants
from .signals import any_pattern_in_text, field_or_label_matches, normalized_text


def _form_stats(soup):
    forms = soup.find_all("form")
    inputs = soup.find_all("input")
    textareas = soup.find_all("textarea")
    selects = soup.find_all("select")
    file_inputs = soup.find_all("input", attrs={"type": "file"})
    return {
        "count": len(forms),
        "inputs": len(inputs),
        "textareas": len(textareas),
        "selects": len(selects),
        "file_inputs": len(file_inputs),
    }


def score_application(soup, text, penalties, config):
    """penalties: dict of {login, captcha, error, closed_job} -> bool."""
    weights = config.get("application_score_weights", constants.APPLICATION_SCORE_WEIGHTS)

    score = 0
    evidence = []

    def add(key, condition):
        nonlocal score
        if condition:
            score += weights[key]
            evidence.append(key)

    inputs = soup.find_all("input")
    email_inputs = [i for i in inputs if (i.get("type") or "").lower() == "email"]
    text_inputs = [i for i in inputs if (i.get("type") or "text").lower() == "text"]
    file_inputs = [i for i in inputs if (i.get("type") or "").lower() == "file"]
    tel_inputs = [i for i in inputs if (i.get("type") or "").lower() == "tel"]
    textareas = soup.find_all("textarea")
    selects = soup.find_all("select")
    forms = soup.find_all("form")

    add("email_input", bool(email_inputs))
    add("text_input", bool(text_inputs))
    add("textarea", bool(textareas))
    add("file_input", bool(file_inputs))
    add("select", bool(selects))

    form_kw = config.get("application_form_keywords", constants.APPLICATION_FORM_KEYWORDS)
    application_form = any(
        any_pattern_in_text(
            " ".join(str(f.get(attr, "")) for attr in ("action", "id", "class")).lower(), form_kw
        )
        for f in forms
    )
    add("application_form", application_form)

    phone_kw = config.get("phone_field_keywords", constants.PHONE_FIELD_KEYWORDS)
    phone_field = bool(tel_inputs) or any(
        field_or_label_matches(i, soup, phone_kw) for i in inputs
    )
    add("phone_field", phone_field)

    resume_kw = config.get("resume_field_keywords", constants.RESUME_FIELD_KEYWORDS)
    resume_field = any(field_or_label_matches(i, soup, resume_kw) for i in inputs)
    add("resume_field", resume_field)

    cover_kw = config.get("cover_letter_field_keywords", constants.COVER_LETTER_FIELD_KEYWORDS)
    cover_letter_field = any(
        field_or_label_matches(i, soup, cover_kw) for i in (inputs + textareas)
    )
    add("cover_letter_field", cover_letter_field)

    first_name_kw = config.get("first_name_field_keywords", constants.FIRST_NAME_FIELD_KEYWORDS)
    first_name_field = any(field_or_label_matches(i, soup, first_name_kw) for i in inputs)
    add("first_name_field", first_name_field)

    last_name_kw = config.get("last_name_field_keywords", constants.LAST_NAME_FIELD_KEYWORDS)
    last_name_field = any(field_or_label_matches(i, soup, last_name_kw) for i in inputs)
    add("last_name_field", last_name_field)

    work_auth_patterns = config.get("work_auth_text_patterns", constants.WORK_AUTH_TEXT_PATTERNS)
    add("work_authorization", any_pattern_in_text(text, work_auth_patterns))

    linkedin_kw = config.get("linkedin_field_keywords", constants.LINKEDIN_FIELD_KEYWORDS)
    linkedin_field = any(field_or_label_matches(i, soup, linkedin_kw) for i in inputs)
    add("linkedin_field", linkedin_field)

    add("login_penalty", penalties.get("login", False))
    add("captcha_penalty", penalties.get("captcha", False))
    add("error_penalty", penalties.get("error", False))
    add("closed_job_penalty", penalties.get("closed_job", False))

    return score, evidence, _form_stats(soup)
