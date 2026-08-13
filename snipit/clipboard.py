"""Clipboard writes that outlive the process.

Tk does not put data *on* the Windows clipboard — it claims ownership and
renders the text on demand, so everything copied vanishes the moment SnipIt
exits. Handing the text to Win32 ourselves stores a real ``CF_UNICODETEXT``
block, which survives our exit and shows up in clipboard history (Win+V).

``copy()`` falls back to Tk if the Win32 path is unavailable or fails, so the
app still works (with the old caveat) on a non-Windows box.
"""
from __future__ import annotations

import ctypes
import sys
import time
from ctypes import wintypes

from .config import CLIPBOARD_CRLF

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002

# Another application can hold the clipboard open for a moment; retry briefly.
_OPEN_RETRIES = 10
_RETRY_DELAY = 0.01

IS_WINDOWS = sys.platform == "win32"


def _to_crlf(text: str) -> str:
    """Windows clipboard formats are documented as CRLF-delimited; some legacy
    Win32 edit controls run LF-only text together into one line."""
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\r\n")


def _win_api():
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.CloseClipboard.argtypes = []
    user32.CloseClipboard.restype = wintypes.BOOL
    user32.EmptyClipboard.argtypes = []
    user32.EmptyClipboard.restype = wintypes.BOOL
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.SetClipboardData.restype = wintypes.HANDLE

    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = wintypes.LPVOID
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalUnlock.restype = wintypes.BOOL
    kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalFree.restype = wintypes.HGLOBAL
    return user32, kernel32


def _set_windows(text: str) -> None:
    user32, kernel32 = _win_api()
    data = text.encode("utf-16-le") + b"\x00\x00"

    for _ in range(_OPEN_RETRIES):
        if user32.OpenClipboard(None):
            break
        time.sleep(_RETRY_DELAY)
    else:
        raise ctypes.WinError(ctypes.get_last_error())

    handle = None
    try:
        if not user32.EmptyClipboard():
            raise ctypes.WinError(ctypes.get_last_error())
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            ctypes.memmove(ptr, data, len(data))
        finally:
            kernel32.GlobalUnlock(handle)  # returns 0 on success too; don't check
        if not user32.SetClipboardData(CF_UNICODETEXT, handle):
            raise ctypes.WinError(ctypes.get_last_error())
        handle = None  # the system owns the block now — must not free it
    finally:
        if handle:
            kernel32.GlobalFree(handle)
        user32.CloseClipboard()


def copy(text: str, tk_widget=None) -> bool:
    """Put *text* on the clipboard.

    Returns True when the text was handed to the OS and will therefore outlive
    this process; False when only the Tk fallback was available.
    """
    if CLIPBOARD_CRLF:
        text = _to_crlf(text)

    if IS_WINDOWS:
        try:
            _set_windows(text)
            return True
        except OSError:
            pass  # fall through to Tk rather than losing the copy entirely

    if tk_widget is not None:
        tk_widget.clipboard_clear()
        tk_widget.clipboard_append(text)
        tk_widget.update_idletasks()
    return False


def paste() -> str:
    """Read UTF-16 text off the clipboard (used by 'New snippet from clipboard'
    style flows and by the tests, which restore what they borrowed)."""
    if not IS_WINDOWS:
        return ""
    user32, kernel32 = _win_api()
    user32.GetClipboardData.argtypes = [wintypes.UINT]
    user32.GetClipboardData.restype = wintypes.HANDLE

    for _ in range(_OPEN_RETRIES):
        if user32.OpenClipboard(None):
            break
        time.sleep(_RETRY_DELAY)
    else:
        return ""
    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return ""
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            return ""
        try:
            return ctypes.c_wchar_p(ptr).value or ""
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()
