from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import sys
import time
from http.cookiejar import Cookie
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import niquests
import utls
from niquests.adapters import HTTPAdapter
from niquests.exceptions import ConnectionError as NiquestsConnectionError
from rich.prompt import Prompt

from pptu.utils.log import eprint, print, wprint
from pptu.utils.twocaptcha import TwoCaptchaError, solve_turnstile

if TYPE_CHECKING:
    from http.cookiejar import MozillaCookieJar

RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})
MAX_TRANSIENT_RETRIES = 5
MAX_CHALLENGE_SOLVES = 2
# A managed challenge usually clears itself within seconds once a real browser
# renders it; the budget covers slow turnstile interludes.
INTERNAL_SOLVE_TIMEOUT = 75
INTERNAL_POLL_INTERVAL = 1
# With a 2captcha key, the browser gets this long to clear the check on its own
# before the Turnstile task is submitted (it costs a little per solve).
TWOCAPTCHA_GRACE = 15

# Injected before the challenge page loads: wraps `turnstile.render` (the widget
# still renders and works) to record what 2captcha needs - sitekey, cData,
# chlPageData, action - plus the callback that hands a token back to the page.
TURNSTILE_HOOK_JS = """
(() => {
  const timer = setInterval(() => {
    const ts = window.turnstile;
    if (!ts || !ts.render || ts.__pptuHooked) return;
    clearInterval(timer);
    ts.__pptuHooked = true;
    const render = ts.render;
    ts.render = function (el, opts) {
      try {
        window.__pptuTurnstile = {
          sitekey: opts.sitekey, pageurl: location.href, data: opts.cData,
          pagedata: opts.chlPageData, action: opts.action, userAgent: navigator.userAgent,
        };
        window.__pptuTurnstileCb =
          typeof opts.callback === "function"
            ? opts.callback
            : typeof opts.callback === "string"
              ? window[opts.callback]
              : null;
      } catch (e) {}
      return render.apply(this, arguments);
    };
  }, 10);
})();
"""

FALLBACK_CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

# Cookies issued by Cloudflare; cleared before re-solving so stale clearances
# never get replayed after they stop working.
CF_COOKIES = frozenset({"cf_clearance", "__cf_bm", "__cfruid", "__cf_chl_tk"})

# Markers found in Cloudflare challenge / block pages.
CHALLENGE_MARKERS = (
    "challenges.cloudflare.com",
    "challenge-platform",
    "_cf_chl_opt",
    "cf-chl",
    "cf-challenge",
    "cf-turnstile",
    "just a moment",
    "attention required",
    "cf-error-details",
    "checking your browser",
)


class CloudflareBlocked(RuntimeError):
    """Raised when a Cloudflare challenge could not be solved."""


def is_cloudflare_challenge(response: niquests.Response) -> bool:
    """Detect Cloudflare managed challenge / JS challenge pages."""
    if str(response.headers.get("cf-mitigated", "")).lower() == "challenge":
        return True
    if response.status_code not in (403, 503):
        return False
    body = (response.text or "")[:16384].lower()
    return any(marker in body for marker in CHALLENGE_MARKERS)


def _challenge_target_url(url: str) -> str:
    """Solve target for a challenged request URL.

    Clearance cookies are issued per host, so the site root is always a safe
    solve target - it exists for GET even when the challenged endpoint was a
    POST-only one (e.g. the upload form).
    """
    parsed = urlparse(url)
    return f"{parsed.scheme or 'https'}://{parsed.netloc}/"


def _chrome_user_agent() -> str:
    """User-Agent of the bundled chrome:stable utls preset."""
    with contextlib.suppress(Exception):
        return utls.Fingerprint.from_preset("chrome:stable").http_headers["User-Agent"]
    return FALLBACK_CHROME_UA


def _make_chrome_tls_context() -> utls.SSLContext:
    """BoringSSL context impersonating the latest stable Chrome on the wire."""
    context = utls.SSLContext(utls.PROTOCOL_TLS_CLIENT)
    context.load_default_certs()
    context.set_fingerprint("chrome:stable")
    return context


class _ChromeTLSAdapter(HTTPAdapter):
    """niquests adapter mounting a Chrome-impersonating utls TLS context.

    niquests has no public `ssl_context` option, so the context is injected
    into the connection pools here. urllib3-future automatically completes a
    bare utls context with the chrome:stable fingerprint, and rewrites request
    headers into Chrome's on-the-wire order (explicit headers keep their values).
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.tls_context = _make_chrome_tls_context()
        super().__init__(*args, **kwargs)

    def init_poolmanager(self, *args: Any, **kwargs: Any) -> None:
        kwargs["ssl_context"] = self.tls_context
        super().init_poolmanager(*args, **kwargs)

    def proxy_manager_for(self, proxy: str, **proxy_kwargs: Any) -> Any:
        proxy_kwargs["ssl_context"] = self.tls_context
        return super().proxy_manager_for(proxy, **proxy_kwargs)


def _internal_solver_available() -> bool:
    """True when the optional in-process browser driver is installed."""
    try:
        import nodriver  # noqa: F401
    except ImportError:
        return False
    return True


def _running_as_root() -> bool:
    return hasattr(os, "geteuid") and os.geteuid() == 0


def _ozone_platform_arg() -> str | None:
    """Ozone backend for a headed Chrome on Linux.

    Without an explicit `--ozone-platform`, a Chrome launched by nodriver under
    a Wayland session often fails to bring up its remote-debugging port, so the
    connection times out ("Failed to connect to browser"). Prefer X11 (XWayland)
    whenever a DISPLAY is reachable - its connect handshake is reliable - and
    fall back to the native Wayland backend only when there is no X server.
    macOS/Windows do not use Ozone.
    """
    if sys.platform in ("win32", "darwin"):
        return None
    if os.environ.get("DISPLAY"):
        return "x11"
    if os.environ.get("WAYLAND_DISPLAY"):
        return "wayland"
    return None


# Chromium-based browser binaries searched by name on PATH as a fallback when
# nodriver's own auto-detection fails. `which` resolves the platform extension
# (e.g. .exe on Windows), so this list works on Linux, macOS and Windows.
_BROWSER_BINARY_NAMES = (
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
    "chrome",
    "brave-browser",
    "brave-browser-stable",
    "microsoft-edge",
    "microsoft-edge-stable",
    "vivaldi",
    "vivaldi-stable",
)

# Usual install locations per OS, searched when nothing is found on PATH.
_LINUX_BROWSER_PATHS = (
    "/snap/bin/chromium",
    "/snap/bin/chrome",
    "/snap/bin/brave",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/usr/lib64/chromium-browser/chromium-browser",
    "/usr/lib/chromium-browser/chromium-browser",
    "/usr/lib/chromium/chromium",
    "/opt/google/chrome/chrome",
    "/opt/google/chrome-beta/chrome",
    "/opt/brave.com/brave/brave-browser",
    "/opt/brave.com/brave-beta/brave-browser",
    "/opt/microsoft/msedge/msedge",
    "/usr/bin/vivaldi",
    "/usr/bin/vivaldi-stable",
)

_MACOS_BROWSER_PATHS = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
)


def _windows_browser_paths() -> tuple[str, ...]:
    """Usual Windows install locations, expanded from the standard env roots."""
    roots = [
        os.environ.get("PROGRAMFILES", r"C:\Program Files"),
        os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
        os.environ.get("LOCALAPPDATA", ""),
    ]
    relatives = (
        r"Google\Chrome\Application\chrome.exe",
        r"Chromium\Application\chrome.exe",
        r"BraveSoftware\Brave-Browser\Application\brave.exe",
        r"Microsoft\Edge\Application\msedge.exe",
    )
    return tuple(str(Path(root, rel)) for root in roots if root for rel in relatives)


def _platform_browser_paths() -> tuple[str, ...]:
    if sys.platform == "darwin":
        return _MACOS_BROWSER_PATHS
    if sys.platform == "win32":
        return _windows_browser_paths()
    return _LINUX_BROWSER_PATHS


def _find_browser_binary() -> str | None:
    """Best-effort search for a usable Chromium-based browser binary.

    Broader than nodriver's auto-detection: also looks for vendor/distro/snap
    builds under their usual names and per-OS locations (Linux, macOS, Windows).
    Returns an executable path or None when nothing usable is installed.
    """
    from shutil import which

    for name in _BROWSER_BINARY_NAMES:
        found = which(name)
        if found:
            return found
    for candidate in _platform_browser_paths():
        path = Path(candidate)
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    return None


def _example_browser_path() -> str:
    """A `browser_path` example for the current OS."""
    if sys.platform == "darwin":
        return "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    if sys.platform == "win32":
        return r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    return "/snap/bin/chromium"


def _no_browser_message(start_error: Exception) -> str:
    """Actionable, OS-specific error for the 'no browser installed' case."""
    if sys.platform in ("darwin", "win32"):
        install = "Install Google Chrome (https://google.com/chrome), Edge or Brave."
    else:
        install = (
            "Install a Chromium-based browser, e.g.:\n"
            "  Debian/Ubuntu:  sudo apt install chromium-browser\n"
            "  Fedora:         sudo dnf install chromium\n"
            "  Arch:           sudo pacman -S chromium"
        )
    return (
        "The built-in Cloudflare solver could not find a Chrome/Chromium browser.\n"
        f"({start_error})\n"
        f"{install}\n"
        "Already installed somewhere custom? Set it in the tracker's config.toml section:\n"
        f'  browser_path = "{_example_browser_path()}"'
    )


def _cookie_matches_host(cookie_domain: str, host: str) -> bool:
    domain = cookie_domain.lstrip(".")
    return bool(domain) and (host == domain or host.endswith(f".{domain}"))


def _from_cdp_cookie(cookie: Any) -> Cookie:
    """Convert a CDP (nodriver) cookie into an http.cookiejar.Cookie."""
    # CDP uses -1 / None for session cookies.
    expires = (
        int(cookie.expires)
        if isinstance(cookie.expires, (int, float)) and cookie.expires > 0
        else None
    )
    rest: dict[str, Any] = {"HttpOnly": None} if cookie.http_only else {}
    domain = cookie.domain or ""
    return Cookie(
        version=0,
        name=cookie.name,
        value=cookie.value,
        port=None,
        port_specified=False,
        domain=domain,
        domain_specified=bool(domain),
        domain_initial_dot=domain.startswith("."),
        path=cookie.path or "/",
        path_specified=True,
        secure=bool(cookie.secure),
        expires=expires,
        discard=expires is None,
        comment=None,
        comment_url=None,
        rest=rest,
        rfc2109=False,
    )


def _str_from_evaluate(raw: Any) -> str:
    """Normalize a string result of `tab.evaluate(..., return_by_value=True)`."""
    if isinstance(raw, tuple) and raw and raw[0] is not None:
        raw = getattr(raw[0], "value", None)
    return raw if isinstance(raw, str) else ""


class _AsyncioNoiseFilter(logging.Filter):
    """Drop the cosmetic asyncio warnings nodriver's teardown emits.

    Terminating the browser ourselves and closing the loop makes asyncio log a
    child-watcher warning ("exit status already read") and a pending-task
    warning ("Task was destroyed but it is pending"). Both are harmless noise
    once the challenge is already solved, so they are filtered out by message.
    """

    _NEEDLES = ("exit status already read", "Task was destroyed but it is pending")

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        return not any(needle in message for needle in self._NEEDLES)


def _install_asyncio_noise_filter() -> None:
    """Attach the noise filter to the asyncio logger once."""
    logger = logging.getLogger("asyncio")
    if not any(isinstance(f, _AsyncioNoiseFilter) for f in logger.filters):
        logger.addFilter(_AsyncioNoiseFilter())


def _terminate_browser_process(browser: Any) -> None:
    """Make sure the launched Chrome does not outlive the solve."""
    process = getattr(browser, "_process", None)
    if process is not None:
        if getattr(process, "returncode", None) is None:
            with contextlib.suppress(Exception):
                process.terminate()
            time.sleep(0.5)
            if getattr(process, "returncode", None) is None:
                with contextlib.suppress(Exception):
                    process.kill()
        # Close the asyncio transport while the loop is still alive, otherwise
        # its GC finalizer trips over the closed loop and prints
        # "RuntimeError: Event loop is closed" noise after every solve.
        transport = getattr(process, "_transport", None)
        if transport is not None:
            with contextlib.suppress(Exception):
                transport.close()


def _browser_start_error(start_error: Exception, attempted: str | None) -> str:
    """Actionable error for the 'browser found but launch/connect failed' case."""
    lines = [
        "The built-in Cloudflare solver could not launch the browser.",
        f"({start_error})",
        f"Browser binary attempted: {attempted}",
    ]
    if attempted and "/snap/" in attempted:
        lines.extend(
            [
                "This is a snap wrapper - it often breaks Chrome's remote-debugging port.",
                "Prefer a native build: install Google Chrome (google.com/chrome) and let",
                "pptu auto-detect it, or point browser_path at the real inner binary",
                "(e.g. /snap/chromium/current/usr/lib/chromium-browser/chrome).",
            ]
        )
    else:
        lines.extend(
            [
                "If that path is a wrapper script, point browser_path at the real chrome",
                "executable instead, or install a native Google Chrome build.",
            ]
        )
    return "\n".join(lines)


async def _submit_turnstile(tab: Any, api_key: str) -> bool:
    """Have 2captcha solve the page's Turnstile check and hand the token back.

    Returns False while the page has not rendered the widget yet (try again on
    the next poll) and True once a task was submitted, whether or not 2captcha
    succeeded, so a paid task is never repeated. A failure is only reported:
    the browser window stays open, so the user can still click the checkbox.
    """
    raw = _str_from_evaluate(
        await tab.evaluate(
            "window.__pptuTurnstile ? JSON.stringify(window.__pptuTurnstile) : ''",
            return_by_value=True,
        )
    )
    if not raw:
        return False
    wprint("Cloudflare still waiting, asking 2captcha to solve the Turnstile check...")
    try:
        token = await asyncio.to_thread(solve_turnstile, api_key, json.loads(raw))
    except TwoCaptchaError as e:
        wprint(f"2captcha could not solve the Turnstile check: {e}")
        return True
    await tab.evaluate(
        f"(() => {{"
        f"  const token = {json.dumps(token)};"
        f"  const el = document.querySelector('[name=\"cf-turnstile-response\"]');"
        f"  if (el) el.value = token;"
        f"  if (typeof window.__pptuTurnstileCb === 'function') window.__pptuTurnstileCb(token);"
        f"}})()"
    )
    return True


def _solve_via_nodriver(
    url: str,
    *,
    proxy: str | None = None,
    browser_path: str | None = None,
    twocaptcha_api_key: str | None = None,
) -> tuple[str, list[Cookie]]:
    """Solve the challenge with a local Chrome driven by nodriver (in-process).

    Launches a real Chrome - auto-detected by nodriver, or the exact binary
    given via `browser_path` (the tracker config's `browser_path`) - waits
    until the challenge clears itself and a `cf_clearance` cookie for the host
    shows up in the browser cookie store, then returns the browser's
    User-Agent and the host's cookies for injection into CFSession.

    Always runs headed: headless Chrome is reliably detected and fails the
    managed challenge. On a display-less server, run inside a virtual display
    (`xvfb-run pptu ...`) or drop a browser-exported cookie into the tracker's
    cookie file instead.

    With a `twocaptcha_api_key`, a check the browser has not cleared by itself
    within `TWOCAPTCHA_GRACE` seconds is handed to 2captcha as a Turnstile task
    and the token is returned to the page, so unattended runs need no click.
    """
    import nodriver
    from nodriver import cdp

    # hostname (no port) - cookie domains never include ports.
    host = urlparse(url).hostname or ""
    browser_holder: list[Any] = []

    def _make_config(binary: str | None) -> Any:
        config = nodriver.Config(
            headless=False,
            sandbox=not _running_as_root(),
            browser_executable_path=binary,
        )
        if proxy:
            config.add_argument(f"--proxy-server={proxy}")
        if ozone := _ozone_platform_arg():
            config.add_argument(f"--ozone-platform={ozone}")
        return config

    async def _run() -> tuple[str, list[Cookie]]:
        attempted: str | None = browser_path
        try:
            browser = await nodriver.start(config=_make_config(browser_path))
        except Exception as start_error:
            browser = None
            if browser_path is None:
                # nodriver's own detection failed - try a broader scan before
                # giving up (covers snap builds, vendor prefixes, etc.).
                fallback = _find_browser_binary()
                if fallback:
                    attempted = fallback
                    wprint(
                        "nodriver auto-detection failed, using browser found at "
                        f"[cyan]{fallback}[/]"
                    )
                    try:
                        browser = await nodriver.start(config=_make_config(fallback))
                    except Exception:
                        browser = None
            if browser is None:
                message = (
                    _browser_start_error(start_error, attempted)
                    if attempted
                    else _no_browser_message(start_error)
                )
                raise CloudflareBlocked(message) from start_error
        browser_holder.append(browser)
        try:
            if twocaptcha_api_key:
                # The hook must be registered before the challenge page loads.
                tab = await browser.get("about:blank")
                await tab.send(cdp.page.enable())
                await tab.send(
                    cdp.page.add_script_to_evaluate_on_new_document(
                        source=TURNSTILE_HOOK_JS
                    )
                )
                await tab.get(url)
            else:
                tab = await browser.get(url)
            started = time.monotonic()
            deadline = started + INTERNAL_SOLVE_TIMEOUT
            submitted = False
            while True:
                all_cookies = await browser.cookies.get_all()
                if any(
                    cookie.name == "cf_clearance"
                    and _cookie_matches_host(cookie.domain, host)
                    for cookie in all_cookies
                ):
                    break
                if (
                    twocaptcha_api_key
                    and not submitted
                    and time.monotonic() - started >= TWOCAPTCHA_GRACE
                    and await _submit_turnstile(tab, twocaptcha_api_key)
                ):
                    submitted = True
                    # 2captcha takes a while; restart the clock for the page to
                    # accept the token and issue the clearance.
                    deadline = time.monotonic() + INTERNAL_SOLVE_TIMEOUT
                if time.monotonic() >= deadline:
                    raise CloudflareBlocked(
                        f"The built-in solver did not clear the Cloudflare challenge within "
                        f"{INTERNAL_SOLVE_TIMEOUT} seconds."
                    )
                await asyncio.sleep(INTERNAL_POLL_INTERVAL)

            user_agent = _str_from_evaluate(
                await tab.evaluate("navigator.userAgent", return_by_value=True)
            )
            if not user_agent:
                raise CloudflareBlocked("Could not read the solver browser's User-Agent.")

            host_cookies = [
                _from_cdp_cookie(cookie)
                for cookie in all_cookies
                if _cookie_matches_host(cookie.domain, host)
            ]
            return user_agent, host_cookies
        finally:
            with contextlib.suppress(Exception):
                browser.stop()

    loop = nodriver.loop()
    _install_asyncio_noise_filter()
    try:
        user_agent, cookies = loop.run_until_complete(_run())
    finally:
        # Terminate + close the subprocess transport while the loop is still
        # open, then cancel and drain whatever nodriver left pending (e.g. its
        # Connection.aclose task) so nothing is garbage-collected while still
        # pending - doing it the other way round prints asyncio teardown noise.
        for browser in browser_holder:
            _terminate_browser_process(browser)
        pending = [task for task in asyncio.all_tasks(loop) if not task.done()]
        for task in pending:
            task.cancel()
        with contextlib.suppress(Exception):
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        loop.close()
        asyncio.set_event_loop(None)
    return user_agent, cookies


def _manual_instructions(tracker: str, cookies_path: Path | str | None) -> str:
    location = cookies_path or "the tracker's cookie file"
    # xvfb only exists on Linux; on macOS/Windows there is always a display.
    xvfb_tip = (
        "\nTip: on a server that has a browser but no display, run the solver headed\n"
        "inside a virtual display instead:  xvfb-run pptu ..."
        if sys.platform not in ("win32", "darwin")
        else ""
    )
    return (
        f"Cloudflare blocked the request to {tracker} and no bypass is configured.\n"
        "\n"
        "Pick ONE of the fixes below:\n"
        "\n"
        "1. Built-in browser solver (desktop with a GUI):\n"
        "   pip install 'pptu[cloudflare]'   (or: pip install nodriver)\n"
        "   (needs a locally installed Chrome/Chromium; pptu briefly opens its own\n"
        "   browser to clear the check - nothing else to configure)\n"
        "   Browser not found or in a custom location (snap, flatpak, Brave, ...)?\n"
        f'   Add  browser_path = "{_example_browser_path()}"  to the [{tracker.lower()}] section.\n'
        "\n"
        "2. Browser cookies (headless / CLI-only servers):\n"
        "   a. On a machine with a browser, open the site and pass the Cloudflare check.\n"
        "   b. Export the site's cookies in Netscape cookies.txt format (must include\n"
        "      cf_clearance).\n"
        "   c. Save them as this file - the same one a normal login uses (works even\n"
        "      without username/password set):\n"
        f"      {location}\n"
        f"   d. Add that browser's exact User-Agent to the [{tracker.lower()}] section:\n"
        '      browser_ua = "Mozilla/5.0 ... Safari/537.36"\n'
        "\n"
        "Note: cf_clearance is bound to your IP address and User-Agent, so the browser that\n"
        f"obtained it must share pptu's network (same VPN/proxy exit) and User-Agent.{xvfb_tip}"
    )


def _is_seekable(obj: Any) -> bool:
    return callable(getattr(obj, "seek", None)) and callable(getattr(obj, "tell", None))


def _get_stream_positions(kwargs: dict[str, Any]) -> list[tuple[Any, int]]:
    """Capture initial positions of seekable streams in `data` / `files`.

    Request bodies are read to EOF on each attempt, so retries must rewind
    them or they would resend empty uploads.
    """
    candidates: list[Any] = [kwargs.get("data")]
    files = kwargs.get("files")
    if isinstance(files, dict):
        values: Any = files.values()
    elif isinstance(files, (list, tuple)):
        values = [value for _, value in files]
    else:
        values = []
    for value in values:
        # (filename, fileobj[, content_type[, headers]]) or a bare fileobj
        candidates.append(
            value[1] if isinstance(value, tuple) and len(value) > 1 else value
        )

    streams: list[tuple[Any, int]] = []
    for obj in candidates:
        if _is_seekable(obj):
            with contextlib.suppress(Exception):
                streams.append((obj, obj.tell()))
    return streams


def _rewind_streams(positions: list[tuple[Any, int]]) -> None:
    """Rewind seekable streams to their recorded positions before retrying."""
    for stream, pos in positions:
        with contextlib.suppress(Exception):
            stream.seek(pos)


class CFSession(niquests.Session):
    """Session for Cloudflare-protected trackers.

    A niquests session riding a Chrome-impersonating utls TLS context that
    transparently solves Cloudflare challenges (via a local Chrome driven by
    the optional `nodriver` package, or with a browser-exported cf_clearance
    cookie) and retries the original request. When no automatic solver is
    available on an interactive run, it tells the user where to drop a cookie
    file and waits for them before retrying.
    """

    def __init__(
        self,
        *,
        cookie_jar: MozillaCookieJar | None = None,
        cookies_path: Path | None = None,
        proxy: str | None = None,
        user_agent: str | None = None,
        browser_path: str | None = None,
        tracker_name: str = "tracker",
        twocaptcha_api_key: str | None = None,
        interactive: bool = True,
        **kwargs: Any,
    ) -> None:
        kwargs.setdefault("disable_http3", True)
        super().__init__(**kwargs)
        self._adapter = _ChromeTLSAdapter(disable_http3=True)
        self.mount("https://", self._adapter)
        self.mount("http://", self._adapter)
        self._cookie_jar = cookie_jar
        if cookie_jar is not None:
            for cookie in cookie_jar:
                self.cookies.set_cookie(cookie)
        if proxy:
            self.proxies.update({"all": proxy})
        self._tracker_name = tracker_name
        self._proxy = proxy
        self._browser_path = browser_path or None
        self._cookies_path = cookies_path
        self._twocaptcha_api_key = twocaptcha_api_key or None
        self._interactive = interactive
        # cf_clearance is bound to the User-Agent that minted it. Prefer the
        # explicit browser_ua, else the UA persisted from the last solve (so a
        # cached clearance keeps matching on later runs instead of forcing a new
        # solve), else the impersonated Chrome's UA.
        self.headers.update(
            {"User-Agent": user_agent or self._load_saved_ua() or _chrome_user_agent()}
        )

    def request(self, method: Any, url: str, **kwargs: Any) -> niquests.Response:  # type: ignore[override]  # ty: ignore[invalid-method-override]
        stream_positions = _get_stream_positions(kwargs)
        transient_retries = 0
        challenge_solves = 0
        while True:
            try:
                response = super().request(method, url, **kwargs)
            except NiquestsConnectionError:
                # Transport-level failure (DNS, connect, TLS...). Retry a few times
                # with backoff, mirroring the Retry adapter used for other trackers.
                transient_retries += 1
                if transient_retries > MAX_TRANSIENT_RETRIES:
                    raise
                _rewind_streams(stream_positions)
                time.sleep(min(2 ** (transient_retries - 1), 16))
                continue

            if is_cloudflare_challenge(response):
                challenge_solves += 1
                if challenge_solves > MAX_CHALLENGE_SOLVES:
                    eprint(
                        "Cloudflare challenge persists even after solving - the clearance "
                        "is likely bound to a different IP or User-Agent."
                    )
                    raise CloudflareBlocked(
                        _manual_instructions(self._tracker_name, self._cookies_path)
                    )
                self._solve_challenge(response, request_url=url)
                _rewind_streams(stream_positions)
                continue

            if (
                response.status_code in RETRYABLE_STATUSES
                and transient_retries < MAX_TRANSIENT_RETRIES
            ):
                transient_retries += 1
                _rewind_streams(stream_positions)
                time.sleep(min(2 ** (transient_retries - 1), 16))
                continue

            return response

    def _solve_challenge(
        self, response: niquests.Response, request_url: str = ""
    ) -> None:
        target = _challenge_target_url(str(response.url or request_url))
        target_host = urlparse(target).hostname or ""

        if _internal_solver_available():
            wprint(
                "Cloudflare challenge detected, solving with the built-in browser "
                "(if it shows a 'Verify you are human' checkbox, click it)..."
            )
            self._clear_cf_cookies(target_host)
            try:
                user_agent, cookies = _solve_via_nodriver(
                    target,
                    proxy=self._proxy,
                    browser_path=self._browser_path,
                    twocaptcha_api_key=self._twocaptcha_api_key,
                )
            except CloudflareBlocked:
                raise
            except Exception as e:
                raise CloudflareBlocked(
                    f"Built-in Cloudflare solver failed: {e}\n"
                    "\n"
                    f"{_manual_instructions(self._tracker_name, self._cookies_path)}"
                ) from e
            self._apply_solution(user_agent, cookies)
            return

        # No automatic solver: on an interactive run, let the user drop in an
        # exported cookie file at the login path and retry; otherwise give up
        # with the setup instructions.
        if self._prompt_for_cookies(target_host):
            return
        raise CloudflareBlocked(
            _manual_instructions(self._tracker_name, self._cookies_path)
        )

    def _apply_solution(self, user_agent: str, cookies: list[Cookie]) -> None:
        """Inject solver results (cookies + User-Agent) and persist them."""
        if user_agent:
            # cf_clearance is bound to the User-Agent of the solver - use it from
            # now on or the next request gets challenged again, and persist it so
            # later runs reuse the cached clearance instead of re-solving.
            self.headers.update({"User-Agent": user_agent})
            self._save_ua(user_agent)

        has_clearance = False
        for cookie in cookies:
            self.cookies.set_cookie(cookie)
            if self._cookie_jar is not None:
                self._cookie_jar.set_cookie(cookie)
            has_clearance = has_clearance or cookie.name == "cf_clearance"

        if not has_clearance:
            raise CloudflareBlocked(
                "The solver returned no cf_clearance cookie; the challenge was not solved."
            )
        print(f"Cloudflare challenge solved, injected [cyan]{len(cookies)}[/] cookies.")
        self._save_jar()

    def _clear_cf_cookies(self, host: str | None = None) -> None:
        for jar in (self.cookies, self._cookie_jar):
            if jar is None:
                continue
            for cookie in list(jar):
                if (cookie.name in CF_COOKIES or cookie.name.startswith("cf_chl")) and (
                    host is None or _cookie_matches_host(cookie.domain, host)
                ):
                    with contextlib.suppress(KeyError):
                        jar.clear(cookie.domain, cookie.path, cookie.name)

    def _save_jar(self) -> None:
        if self._cookie_jar is None:
            return
        filename = getattr(self._cookie_jar, "filename", None)
        if not filename:
            return
        with contextlib.suppress(OSError):
            Path(filename).parent.mkdir(parents=True, exist_ok=True)
            self._cookie_jar.save(ignore_discard=True, ignore_expires=True)

    def _ua_path(self) -> Path | None:
        """Sidecar file next to the cookie jar holding the last solved UA."""
        if self._cookies_path is None:
            return None
        return self._cookies_path.with_suffix(".ua")

    def _load_saved_ua(self) -> str | None:
        path = self._ua_path()
        if path is None:
            return None
        with contextlib.suppress(OSError):
            ua = path.read_text(encoding="utf-8").strip()
            return ua or None
        return None

    def _save_ua(self, user_agent: str) -> None:
        path = self._ua_path()
        if path is None:
            return
        with contextlib.suppress(OSError):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(user_agent, encoding="utf-8")

    def _prompt_for_cookies(self, target_host: str | None = None) -> bool:
        """Ask the user for exported cookies (and their User-Agent), then retry.

        Cookies go to the same file a normal login uses, so solved and
        hand-exported cookies live in one place. Skipped on unattended
        (`--auto`) or non-tty runs, where nobody can answer.
        """
        if not self._interactive or not sys.stdin.isatty() or self._cookies_path is None:
            return False
        wprint(
            f"Cloudflare is blocking {self._tracker_name} and no automatic solver is available."
        )
        print(
            "In a browser on the same network, pass the Cloudflare check, then export\n"
            "its cookies (Netscape cookies.txt format, including [cyan]cf_clearance[/]) to:\n"
            f"  [cyan]{self._cookies_path}[/]"
        )
        try:
            Prompt.ask(
                "Press Enter when the file is in place", default="", show_default=False
            )
            user_agent = Prompt.ask(
                "That browser's exact User-Agent (Enter to keep the current one)",
                default="",
                show_default=False,
            ).strip()
        except (EOFError, KeyboardInterrupt):
            return False
        if user_agent:
            self.headers.update({"User-Agent": user_agent})
            self._save_ua(user_agent)
        return self._reload_cookies(target_host)

    def _reload_cookies(self, host: str | None = None) -> bool:
        """Reload the cookie jar from disk into the session after the user edits it."""
        jar = self._cookie_jar
        filename = getattr(jar, "filename", None)
        if jar is None or not filename or not Path(filename).exists():
            wprint("No cookies file found at that path yet - giving up.")
            return False
        self._clear_cf_cookies(host)
        try:
            jar.load(ignore_discard=True, ignore_expires=True)
        except OSError as e:
            wprint(f"Could not read the cookies file: {e}")
            return False
        for cookie in jar:
            self.cookies.set_cookie(cookie)
        return True
