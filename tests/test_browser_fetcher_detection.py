"""Tests for browser_fetcher block-detection logic.

Tests _detect_block() directly — no Playwright, no network required.
"""
import pytest

import config
from src.browser_fetcher import _detect_block
from src.flight_fetcher import BotChallengeError, RateLimitedError

# Minimal valid HTML: long enough, benign title
_VALID_HTML = (
    "<html><head><title>Flights from CPH to AMS</title></head>"
    "<body>" + ("x" * 12000) + "</body></html>"
)

# Block page: title matches the "unusual traffic" challenge pattern
_BLOCK_HTML = (
    "<html><head><title>Unusual Traffic Detected</title></head>"
    "<body>" + ("x" * 12000) + "</body></html>"
)


def test_valid_response_does_not_raise():
    """A 200 response with a benign title and sufficient length passes."""
    _detect_block(200, _VALID_HTML)  # must not raise


def test_rate_limited_raises_on_429():
    """HTTP 429 raises RateLimitedError."""
    with pytest.raises(RateLimitedError, match="429"):
        _detect_block(429, _VALID_HTML)


def test_rate_limited_raises_on_403():
    """HTTP 403 raises RateLimitedError."""
    with pytest.raises(RateLimitedError, match="403"):
        _detect_block(403, _VALID_HTML)


def test_unexpected_status_raises_runtime_error():
    """Non-200/429/403 status raises RuntimeError."""
    with pytest.raises(RuntimeError, match="500"):
        _detect_block(500, _VALID_HTML)


def test_short_body_raises_bot_challenge():
    """Body shorter than BOT_CHALLENGE_MIN_BYTES raises BotChallengeError."""
    tiny = "<html><title>Flights</title><body>x</body></html>"
    assert len(tiny.encode("utf-8")) < config.BOT_CHALLENGE_MIN_BYTES
    with pytest.raises(BotChallengeError, match="minimum length"):
        _detect_block(200, tiny)


def test_challenge_title_raises_bot_challenge():
    """Title containing a BOT_CHALLENGE_TITLE_PATTERNS entry raises BotChallengeError."""  # noqa: E501
    with pytest.raises(BotChallengeError):
        _detect_block(200, _BLOCK_HTML)


def test_challenge_title_captcha_raises_bot_challenge():
    """Title with 'captcha' raises BotChallengeError."""
    captcha_html = (
        "<html><head><title>reCaptcha Required</title></head>"
        "<body>" + ("x" * 12000) + "</body></html>"
    )
    with pytest.raises(BotChallengeError, match="captcha"):
        _detect_block(200, captcha_html)


def test_challenge_title_are_you_a_robot_raises_bot_challenge():
    """Title with 'are you a robot' raises BotChallengeError."""
    robot_html = (
        "<html><head><title>Are You a Robot?</title></head>"
        "<body>" + ("x" * 12000) + "</body></html>"
    )
    with pytest.raises(BotChallengeError, match="are you a robot"):
        _detect_block(200, robot_html)


def test_challenge_title_consent_raises_bot_challenge():
    """Title with 'consent' raises BotChallengeError."""
    consent_html = (
        "<html><head><title>Before you continue: Consent required</title></head>"
        "<body>" + ("x" * 12000) + "</body></html>"
    )
    with pytest.raises(BotChallengeError, match="consent"):
        _detect_block(200, consent_html)


def test_title_case_insensitive():
    """Title pattern matching is case-insensitive."""
    upper_html = (
        "<html><head><title>UNUSUAL TRAFFIC DETECTED</title></head>"
        "<body>" + ("x" * 12000) + "</body></html>"
    )
    with pytest.raises(BotChallengeError):
        _detect_block(200, upper_html)


def test_no_title_with_short_body_raises_bot_challenge():
    """A page with no <title> but short body still raises BotChallengeError."""
    no_title = "<html><body>short</body></html>"
    assert len(no_title.encode("utf-8")) < config.BOT_CHALLENGE_MIN_BYTES
    with pytest.raises(BotChallengeError, match="minimum length"):
        _detect_block(200, no_title)


def test_no_title_with_long_body_does_not_raise():
    """A page with no <title> but sufficient body length passes block detection."""
    no_title = "<html><body>" + ("x" * 12000) + "</body></html>"
    _detect_block(200, no_title)  # must not raise


def test_status_301_raises_runtime_error():
    """Redirect status (301) raises RuntimeError, not RateLimitedError."""
    with pytest.raises(RuntimeError, match="301"):
        _detect_block(301, _VALID_HTML)


def test_status_404_raises_runtime_error():
    """404 status raises RuntimeError."""
    with pytest.raises(RuntimeError, match="404"):
        _detect_block(404, _VALID_HTML)
