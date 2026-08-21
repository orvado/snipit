"""System tray / menu-bar integration via ``pystray``.

Windows: system tray.  macOS: menu-bar status item (pystray uses NSStatusItem).
Linux: AppIndicator / tray as available.
"""
from __future__ import annotations

import sys
import threading

import pystray
from PIL import Image, ImageDraw

from .platform import IS_MACOS


def build_icon_image() -> Image.Image:
    """A tiny rounded tile with three horizontal 'snippet' bars.

    On macOS the image is used as a menu-bar icon; providing a 22x22
    template variant helps it render correctly in light/dark mode.
    pystray handles the conversion, but we keep the 64x64 source for
    Windows/Linux where a larger tray icon is expected.
    """
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((2, 2, 62, 62), radius=14, fill=(37, 48, 68, 255))
    d.rounded_rectangle((10, 10, 54, 54), radius=8, outline=(130, 150, 190, 255), width=2)
    d.rectangle((20, 23, 44, 26), fill=(255, 255, 255, 255))
    d.rectangle((20, 31, 44, 34), fill=(255, 255, 255, 255))
    d.rectangle((20, 39, 44, 42), fill=(255, 255, 255, 255))
    return img


def _mac_icon_image() -> Image.Image:
    # Smaller, higher-contrast version for macOS menu bar (template)
    img = Image.new("RGBA", (22, 22), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((1, 1, 21, 21), radius=5, fill=(37, 48, 68, 255))
    d.rectangle((6, 7, 16, 9), fill=(255, 255, 255, 255))
    d.rectangle((6, 11, 16, 13), fill=(255, 255, 255, 255))
    d.rectangle((6, 15, 16, 17), fill=(255, 255, 255, 255))
    return img


class TrayIcon:
    """Runs a pystray icon in a daemon thread. Callbacks are forwarded to the
    caller as-is, so they should marshal onto the UI thread if needed."""

    def __init__(self, show_callback, new_callback, quit_callback,
                 cloud_callback, backup_callback):
        menu = pystray.Menu(
            pystray.MenuItem("Show SnipIt", lambda: show_callback(), default=True),
            pystray.MenuItem("New snippet…", lambda: new_callback()),
            pystray.MenuItem("Back up now…", lambda: backup_callback()),
            pystray.MenuItem("Cloud…", lambda: cloud_callback()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", lambda: quit_callback()),
        )
        icon_img = _mac_icon_image() if IS_MACOS else build_icon_image()
        self._icon = pystray.Icon("snipit", icon_img, "SnipIt — snippet manager", menu)
        self._thread = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._icon.run, name="snipit-tray", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        try:
            self._icon.stop()
        except Exception:
            pass
