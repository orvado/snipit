#!/usr/bin/env python3
"""Cross-platform build script for SnipIt.

Usage:
  python build.py            # build for current OS
  python build.py --onefile  # single-file bundle (default)

Produces:
  Windows: dist/snipit.exe
  macOS:   dist/snipit       (and optionally dist/SnipIt.app with --app)
  Linux:   dist/snipit
"""
from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys

APP_NAME = "snipit"


def run(cmd: list[str]) -> None:
    print(f"+ {' '.join(cmd)}")
    subprocess.check_call(cmd)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Build SnipIt")
    parser.add_argument("--onefile", action="store_true", default=True, help="single-file bundle")
    parser.add_argument("--onedir", action="store_true", help="one-dir bundle instead of one-file")
    parser.add_argument("--app", action="store_true", help="on macOS, also build a .app bundle (requires py2app)")
    parser.add_argument("--no-clean", action="store_true", help="skip --clean")
    args = parser.parse_args(argv)

    is_macos = platform.system() == "Darwin"
    is_windows = platform.system() == "Windows"

    # Ensure PyInstaller is available
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        run([sys.executable, "-m", "pip", "install", "--upgrade", "pyinstaller"])

    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm"]
    if not args.no_clean:
        cmd.append("--clean")
    if args.onedir:
        pass
    else:
        cmd.append("--onefile")
    if is_windows:
        cmd.append("--noconsole")
        cmd += ["--name", APP_NAME]
    elif is_macos:
        cmd.append("--noconsole")
        cmd += ["--name", APP_NAME]
        # macOS: hide dock icon for background agent? Keep as normal app.
        # Add icon if available
    else:
        cmd += ["--name", APP_NAME]
    cmd.append("launcher.py")

    run(cmd)

    out = "dist/snipit.exe" if is_windows else "dist/snipit"
    print(f"\nBuilt: {out}")
    if is_macos and args.app:
        # Optional py2app build for a proper .app
        print("\nNote: --app with py2app not yet configured; use py2app directly or add setup.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
