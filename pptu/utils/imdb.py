from secrets import SystemRandom
from typing import Any

import niquests

from pptu.utils import dict_to_json

random = SystemRandom()


def __generate_fake_amz_sessid():
    # ie 198-4028299-3764156
    return f"{random.randint(100, 999)}-{random.randint(1000000, 9999999)}-{random.randint(1000000, 9999999)}"


# TODO: Add search
def get_imdb_data(title_id: str) -> dict[Any, Any]:
    if not title_id:
        raise ValueError("IMDb ID is required")
    if not isinstance(title_id, str):
        raise TypeError("IMDb ID must be a string")
    if not title_id.startswith("tt"):
        title_id = f"tt{title_id.lstrip('tT')}"

    res = niquests.get(
        url="https://imdb.com/",
        params={
            "operationName": "",
            "variables": dict_to_json(
                {
                    "id": title_id,
                }
            ),
            "extensions": dict_to_json(
                {
                    "persistedQuery": {
                        "version": 1,
                        "sha256Hash": "",
                    }
                }
            ),
        },
        headers={
            "connection": "Keep-Alive",
            "accept-encoding": "gzip",
            "x-amzn-sessionid": __generate_fake_amz_sessid(),
        },
    )

    res.raise_for_status()

    try:
        data = res.json()
    except niquests.exceptions.JSONDecodeError:
        raise ValueError("Failed to decode JSON response from IMDb API") from None

    return data.get("data", {}).get("title", {})
