"""One-command desktop build for SurveySuite.

Runs PyInstaller to produce a single-file executable. PyInstaller targets
the OS it runs on: run this on Windows for the distributable .exe.

Usage:
    python build.py            # one-file, windowed build into dist/
    python build.py --onedir   # one-folder build (faster startup)
"""
from __future__ import annotations

import subprocess
import sys

APP_NAME = "SurveySuite"
ENTRY = "src/suite/app.py"


def main() -> None:
    onefile = "--onefile" if "--onedir" not in sys.argv else ""
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        f"--name={APP_NAME}",
        # tkinter is stdlib; make sure its data files are collected
        "--collect-all", "tkinter",
        ENTRY,
    ]
    if onefile:
        cmd.insert(3, onefile)
    print("Running:", " ".join(cmd))
    subprocess.run(cmd, check=True)
    print(f"\nBuild complete: dist/{APP_NAME}/")


if __name__ == "__main__":
    main()
