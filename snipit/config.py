"""Central configuration for SnipIt."""
from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "SnipIt"
APP_VERSION = "0.1.0"

# Global hotkey that summons / hides the window (syntax: the `keyboard` library).
DEFAULT_HOTKEY = os.environ.get("SNIPIT_HOTKEY", "ctrl+alt+s")

# Keep the window open for this long after a copy, then auto-hide.
# The user can press Esc during this window to cancel the auto-hide.
AUTO_CLOSE_MS = 1500

# Performance guards. SQLite TEXT can hold far more, but hundreds of multi-KB
# rows would slow down progressive search on every keystroke.
MAX_CONTENT_LEN = 1024
MAX_HEADING_LEN = 120

# Upper bound of rows rendered in the single-line search list.
MAX_RESULTS = 300

# Fixed localhost port used for single-instance signalling.
IPC_PORT = 48731

# Window geometry.
WINDOW_WIDTH = 720
WINDOW_HEIGHT = 420
MARGIN_TOP = 140


def data_dir() -> Path:
    base = os.environ.get("SNIPIT_DATA_DIR")
    if not base:
        base = os.environ.get("APPDATA") or str(Path.home())
    p = Path(base) / "SnipIt"
    p.mkdir(parents=True, exist_ok=True)
    return p


def db_path() -> Path:
    return data_dir() / "snipit.db"
