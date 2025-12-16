from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import toml

from pptu.utils.click import CaseInsensitiveDict
from pptu.utils.log import eprint


if TYPE_CHECKING:
    from pptu.uploaders import Uploader


class Config:
    def __init__(self, file: Path):
        try:
            self._config = CaseInsensitiveDict(toml.load(file))
        except FileNotFoundError:
            shutil.copy(
                Path(__file__).resolve().parent.with_name("config.example.toml"), file
            )
            eprint(f"Config file doesn't exist, created to: [cyan]{file}[/]", fatal=True)

    def get(
        self,
        tracker: Uploader | Literal["default"] | str,
        key: str,
        default: Any = None,
    ) -> Any:
        value = None
        if isinstance(tracker, str) and tracker != "default":
            value = self._config.get(tracker, {}).get(key)
        elif tracker != "default":
            value = self._config.get(tracker.cli.name, {}).get(key) or self._config.get(
                tracker.cli.aliases[0], {}
            ).get(key)

        if value is False:
            return value
        defa = self._config.get("default", {}).get(key)
        if not value and defa is False:
            return defa

        return value or defa or default
