import logging
import random
import re
from typing import Optional
from urllib.parse import urlencode, urlparse

from playwright.sync_api import BrowserContext, sync_playwright

import config
from src.flight_fetcher import BotChallengeError, NetworkError, RateLimitedError
from src.proxy_manager import load_proxies

logger = logging.getLogger(__name__)

# --- Module-level browser state (dual persistent contexts: direct and proxy) ---
_playwright_instance = None
_context_direct: Optional[BrowserContext] = None
_context_proxy: Optional[BrowserContext] = None
_proxy_url: Optional[str] = None

_LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-infobars",
]

# Injected into every new page before any page scripts run.
# Covers all major JavaScript-level bot-detection vectors. The launch arg
# --disable-blink-features=AutomationControlled handles the C++ level;
# this script handles the JS-observable surface.
_STEALTH_SCRIPT = """
(function () {
    // 1. Remove the webdriver flag
    Object.defineProperty(navigator, 'webdriver', {
        get: () => undefined,
        configurable: true,
    });

    // 2. Full window.chrome object — headless Chromium only stubs runtime
    if (!window.chrome || !window.chrome.loadTimes) {
        window.chrome = {
            app: {
                isInstalled: false,
                InstallState: {
                    DISABLED: 'disabled',
                    INSTALLED: 'installed',
                    NOT_INSTALLED: 'not_installed',
                },
                RunningState: {
                    CANNOT_RUN: 'cannot_run',
                    READY_TO_RUN: 'ready_to_run',
                    RUNNING: 'running',
                },
            },
            csi: function () { return {}; },
            loadTimes: function () { return {}; },
            runtime: {},
        };
    }

    // 3. navigator.plugins — empty array is an instant bot signal
    const pluginData = [];
    const pluginArray = Object.create(PluginArray.prototype);
    Object.defineProperty(pluginArray, 'length', { value: pluginData.length });
    pluginData.forEach(function (p, i) {
        const plugin = Object.create(Plugin.prototype);
        Object.defineProperty(plugin, 'name', { value: p.name });
        Object.defineProperty(plugin, 'filename', { value: p.filename });
        Object.defineProperty(plugin, 'description', { value: p.description });
        Object.defineProperty(plugin, 'length', { value: 0 });
        Object.defineProperty(pluginArray, i, { value: plugin });
        Object.defineProperty(pluginArray, p.name, { value: plugin });
    });
    Object.defineProperty(navigator, 'plugins', { get: function () { return pluginArray; }, configurable: true });
    Object.defineProperty(navigator, 'mimeTypes', {
        get: function () {
            const mt = Object.create(MimeTypeArray.prototype);
            Object.defineProperty(mt, 'length', { value: 0 });
            return mt;
        },
        configurable: true,
    });

    // 4. navigator.languages
    Object.defineProperty(navigator, 'languages', {
        get: function () { return ['en-US', 'en']; },
        configurable: true,
    });

    // 5. Permissions API — automation returns wrong state for notifications
    if (window.Permissions && window.Permissions.prototype.query) {
        const originalQuery = window.Permissions.prototype.query;
        window.Permissions.prototype.query = function (parameters) {
            if (parameters && parameters.name === 'notifications') {
                return Promise.resolve({ state: Notification.permission, onchange: null });
            }
            return originalQuery.call(this, parameters);
        };
    }

    // 6. WebGL vendor / renderer — headless reports generic Mesa strings
    (function patchWebGL(ctx) {
        if (!ctx) return;
        const getParameter = ctx.prototype.getParameter;
        ctx.prototype.getParameter = function (parameter) {
            if (parameter === 37445) return 'Intel Inc.';
            if (parameter === 37446) return 'Intel Iris OpenGL Engine';
            return getParameter.call(this, parameter);
        };
    })(window.WebGLRenderingContext);
    (function patchWebGL2(ctx) {
        if (!ctx) return;
        const getParameter = ctx.prototype.getParameter;
        ctx.prototype.getParameter = function (parameter) {
            if (parameter === 37445) return 'Intel Inc.';
            if (parameter === 37446) return 'Intel Iris OpenGL Engine';
            return getParameter.call(this, parameter);
        };
    })(window.WebGL2RenderingContext);

    // 7. Hardware signals — 0 is an automation giveaway
    Object.defineProperty(navigator, 'hardwareConcurrency', { get: function () { return 8; }, configurable: true });
    Object.defineProperty(navigator, 'deviceMemory', { get: function () { return 8; }, configurable: true });

    // 8. outerWidth/Height must be >= innerWidth/Height (headless omits them)
    if (window.outerWidth === 0) {
        Object.defineProperty(window, 'outerWidth', { get: function () { return window.innerWidth; } });
    }
    if (window.outerHeight === 0) {
        Object.defineProperty(window, 'outerHeight', { get: function () { return window.innerHeight + 74; } });
    }
})();
"""


class BrowserResponse:
    """Minimal response interface matching what fast_flights expects from its fetch function."""

    def __init__(self, status_code: int, text: str) -> None:
        self.status_code = status_code
        self.text = text
        self.text_markdown = text


def _get_context(use_proxy: bool) -> BrowserContext:
    """Return a persistent browser context, creating it on first call for its kind.

    Args:
        use_proxy: If True, return or create _context_proxy; otherwise _context_direct.

    Uses launch_persistent_context so cookies and localStorage survive across
    scrape runs. Profile directories are created by Playwright on first launch.
    """
    global _playwright_instance, _context_direct, _context_proxy, _proxy_url

    if _playwright_instance is None:
        _playwright_instance = sync_playwright().start()

    browser_type = getattr(_playwright_instance, config.PLAYWRIGHT_BROWSER)
    viewport = random.choice(config.PLAYWRIGHT_VIEWPORT_POOL)

    if use_proxy:
        if _context_proxy is None:
            if _proxy_url is None:
                raise RuntimeError("use_proxy=True but no proxy URL was configured")
            parsed = urlparse(_proxy_url)
            proxy = {
                "server": f"{parsed.scheme}://{parsed.hostname}:{parsed.port}",
                "username": parsed.username or "",
                "password": parsed.password or "",
            }
            _context_proxy = browser_type.launch_persistent_context(
                user_data_dir=config.PLAYWRIGHT_PROFILE_PROXY,
                headless=config.PLAYWRIGHT_HEADLESS,
                args=_LAUNCH_ARGS,
                viewport=viewport,
                user_agent=config.PLAYWRIGHT_USER_AGENT,
                locale="en-US",
                timezone_id="Europe/Amsterdam",
                extra_http_headers=config.PLAYWRIGHT_EXTRA_HEADERS,
                proxy=proxy,
            )
            _context_proxy.add_init_script(_STEALTH_SCRIPT)
            _context_proxy.add_cookies([{
                "name": "SOCS",
                "value": "CAI",
                "domain": ".google.com",
                "path": "/",
                "sameSite": "Lax",
            }])
            logger.info("Persistent browser context created (proxy=%s)", _proxy_url)
        return _context_proxy
    else:
        if _context_direct is None:
            _context_direct = browser_type.launch_persistent_context(
                user_data_dir=config.PLAYWRIGHT_PROFILE_DIRECT,
                headless=config.PLAYWRIGHT_HEADLESS,
                args=_LAUNCH_ARGS,
                viewport=viewport,
                user_agent=config.PLAYWRIGHT_USER_AGENT,
                locale="en-US",
                timezone_id="Europe/Amsterdam",
                extra_http_headers=config.PLAYWRIGHT_EXTRA_HEADERS,
            )
            _context_direct.add_init_script(_STEALTH_SCRIPT)
            _context_direct.add_cookies([{
                "name": "SOCS",
                "value": "CAI",
                "domain": ".google.com",
                "path": "/",
                "sameSite": "Lax",
            }])
            logger.info("Persistent browser context created (direct)")
        return _context_direct


def shutdown_browser() -> None:
    """Close both persistent contexts and clean up Playwright. Call on process exit."""
    global _playwright_instance, _context_direct, _context_proxy, _proxy_url
    if _context_direct:
        _context_direct.close()
        _context_direct = None
    if _context_proxy:
        _context_proxy.close()
        _context_proxy = None
    if _playwright_instance:
        _playwright_instance.stop()
        _playwright_instance = None
    _proxy_url = None


def browser_fetch(params: dict) -> BrowserResponse:
    """Navigate to Google Flights via a real headed browser and return the page body.

    Replaces patched_fetch as the transport layer. fast_flights' URL construction
    and response parsing are unchanged — only the HTTP layer is swapped.
    Routing decision: randomly choose direct or proxy context based on _proxy_url and PROXY_SPLIT_RATIO.
    page.close() is always called via finally so no pages leak between requests.
    """
    url = "https://www.google.com/travel/flights?" + urlencode(params)

    # Routing decision: 50/50 split if proxy is available
    use_proxy = _proxy_url is not None and random.random() < config.PROXY_SPLIT_RATIO
    context = _get_context(use_proxy=use_proxy)
    logger.debug("routing via %s", "proxy" if use_proxy else "direct")

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

    Loads proxies if available, probes both direct and proxy contexts, then patches
    fast_flights.core.fetch. Must be called once at process startup. Raises RuntimeError
    if the browser cannot be launched (missing display, bad PLAYWRIGHT_BROWSER value, etc.)
    so that misconfigurations are immediately visible rather than silently degrading.
    """
    import fast_flights.core
    global _proxy_url

    # Load proxies: if file missing or empty, log warning and continue direct-only
    try:
        proxies = load_proxies(config.PROXY_LIST_PATH)
        if proxies:
            _proxy_url = proxies[0]
            logger.info("Loaded %d proxies; using first: %s", len(proxies), _proxy_url)
        else:
            logger.warning("Proxy file %s is empty; running direct-only", config.PROXY_LIST_PATH)
    except FileNotFoundError:
        logger.warning("Proxy file %s not found; running direct-only", config.PROXY_LIST_PATH)

    # Probe direct context
    try:
        _get_context(use_proxy=False)
    except Exception as exc:
        raise RuntimeError(
            f"Failed to launch Playwright browser ({config.PLAYWRIGHT_BROWSER}, "
            f"headless={config.PLAYWRIGHT_HEADLESS}): {exc}. "
            "Check that 'playwright install chromium' has been run and, if "
            "headless=False, that a display is available."
        ) from exc

    # Probe proxy context if available
    if _proxy_url:
        try:
            _get_context(use_proxy=True)
        except Exception as exc:
            raise RuntimeError(
                f"Failed to create proxy context with proxy {_proxy_url}: {exc}"
            ) from exc

    fast_flights.core.fetch = browser_fetch
    logger.info("fast_flights.core.fetch replaced with browser_fetch")
