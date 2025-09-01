from types import SimpleNamespace
from typing import Any

import cloup

from pptu.uploaders._avistaznetwork import AvistaZNetwork, common_options


class AvistaZ(AvistaZNetwork):
    @staticmethod
    @cloup.command(
        name="AvistaZ",
        aliases=["AvZ"],
        short_help="https://avistaz.to/",
        help=__doc__,
    )
    @common_options
    def cli(ctx: cloup.Context, **kwargs: Any) -> "AvistaZ":
        return AvistaZ(ctx, SimpleNamespace(**kwargs))

    def __init__(self, ctx: cloup.Context, args: Any) -> None:
        super().__init__(ctx, args)

        self.year_in_series_name: bool = True
        self.keep_dubbed_dual_tags: bool = True
