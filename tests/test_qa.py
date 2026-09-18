"""
Unit tests for qa.py — the optional LLM question-extraction-and-answering module
used by parse-html/render-and-parse's --answer-questions flag.

No real network calls or anthropic SDK install are needed: the Anthropic client is
faked wherever it would otherwise be constructed.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import qa  # noqa: E402


# ---------------------------------------------------------------------------
# resolve_model
# ---------------------------------------------------------------------------

class TestResolveModel:
    def test_known_short_name(self):
        assert qa.resolve_model("sonnet5") == "claude-sonnet-5"

    def test_case_insensitive(self):
        assert qa.resolve_model("SONNET5") == "claude-sonnet-5"

    def test_whitespace_stripped(self):
        assert qa.resolve_model("  opus5  ") == "claude-opus-5"

    def test_dotted_short_name(self):
        assert qa.resolve_model("haiku4.5") == "claude-haiku-4-5-20251001"

    def test_unrecognized_name_passed_through(self):
        assert qa.resolve_model("claude-sonnet-4-20250514") == "claude-sonnet-4-20250514"

    @pytest.mark.parametrize("alias", list(qa.MODEL_ALIASES.keys()))
    def test_every_alias_resolves_to_nonempty_string(self, alias):
        resolved = qa.resolve_model(alias)
        assert resolved == qa.MODEL_ALIASES[alias]
        assert resolved.startswith("claude-")


# ---------------------------------------------------------------------------
# load_dotenv
# ---------------------------------------------------------------------------

class TestLoadDotenv:
    def test_missing_file_is_a_noop(self, tmp_path, monkeypatch):
        monkeypatch.delenv("SOME_TEST_VAR", raising=False)
        qa.load_dotenv(str(tmp_path / "does_not_exist.env"))
        import os
        assert "SOME_TEST_VAR" not in os.environ

    def test_sets_env_vars_from_file(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text("FOO_TEST=bar\nBAZ_TEST=\"quoted\"\n", encoding="utf-8")
        monkeypatch.delenv("FOO_TEST", raising=False)
        monkeypatch.delenv("BAZ_TEST", raising=False)
        qa.load_dotenv(str(env_file))
        import os
        assert os.environ["FOO_TEST"] == "bar"
        assert os.environ["BAZ_TEST"] == "quoted"

    def test_does_not_override_existing_env_var(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text("FOO_TEST=from_dotenv\n", encoding="utf-8")
        monkeypatch.setenv("FOO_TEST", "from_shell")
        qa.load_dotenv(str(env_file))
        import os
        assert os.environ["FOO_TEST"] == "from_shell"

    def test_ignores_comments_and_blank_lines(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text("# a comment\n\nFOO_TEST=bar\n", encoding="utf-8")
        monkeypatch.delenv("FOO_TEST", raising=False)
        qa.load_dotenv(str(env_file))
        import os
        assert os.environ["FOO_TEST"] == "bar"


# ---------------------------------------------------------------------------
# parse_llm_json
# ---------------------------------------------------------------------------

class TestParseLlmJson:
    def test_plain_json(self):
        raw = '{"application_questions": ["a"], "answers": []}'
        assert qa.parse_llm_json(raw) == {"application_questions": ["a"], "answers": []}

    def test_fenced_json(self):
        raw = '```json\n{"application_questions": [], "answers": []}\n```'
        assert qa.parse_llm_json(raw) == {"application_questions": [], "answers": []}

    def test_fenced_json_no_language_tag(self):
        raw = '```\n{"application_questions": [], "answers": []}\n```'
        assert qa.parse_llm_json(raw) == {"application_questions": [], "answers": []}

    def test_json_with_surrounding_prose(self):
        raw = 'Sure, here is the JSON:\n{"application_questions": ["q"], "answers": []}\nHope that helps!'
        assert qa.parse_llm_json(raw) == {"application_questions": ["q"], "answers": []}

    def test_invalid_json_raises(self):
        with pytest.raises(json.JSONDecodeError):
            qa.parse_llm_json("not json at all")


# ---------------------------------------------------------------------------
# load_resume
# ---------------------------------------------------------------------------

class TestLoadResume:
    def test_reads_resume_text(self, tmp_path):
        resume_path = tmp_path / "resume.md"
        resume_path.write_text("# Jane Doe\n\nSoftware engineer.", encoding="utf-8")
        assert qa.load_resume(resume_path) == "# Jane Doe\n\nSoftware engineer."

    def test_strips_surrounding_whitespace(self, tmp_path):
        resume_path = tmp_path / "resume.md"
        resume_path.write_text("\n\n  hello  \n\n", encoding="utf-8")
        assert qa.load_resume(resume_path) == "hello"

    def test_missing_file_raises_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="resume file not found"):
            qa.load_resume(tmp_path / "nope.md")

    def test_empty_file_raises_value_error(self, tmp_path):
        resume_path = tmp_path / "resume.md"
        resume_path.write_text("   \n  ", encoding="utf-8")
        with pytest.raises(ValueError, match="resume file is empty"):
            qa.load_resume(resume_path)


# ---------------------------------------------------------------------------
# answer_questions (fake Anthropic client)
# ---------------------------------------------------------------------------

class FakeTextBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class FakeResponse:
    def __init__(self, text):
        self.content = [FakeTextBlock(text)]


class FakeMessages:
    def __init__(self, responses=None, exceptions=None):
        self._queue = responses if responses is not None else []
        self._exceptions = exceptions or []
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self._exceptions:
            exc = self._exceptions.pop(0)
            if exc is not None:
                raise exc
        text = self._queue.pop(0)
        return FakeResponse(text)


class FakeClient:
    def __init__(self, messages):
        self.messages = messages


class TestAnswerQuestions:
    def test_success_first_try(self):
        good = json.dumps({
            "application_questions": ["Are you legally authorized to work in Canada?"],
            "answers": [{"question": "Are you legally authorized to work in Canada?", "answer": "Yes."}],
        })
        client = FakeClient(FakeMessages(responses=[good]))
        provider = {"client": client, "model": "claude-sonnet-5"}
        result = qa.answer_questions("Job", "https://x", "some page text", "# Resume", provider)
        assert result["application_questions"] == ["Are you legally authorized to work in Canada?"]
        assert result["answers"][0]["answer"] == "Yes."
        assert len(client.messages.calls) == 1
        assert client.messages.calls[0]["model"] == "claude-sonnet-5"
        assert "# Resume" in client.messages.calls[0]["messages"][0]["content"]

    def test_truncates_page_text_to_max_chars(self):
        good = '{"application_questions": [], "answers": []}'
        client = FakeClient(FakeMessages(responses=[good]))
        provider = {"client": client, "model": "m"}
        qa.answer_questions("T", "u", "x" * 100, "resume", provider, max_chars=10)
        sent = client.messages.calls[0]["messages"][0]["content"]
        assert "x" * 100 not in sent
        assert "x" * 10 in sent

    def test_retries_on_malformed_json_then_succeeds(self, monkeypatch):
        monkeypatch.setattr(qa.time, "sleep", lambda *_: None)
        bad = "not json"
        good = '{"application_questions": [], "answers": []}'
        client = FakeClient(FakeMessages(responses=[bad, good]))
        provider = {"client": client, "model": "m"}
        result = qa.answer_questions("T", "u", "text", "resume", provider, max_retries=3, backoff=0)
        assert result == {"application_questions": [], "answers": []}
        assert len(client.messages.calls) == 2

    def test_retries_on_exception_then_succeeds(self, monkeypatch):
        monkeypatch.setattr(qa.time, "sleep", lambda *_: None)
        good = '{"application_questions": [], "answers": []}'
        client = FakeClient(FakeMessages(responses=[good], exceptions=[RuntimeError("boom"), None]))
        provider = {"client": client, "model": "m"}
        result = qa.answer_questions("T", "u", "text", "resume", provider, max_retries=3, backoff=0)
        assert result == {"application_questions": [], "answers": []}

    def test_raises_after_exhausting_retries(self, monkeypatch):
        monkeypatch.setattr(qa.time, "sleep", lambda *_: None)
        client = FakeClient(FakeMessages(responses=["bad", "bad", "bad"]))
        provider = {"client": client, "model": "m"}
        with pytest.raises(RuntimeError, match="LLM question-answering failed after 3 attempts"):
            qa.answer_questions("T", "u", "text", "resume", provider, max_retries=3, backoff=0)

    def test_response_missing_expected_lists_triggers_retry(self, monkeypatch):
        monkeypatch.setattr(qa.time, "sleep", lambda *_: None)
        malformed = '{"application_questions": "not a list", "answers": []}'
        good = '{"application_questions": [], "answers": []}'
        client = FakeClient(FakeMessages(responses=[malformed, good]))
        provider = {"client": client, "model": "m"}
        result = qa.answer_questions("T", "u", "text", "resume", provider, max_retries=2, backoff=0)
        assert result == {"application_questions": [], "answers": []}


# ---------------------------------------------------------------------------
# run() — the high-level entry point used by parse_html.apply_answer_questions
# ---------------------------------------------------------------------------

class TestRun:
    def _resume(self, tmp_path, text="# Jane Doe"):
        p = tmp_path / "resume.md"
        p.write_text(text, encoding="utf-8")
        return p

    def test_missing_resume_raises(self, tmp_path):
        settings = {"resume_path": str(tmp_path / "nope.md"), "provider": "anthropic", "api_key": "x", "model": "sonnet5"}
        with pytest.raises(FileNotFoundError):
            qa.run("T", "u", "text", settings)

    def test_missing_api_key_raises(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        # qa.run() calls load_dotenv(".env") relative to cwd; chdir to an empty tmp_path
        # so a real .env in the repo root (if present) can't leak an API key into this test.
        monkeypatch.chdir(tmp_path)
        resume = self._resume(tmp_path)
        settings = {"resume_path": str(resume), "provider": "anthropic", "api_key": None, "model": "sonnet5"}
        with pytest.raises(ValueError, match="Missing API key"):
            qa.run("T", "u", "text", settings)

    def test_unsupported_provider_raises(self, tmp_path):
        resume = self._resume(tmp_path)
        settings = {"resume_path": str(resume), "provider": "openai", "api_key": "x", "model": "sonnet5"}
        with pytest.raises(ValueError, match="Unsupported qa provider"):
            qa.run("T", "u", "text", settings)

    def test_success_uses_resume_and_api_key(self, tmp_path, monkeypatch):
        resume = self._resume(tmp_path, "# Jane Doe\n\nPython dev.")
        good = '{"application_questions": ["q"], "answers": [{"question": "q", "answer": "a"}]}'

        def fake_get_provider_client(provider, api_key, model):
            assert provider == "anthropic"
            assert api_key == "fake-key"
            assert model == "claude-sonnet-5"
            return {"client": FakeClient(FakeMessages(responses=[good])), "model": model}

        monkeypatch.setattr(qa, "get_provider_client", fake_get_provider_client)
        settings = {"resume_path": str(resume), "provider": "anthropic", "api_key": "fake-key", "model": "sonnet5"}
        result = qa.run("Job Title", "https://x", "page text", settings)
        assert result == {"application_questions": ["q"], "answers": [{"question": "q", "answer": "a"}]}

    def test_falls_back_to_env_api_key(self, tmp_path, monkeypatch):
        resume = self._resume(tmp_path)
        good = '{"application_questions": [], "answers": []}'
        monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key")

        captured = {}

        def fake_get_provider_client(provider, api_key, model):
            captured["api_key"] = api_key
            return {"client": FakeClient(FakeMessages(responses=[good])), "model": model}

        monkeypatch.setattr(qa, "get_provider_client", fake_get_provider_client)
        settings = {"resume_path": str(resume), "provider": "anthropic", "api_key": None, "model": "sonnet5"}
        qa.run("T", "u", "text", settings)
        assert captured["api_key"] == "env-key"
