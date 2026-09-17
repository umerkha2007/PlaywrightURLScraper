"""detector/signals.py — shared text/DOM helper primitives for the detector checks.

Pure functions over a BeautifulSoup document. No network access, no
Playwright, no LLM/AI reasoning.
"""

import re

_WHITESPACE_RE = re.compile(r"\s+")


def normalized_text(soup):
    """Lowercased, whitespace-collapsed visible text of the whole document."""
    text = soup.get_text(separator=" ")
    return _WHITESPACE_RE.sub(" ", text).strip().lower()


def any_pattern_in_text(text, patterns):
    """True if any of `patterns` (already-lowercase substrings) occurs in `text`."""
    return any(p in text for p in patterns)


def matched_patterns_in_text(text, patterns):
    return [p for p in patterns if p in text]


def field_matches_keywords(tag, keywords):
    """True if a form-field tag's name/id/placeholder/aria-label matches any keyword."""
    haystack = " ".join(
        str(tag.get(attr, "")) for attr in ("name", "id", "placeholder", "aria-label", "class")
    ).lower()
    return any(k in haystack for k in keywords)


def label_text_for(tag, soup):
    """Best-effort label text associated with a form field, or ''."""
    field_id = tag.get("id")
    if field_id:
        label = soup.find("label", attrs={"for": field_id})
        if label is not None:
            return label.get_text(separator=" ").strip().lower()
    parent_label = tag.find_parent("label")
    if parent_label is not None:
        return parent_label.get_text(separator=" ").strip().lower()
    return ""


def field_or_label_matches(tag, soup, keywords):
    if field_matches_keywords(tag, keywords):
        return True
    label = label_text_for(tag, soup)
    return any(k in label for k in keywords)
