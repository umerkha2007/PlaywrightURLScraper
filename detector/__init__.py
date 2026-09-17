"""detector — deterministic page-classification for the render-url pipeline.

No LLM/AI/agent reasoning anywhere in this package. Pure DOM/text/HTTP-status
rule checks, so it stays cheap and reliable ahead of any LLM stage that
consumes the resulting APPLICATION-only JSON.
"""

from .classify import classify
from .config import load_detector_config

__all__ = ["classify", "load_detector_config"]
