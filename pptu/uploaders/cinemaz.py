from types import SimpleNamespace
from typing import Any

import cloup

from pptu.uploaders._avistaznetwork import AvistaZNetwork, common_options


class CinemaZ(AvistaZNetwork):
    @staticmethod
    @cloup.command(
        name="CinemaZ",
        aliases=["CZ"],
        short_help="https://cinemaz.to/",
        help=__doc__,
    )
    @common_options
    def cli(ctx: cloup.Context, **kwargs: Any) -> "CinemaZ":
        return CinemaZ(ctx, SimpleNamespace(**kwargs))
