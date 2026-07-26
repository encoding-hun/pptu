from __future__ import annotations

from typing import Any

import niquests

from pptu.utils.log import wprint


def send_telegram_message(
    uploader: Any,
    message: str,
    parse_mode: str = "html",
    disable_web_page_preview: bool = True,
    timeout: int = 30,
) -> bool:
    """Send a Telegram notification message using token and chat_id from uploader config."""
    if not message:
        return False

    config = getattr(uploader, "config", None)
    if not config:
        return False

    tg_token = config.get(uploader, "telegram_token") or config.get(
        "default", "telegram_token"
    )
    tg_id = config.get(uploader, "telegram_chat_id") or config.get(
        "default", "telegram_chat_id"
    )

    if not tg_token or not tg_id:
        return False

    try:
        with niquests.Session(retries=5, disable_http3=True) as client:
            res = client.post(
                url=f"https://api.telegram.org/bot{tg_token}/sendMessage",
                params={
                    "text": message,
                    "chat_id": str(tg_id),
                    "parse_mode": parse_mode,
                    "disable_web_page_preview": str(disable_web_page_preview).lower(),
                },
                timeout=timeout,
            )
            res.raise_for_status()
            return True
    except Exception as e:
        wprint(f"Failed to send Telegram notification: {e}")
        return False
