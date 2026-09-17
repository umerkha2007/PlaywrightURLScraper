"""detector/errors.py — deterministic error-page detection.

Checks both HTTP status and rendered text, since some ATS systems return
HTTP 200 with an error message rendered client-side.
"""

from . import constants
from .signals import any_pattern_in_text


def detect_error(status_code, text, config):
    error_codes = config.get("error_http_status_codes", constants.ERROR_HTTP_STATUS_CODES)
    patterns = config.get("error_text_patterns", constants.ERROR_TEXT_PATTERNS)

    if status_code is not None and status_code in error_codes:
        return True, f"http_status_{status_code}"

    if any_pattern_in_text(text, patterns):
        return True, "error_text_detected"

    return False, None
