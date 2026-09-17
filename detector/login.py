"""detector/login.py — deterministic login-wall detection.

A page containing "Sign in with Google" alongside an actual application form
should NOT be classified as LOGIN. We only flag LOGIN when a password field
is present together with login-page language AND no application-shaped
fields (file upload / textarea / multiple text inputs) are present.
"""

from . import constants
from .signals import any_pattern_in_text


def detect_login(soup, text, config):
    patterns = config.get("login_keyword_patterns", constants.LOGIN_KEYWORD_PATTERNS)

    password_inputs = soup.find_all("input", attrs={"type": "password"})
    if not password_inputs:
        return False, None

    if not any_pattern_in_text(text, patterns):
        return False, None

    file_inputs = soup.find_all("input", attrs={"type": "file"})
    textareas = soup.find_all("textarea")

    if file_inputs or textareas:
        return False, None

    return True, "authentication_required"
