"""detector/closed_job.py — deterministic closed/expired-job detection."""

from . import constants
from .signals import any_pattern_in_text


def detect_closed_job(text, config):
    patterns = config.get("closed_job_text_patterns", constants.CLOSED_JOB_TEXT_PATTERNS)
    if any_pattern_in_text(text, patterns):
        return True, "closed_job_text_detected"
    return False, None
