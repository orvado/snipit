"""Global hotkey support built on the ``keyboard`` package.

Cross-platform notes:
- Windows: low-level hook, works unless a UAC-elevated window has focus.
- macOS: requires Accessibility permission + Input Monitoring; without it the
  hook install raises.  The error is surfaced via ``error_callback`` so the
  app can fall back to the tray icon and explain to the user.
- Linux: requires root or ``/dev/input`` access on some distros.
"""
from __future__ import annotations

import sys
import threading

try:
    import keyboard  # type: ignore
except Exception:  # pragma: no cover - import may fail on minimal installs
    keyboard = None  # type: ignore

from .platform import IS_MACOS


class Hotkey:
    """Registers a system-wide hotkey; the callback runs on the hook thread,
    so callers should funnel it to the UI thread themselves."""

    def __init__(self, combo: str, callback, error_callback=None):
        self.combo = combo
        self._callback = callback
        self._error = error_callback or (lambda exc: None)
        self._handler = None
        self._stop = threading.Event()
        self._thread = None

    def start(self) -> None:
        if self._thread is not None:
            return
        if keyboard is None:
            self._error(RuntimeError("keyboard package not available"))
            return

        def runner() -> None:
            try:
                # suppress is not supported on macOS darwin in some keyboard versions
                kwargs = {}
                if not IS_MACOS:
                    kwargs["suppress"] = True
                self._handler = keyboard.add_hotkey(self.combo, self._callback, **kwargs)
            except Exception as exc:  # hook installation can fail (permissions etc.)
                # Enrich macOS error with actionable hint
                if IS_MACOS and "permission" in str(exc).lower():
                    exc = RuntimeError(
                        f"{exc} — grant Accessibility + Input Monitoring permission "
                        "to SnipIt/Terminal in System Settings → Privacy & Security"
                    )
                self._error(exc)
                return
            self._stop.wait()
            if self._handler is not None:
                try:
                    keyboard.remove_hotkey(self._handler)
                except Exception:
                    pass

        self._thread = threading.Thread(target=runner, name="snipit-hotkey", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
