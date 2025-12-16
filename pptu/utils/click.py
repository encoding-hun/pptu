from __future__ import annotations

import re
from typing import Any

import cloup
import click


def comma_separated_param(ctx, param, value) -> list[str] | str:
    if isinstance(value, list):
        return value
    if not value:
        return []
    return re.split(r"\s*[,;]\s*", value)


class CaseInsensitiveSection(cloup.Section):
    def list_commands(self):
        return sorted(super().list_commands(), key=lambda x: x[0].casefold())


class CaseInsensitiveDict(dict[str, Any]):
    def __getitem__(self, key: str) -> Any:
        return super().__getitem__(key.lower())

    def __setitem__(self, key: str, value: Any) -> None:
        super().__setitem__(key.lower(), value)

    def get(self, key: str, default: Any | None = None) -> Any:
        return super().get(key.lower(), default)


class AliasedGroup(cloup.Group):
    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)

        self.alias2name = CaseInsensitiveDict()

    def add_command(self, cmd: click.Command, name: str, **kwargs: Any):
        super().add_command(cmd, name, **kwargs)

        # Allow the main command name to be used case-insensitively
        name = name or cmd.name
        self.alias2name[name] = name

    def handle_bad_command_name(self, valid_names: list[str], **kwargs: Any):
        # Filter out aliases from the error message
        # TODO: Figure out why commands are duplicated
        return super().handle_bad_command_name(
            valid_names=OrderedSet(x for x in valid_names if x in self.commands),
            **kwargs,
        )

    def resolve_command(
        self, ctx: click.Context, args: Any
    ) -> tuple[str | None, click.Command | None, list[str]]:
        # Always return the full command name
        _, cmd, args = super().resolve_command(ctx, args)
        return cmd.name, cmd, args
