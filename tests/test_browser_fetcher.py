import importlib
from unittest.mock import MagicMock, patch, call

import fast_flights.core
import pytest

import src.browser_fetcher as browser_fetcher


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_proxy_url(monkeypatch):
    """Ensure _proxy_url = None for all tests that don't explicitly test proxy routing."""
    monkeypatch.setattr(browser_fetcher, "_proxy_url", None)


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
# _STEALTH_SCRIPT content checks
# ---------------------------------------------------------------------------

def test_stealth_script_patches_webdriver():
    assert "webdriver" in browser_fetcher._STEALTH_SCRIPT

def test_stealth_script_patches_plugins():
    assert "plugins" in browser_fetcher._STEALTH_SCRIPT

def test_stealth_script_patches_languages():
    assert "languages" in browser_fetcher._STEALTH_SCRIPT

def test_stealth_script_patches_permissions():
    assert "Permissions" in browser_fetcher._STEALTH_SCRIPT

def test_stealth_script_patches_webgl():
    assert "WebGLRenderingContext" in browser_fetcher._STEALTH_SCRIPT

def test_stealth_script_has_full_chrome_object():
    assert "loadTimes" in browser_fetcher._STEALTH_SCRIPT
    assert "csi" in browser_fetcher._STEALTH_SCRIPT


# ---------------------------------------------------------------------------
# _get_context — lazy init
# ---------------------------------------------------------------------------


def test_get_context_creates_browser_and_context(monkeypatch):
    """_get_context(use_proxy=False) must call launch_persistent_context on first call."""
    monkeypatch.setattr(browser_fetcher, "_playwright_instance", None)
    monkeypatch.setattr(browser_fetcher, "_context_direct", None)
    monkeypatch.setattr(browser_fetcher, "_context_proxy", None)

    mock_context = MagicMock()
    mock_browser_type = MagicMock()
    mock_browser_type.launch_persistent_context.return_value = mock_context
    mock_playwright = MagicMock()
    mock_playwright.chromium = mock_browser_type
    mock_sync_playwright = MagicMock()
    mock_sync_playwright.return_value.start.return_value = mock_playwright

    with patch("src.browser_fetcher.sync_playwright", mock_sync_playwright):
        ctx = browser_fetcher._get_context(use_proxy=False)

    assert ctx is mock_context
    mock_browser_type.launch_persistent_context.assert_called_once()
    call_kwargs = mock_browser_type.launch_persistent_context.call_args[1]
    launch_args = call_kwargs.get("args", [])
    assert "--disable-blink-features=AutomationControlled" in launch_args
    mock_context.add_init_script.assert_called_once()


def test_get_context_returns_same_instance_on_second_call(monkeypatch):
    """_get_context(use_proxy=False) must NOT re-launch the browser on subsequent calls."""
    mock_context = MagicMock()
    monkeypatch.setattr(browser_fetcher, "_playwright_instance", MagicMock())
    monkeypatch.setattr(browser_fetcher, "_context_direct", mock_context)
    monkeypatch.setattr(browser_fetcher, "_context_proxy", None)

    ctx = browser_fetcher._get_context(use_proxy=False)
    assert ctx is mock_context


# ---------------------------------------------------------------------------
# shutdown_browser
# ---------------------------------------------------------------------------


def test_shutdown_browser_closes_context_browser_and_playwright(monkeypatch):
    mock_context = MagicMock()
    mock_pw = MagicMock()
    monkeypatch.setattr(browser_fetcher, "_playwright_instance", mock_pw)
    monkeypatch.setattr(browser_fetcher, "_context_direct", mock_context)
    monkeypatch.setattr(browser_fetcher, "_context_proxy", None)

    browser_fetcher.shutdown_browser()

    mock_context.close.assert_called_once()
    mock_pw.stop.assert_called_once()


def test_shutdown_browser_clears_module_state(monkeypatch):
    monkeypatch.setattr(browser_fetcher, "_playwright_instance", MagicMock())
    monkeypatch.setattr(browser_fetcher, "_context_direct", MagicMock())
    monkeypatch.setattr(browser_fetcher, "_context_proxy", MagicMock())

    browser_fetcher.shutdown_browser()

    assert browser_fetcher._playwright_instance is None
    assert browser_fetcher._context_direct is None
    assert browser_fetcher._context_proxy is None


def test_shutdown_browser_is_idempotent(monkeypatch):
    """Calling shutdown_browser() twice must not raise."""
    monkeypatch.setattr(browser_fetcher, "_playwright_instance", None)
    monkeypatch.setattr(browser_fetcher, "_context_direct", None)
    monkeypatch.setattr(browser_fetcher, "_context_proxy", None)

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
    body = _good_body() + "<title>CAPTCHA required</title>"
    page = _make_page(200, body)
    with patch("src.browser_fetcher._get_context") as mock_ctx:
        mock_ctx.return_value.new_page.return_value = page
        with pytest.raises(browser_fetcher.BotChallengeError, match="captcha"):
            browser_fetcher.browser_fetch({"tfs": "abc"})


def test_browser_fetch_raises_bot_challenge_on_consent_pattern():
    body = _good_body() + "<title>Before you continue, consent required</title>"
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


# ---------------------------------------------------------------------------
# install_browser_patch: proxy loading (new tests)
# ---------------------------------------------------------------------------


def test_install_browser_patch_direct_only_when_proxies_file_missing(monkeypatch):
    """Missing proxies.txt → _proxy_url stays None, only direct context probed."""
    monkeypatch.setattr(browser_fetcher, "_proxy_url", None)
    with patch("src.browser_fetcher._get_context") as mock_gc, \
         patch("src.browser_fetcher.load_proxies", side_effect=FileNotFoundError):
        browser_fetcher.install_browser_patch()
    # Only direct context probed (use_proxy=False)
    mock_gc.assert_called_once_with(use_proxy=False)
    assert browser_fetcher._proxy_url is None


def test_install_browser_patch_direct_only_when_proxies_file_empty(monkeypatch):
    """Empty proxies.txt → _proxy_url stays None, only direct context probed."""
    monkeypatch.setattr(browser_fetcher, "_proxy_url", None)
    with patch("src.browser_fetcher._get_context") as mock_gc, \
         patch("src.browser_fetcher.load_proxies", return_value=[]):
        browser_fetcher.install_browser_patch()
    mock_gc.assert_called_once_with(use_proxy=False)
    assert browser_fetcher._proxy_url is None


def test_install_browser_patch_sets_proxy_url_and_probes_both(monkeypatch):
    """Valid proxies.txt → _proxy_url set, both direct and proxy contexts probed."""
    monkeypatch.setattr(browser_fetcher, "_proxy_url", None)
    proxy = "http://user:pass@host:8080"
    with patch("src.browser_fetcher._get_context") as mock_gc, \
         patch("src.browser_fetcher.load_proxies", return_value=[proxy]):
        browser_fetcher.install_browser_patch()
    assert browser_fetcher._proxy_url == proxy
    mock_gc.assert_any_call(use_proxy=False)
    mock_gc.assert_any_call(use_proxy=True)
    assert mock_gc.call_count == 2


# ---------------------------------------------------------------------------
# browser_fetch routing (new tests)
# ---------------------------------------------------------------------------


def test_browser_fetch_uses_proxy_context_when_random_below_ratio(monkeypatch):
    """random.random() < PROXY_SPLIT_RATIO → use_proxy=True, proxy context selected."""
    page = _make_page(200, _good_body())
    monkeypatch.setattr(browser_fetcher, "_proxy_url", "http://u:p@h:1")
    with patch("src.browser_fetcher.random") as mock_random, \
         patch("src.browser_fetcher._get_context") as mock_gc:
        mock_random.random.return_value = 0.1  # < 0.5
        mock_gc.return_value.new_page.return_value = page
        browser_fetcher.browser_fetch({"tfs": "abc"})
    mock_gc.assert_called_once_with(use_proxy=True)


def test_browser_fetch_uses_direct_context_when_random_above_ratio(monkeypatch):
    """random.random() >= PROXY_SPLIT_RATIO → use_proxy=False, direct context selected."""
    page = _make_page(200, _good_body())
    monkeypatch.setattr(browser_fetcher, "_proxy_url", "http://u:p@h:1")
    with patch("src.browser_fetcher.random") as mock_random, \
         patch("src.browser_fetcher._get_context") as mock_gc:
        mock_random.random.return_value = 0.9  # >= 0.5
        mock_gc.return_value.new_page.return_value = page
        browser_fetcher.browser_fetch({"tfs": "abc"})
    mock_gc.assert_called_once_with(use_proxy=False)


def test_browser_fetch_always_direct_when_no_proxy_url(monkeypatch):
    """_proxy_url = None → always direct regardless of random value."""
    page = _make_page(200, _good_body())
    monkeypatch.setattr(browser_fetcher, "_proxy_url", None)
    with patch("src.browser_fetcher.random") as mock_random, \
         patch("src.browser_fetcher._get_context") as mock_gc:
        mock_random.random.return_value = 0.1  # Would be proxy if _proxy_url were set
        mock_gc.return_value.new_page.return_value = page
        browser_fetcher.browser_fetch({"tfs": "abc"})
    mock_gc.assert_called_once_with(use_proxy=False)


# ---------------------------------------------------------------------------
# shutdown with two contexts (new tests)
# ---------------------------------------------------------------------------


def test_shutdown_browser_closes_both_contexts(monkeypatch):
    """shutdown_browser() closes both direct and proxy contexts."""
    ctx_direct = MagicMock()
    ctx_proxy = MagicMock()
    monkeypatch.setattr(browser_fetcher, "_context_direct", ctx_direct)
    monkeypatch.setattr(browser_fetcher, "_context_proxy", ctx_proxy)
    monkeypatch.setattr(browser_fetcher, "_playwright_instance", MagicMock())
    browser_fetcher.shutdown_browser()
    ctx_direct.close.assert_called_once()
    ctx_proxy.close.assert_called_once()


def test_shutdown_browser_no_crash_with_only_direct_context(monkeypatch):
    """shutdown_browser() does not crash if proxy context was never initialized."""
    monkeypatch.setattr(browser_fetcher, "_context_direct", MagicMock())
    monkeypatch.setattr(browser_fetcher, "_context_proxy", None)
    monkeypatch.setattr(browser_fetcher, "_playwright_instance", MagicMock())
    browser_fetcher.shutdown_browser()  # Must not raise
