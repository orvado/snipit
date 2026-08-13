"""Global hotkey support built on the `keyboard` package."""
from __future__ import annotations

import threading

import keyboard


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

        def runner() -> None:
            try:
                self._handler = keyboard.add_hotkey(self.combo, self._callback, suppress=True)
            except Exception as exc:  # hook installation can fail (permissions etc.)
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
