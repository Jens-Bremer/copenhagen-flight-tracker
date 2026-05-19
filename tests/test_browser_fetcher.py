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
