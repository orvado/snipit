"""Test sandbox: keeps the suite away from real user data.

Importing this module *before* anything from ``snipit`` points the app at a
throwaway data directory. Without it, ``test_app`` builds a real ``App``, which
seeds and mutates the live database in %APPDATA%\\SnipIt.
"""
from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DATA_DIR = tempfile.mkdtemp(prefix="snipit-test-")
os.environ["SNIPIT_DATA_DIR"] = DATA_DIR
atexit.register(shutil.rmtree, DATA_DIR, True)


def db_path(name: str = "snipit.db") -> str:
    base = os.path.join(DATA_DIR, "SnipIt")
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, name)


def borrow_clipboard():
    """Copies now outlive the process (that is the point of clipboard.py), so
    tests must hand the user's clipboard back when they are done with it."""
    from snipit import clipboard

    saved = clipboard.paste()
    atexit.register(lambda: clipboard.copy(saved) if saved else None)
