"""detector/captcha.py — deterministic CAPTCHA detection.

Does not attempt to solve or bypass any CAPTCHA. Only identifies that one is
present, so downstream automation knows the application cannot currently be
reached normally.
"""

from . import constants
from .signals import any_pattern_in_text


def detect_captcha(soup, text, config):
    patterns = config.get("captcha_text_patterns", constants.CAPTCHA_TEXT_PATTERNS)
    iframe_patterns = config.get("captcha_iframe_src_patterns", constants.CAPTCHA_IFRAME_SRC_PATTERNS)

    for iframe in soup.find_all("iframe"):
        src = (iframe.get("src") or "").lower()
        if any(p in src for p in iframe_patterns):
            return True, "captcha_iframe_detected"

    for tag in soup.find_all(True):
        classes = " ".join(tag.get("class", [])).lower()
        tag_id = str(tag.get("id", "")).lower()
        if "g-recaptcha" in classes or "h-captcha" in classes or "recaptcha" in tag_id or "hcaptcha" in tag_id:
            return True, "captcha_widget_detected"

    if any_pattern_in_text(text, patterns):
        return True, "captcha_text_detected"

    return False, None
