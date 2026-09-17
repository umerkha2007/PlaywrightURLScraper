"""detector/bot_challenge.py — deterministic bot/security-challenge detection.

Kept separate from CAPTCHA: this covers interstitial pages ("Checking your
browser...", Cloudflare/Akamai/PerimeterX/DataDome style challenges) that a
real browser may resolve on its own given a short wait. The caller
(render_url.render) is responsible for the navigate -> wait -> inspect ->
wait -> inspect loop; this module only classifies a single snapshot.
"""

from . import constants
from .signals import any_pattern_in_text


def detect_bot_challenge(soup, text, config):
    patterns = config.get("bot_challenge_text_patterns", constants.BOT_CHALLENGE_TEXT_PATTERNS)
    provider_hints = config.get("bot_challenge_provider_hints", constants.BOT_CHALLENGE_PROVIDER_HINTS)

    if not any_pattern_in_text(text, patterns):
        return False, None

    for provider, hints in provider_hints.items():
        if any_pattern_in_text(text, hints):
            return True, provider

    html_str = str(soup)
    for provider, hints in provider_hints.items():
        if any(h in html_str.lower() for h in hints):
            return True, provider

    return True, "unknown"
