from __future__ import annotations

from collections.abc import Mapping
from difflib import SequenceMatcher
from functools import lru_cache
from typing import Any

import orjson
from langcodes import closest_match


def dict_to_json(data: Mapping[Any, Any]) -> str:
    return orjson.dumps(data).decode()


def pluralize(count: int, singular: int, plural=None, include_count=True) -> str | Any:
    plural = plural or f"{singular}s"
    form = singular if count == 1 else plural
    return f"{count} {form}" if include_count else form


def similar(x: str, y: str) -> float:
    return SequenceMatcher(None, x, y).ratio()


@lru_cache(maxsize=50)
def is_close_match(language: str, languages: tuple[str]):
    if not (language and languages and all(languages)):
        return False

    languages = [str(x) for x in languages if x]

    return closest_match(language, languages)[1] <= 5
