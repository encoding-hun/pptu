#!/usr/bin/env python3

import os
import platform
import subprocess
from pathlib import Path


print("[*] Updating pywidevine submodule")
subprocess.run(["git", "submodule", "update", "--init"], check=True)

print("\n[*] Installing dependencies")
subprocess.run(["poetry", "install"], check=True)

if platform.system() != "Windows":
    d = Path("~/.local/bin").expanduser()
    d.mkdir(parents=True, exist_ok=True)

    print("\n[*] Installing launcher script")
    (d / "pptu").unlink(missing_ok=True)
    (d / "pptu").symlink_to(Path(".venv/bin/pptu").resolve())

    if not any(
        Path(x).resolve() == d.resolve() for x in os.environ["PATH"].split(os.pathsep)
    ):
        print(f"[!] WARNING: {d} is not in PATH.")
