from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any

import niquests

if TYPE_CHECKING:
    from collections.abc import Iterator

_current: ContextVar[str | None] = ContextVar("proxy", default=None)


def current() -> str | None:
    return _current.get()


def _set_pymal(proxy: str | None) -> None:
    try:
        from pymal import global_functions  # type: ignore[import-untyped]
    except ImportError:
        return
    session: niquests.Session | None = getattr(global_functions, "__SESSION", None)
    if session is None:
        return
    session.proxies.pop("all", None)
    if proxy:
        session.proxies["all"] = proxy


@contextmanager
def using(proxy: str | None) -> Iterator[None]:
    token = _current.set(proxy)
    _set_pymal(proxy)
    try:
        yield
    finally:
        _current.reset(token)
        _set_pymal(_current.get())


def session(**kwargs: Any) -> niquests.Session:
    s = niquests.Session(disable_http3=True, **kwargs)
    if proxy := current():
        s.proxies.update({"all": proxy})
    return s
