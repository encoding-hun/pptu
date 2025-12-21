import json
from secrets import SystemRandom
from typing import Any

import httpx

from pptu.utils import dict_to_json


random = SystemRandom()


def __generate_fake_amz_sessid() -> str:
    # ie 198-4028299-3764156
    return f"{random.randint(100, 999)}-{random.randint(1000000, 9999999)}-{random.randint(1000000, 9999999)}"


IMDB_HEAERS = {
    "x-imdb-weblab-search-algorithm": "C",
    "user-agent": "Mozilla/5.0 (Linux; Android 14; sdk_gphone64_x86_64 Build/UE1A.230829.036.A4; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/139.0.7258.143 Mobile Safari/537.36 IMDb/9.2.4.109240300 (google|sdk_gphone64_x86_64; Android 34; google) IMDb-flg/9.1.8 (1344,2992,480,480) IMDb-var/app-andr-ph",
    "x-imdb-client-name": "imdb-app-android",
    "x-imdb-client-version": "9.2.4.109240300",
    "x-imdb-user-language": "en-US",
    "x-imdb-user-country": "US",
}


def imdb_search(query) -> list[dict[str, Any]]:
    if not query:
        raise ValueError("query is required")
    if not isinstance(query, str):
        raise TypeError("query must be a string")

    with httpx.Client(
        transport=httpx.HTTPTransport(retries=5),
        follow_redirects=True,
    ) as client:
        res = client.get(
            url=f"https://v3.sg.media-imdb.com/suggestion/a/{query}.json",
            params={
                "showOriginalTitles": "1",
            },
            headers={
                **IMDB_HEAERS,
                "content-type": "application/json",
                "connection": "Keep-Alive",
                "accept-encoding": "gzip",
                "x-amzn-sessionid": __generate_fake_amz_sessid(),
            },
        )

    res.raise_for_status()

    try:
        data = res.json()
    except json.JSONDecodeError:
        raise ValueError("Failed to decode JSON response from IMDb API") from res

    return [
        x
        for x in data.get("d", [])
        if x.get("qid", "").lower()
        in [
            "movie",
            "tvseries",
            "tvminiseries",
            "tvspecial",
            "tvmovie",
            "tvshort",
            "documentary",
        ]
    ]


def imdb_data(title_id) -> dict[str, Any]:
    if not title_id:
        raise ValueError("IMDb ID is required")
    if not isinstance(title_id, str):
        raise TypeError("IMDb ID must be a string")
    if not title_id.startswith("tt"):
        title_id = f"tt{title_id.lstrip('tT')}"

    with httpx.Client(
        transport=httpx.HTTPTransport(retries=5),
        follow_redirects=True,
    ) as client:
        res = client.get(
            url="https://caching.graphql.imdb.com/",
            params={
                "operationName": "TitleReduxOverviewQuery",
                "variables": dict_to_json(
                    {
                        "id": title_id,
                    }
                ),
                "extensions": dict_to_json(
                    {
                        "persistedQuery": {
                            "version": 1,
                            "sha256Hash": "7d991639daf1b0dbbd8f128253fde1c66445d9431a3d1f52bf6cd7586b403229",
                        }
                    }
                ),
            },
            headers={
                **IMDB_HEAERS,
                "apollo-require-preflight": "true",
                "accept": "multipart/mixed;deferSpec=20220824, application/graphql-response+json, application/json",
                "x-apollo-operation-name": "TitleReduxOverviewQuery",
                "content-type": "application/json",
                "connection": "Keep-Alive",
                "accept-encoding": "gzip",
                "x-amzn-sessionid": __generate_fake_amz_sessid(),
            },
        )

    res.raise_for_status()

    try:
        data = res.json()
    except json.JSONDecodeError:
        raise ValueError("Failed to decode JSON response from IMDb API") from res

    return data.get("data", {}).get("title", {})
