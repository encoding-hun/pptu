import time

from pymal.anime import Anime
from pymal.searches.search_animes_provider import SearchAnimesProvider
from rich import get_console

from pptu.utils import similar
from pptu.utils.anilist import extract_name_from_filename, get_anilist_data
from pptu.utils.collections import first
from pptu.utils.log import eprint, wprint
from pptu.utils.regex import find


def get_mal_data(search_name: str = "", mal_id: int | str | None = None) -> dict | None:
    console = get_console()

    if mal_id:
        try:
            with console.status("[bold magenta]Getting MAL info from input link..."):
                anime = Anime(int(mal_id))
                return {
                    "mal_id": anime.id,
                    "title": anime.title,
                    "title_english": anime.english,
                    "title_synonyms": anime.synonyms or [],
                    "url": f"https://myanimelist.net/anime/{anime.id}",
                }
        except Exception as e:
            wprint(f"Failed to fetch MAL data via pymal for ID {mal_id}: {e}")
            return None

    if search_name:
        try:
            with console.status("[bold magenta]Searching in MyAnimeList database..."):
                provider = SearchAnimesProvider()
                results = provider.search(search_name)
            if results:
                results_list = list(results)
                for anime in results_list[:10]:
                    name_in = (search_name or "").casefold()
                    name_ori = (anime.title or "").casefold()
                    name_en = (anime.english or "").casefold()
                    synonyms = anime.synonyms or []
                    name_syn = (synonyms[0] if synonyms else "").casefold()

                    if (
                        (similar(name_en, name_in) >= 0.75)
                        or (similar(name_ori, name_in) >= 0.75)
                        or (similar(name_syn, name_in) >= 0.75)
                    ):
                        return {
                            "mal_id": anime.id,
                            "title": anime.title,
                            "title_english": anime.english,
                            "title_synonyms": synonyms,
                            "url": f"https://myanimelist.net/anime/{anime.id}",
                        }

                best = first(
                    sorted(
                        results_list,
                        key=lambda x: similar(x.title or "", search_name),
                        reverse=True,
                    )
                )

                if best:
                    return {
                        "mal_id": best.id,
                        "title": best.title,
                        "title_english": best.english,
                        "title_synonyms": best.synonyms or [],
                        "url": f"https://myanimelist.net/anime/{best.id}",
                    }
        except Exception as e:
            wprint(f"Failed pymal search for '{search_name}': {e}")

    return None


def get_mal_title(
    search_name: str = "",
    non_english: bool = False,
    mal_id: int | str | None = None,
    mal_data: dict | None = None,
) -> str | None:
    if not mal_data:
        if mal_id:
            mal_data = get_mal_data(mal_id=mal_id)
        elif search_name:
            mal_data = get_mal_data(search_name=search_name)

    if not mal_data:
        return None

    eng_title = mal_data.get("title_english")
    main_title = mal_data.get("title")
    synonyms = mal_data.get("title_synonyms") or []

    if non_english:
        if eng_title and eng_title.casefold() not in search_name.casefold():
            return eng_title
        return ""

    if main_title and main_title.casefold() not in search_name.casefold():
        if len(main_title) > 85:
            if (
                synonyms
                and len(synonyms[0]) < 85
                and synonyms[0].casefold() not in search_name.casefold()
            ):
                return synonyms[0]
            return main_title[:80]
        return main_title

    return ""


def get_mal_link(mal_url: str = "", search_name: str = "") -> dict | None:
    """Get MAL data from input URL (MAL or AniList link) or search name."""
    if mal_url:
        if "myanimelist.net" in mal_url.lower():
            if mal_id := find(r"https://myanimelist.net/anime/(\d+)", mal_url):
                return get_mal_data(mal_id=mal_id)
        else:
            # Try resolving idMal from AniList link
            if (plus_data := get_anilist_data(anilist_url=mal_url)) and (
                mal_id := plus_data.get("idMal")
            ):
                return get_mal_data(mal_id=mal_id)

    if search_name:
        return get_mal_data(search_name=search_name)

    return None


def process_mal_info(
    link: str | None, name: str, max_retries: int = 3
) -> tuple[str, str]:
    """Process MAL info and return name additions and info URL."""
    search_name, _ = extract_name_from_filename(name)

    mal_data: dict | None = None
    for attempt in range(max_retries):
        try:
            mal_data = get_mal_link(link or "", search_name)
            break
        except Exception as e:
            delay = 2 ** (attempt - 1)
            wprint(f"Attempt {attempt + 1} failed for: {e}")
            if attempt == max_retries - 1:
                eprint("All MyAnimeList attempts failed")
            else:
                time.sleep(delay)

    if not mal_data and not link:
        return "", ""

    target_url = link or ""
    if not target_url and mal_data and mal_data.get("url"):
        target_url = mal_data["url"]

    title = ""
    if mal_data:
        try:
            title = get_mal_title(search_name=search_name, mal_data=mal_data) or ""
        except Exception as e:
            wprint(f"Failed to get MAL title: {e}")

    return title, target_url
