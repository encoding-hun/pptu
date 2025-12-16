from __future__ import annotations

import sys
from typing import Any, IO, Literal, NoReturn, overload

from rich.console import Console


def print(
    text: Any = "",
    highlight: bool = False,
    file: IO[str] = sys.stdout,
    flush: bool = False,
    **kwargs: Any,
) -> None:
    with Console(highlight=highlight) as console:
        console.print(text, **kwargs)
        if flush:
            file.flush()


def wprint(text: str) -> None:
    if text.startswith("\n"):
        text = text.lstrip("\n")
        print()
    print(f"[bold color(231) on yellow]WARNING:[/] [yellow]{text}[/]")


@overload
def eprint(text: str, fatal: Literal[False] = False, exit_code: int = 1) -> None: ...


@overload
def eprint(text: str, fatal: Literal[True], exit_code: int = 1) -> NoReturn: ...


def eprint(text: str, fatal: bool = False, exit_code: int = 1) -> None | NoReturn:
    if text.startswith("\n"):
        text = text.lstrip("\n")
        print()
    print(f"[bold color(231) on red]ERROR:[/] [red]{text}[/]")
    if fatal:
        sys.exit(exit_code)
    return None