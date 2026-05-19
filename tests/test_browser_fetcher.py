import importlib
from unittest.mock import MagicMock, patch, call

import fast_flights.core
import pytest

import src.browser_fetcher as browser_fetcher


# ---------------------------------------------------------------------------
# BrowserResponse
# ---------------------------------------------------------------------------


def test_browser_response_exposes_status_code():
    r = browser_fetcher.BrowserResponse(200, "hello")
    assert r.status_code == 200


def test_browser_response_exposes_text():
    r = browser_fetcher.BrowserResponse(200, "hello")
    assert r.text == "hello"


def test_browser_response_text_markdown_equals_text():
    r = browser_fetcher.BrowserResponse(200, "hello")
    assert r.text_markdown == "hello"


# ---------------------------------------------------------------------------
# _get_context — lazy init
# ---------------------------------------------------------------------------


def test_get_context_creates_browser_and_context(monkeypatch):
    """_get_context() must launch browser and create a context on first call."""
    # Reset module-level state before test
    monkeypatch.setattr(browser_fetcher, "_playwright_instance", None)
    monkeypatch.setattr(browser_fetcher, "_browser", None)
    monkeypatch.setattr(browser_fetcher, "_context", None)

    mock_context = MagicMock()
    mock_browser = MagicMock()
    mock_browser.new_context.return_value = mock_context
    mock_browser_type = MagicMock()
    mock_browser_type.launch.return_value = mock_browser
    mock_playwright = MagicMock()
    mock_playwright.chromium = mock_browser_type
    mock_sync_playwright = MagicMock()
    mock_sync_playwright.return_value.__enter__ = MagicMock(return_value=mock_playwright)
    mock_sync_playwright.return_value.start.return_value = mock_playwright

    with patch("src.browser_fetcher.sync_playwright", mock_sync_playwright):
        ctx = browser_fetcher._get_context()

    assert ctx is mock_context
    mock_browser_type.launch.assert_called_once()
    mock_browser.new_context.assert_called_once()
    mock_context.add_init_script.assert_called_once()


def test_get_context_returns_same_instance_on_second_call(monkeypatch):
    """_get_context() must NOT re-launch the browser on subsequent calls."""
    mock_context = MagicMock()
    monkeypatch.setattr(browser_fetcher, "_playwright_instance", MagicMock())
    monkeypatch.setattr(browser_fetcher, "_browser", MagicMock())
    monkeypatch.setattr(browser_fetcher, "_context", mock_context)

    ctx = browser_fetcher._get_context()
    assert ctx is mock_context


# ---------------------------------------------------------------------------
# shutdown_browser
# ---------------------------------------------------------------------------


def test_shutdown_browser_closes_context_browser_and_playwright(monkeypatch):
    mock_context = MagicMock()
    mock_browser = MagicMock()
    mock_pw = MagicMock()
    monkeypatch.setattr(browser_fetcher, "_playwright_instance", mock_pw)
    monkeypatch.setattr(browser_fetcher, "_browser", mock_browser)
    monkeypatch.setattr(browser_fetcher, "_context", mock_context)

    browser_fetcher.shutdown_browser()

    mock_context.close.assert_called_once()
    mock_browser.close.assert_called_once()
    mock_pw.stop.assert_called_once()


def test_shutdown_browser_clears_module_state(monkeypatch):
    monkeypatch.setattr(browser_fetcher, "_playwright_instance", MagicMock())
    monkeypatch.setattr(browser_fetcher, "_browser", MagicMock())
    monkeypatch.setattr(browser_fetcher, "_context", MagicMock())

    browser_fetcher.shutdown_browser()

    assert browser_fetcher._playwright_instance is None
    assert browser_fetcher._browser is None
    assert browser_fetcher._context is None


def test_shutdown_browser_is_idempotent(monkeypatch):
    """Calling shutdown_browser() twice must not raise."""
    monkeypatch.setattr(browser_fetcher, "_playwright_instance", None)
    monkeypatch.setattr(browser_fetcher, "_browser", None)
    monkeypatch.setattr(browser_fetcher, "_context", None)

    browser_fetcher.shutdown_browser()  # first call — all None, no-op
    browser_fetcher.shutdown_browser()  # second call — still all None, no-op


# ---------------------------------------------------------------------------
# browser_fetch
# ---------------------------------------------------------------------------


def _make_page(status: int = 200, content: str = "") -> MagicMock:
    """Return a mock Playwright page with goto + content configured."""
    page = MagicMock()
    mock_response = MagicMock()
    mock_response.status = status
    page.goto.return_value = mock_response
    page.content.return_value = content
    return page


def _good_body() -> str:
    import config
    return "x" * (config.BOT_CHALLENGE_MIN_BYTES + 1000)


def test_browser_fetch_returns_browser_response_on_200():
    page = _make_page(200, _good_body())
    with patch("src.browser_fetcher._get_context") as mock_ctx:
        mock_ctx.return_value.new_page.return_value = page
        result = browser_fetcher.browser_fetch({"tfs": "abc"})
    assert result.status_code == 200
    assert isinstance(result.text, str)


def test_browser_fetch_closes_page_on_success():
    page = _make_page(200, _good_body())
    with patch("src.browser_fetcher._get_context") as mock_ctx:
        mock_ctx.return_value.new_page.return_value = page
        browser_fetcher.browser_fetch({"tfs": "abc"})
    page.close.assert_called_once()


def test_browser_fetch_closes_page_on_goto_exception():
    page = MagicMock()
    page.goto.side_effect = Exception("timeout")
    with patch("src.browser_fetcher._get_context") as mock_ctx:
        mock_ctx.return_value.new_page.return_value = page
        with pytest.raises(browser_fetcher.NetworkError):
            browser_fetcher.browser_fetch({"tfs": "abc"})
    page.close.assert_called_once()


def test_browser_fetch_raises_network_error_on_goto_exception():
    page = MagicMock()
    page.goto.side_effect = Exception("connection refused")
    with patch("src.browser_fetcher._get_context") as mock_ctx:
        mock_ctx.return_value.new_page.return_value = page
        with pytest.raises(browser_fetcher.NetworkError, match="connection refused"):
            browser_fetcher.browser_fetch({"tfs": "abc"})


def test_browser_fetch_raises_network_error_when_goto_returns_none():
    page = MagicMock()
    page.goto.return_value = None
    with patch("src.browser_fetcher._get_context") as mock_ctx:
        mock_ctx.return_value.new_page.return_value = page
        with pytest.raises(browser_fetcher.NetworkError):
            browser_fetcher.browser_fetch({"tfs": "abc"})


def test_browser_fetch_raises_rate_limited_on_429():
    page = _make_page(429, _good_body())
    with patch("src.browser_fetcher._get_context") as mock_ctx:
        mock_ctx.return_value.new_page.return_value = page
        with pytest.raises(browser_fetcher.RateLimitedError, match="HTTP 429"):
            browser_fetcher.browser_fetch({"tfs": "abc"})


def test_browser_fetch_raises_rate_limited_on_403():
    page = _make_page(403, _good_body())
    with patch("src.browser_fetcher._get_context") as mock_ctx:
        mock_ctx.return_value.new_page.return_value = page
        with pytest.raises(browser_fetcher.RateLimitedError, match="HTTP 403"):
            browser_fetcher.browser_fetch({"tfs": "abc"})


def test_browser_fetch_raises_runtime_error_on_500():
    page = _make_page(500, _good_body())
    with patch("src.browser_fetcher._get_context") as mock_ctx:
        mock_ctx.return_value.new_page.return_value = page
        with pytest.raises(RuntimeError, match="HTTP 500"):
            browser_fetcher.browser_fetch({"tfs": "abc"})


def test_browser_fetch_raises_bot_challenge_on_short_body():
    page = _make_page(200, "tiny")
    with patch("src.browser_fetcher._get_context") as mock_ctx:
        mock_ctx.return_value.new_page.return_value = page
        with pytest.raises(browser_fetcher.BotChallengeError, match="below minimum length"):
            browser_fetcher.browser_fetch({"tfs": "abc"})


def test_browser_fetch_raises_bot_challenge_on_captcha_pattern():
    body = _good_body() + "Please solve this CAPTCHA to continue"
    page = _make_page(200, body)
    with patch("src.browser_fetcher._get_context") as mock_ctx:
        mock_ctx.return_value.new_page.return_value = page
        with pytest.raises(browser_fetcher.BotChallengeError, match="captcha"):
            browser_fetcher.browser_fetch({"tfs": "abc"})


def test_browser_fetch_raises_bot_challenge_on_consent_pattern():
    body = _good_body() + "Before you continue to Google CONSENT required"
    page = _make_page(200, body)
    with patch("src.browser_fetcher._get_context") as mock_ctx:
        mock_ctx.return_value.new_page.return_value = page
        with pytest.raises(browser_fetcher.BotChallengeError, match="consent"):
            browser_fetcher.browser_fetch({"tfs": "abc"})


def test_browser_fetch_passes_url_with_params_to_goto():
    page = _make_page(200, _good_body())
    with patch("src.browser_fetcher._get_context") as mock_ctx:
        mock_ctx.return_value.new_page.return_value = page
        browser_fetcher.browser_fetch({"tfs": "MYENCODED", "hl": "en"})
    call_url = page.goto.call_args[0][0]
    assert "tfs=MYENCODED" in call_url
    assert "hl=en" in call_url
    assert call_url.startswith("https://www.google.com/travel/flights")


# ---------------------------------------------------------------------------
# install_browser_patch
# ---------------------------------------------------------------------------


def test_install_browser_patch_replaces_fast_flights_fetch(monkeypatch):
    """install_browser_patch must rebind fast_flights.core.fetch to browser_fetch."""
    sentinel = object()
    monkeypatch.setattr(fast_flights.core, "fetch", sentinel)

    with patch("src.browser_fetcher._get_context"):
        browser_fetcher.install_browser_patch()

    assert fast_flights.core.fetch is browser_fetcher.browser_fetch


def test_install_browser_patch_does_not_rebind_on_context_failure(monkeypatch):
    """If the browser cannot launch, fast_flights.core.fetch must NOT be rebound."""
    sentinel = object()
    monkeypatch.setattr(fast_flights.core, "fetch", sentinel)

    with patch(
        "src.browser_fetcher._get_context", side_effect=Exception("browser crashed")
    ):
        with pytest.raises(RuntimeError, match="browser crashed"):
            browser_fetcher.install_browser_patch()

    assert fast_flights.core.fetch is sentinel


def test_install_browser_patch_raises_runtime_error_with_helpful_message(monkeypatch):
    monkeypatch.setattr(fast_flights.core, "fetch", object())
    with patch(
        "src.browser_fetcher._get_context", side_effect=Exception("no display")
    ):
        with pytest.raises(RuntimeError, match="no display"):
            browser_fetcher.install_browser_patch()
