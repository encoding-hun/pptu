from __future__ import annotations

import time
from typing import Any

import niquests

from pptu import __version__

SUBMIT_URL = "https://2captcha.com/in.php"
RESULT_URL = "https://2captcha.com/res.php"
# 2captcha asks for a short wait before the first poll, then ~5s between polls.
INITIAL_WAIT = 10
POLL_INTERVAL = 5
REQUEST_TIMEOUT = 30


class TwoCaptchaError(RuntimeError):
    """Raised when 2captcha rejects the task or cannot solve it in time."""


def _call(method: str, url: str, **kwargs: Any) -> dict[str, Any]:
    try:
        response = niquests.request(
            method,
            url,
            headers={"User-Agent": f"pptu/{__version__}"},
            timeout=REQUEST_TIMEOUT,
            **kwargs,
        )
        data: dict[str, Any] = response.json()
    except (niquests.exceptions.RequestException, ValueError) as e:
        raise TwoCaptchaError(f"2captcha request failed: {e}") from e
    if data.get("status") != 1:
        raise TwoCaptchaError(str(data.get("request") or data))
    return data


def solve_turnstile(api_key: str, params: dict[str, Any], *, timeout: int = 120) -> str:
    """Solve a Cloudflare Turnstile / challenge-page check and return the token.

    `params` holds what the page passes to `turnstile.render`: `sitekey`,
    `pageurl`, and for challenge pages `data` (cData), `pagedata`
    (chlPageData), `action` and the browser's `userAgent`.
    """
    task = {k: v for k, v in params.items() if v}
    if "useragent" in task and "userAgent" not in task:
        task["userAgent"] = task.pop("useragent")
    submitted = _call(
        "POST",
        SUBMIT_URL,
        data={"key": api_key, "method": "turnstile", "json": 1, **task},
    )
    task_id = submitted["request"]

    deadline = time.monotonic() + timeout
    time.sleep(INITIAL_WAIT)
    while True:
        try:
            return str(
                _call(
                    "GET",
                    RESULT_URL,
                    params={"key": api_key, "action": "get", "id": task_id, "json": 1},
                )["request"]
            )
        except TwoCaptchaError as e:
            if "CAPCHA_NOT_READY" not in str(e):
                raise
        if time.monotonic() >= deadline:
            raise TwoCaptchaError(f"timed out after {timeout} seconds")
        time.sleep(POLL_INTERVAL)
