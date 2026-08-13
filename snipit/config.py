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

# Sanity limits, not performance guards: measured at 500 rows x 8 KB, a full
# three-term progressive search costs ~15 ms — well under the 60 ms keystroke
# debounce — so the cap only needs to be large enough for real code snippets.
# Over-long content is refused at save time; it is never silently truncated.
MAX_CONTENT_LEN = 32768
MAX_HEADING_LEN = 120

# Upper bound of rows rendered in the single-line search list.
MAX_RESULTS = 300

# Windows clipboard formats are documented as CRLF-delimited. Set to False to
# put snippets on the clipboard with their stored line endings instead.
CLIPBOARD_CRLF = True

# Fixed localhost port used for single-instance signalling.
IPC_PORT = 48731

# Named mutex used for single-instance *detection* on Windows (the port above
# only carries the "come to the front" signal). Session-local on purpose: two
# users switched between accounts each get their own instance and own database.
MUTEX_NAME = "Local\\SnipIt.SingleInstance.v1"

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
