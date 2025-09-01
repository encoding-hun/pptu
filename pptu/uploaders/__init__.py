import importlib
import sys
from pathlib import Path

from pptu.uploaders._base import Uploader  # noqa: F401
from pptu.utils import pluralize


# Load all services
failed_uploader: list[str] = []
successful_uploader: list[str] = []

for uploader in sorted(Path(__file__).parent.iterdir()):
    if not uploader.name.startswith("_"):
        module = importlib.import_module(f"pptu.uploaders.{uploader.stem}")
        try:
            cls = getattr(
                module, next(x for x in module.__dict__ if x.lower() == uploader.stem)
            )
        except StopIteration:
            failed_uploader.append(cls.__name__)
        else:
            globals()[cls.__name__] = cls
            successful_uploader.append(cls.__name__)

if failed_uploader:
    print(
        "Failed to load {form}: {services}".format(
            form=pluralize(len(failed_uploader), "uploader", include_count=False),
            services=", ".join(failed_uploader),
        ),
        file=sys.stderr,
    )
