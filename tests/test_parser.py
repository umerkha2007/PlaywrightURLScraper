"""
Unit tests for parse_html.parse_html() — called directly against fixture
HTML on disk, no HTTP server or subprocess needed.
"""

import glob
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import parse_html  # noqa: E402
import qa  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PARSER_SCRIPT = ROOT / "parse_html.py"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "parser"


def load_fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def cleanup_parsed_files():
    yield
    for f in glob.glob(str(ROOT / "parsed_page_*.json")):
        os.remove(f)


# --- Core extraction ---------------------------------------------------

def test_full_page_extraction():
    html = load_fixture("full_page.html")
    result = parse_html.parse_html(html)
    assert result["ok"] is True
    assert result["title"] == "Full Page Fixture"
    data = result["data"]
    assert data["headings"] == [
        {"level": 1, "text": "Main Heading"},
        {"level": 2, "text": "Sub Heading"},
    ]
    assert data["links"] == [{"text": "Example Link", "href": "https://example.com"}]
    assert data["images"] == [{"src": "pic.jpg", "alt": "A picture"}]
    assert data["meta"] == {"description": "A full test page", "og:title": "OG Title"}
    assert "Some paragraph text." in data["text"]
    assert result["selector_matched"] is None
    assert result["error"] is None


def test_missing_title():
    html = load_fixture("missing_title.html")
    result = parse_html.parse_html(html)
    assert result["ok"] is True
    assert result["title"] is None


def test_empty_elements():
    html = load_fixture("empty_elements.html")
    result = parse_html.parse_html(html)
    assert result["ok"] is True
    assert result["title"] is None
    data = result["data"]
    assert data["headings"] == [{"level": 1, "text": ""}]
    assert data["links"] == [{"text": "", "href": "https://example.com"}]
    assert data["images"] == [{"src": "empty.jpg", "alt": ""}]


def test_duplicate_headings_preserved():
    html = load_fixture("duplicate_headings.html")
    result = parse_html.parse_html(html)
    headings = result["data"]["headings"]
    assert len(headings) == 4
    assert headings[0] == headings[1] == {"level": 1, "text": "Intro"}
    assert headings[2] == headings[3] == {"level": 2, "text": "Details"}


def test_meta_name_and_property_last_wins():
    html = load_fixture("meta_variants.html")
    result = parse_html.parse_html(html)
    meta = result["data"]["meta"]
    assert meta["description"] == "Second description wins"
    assert meta["og:type"] == "website"


def test_links_without_href_excluded():
    html = load_fixture("no_href_links.html")
    result = parse_html.parse_html(html)
    links = result["data"]["links"]
    assert links == [{"text": "Real Link", "href": "https://example.com/real"}]


def test_images_without_alt_default_empty():
    html = "<html><body><img src='a.jpg'></body></html>"
    result = parse_html.parse_html(html)
    assert result["data"]["images"] == [{"src": "a.jpg", "alt": ""}]


def test_scripts_and_styles_excluded_from_text():
    html = load_fixture("scripts_styles.html")
    result = parse_html.parse_html(html)
    text = result["data"]["text"]
    assert "SCRIPT_CONTENT_SHOULD_NOT_APPEAR" not in text
    assert "hidden-css-text" not in text
    assert "also-not-visible" not in text
    assert "Visible paragraph text." in text
    assert "Visible Heading" in text


def test_whitespace_normalization_on():
    html = load_fixture("whitespace_heavy.html")
    result = parse_html.parse_html(html, config={"strip_whitespace": True})
    assert result["title"] == "Whitespace Heavy Title"
    heading = result["data"]["headings"][0]["text"]
    assert heading == "Heading With Newlines"
    assert "  " not in result["data"]["text"]


def test_whitespace_normalization_off():
    html = load_fixture("whitespace_heavy.html")
    result = parse_html.parse_html(html, config={"strip_whitespace": False})
    # Raw get_text() output retains original newlines/indentation.
    assert "\n" in result["data"]["headings"][0]["text"]


def test_unicode_and_entities_decoded():
    html = load_fixture("entities.html")
    result = parse_html.parse_html(html)
    assert result["title"] == "Entities & Fixture"
    heading = result["data"]["headings"][0]["text"]
    assert "Fish & Chips" in heading
    assert "<Tasty>" in heading

    html2 = load_fixture("unicode.html")
    result2 = parse_html.parse_html(html2)
    assert "日本語" in result2["title"]
    assert "Café Müller" in result2["data"]["headings"][0]["text"]
    assert "🎉" in result2["data"]["headings"][0]["text"]


def test_malformed_html_does_not_crash():
    html = load_fixture("malformed.html")
    result = parse_html.parse_html(html)
    assert result["ok"] is True
    assert result["title"] is not None
    assert len(result["data"]["headings"]) >= 1
    assert len(result["data"]["links"]) >= 1


def test_nested_structure():
    html = load_fixture("nested_structure.html")
    result = parse_html.parse_html(html)
    assert result["data"]["headings"] == [{"level": 1, "text": "Nested Heading"}]
    assert len(result["data"]["links"]) == 3


# --- Selector scoping ----------------------------------------------------

def test_selector_matching_scopes_extraction():
    html = load_fixture("scoped_content.html")
    result = parse_html.parse_html(html, config={"selector": "#main-content"})
    assert result["ok"] is True
    assert result["selector_matched"] is True
    data = result["data"]
    assert data["headings"] == [{"level": 2, "text": "Main Content Heading"}]
    assert data["links"] == [{"text": "Main Link", "href": "https://example.com/main-link"}]
    assert data["images"] == [{"src": "main.jpg", "alt": "Main image"}]
    # title/meta remain document-level regardless of selector.
    assert result["title"] == "Scoped Content Fixture"


def test_selector_non_matching_returns_empty_not_error():
    html = load_fixture("scoped_content.html")
    result = parse_html.parse_html(html, config={"selector": "#does-not-exist"})
    assert result["ok"] is True
    assert result["selector_matched"] is False
    assert result["data"]["headings"] == []
    assert result["data"]["links"] == []
    assert result["data"]["images"] == []
    assert result["data"]["text"] == ""
    # title/meta still populated.
    assert result["title"] == "Scoped Content Fixture"


# --- Error handling --------------------------------------------------------

def test_invalid_input_none():
    result = parse_html.parse_html(None)
    assert result["ok"] is False
    assert result["error"]["type"] == "invalid_input"


def test_invalid_input_non_string():
    result = parse_html.parse_html(12345)
    assert result["ok"] is False
    assert result["error"]["type"] == "invalid_input"


def test_invalid_config_selector_type():
    result = parse_html.parse_html("<html></html>", config={"selector": 123})
    assert result["ok"] is False
    assert result["error"]["type"] == "invalid_config"


def test_invalid_config_strip_whitespace_type():
    result = parse_html.parse_html("<html></html>", config={"strip_whitespace": "yes"})
    assert result["ok"] is False
    assert result["error"]["type"] == "invalid_config"


# --- Determinism -----------------------------------------------------------

def test_determinism():
    html = load_fixture("realistic_page.html")
    config = {"selector": "article", "strip_whitespace": True}
    r1 = parse_html.parse_html(html, config=dict(config))
    r2 = parse_html.parse_html(html, config=dict(config))
    assert r1 == r2


def test_realistic_page():
    html = load_fixture("realistic_page.html")
    result = parse_html.parse_html(html)
    assert result["ok"] is True
    assert "10 Tips for Better Code" in result["title"]
    assert result["data"]["meta"]["og:image"] == "https://acme.example/cover.png"
    assert "console.log" not in result["data"]["text"]
    assert "background: #eee" not in result["data"]["text"]


# --- qa_gate_error (--answer-questions requires --detect + APPLICATION) ----

class TestQaGateError:
    def test_no_status_is_blocked(self):
        error = parse_html.qa_gate_error(None)
        assert error is not None
        assert "requires --detect" in error

    def test_application_status_is_allowed(self):
        assert parse_html.qa_gate_error("APPLICATION") is None

    def test_non_application_status_is_blocked(self):
        error = parse_html.qa_gate_error("CAPTCHA")
        assert error is not None
        assert "classified as CAPTCHA" in error


# --- apply_answer_questions (--answer-questions) ----------------------------
# qa.run() itself is unit-tested in tests/test_qa.py; here we only test the
# glue in parse_html.apply_answer_questions() with qa.run() stubbed out.

class TestApplyAnswerQuestions:
    def _base_result(self):
        html = load_fixture("full_page.html")
        return parse_html.parse_html(html, config={"source_url": "https://example.com/job/1"})

    def _settings(self):
        return {"resume_path": "resume.md", "qa_provider": "anthropic", "qa_model": "sonnet5"}

    def test_success_adds_questions_and_answers(self, monkeypatch):
        result = self._base_result()

        def fake_run(title, source_url, text, settings):
            assert source_url == "https://example.com/job/1"
            return {
                "application_questions": ["Are you legally authorized to work in Canada?"],
                "answers": [{"question": "Are you legally authorized to work in Canada?", "answer": "Yes."}],
            }

        monkeypatch.setattr(qa, "run", fake_run)
        parse_html.apply_answer_questions(result, self._settings(), api_key="fake")

        assert result["data"]["application_questions"] == ["Are you legally authorized to work in Canada?"]
        assert result["data"]["answers"][0]["answer"] == "Yes."
        assert "qa_error" not in result

    def test_failure_sets_qa_error_without_discarding_parse(self, monkeypatch):
        result = self._base_result()
        original_data = dict(result["data"])

        def fake_run(title, source_url, text, settings):
            raise FileNotFoundError("resume file not found: resume.md")

        monkeypatch.setattr(qa, "run", fake_run)
        parse_html.apply_answer_questions(result, self._settings(), api_key="fake")

        assert result["ok"] is True
        assert "resume file not found" in result["qa_error"]
        assert result["data"] == original_data
        assert "application_questions" not in result["data"]

    def test_passes_resume_and_model_settings_through(self, monkeypatch):
        result = self._base_result()
        captured = {}

        def fake_run(title, source_url, text, settings):
            captured.update(settings)
            return {"application_questions": [], "answers": []}

        monkeypatch.setattr(qa, "run", fake_run)
        settings = {"resume_path": "my_resume.md", "qa_provider": "anthropic", "qa_model": "opus5"}
        parse_html.apply_answer_questions(result, settings, api_key="fake-key")

        assert captured["resume_path"] == "my_resume.md"
        assert captured["provider"] == "anthropic"
        assert captured["model"] == "opus5"
        assert captured["api_key"] == "fake-key"
