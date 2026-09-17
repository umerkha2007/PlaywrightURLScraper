"""detector/constants.py — default keyword lists, scoring weights, and timing.

All values here are deterministic constants with no LLM/AI involvement.
Every list can be overridden via the "detector" section of config.json
(see detector/config.py).
"""

# --- status values -----------------------------------------------------

STATUS_APPLICATION = "APPLICATION"
STATUS_CAPTCHA = "CAPTCHA"
STATUS_LOGIN = "LOGIN"
STATUS_ERROR = "ERROR"
STATUS_REDIRECT = "REDIRECT"
STATUS_CLOSED_JOB = "CLOSED_JOB"
STATUS_NO_FORM = "NO_FORM"
STATUS_BOT_CHALLENGE = "BOT_CHALLENGE"
STATUS_TIMEOUT = "TIMEOUT"
STATUS_UNKNOWN = "UNKNOWN"

ALL_STATUSES = (
    STATUS_APPLICATION,
    STATUS_CAPTCHA,
    STATUS_LOGIN,
    STATUS_ERROR,
    STATUS_REDIRECT,
    STATUS_CLOSED_JOB,
    STATUS_NO_FORM,
    STATUS_BOT_CHALLENGE,
    STATUS_TIMEOUT,
    STATUS_UNKNOWN,
)

# --- CAPTCHA -------------------------------------------------------------

CAPTCHA_TEXT_PATTERNS = [
    "captcha",
    "recaptcha",
    "hcaptcha",
    "verify you are human",
    "verify you're human",
    "are you a human",
    "i'm not a robot",
    "im not a robot",
    "prove you are human",
]

CAPTCHA_IFRAME_SRC_PATTERNS = [
    "recaptcha",
    "hcaptcha",
    "challenges.cloudflare",
    "turnstile",
]

# --- Bot / security challenge --------------------------------------------

BOT_CHALLENGE_TEXT_PATTERNS = [
    "checking your browser",
    "just a moment",
    "enable javascript and cookies to continue",
    "access denied",
    "request blocked",
    "bot detected",
    "security verification",
    "ddos protection by",
    "attention required",
    "this process is automatic",
    "please stand by, while we are checking your browser",
    "verifying you are human",
]

BOT_CHALLENGE_PROVIDER_HINTS = {
    "cloudflare": ["cloudflare", "cf-ray", "challenges.cloudflare.com"],
    "akamai": ["akamai"],
    "perimeterx": ["perimeterx", "px-captcha"],
    "datadome": ["datadome"],
}

CHALLENGE_WAIT_MS_DEFAULT = 2000
CHALLENGE_MAX_CHECKS_DEFAULT = 2

# --- Login -----------------------------------------------------------------

LOGIN_KEYWORD_PATTERNS = [
    "sign in",
    "log in",
    "login",
    "create an account",
    "forgot password",
    "forgot your password",
]

# --- Errors ------------------------------------------------------------

ERROR_HTTP_STATUS_CODES = [404, 410, 500, 502, 503, 504]

ERROR_TEXT_PATTERNS = [
    "404",
    "page not found",
    "500",
    "internal server error",
    "something went wrong",
    "this page doesn't exist",
    "this page does not exist",
    "access denied",
    "we can't find that page",
    "we cannot find that page",
]

# --- Closed job ----------------------------------------------------------

CLOSED_JOB_TEXT_PATTERNS = [
    "job is no longer available",
    "position has been filled",
    "this job has expired",
    "job is closed",
    "no longer accepting applications",
    "applications are closed",
    "position is no longer available",
    "this posting has expired",
    "this job posting is no longer active",
]

# --- Application scoring ---------------------------------------------------

APPLICATION_FORM_KEYWORDS = ["apply", "application", "job"]
RESUME_FIELD_KEYWORDS = ["resume", "cv", "curriculum vitae"]
COVER_LETTER_FIELD_KEYWORDS = ["cover letter", "cover-letter", "coverletter"]
FIRST_NAME_FIELD_KEYWORDS = ["first name", "first-name", "firstname", "fname"]
LAST_NAME_FIELD_KEYWORDS = ["last name", "last-name", "lastname", "lname"]
WORK_AUTH_TEXT_PATTERNS = ["work authorization", "authorized to work", "sponsorship"]
LINKEDIN_FIELD_KEYWORDS = ["linkedin"]
PHONE_FIELD_KEYWORDS = ["phone", "mobile", "telephone"]

APPLICATION_SCORE_WEIGHTS = {
    "email_input": 5,
    "text_input": 5,
    "textarea": 5,
    "file_input": 5,
    "application_form": 5,
    "select": 3,
    "phone_field": 3,
    "resume_field": 3,
    "cover_letter_field": 3,
    "first_name_field": 2,
    "last_name_field": 2,
    "work_authorization": 2,
    "linkedin_field": 2,
    "login_penalty": -10,
    "captcha_penalty": -10,
    "error_penalty": -10,
    "closed_job_penalty": -10,
}

APPLICATION_SCORE_THRESHOLD_DEFAULT = 10
