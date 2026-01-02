from __future__ import annotations

import os
import shutil
from pathlib import Path

from pptu.utils.collections import first_or_none


def which(*executables):
    return first_or_none(
        sorted(
            (Path(x) for x in (shutil.which(x) for x in executables) if x),
            key=lambda x: os.environ["PATH"].split(os.pathsep).index(str(x.parent)),
        ),
    )
