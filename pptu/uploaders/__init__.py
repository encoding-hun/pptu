import importlib
import pkgutil
import sys

from pptu.uploaders._base import Uploader  # noqa: F401
from pptu.utils import pluralize

# Load all services
failed_uploader: list[str] = []
successful_uploader: list[str] = []

# pkgutil instead of listing the directory, so it also works in frozen builds
for uploader in sorted(pkgutil.iter_modules(__path__), key=lambda m: m.name):
    if not uploader.name.startswith("_"):
        module = importlib.import_module(f"pptu.uploaders.{uploader.name}")
        try:
            cls = getattr(
                module, next(x for x in module.__dict__ if x.lower() == uploader.name)
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
