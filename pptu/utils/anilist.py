import re
from typing import Any

import niquests
from guessit import guessit

from pptu.utils import similar
from pptu.utils.collections import first_or_else, first_or_none
from pptu.utils.log import wprint
from pptu.utils.regex import find


def extract_name_from_filename(file_name: str) -> tuple[str, bool]:
    is_movie = False

    gi = guessit(file_name)
    is_movie = gi.get("type") == "movie"
    if name := gi.get("title"):
        name = name.replace(".", " ")[:100]
    name = re.sub(r"[\.|\-]S\d+.*", "", file_name)
    if name == file_name:
        name = re.sub(r"[\.|\-]\d{4}\..*", "", file_name)
        if name != file_name:
            is_movie = True
    name = name.replace(".", " ")[:100]

    return name, is_movie


def get_anilist_title(
    search_name: str = "", non_english: bool = False, anilist_data: dict | None = None
) -> str | None:
    if not anilist_data:
        if not search_name:
            return None
        anilist_data = get_anilist_data(search_name)

    if not anilist_data:
        wprint("Failed to get anilist data")
        return None

    title: dict[str, str] = anilist_data.get("title", {})
    eng_title = title.get("english")
    romaji_title = title.get("romaji")

    if non_english:
        if eng_title and eng_title.casefold() not in search_name.casefold():
            return eng_title
        return ""

    if romaji_title and romaji_title.casefold() not in search_name.casefold():
        return romaji_title[:80] if len(romaji_title) > 85 else romaji_title
    return ""


def get_anilist_data(search_name: str = "", anilist_url: str = "") -> dict[str, Any]:
    if anilist_url:
        if mal_id := find(r"https://myanimelist.net/anime/(\d+)", anilist_url):
            json_data = {
                "query": """
                    query ($idMal: Int) {
                        Media(idMal: $idMal, type: ANIME) {
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
                "variables": {"idMal": int(mal_id)},
            }
        else:
            anilist_id = find(r"https://anilist.co/anime/(\d+)", anilist_url)
            if not anilist_id:
                return {}
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
                "variables": {"id": int(anilist_id)},
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

    with niquests.Session(retries=5, disable_http3=True) as session:
        res = session.post(
            url="https://graphql.anilist.co",
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            json=json_data,
        ).json()

    if error := first_or_none(res.get("errors", [])):
        wprint(f"Anilist error: {error.get('message')}")
        return {}

    if anilist_url:
        return res.get("data", {}).get("Media") or {}
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


def get_anilist_link(anilist_url: str = "", search_name: str = "") -> dict[str, Any]:
    """Get AniList data from URL or search name."""
    if anilist_url:
        return get_anilist_data(anilist_url=anilist_url)
    if search_name:
        return get_anilist_data(search_name=search_name)
    return {}


def process_anilist_info(link: str | None, name: str) -> tuple[str, str]:
    """Process AniList info and return name additions and info URL."""
    base_search_name, is_movie = extract_name_from_filename(name)
    gi = guessit(name)
    season = str(gi.get("season", "")) if gi.get("season") else ""

    search_name = base_search_name
    if not is_movie and season and season not in ["01", "1"]:
        search_name = f"{base_search_name} season {season}"

    anilist_data = get_anilist_link(link or "", search_name)

    # Fallback to search without season if initial season search returned nothing
    if not anilist_data and search_name != base_search_name:
        anilist_data = get_anilist_link(link or "", base_search_name)
        search_name = base_search_name

    target_url = link or ""
    if not target_url and anilist_data:
        target_url = anilist_data.get("siteUrl") or ""

    title = ""
    if anilist_data:
        t = get_anilist_title(search_name=search_name, anilist_data=anilist_data)
        if t is not None:
            title = t
        else:
            wprint("Failed to get AniList title")
    else:
        wprint("Failed to get AniList data")

    return title, target_url
