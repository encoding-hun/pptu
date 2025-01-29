import importlib
import sys
from pathlib import Path

from ..utils import pluralize
from ._base import Uploader  # noqa: F401


# Load all services
failed_uploader = []

for uploader in sorted(Path(__file__).parent.iterdir()):
    if not uploader.name.startswith("_"):
        module = importlib.import_module(f"pptu.uploaders.{uploader.stem}")
        try:
            cls = getattr(
                module,
                next(
                    x
                    for x in module.__dict__
                    if x.lower() == f"{uploader.stem}uploader"
                ),
            )
        except StopIteration:
            failed_uploader.append(uploader.stem)
        else:
            globals()[cls.__name__] = cls


if failed_uploader:
    print(
        "Failed to load {form}: {services}".format(
            form=pluralize(len(failed_uploader), "uploader", include_count=False),
            services=", ".join(failed_uploader),
        ),
        file=sys.stderr,
    )
