"""
Unit tests for the detector package (detector.classify and its checks).

Pure function over HTML strings — no Playwright, no network, no LLM. Each
test targets one classification outcome in isolation.
"""

import detector


def test_application_form_detected():
    html = """
    <html><body>
      <h1>Senior Software Engineer</h1>
      <form action="/apply" id="application-form">
        <input type="text" name="first_name" id="first_name">
        <input type="text" name="last_name" id="last_name">
        <input type="email" name="email">
        <input type="tel" name="phone">
        <input type="file" name="resume">
        <textarea name="cover_letter"></textarea>
        <select name="work_auth"><option>Yes</option></select>
      </form>
    </body></html>
    """
    result = detector.classify(html)
    assert result["status"] == "APPLICATION"
    assert result["detector"]["form_detected"] is True
    assert result["detector"]["captcha"] is False
    assert result["detector"]["login"] is False
    assert result["form"]["count"] == 1
    assert result["form"]["file_inputs"] == 1


def test_no_form_detected_for_plain_page():
    html = "<html><body><h1>Hello</h1><p>Just a static page with no form.</p></body></html>"
    result = detector.classify(html)
    assert result["status"] == "NO_FORM"
    assert result["detector"]["form_detected"] is False


def test_captcha_via_widget_class():
    html = '<html><body><div class="g-recaptcha" data-sitekey="x"></div></body></html>'
    result = detector.classify(html)
    assert result["status"] == "CAPTCHA"
    assert result["detector"]["captcha"] is True


def test_captcha_via_text():
    html = "<html><body><h1>Verify you are human</h1><p>Please complete the captcha.</p></body></html>"
    result = detector.classify(html)
    assert result["status"] == "CAPTCHA"


def test_captcha_via_iframe():
    html = '<html><body><iframe src="https://www.google.com/recaptcha/api2/anchor"></iframe></body></html>'
    result = detector.classify(html)
    assert result["status"] == "CAPTCHA"


def test_bot_challenge_cloudflare():
    html = """
    <html><body>
      <h1>Checking your browser before accessing this site.</h1>
      <p>This process is automatic. cloudflare</p>
    </body></html>
    """
    result = detector.classify(html)
    assert result["status"] == "BOT_CHALLENGE"
    assert result["detector"]["bot_challenge"] is True
    assert result["provider"] == "cloudflare"


def test_login_wall_detected():
    html = """
    <html><body>
      <h2>Sign in to continue</h2>
      <form>
        <input type="email" name="email">
        <input type="password" name="password">
        <button type="submit">Log in</button>
      </form>
    </body></html>
    """
    result = detector.classify(html)
    assert result["status"] == "LOGIN"
    assert result["detector"]["login"] is True


def test_sign_in_with_google_alongside_application_is_not_login():
    """A 'Sign in with Google' button next to an actual application form
    should not cause a false LOGIN classification (no password field, and
    file/textarea fields are present)."""
    html = """
    <html><body>
      <h1>Apply for this job</h1>
      <button>Sign in with Google</button>
      <form action="/apply">
        <input type="email" name="email">
        <input type="text" name="first_name">
        <textarea name="cover_letter"></textarea>
        <input type="file" name="resume">
      </form>
    </body></html>
    """
    result = detector.classify(html)
    assert result["detector"]["login"] is False
    assert result["status"] == "APPLICATION"


def test_error_page_via_http_status():
    html = "<html><body><h1>Oops</h1></body></html>"
    result = detector.classify(html, status_code=404)
    assert result["status"] == "ERROR"
    assert result["reason"] == "http_status_404"


def test_error_page_via_rendered_text_with_200_status():
    """Some ATS systems return HTTP 200 with an error rendered client-side."""
    html = "<html><body><h1>500 Internal Server Error</h1></body></html>"
    result = detector.classify(html, status_code=200)
    assert result["status"] == "ERROR"


def test_closed_job_detected():
    html = """
    <html><body>
      <h1>Senior Software Engineer</h1>
      <p>This position is no longer accepting applications.</p>
    </body></html>
    """
    result = detector.classify(html)
    assert result["status"] == "CLOSED_JOB"
    assert result["detector"]["closed_job"] is True


def test_closed_job_not_triggered_by_unrelated_text():
    html = """
    <html><body>
      <h1>Senior Software Engineer</h1>
      <p>Applications are reviewed weekly.</p>
      <form action="/apply">
        <input type="text" name="first_name">
        <input type="email" name="email">
        <textarea name="cover_letter"></textarea>
        <input type="file" name="resume">
      </form>
    </body></html>
    """
    result = detector.classify(html)
    assert result["detector"]["closed_job"] is False
    assert result["status"] == "APPLICATION"


def test_priority_captcha_wins_over_form():
    """A page can technically have form-shaped fields behind a captcha wall;
    CAPTCHA must still take priority over an APPLICATION classification."""
    html = """
    <html><body>
      <div class="g-recaptcha"></div>
      <form>
        <input type="text" name="first_name">
        <input type="email" name="email">
        <textarea name="cover_letter"></textarea>
        <input type="file" name="resume">
      </form>
    </body></html>
    """
    result = detector.classify(html)
    assert result["status"] == "CAPTCHA"


def test_threshold_is_configurable():
    html = """
    <html><body>
      <form><input type="email" name="email"></form>
    </body></html>
    """
    default_result = detector.classify(html)
    assert default_result["status"] == "NO_FORM"

    lenient_result = detector.classify(html, config={"threshold": 1})
    assert lenient_result["status"] == "APPLICATION"
