import logging
import re
from typing import Optional
from urllib.parse import urlencode

from playwright.sync_api import BrowserContext, sync_playwright

import config
from src.flight_fetcher import BotChallengeError, NetworkError, RateLimitedError

logger = logging.getLogger(__name__)

# --- Module-level browser state (single persistent context for process lifetime) ---
_playwright_instance = None
_browser = None
_context: Optional[BrowserContext] = None

# Injected into every new page before any page scripts run.
# Removes the navigator.webdriver flag that automation leaves behind, and
# ensures window.chrome exists (real Chromium has it; headless Playwright doesn't).
_STEALTH_SCRIPT = """
    Object.defineProperty(navigator, 'webdriver', {
        get: () => undefined,
        configurable: true,
    });
    if (!window.chrome) {
        window.chrome = { runtime: {} };
    }
"""


class BrowserResponse:
    """Minimal response interface matching what fast_flights expects from its fetch function."""

    def __init__(self, status_code: int, text: str) -> None:
        self.status_code = status_code
        self.text = text
        self.text_markdown = text


def _get_context() -> BrowserContext:
    """Return the shared browser context, creating it on the first call."""
    global _playwright_instance, _browser, _context
    if _context is None:
        _playwright_instance = sync_playwright().start()
        browser_type = getattr(_playwright_instance, config.PLAYWRIGHT_BROWSER)
        _browser = browser_type.launch(headless=config.PLAYWRIGHT_HEADLESS)
        proxy = {"server": config.PLAYWRIGHT_PROXY_URL} if config.PLAYWRIGHT_PROXY_URL else None
        _context = _browser.new_context(
            viewport={"width": 1280, "height": 900},
            proxy=proxy,
        )
        _context.add_init_script(_STEALTH_SCRIPT)
        # Signal to Google that the user has already handled cookie consent,
        # bypassing the EU GDPR consent wall. Same approach as the old primp
        # path which sent Cookie: SOCS=CAI on every request.
        _context.add_cookies([{
            "name": "SOCS",
            "value": "CAI",
            "domain": ".google.com",
            "path": "/",
            "sameSite": "Lax",
        }])
        logger.info(
            "Browser launched: %s headless=%s proxy=%s",
            config.PLAYWRIGHT_BROWSER,
            config.PLAYWRIGHT_HEADLESS,
            bool(config.PLAYWRIGHT_PROXY_URL),
        )
    return _context


def shutdown_browser() -> None:
    """Close the browser cleanly. Call on process exit."""
    global _playwright_instance, _browser, _context
    if _context:
        _context.close()
        _context = None
    if _browser:
        _browser.close()
        _browser = None
    if _playwright_instance:
        _playwright_instance.stop()
        _playwright_instance = None


def browser_fetch(params: dict) -> BrowserResponse:
    """Navigate to Google Flights via a real headed browser and return the page body.

    Replaces patched_fetch as the transport layer. fast_flights' URL construction
    and response parsing are unchanged — only the HTTP layer is swapped.
    page.close() is always called via finally so no pages leak between requests.
    """
    url = "https://www.google.com/travel/flights?" + urlencode(params)
    context = _get_context()
    page = context.new_page()
    try:
        try:
            response = page.goto(
                url,
                timeout=config.PLAYWRIGHT_TIMEOUT_MS,
                wait_until="domcontentloaded",
            )
        except Exception as exc:
            raise NetworkError(str(exc)) from exc

        if response is None:
            raise NetworkError("page.goto returned no response")

        status = response.status
        body = page.content()
    finally:
        page.close()

    if status in (429, 403):
        raise RateLimitedError(f"HTTP {status}")
    if status != 200:
        raise RuntimeError(f"HTTP {status}")

    if len(body.encode("utf-8")) < config.BOT_CHALLENGE_MIN_BYTES:
        raise BotChallengeError("response below minimum length")

    # Match patterns against the page <title> only — not the full body.
    # Google Flights legitimately includes reCAPTCHA JS on every page, so
    # "captcha" appears in script URLs even on clean responses. A real block
    # page has a suspicious title ("Unusual Traffic Detected", "Before you
    # continue"); a real Flights page title never contains these words.
    title_match = re.search(r"<title[^>]*>(.*?)</title>", body, re.IGNORECASE | re.DOTALL)
    title = title_match.group(1).lower() if title_match else ""
    for pattern in config.BOT_CHALLENGE_TITLE_PATTERNS:
        if pattern.lower() in title:
            raise BotChallengeError(f"detected pattern in title: {pattern}")

    return BrowserResponse(status, body)


def install_browser_patch() -> None:
    """Probe the browser config and patch fast_flights.core.fetch with browser_fetch.

    Must be called once at process startup. Raises RuntimeError if the browser
    cannot be launched (missing display, bad PLAYWRIGHT_BROWSER value, etc.) so
    that misconfigurations are immediately visible rather than silently degrading.
    """
    import fast_flights.core

    try:
        _get_context()
    except Exception as exc:
        raise RuntimeError(
            f"Failed to launch Playwright browser ({config.PLAYWRIGHT_BROWSER}, "
            f"headless={config.PLAYWRIGHT_HEADLESS}): {exc}. "
            "Check that 'playwright install chromium' has been run and, if "
            "headless=False, that a display is available."
        ) from exc

    fast_flights.core.fetch = browser_fetch
    logger.info("fast_flights.core.fetch replaced with browser_fetch")
