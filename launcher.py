"""Simple launcher: `python launcher.py` (also used by PyInstaller)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from snipit.app import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
