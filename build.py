"""One-command desktop build for SurveySuite.

Runs PyInstaller to produce a single-file executable. PyInstaller targets
the OS it runs on: run this on Windows for the distributable .exe.

Usage:
    python build.py            # one-file, windowed build into dist/
    python build.py --onedir   # one-folder build (faster startup)
"""
from __future__ import annotations

import pkgutil
import subprocess
import sys

APP_NAME = "SurveySuite"
ENTRY = "src/suite/app.py"


def _toolbox_hidden_imports() -> list[str]:
    """Every suite.toolbox_* module, for PyInstaller.

    Toolbox modules self-register via importlib with a computed module
    name, which static analysis cannot see -- without this the frozen
    app would silently lose every auto-discovered toolbox.
    """
    sys.path.insert(0, "src")
    import suite as _suite_pkg
    return [
        f"suite.{info.name}"
        for info in pkgutil.iter_modules(_suite_pkg.__path__)
        if info.name.startswith("toolbox_")
    ]


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
    ]
    for mod in _toolbox_hidden_imports():
        cmd += ["--hidden-import", mod]
    cmd.append(ENTRY)
    if onefile:
        cmd.insert(3, onefile)
    print("Running:", " ".join(cmd))
    subprocess.run(cmd, check=True)
    print(f"\nBuild complete: dist/{APP_NAME}/")


if __name__ == "__main__":
    main()
