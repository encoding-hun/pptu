import sys
import tomllib
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

PROG_NAME = "pptu"


def _get_version() -> str:
    try:
        return version(PROG_NAME)
    except PackageNotFoundError:
        pass

    try:
        meipass = getattr(sys, "_MEIPASS", None)
        base_dir = Path(meipass) if meipass else Path(__file__).resolve().parent.parent
        pyproject_file = base_dir / "pyproject.toml"
        if pyproject_file.is_file():
            data = tomllib.loads(pyproject_file.read_text(encoding="utf-8"))
            ver = data.get("project", {}).get("version")
            if isinstance(ver, str):
                return ver
    except Exception:
        pass

    return "unknown"


__version__ = _get_version()
