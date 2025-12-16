from __future__ import annotations

import itertools
from collections.abc import Iterable
from typing import Any


def first_or_else(iterable: Iterable[Any], default: Any) -> Any | None:
    item = next(iter(iterable or []), None)
    if item is None:
        return default
    return item


def first_or_none(iterable: Iterable[Any]) -> Any | None:
    return first_or_else(iterable, None)


def first(iterable: Iterable[Any]) -> Any:
    return next(iter(iterable))


def as_lists(*args: Any) -> Any:
    """Convert any input objects to list objects."""
    for item in args:
        yield item if isinstance(item, list) else [item]


def as_list(*args: Any) -> list[Any]:
    """
    Convert any input objects to a single merged list object.

    Example:
    >>> as_list('foo', ['buzz', 'bizz'], 'bazz', 'bozz', ['bar'], ['bur'])
    ['foo', 'buzz', 'bizz', 'bazz', 'bozz', 'bar', 'bur']
    """
    if args == (None,):
        return []
    return list(itertools.chain.from_iterable(as_lists(*args)))


def flatten(L: Iterable[Any]) -> list[Any]:
    # https://stackoverflow.com/a/952952/492203
    return [item for sublist in L for item in sublist]
