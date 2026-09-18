"""
Full-scenario tests for render_and_parse.py's --answer-questions x --detect interaction.

These call render_and_parse.main() directly (not as a subprocess) with render_url.render()
and qa.run() monkeypatched out, so every scenario below runs instantly with no real browser,
network, or LLM call -- covering the cases tests/test_detect_integration.py can only reach
with a live Chromium + local HTTP server (Playwright rendering isn't reliable in every
environment, so this suite doesn't depend on it).
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import render_and_parse  # noqa: E402
import render_url  # noqa: E402
import qa  # noqa: E402


@pytest.fixture(autouse=True)
def isolate_cwd(tmp_path, monkeypatch):
    """Run every test from an empty tmp_path: no repo-root config.json/.env/resume.md can
    leak in, and output files (rendered_page_*.json/parsed_page_*.json) land in tmp_path,
    which pytest cleans up on its own."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


def fake_render_result(url, status="APPLICATION", html="<html><body><h1>Apply</h1></body></html>",
                        ok=True, reason="application_form_detected"):
    result = {
        "ok": ok, "url": url, "final_url": url, "status_code": 200, "title": "Job",
        "html": html, "error": None,
    }
    if status is not None:
        result["status"] = status
        result["reason"] = reason
        result["detector"] = {"captcha": False, "login": False, "bot_challenge": False,
                               "error": False, "closed_job": False, "form_detected": status == "APPLICATION"}
        result["form"] = {"count": 1, "inputs": 5, "textareas": 1, "selects": 0, "file_inputs": 1} if status == "APPLICATION" else None
        result["redirected"] = False
    return result


def run_main(argv, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["render_and_parse.py"] + argv)
    render_and_parse.main()


def get_stdout_json(capsys):
    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == 1, f"expected exactly one stdout line, got: {out!r}"
    return json.loads(out[0])


class TestAnswerQuestionsRequiresDetect:
    def test_without_detect_is_rejected_before_render_is_called(self, monkeypatch, capsys):
        called = {"render": False}

        def fake_render(*a, **kw):
            called["render"] = True
            return fake_render_result("https://x/job/1")

        monkeypatch.setattr(render_url, "render", fake_render)

        with pytest.raises(SystemExit) as excinfo:
            run_main(["https://x/job/1", "--answer-questions"], monkeypatch)
        assert excinfo.value.code == 1
        result = get_stdout_json(capsys)
        assert result["ok"] is False
        assert result["error"]["type"] == "invalid_input"
        assert "requires --detect" in result["error"]["message"]
        assert called["render"] is False


class TestAnswerQuestionsWithDetectApplication:
    def test_success_path_adds_questions_and_answers(self, monkeypatch, capsys):
        monkeypatch.setattr(render_url, "render", lambda *a, **kw: fake_render_result("https://x/job/1"))

        def fake_qa_run(title, source_url, text, settings):
            return {
                "application_questions": ["Are you legally authorized to work in Canada?"],
                "answers": [{"question": "Are you legally authorized to work in Canada?", "answer": "Yes."}],
            }

        monkeypatch.setattr(qa, "run", fake_qa_run)
        Path("resume.md").write_text("# Jane Doe", encoding="utf-8")

        run_main(["https://x/job/1", "--detect", "--answer-questions", "--qa-api-key", "fake-key"], monkeypatch)
        result = get_stdout_json(capsys)

        assert result["ok"] is True
        assert result["status"] == "APPLICATION"
        assert result["data"]["application_questions"] == ["Are you legally authorized to work in Canada?"]
        assert result["data"]["answers"][0]["answer"] == "Yes."
        assert "qa_error" not in result

    def test_missing_resume_sets_qa_error_without_crashing(self, monkeypatch, capsys):
        monkeypatch.setattr(render_url, "render", lambda *a, **kw: fake_render_result("https://x/job/1"))

        run_main([
            "https://x/job/1", "--detect", "--answer-questions",
            "--resume", "does_not_exist.md", "--qa-api-key", "fake-key",
        ], monkeypatch)
        result = get_stdout_json(capsys)

        assert result["ok"] is True
        assert result["status"] == "APPLICATION"
        assert result["data"] is not None
        assert "resume file not found" in result["qa_error"]
        assert "application_questions" not in result["data"]

    def test_missing_api_key_sets_qa_error(self, monkeypatch, capsys):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setattr(render_url, "render", lambda *a, **kw: fake_render_result("https://x/job/1"))
        Path("resume.md").write_text("# Jane Doe", encoding="utf-8")

        run_main(["https://x/job/1", "--detect", "--answer-questions"], monkeypatch)
        result = get_stdout_json(capsys)

        assert result["ok"] is True
        assert "Missing API key" in result["qa_error"]

    def test_llm_error_sets_qa_error_without_crashing(self, monkeypatch, capsys):
        monkeypatch.setattr(render_url, "render", lambda *a, **kw: fake_render_result("https://x/job/1"))

        def failing_qa_run(title, source_url, text, settings):
            raise RuntimeError("LLM question-answering failed after 3 attempts: boom")

        monkeypatch.setattr(qa, "run", failing_qa_run)
        Path("resume.md").write_text("# Jane Doe", encoding="utf-8")

        run_main(["https://x/job/1", "--detect", "--answer-questions", "--qa-api-key", "fake-key"], monkeypatch)
        result = get_stdout_json(capsys)

        assert result["ok"] is True
        assert "LLM question-answering failed" in result["qa_error"]


class TestAnswerQuestionsWithDetectNonApplication:
    @pytest.mark.parametrize("status", ["CAPTCHA", "LOGIN", "ERROR", "CLOSED_JOB", "BOT_CHALLENGE", "NO_FORM"])
    def test_non_application_status_skips_llm_with_no_qa_error(self, status, monkeypatch, capsys):
        """render_and_parse already sets data=None for non-APPLICATION pages; the QA gate's
        "and data is not None" check means the LLM is never reached and qa_error is never
        added -- the classification result is returned exactly as --detect alone would produce."""
        monkeypatch.setattr(render_url, "render", lambda *a, **kw: fake_render_result("https://x/job/1", status=status, html=None))

        called = {"qa": False}

        def fake_qa_run(*a, **kw):
            called["qa"] = True
            return {"application_questions": [], "answers": []}

        monkeypatch.setattr(qa, "run", fake_qa_run)

        run_main(["https://x/job/1", "--detect", "--answer-questions", "--qa-api-key", "fake-key"], monkeypatch)
        result = get_stdout_json(capsys)

        assert result["ok"] is True
        assert result["status"] == status
        assert result["data"] is None
        assert "qa_error" not in result
        assert called["qa"] is False


class TestAnswerQuestionsRenderFailure:
    def test_render_failure_skips_llm_with_no_qa_error(self, monkeypatch, capsys):
        monkeypatch.setattr(render_url, "render", lambda *a, **kw: render_url.error_result(
            "https://x/job/1", "navigation_timeout", "timed out"))

        called = {"qa": False}
        monkeypatch.setattr(qa, "run", lambda *a, **kw: called.__setitem__("qa", True))

        run_main(["https://x/job/1", "--detect", "--answer-questions", "--qa-api-key", "fake-key"], monkeypatch)
        result = get_stdout_json(capsys)

        assert result["ok"] is False
        assert "qa_error" not in result
        assert called["qa"] is False


class TestAnswerQuestionsOffByDefault:
    def test_detect_alone_never_calls_llm(self, monkeypatch, capsys):
        monkeypatch.setattr(render_url, "render", lambda *a, **kw: fake_render_result("https://x/job/1"))

        called = {"qa": False}
        monkeypatch.setattr(qa, "run", lambda *a, **kw: called.__setitem__("qa", True))

        run_main(["https://x/job/1", "--detect"], monkeypatch)
        result = get_stdout_json(capsys)

        assert result["ok"] is True
        assert result["status"] == "APPLICATION"
        assert "qa_error" not in result
        assert "application_questions" not in result["data"]
        assert called["qa"] is False
