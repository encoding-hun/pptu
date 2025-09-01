from types import SimpleNamespace
from typing import Any

import cloup

from pptu.uploaders._avistaznetwork import AvistaZNetwork, common_options


class PrivateHD(AvistaZNetwork):
    @staticmethod
    @cloup.command(
        name="PrivateHD",
        aliases=["PHD"],
        short_help="https://privatehd.to/",
        help=__doc__,
    )
    @common_options
    def cli(ctx: cloup.Context, **kwargs: Any) -> "PrivateHD":
        return PrivateHD(ctx, SimpleNamespace(**kwargs))
