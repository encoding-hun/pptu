import re

import httpx
from guessit import guessit

from pptu.utils.collections import first_or_none, first_or_else
from pptu.utils import similar
from pptu.utils.regex import find
from pptu.utils.log import wprint


def extract_name_from_filename(file_name: str) -> str:
    gi = guessit(file_name)
    if name := gi.get("title"):
        name.replace(".", " ")[:100]
    name = re.sub(r"[\.|\-]S\d+.*", "", file_name)
    if name == file_name:
        name = re.sub(r"[\.|\-]\d{4}\..*", "", file_name)
    name = name.replace(".", " ")[:100]

    return name


def get_anilist_title(
    search_name: str, non_english: bool = False, anilist_data: dict | None = None
) -> str | None:
    if not anilist_data:
        anilist_data = get_anilist_data(search_name)

    title: dict[str, str] = anilist_data.get("title", {})
    if non_english and title.get("english"):
        if title.get("english").casefold() not in search_name.casefold():
            return title.get("english")
        else:
            return ""
    elif title.get("romaji"):
        if title.get("romaji").casefold() not in search_name.casefold():
            if len(title.get("romaji")) > 85:
                return title.get("romaji")[:80]
            else:
                return title.get("romaji")
        else:
            return ""

    return None


def get_anilist_data(search_name: str, anilist_url: str = "") -> dict[str, str | int]:
    if anilist_url:
        anilist_id = find(r"https://anilist.co/anime/(\d+)", anilist_url)
        json_data = {
            "query": """
                query ($id: Int) {
                    Media(id: $id, type: ANIME) {
                        idMal
                        siteUrl
                        title {
                            romaji
                            english
                        }
                        synonyms
                    }
                }
            """,
            "variables": {"id": str(anilist_id)},
        }
    else:
        json_data = {
            "query": """
                query ($search: String) {
                    Page(perPage: 10) {
                        media(search: $search, type: ANIME) {
                            idMal
                            siteUrl
                            title {
                                romaji
                                english
                            }
                            synonyms
                        }
                    }
                }
            """,
            "variables": {"search": search_name},
        }

    with httpx.Client(transport=httpx.HTTPTransport(retries=5)) as client:
        res = client.post(
            url="https://graphql.anilist.co",
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            json=json_data,
        ).json()

    if error := first_or_none(res.get("errors", [])):
        wprint(f"Anilist error: {error.get('message')}")
        return {}

    if anilist_url:
        return res.get("data", {}).get("Media")
    else:
        if data := res.get("data", {}).get("Page", {}).get("media", []):
            for result in data:
                name_in = (search_name or "").casefold()
                name_en = (result.get("title", {}).get("english") or "").casefold()
                name_ori = (result.get("title", {}).get("romaji") or "").casefold()
                name_synonyms = result.get("synonyms", [])

                if (
                    (similar(name_en, name_in) >= 0.75)
                    or (similar(name_ori, name_in) >= 0.75)
                    or any(
                        x for x in name_synonyms if similar(x.casefold(), name_in) >= 0.75
                    )
                ):
                    return result

            return first_or_else(data, {})

    return {}
