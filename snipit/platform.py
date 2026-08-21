"""Cross-platform helpers for SnipIt.

Centralises OS detection and per-OS behaviour so the rest of the
codebase stays platform-agnostic.  No third-party dependencies.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"
IS_MACOS = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")

# ------------------------------------------------------------------ paths
def data_dir() -> Path:
    """Return the per-user data directory for SnipIt.

    Respects SNIPIT_DATA_DIR override first (used by tests).

    Windows: %APPDATA%\\SnipIt  (fallback %USERPROFILE% or ~)
    macOS:   ~/Library/Application Support/SnipIt
    Linux:   $XDG_DATA_HOME/snipit or ~/.local/share/snipit
    """
    override = os.environ.get("SNIPIT_DATA_DIR")
    if override:
        p = Path(override) / "SnipIt" if Path(override).name != "SnipIt" else Path(override)
        # Tests set SNIPIT_DATA_DIR to a temp dir and expect data_dir() == that_temp/SnipIt
        # but _sandbox already sets it to temp prefix; handle both.
        # For backwards compat: if SNIPIT_DATA_DIR already ends with SnipIt, don't double.
        # However regular user override like "/tmp/mydata" should become "/tmp/mydata/SnipIt"
        # The check above handles it.  But when SNIPIT_DATA_DIR is set to temp dir in tests,
        # data_dir() in config.py appends SnipIt again — we replicate that logic there.
        # Here we just return Path(override) verbatim if caller already handled.
        # Actually platform.data_dir() is low-level; config.data_dir() will handle
        # the override.  So this function when called with override should NOT be used.
        # We keep simple: return override path as-is if env set — config layer decides.
        # For direct use, honour env literally:
        return Path(override)

    if IS_WINDOWS:
        base = os.environ.get("APPDATA") or str(Path.home())
        return Path(base) / "SnipIt"
    if IS_MACOS:
        return Path.home() / "Library" / "Application Support" / "SnipIt"
    # Linux / other Unix
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / "snipit"
    return Path.home() / ".local" / "share" / "snipit"


def default_hotkey() -> str:
    """Sensible default hotkey per platform (``keyboard`` library syntax)."""
    # macOS keyboards have Cmd (command) — map to cmd+alt+s there,
    # but keep ctrl+alt+s as fallback if the user prefers.
    if IS_MACOS:
        # keyboard lib uses 'command' or 'cmd' for ⌘
        return os.environ.get("SNIPIT_HOTKEY", "command+alt+s")
    return os.environ.get("SNIPIT_HOTKEY", "ctrl+alt+s")


# ------------------------------------------------------------------ clipboard helpers
def clipboard_line_ending() -> str:
    """Line ending to use on the system clipboard."""
    if IS_WINDOWS:
        return "\r\n"
    return "\n"


# ------------------------------------------------------------------ single instance
def mutex_name() -> str:
    return "Local\\SnipIt.SingleInstance.v1"


# ------------------------------------------------------------------ display helpers
def hotkey_display(combo: str) -> str:
    """Human-readable hotkey for menus/status."""
    if IS_MACOS:
        return combo.replace("command", "⌘").replace("ctrl", "⌃").replace("alt", "⌥")
    return combo
