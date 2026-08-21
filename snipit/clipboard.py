"""Cross-platform clipboard writes that outlive the process.

Windows:  Win32 CF_UNICODETEXT block (survives exit, shows in Win+V).
macOS:    pbcopy / NSPasteboard (survives exit, shows in clipboard history).
Linux:    xclip/xsel if available, otherwise Tk fallback.
Tk fallback only lends the clipboard while the app runs.

``copy()`` always tries the native path first and falls back to Tk.
"""
from __future__ import annotations

import ctypes
import shutil
import subprocess
import sys
import time
from ctypes import wintypes

from .config import CLIPBOARD_CRLF
from .platform import IS_MACOS, IS_WINDOWS

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002

_OPEN_RETRIES = 10
_RETRY_DELAY = 0.01


def _to_crlf(text: str) -> str:
    """Windows clipboard formats are documented as CRLF-delimited."""
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
            kernel32.GlobalUnlock(handle)
        if not user32.SetClipboardData(CF_UNICODETEXT, handle):
            raise ctypes.WinError(ctypes.get_last_error())
        handle = None
    finally:
        if handle:
            kernel32.GlobalFree(handle)
        user32.CloseClipboard()


# ------------------------------------------------------------------ macOS

def _set_macos(text: str) -> None:
    """Copy via pbcopy (always present on macOS). Raises on failure."""
    # pbcopy reads stdin and puts it on the general pasteboard
    proc = subprocess.run(
        ["pbcopy"],
        input=text.encode("utf-8"),
        timeout=2,
        check=True,
    )
    # Also try NSPasteboard via AppKit if available for richer types,
    # but pbcopy already suffices for plain text persistence.


def _get_macos() -> str:
    try:
        out = subprocess.run(["pbpaste"], capture_output=True, timeout=2, check=True)
        return out.stdout.decode("utf-8", "replace")
    except Exception:
        return ""


# ------------------------------------------------------------------ Linux

def _set_linux(text: str) -> bool:
    """Try xclip / xsel; return True if one succeeded."""
    encoded = text.encode("utf-8")
    for cmd in (["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]):
        if shutil.which(cmd[0]) is None:
            continue
        try:
            subprocess.run(cmd, input=encoded, timeout=2, check=True)
            return True
        except Exception:
            continue
    return False


def _get_linux(tk_widget=None) -> str:
    for cmd in (["xclip", "-selection", "clipboard", "-o"], ["xsel", "--clipboard", "--output"]):
        if shutil.which(cmd[0]) is None:
            continue
        try:
            out = subprocess.run(cmd, capture_output=True, timeout=2, check=True)
            return out.stdout.decode("utf-8", "replace")
        except Exception:
            continue
    if tk_widget is not None:
        try:
            return tk_widget.clipboard_get()
        except Exception:
            pass
    return ""


# ------------------------------------------------------------------ public API

def copy(text: str, tk_widget=None) -> bool:
    """Put *text* on the clipboard.

    Returns True when the text was handed to the OS and will therefore outlive
    this process; False when only the Tk fallback was available.
    """
    # Only Windows historically needs CRLF normalization
    if CLIPBOARD_CRLF and IS_WINDOWS:
        text = _to_crlf(text)

    if IS_WINDOWS:
        try:
            _set_windows(text)
            return True
        except OSError:
            pass
    elif IS_MACOS:
        try:
            _set_macos(text)
            return True
        except OSError:
            pass
        except subprocess.CalledProcessError:
            pass
        except FileNotFoundError:
            pass
    else:
        # Linux / other Unix
        try:
            if _set_linux(text):
                return True
        except Exception:
            pass

    if tk_widget is not None:
        try:
            tk_widget.clipboard_clear()
            tk_widget.clipboard_append(text)
            tk_widget.update_idletasks()
        except Exception:
            pass
        return False
    return False


def paste(tk_widget=None) -> str:
    """Read text off the clipboard."""
    if IS_WINDOWS:
        try:
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
        except Exception:
            return ""
    elif IS_MACOS:
        text = _get_macos()
        if text:
            return text
        if tk_widget is not None:
            try:
                return tk_widget.clipboard_get()
            except Exception:
                return ""
        return ""
    else:
        return _get_linux(tk_widget)
