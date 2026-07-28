from __future__ import annotations

import time
from functools import lru_cache
from typing import Any

import niquests

from pptu.utils.log import wprint


@lru_cache(maxsize=32)
def rentry_upload(text: str, edit_code: str | None = None) -> dict[str, Any] | None:
    base_url = "https://rentry.co"
    for attempt in range(3):
        try:
            with niquests.Session(retries=3, disable_http3=True) as session:
                session.get(base_url, timeout=30)
                token = session.cookies.get("csrftoken", "")
                if not token:
                    wprint("Failed to get CSRF token from Rentry")
                    time.sleep(2**attempt)
                    continue

                res = session.post(
                    f"{base_url}/api/new",
                    headers={"Referer": base_url},
                    data={
                        "csrfmiddlewaretoken": token,
                        "edit_code": edit_code or "",
                        "text": text,
                        "url": "",
                    },
                    timeout=30,
                )
                if res.status_code == 200:
                    data = res.json()
                    if isinstance(data, dict):
                        return data
                wprint(f"Rentry upload returned status code {res.status_code}")
        except Exception as e:
            wprint(f"Rentry upload attempt {attempt + 1} failed: {e}")
        time.sleep(2**attempt)
    return None
