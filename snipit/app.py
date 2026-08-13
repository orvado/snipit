"""SnipIt application wiring: database, UI, tray, hotkey, auto-close, IPC."""
from __future__ import annotations

import queue
import socket
import sys
import threading
import tkinter as tk
from tkinter import messagebox

from . import clipboard, config
from .config import APP_NAME, APP_VERSION, AUTO_CLOSE_MS
from .db import Database
from .hotkey import Hotkey
from .tray import TrayIcon
from .ui import DetailWindow, EditWindow, SearchWindow


class App:
    def __init__(self, ipc_socket):
        self._ipc_sock = ipc_socket
        self._queue = queue.Queue()

        self.db = Database(config.db_path())
        self._first_run = self.db.first_run

        self.root = tk.Tk()
        self.ui = SearchWindow(self.root, self.db, actions={
            "copy": self.copy,
            "detail": self.open_detail,
            "add": self.open_add,
            "edit": self.open_edit_selected,
            "delete": self.delete_selected,
            "escape": self.on_escape,
            "hide": self.hide,
        })
        self.detail = None
        self._auto_hide_job = None

    # ------------------------------------------------------------- run/quit
    def run(self) -> int:
        self._start_ipc_thread()
        self.tray = TrayIcon(self._tray_show, self._tray_new, self._tray_quit)
        self.tray.start()
        self.hotkey = Hotkey(config.DEFAULT_HOTKEY, self._hotkey_pressed,
                             error_callback=self._hotkey_error)
        self.hotkey.start()

        self.root.after(80, self._poll)
        self.root.withdraw()  # live quietly in the tray until summoned
        if self._first_run:
            self.root.after(500, self.show)
        try:
            self.root.mainloop()
        finally:
            self.db.close()
        return 0

    def quit(self) -> None:
        self._cancel_auto_hide()
        closers = [self.tray.stop, self.hotkey.stop]
        if self._ipc_sock is not None:
            closers.append(self._ipc_sock.close)
        for closer in closers:
            try:
                closer()
            except Exception:
                pass
        self.root.after(120, self.root.destroy)

    # ------------------------------------------------------------- visibility
    def show(self) -> None:
        self.root.deiconify()  # also restores a minimised ("iconic") window
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.focus_force()
        self.ui.focus_search()

    def hide(self) -> None:
        self._cancel_auto_hide()
        self.root.withdraw()

    def _is_visible(self) -> bool:
        # "iconic" (minimised) is just as invisible to the user as "withdrawn".
        return self.root.state() == "normal"

    def _has_focus(self) -> bool:
        try:
            # Empty/None when the focus sits in another application.
            return bool(self.root.focus_displayof())
        except (KeyError, tk.TclError):
            return False

    def toggle(self) -> None:
        # Summon when hidden, minimised, or merely buried behind another
        # window; only hide when we already have the user's attention.
        if self._is_visible() and self._has_focus():
            self.hide()
        else:
            self.show()

    def _ensure_visible(self) -> None:
        if not self._is_visible():
            self.root.deiconify()
            self.root.lift()

    # ------------------------------------------------------------- copy flow
    def copy(self, row) -> None:
        # Hands the text to Win32 so it outlives SnipIt; falls back to Tk
        # (which only lends the clipboard while we run) if that fails.
        persisted = clipboard.copy(row["content"], self.root)
        if self.detail is not None and self.detail.winfo_exists():
            self.detail.destroy()
            self.detail = None
        secs = f"{AUTO_CLOSE_MS / 1000:g}"
        self._cancel_auto_hide()
        note = f"Copied ✓ — hiding in {secs}s · press Esc to keep open"
        if not persisted:
            note = "Copied (only while SnipIt runs) — hiding · Esc to keep open"
        self.ui.notify(note, ms=AUTO_CLOSE_MS + 900)
        self._auto_hide_job = self.root.after(AUTO_CLOSE_MS, self._auto_hide_fired)

    def _auto_hide_fired(self) -> None:
        self._auto_hide_job = None
        self.hide()

    def _cancel_auto_hide(self) -> None:
        if self._auto_hide_job:
            self.root.after_cancel(self._auto_hide_job)
            self._auto_hide_job = None

    def on_escape(self) -> None:
        if self._auto_hide_job:
            self._cancel_auto_hide()
            self.ui.notify("Auto-close cancelled — window stays open", ms=1800)
            return
        if self.ui.has_search_text():
            self.ui.clear_search()
            return
        self.hide()

    # ------------------------------------------------------------- dialogs
    def open_detail(self, row) -> None:
        if self.detail is not None and self.detail.winfo_exists():
            self.detail.destroy()
        self._ensure_visible()
        self.detail = DetailWindow(self.root, row, actions={
            "copy": self.copy,
            "edit": lambda: self.open_edit(row),
            "delete": lambda: self.delete(row),
        })

    def open_add(self) -> None:
        was_visible = self._is_visible()
        if not was_visible:
            self._ensure_visible()

        def on_save(heading, content):
            sid = self.db.add(heading, content)
            self.ui.refresh()
            self.ui.select_id(sid)
            self.ui.notify(f"Saved “{heading or '(no title)'}”", ms=1600)
            if not was_visible:
                self.root.after(150, self.hide)

        EditWindow(self.root, on_save=on_save, title="New snippet")

    def open_edit_selected(self) -> None:
        row = self.ui.selected_row()
        if row:
            self.open_edit(row)

    def open_edit(self, row) -> None:
        def on_save(heading, content):
            self.db.update(row["id"], heading, content)
            self.ui.refresh()
            self.ui.select_id(row["id"])
            self.ui.notify("Snippet updated", ms=1600)

        EditWindow(self.root, on_save=on_save, initial_heading=row["heading"],
                   initial_content=row["content"], title="Edit snippet")

    # ------------------------------------------------------------- deletion
    def delete_selected(self) -> None:
        row = self.ui.selected_row()
        if row:
            self.delete(row)

    def delete(self, row) -> None:
        title = (row["heading"] or "").strip() or "(no title)"
        if not messagebox.askyesno(APP_NAME,
                                   f"Delete “{title}”?\n\nThis cannot be undone.",
                                   parent=self.root):
            return
        self.db.delete(row["id"])
        self.ui.refresh()
        if self.detail is not None and self.detail.winfo_exists():
            self.detail.destroy()
            self.detail = None

    # ------------------------------------------------------------- tray/hotkey
    def _tray_show(self) -> None:
        self._queue.put(self.show)

    def _tray_new(self) -> None:
        self._queue.put(self.open_add)

    def _tray_quit(self) -> None:
        self._queue.put(self.quit)

    def _hotkey_pressed(self) -> None:
        self._queue.put(self.toggle)

    def _hotkey_error(self, exc) -> None:
        print(f"[SnipIt] global hotkey unavailable: {exc}", file=sys.stderr)
        self._queue.put(lambda: messagebox.showwarning(
            APP_NAME,
            f"Could not register the global hotkey “{config.DEFAULT_HOTKEY}”:\n{exc}\n\n"
            "Use the system tray icon instead."))

    # ------------------------------------------------------------- plumbing
    def _poll(self) -> None:
        try:
            while True:
                fn = self._queue.get_nowait()
                try:
                    fn()
                except Exception as exc:
                    print(f"[SnipIt] callback error: {exc}", file=sys.stderr)
        except queue.Empty:
            pass
        self.root.after(80, self._poll)

    def _start_ipc_thread(self) -> None:
        if self._ipc_sock is None:  # port was busy; run without signalling
            return

        def serve() -> None:
            while True:
                try:
                    conn, _ = self._ipc_sock.accept()
                    conn.close()
                    self._queue.put(self.show)
                except OSError:
                    return

        threading.Thread(target=serve, daemon=True, name="snipit-ipc").start()


# ---------------------------------------------------------------- entry point
def _try_bind_ipc():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", config.IPC_PORT))
        s.listen(1)
        return s
    except OSError:
        s.close()
        return None


def _ping_running_instance() -> None:
    try:
        s = socket.create_connection(("127.0.0.1", config.IPC_PORT), timeout=0.5)
        s.close()
    except OSError:
        pass


_instance_mutex = None


def _already_running() -> bool:
    """True when another SnipIt owns this session.

    Uses a named mutex rather than the IPC port, so an unrelated process
    sitting on port 48731 can no longer masquerade as "SnipIt is running".
    The handle is parked in a module global to keep it alive for our lifetime.
    """
    global _instance_mutex
    if sys.platform != "win32":
        srv = _try_bind_ipc()  # best effort elsewhere
        if srv is None:
            return True
        srv.close()
        return False

    import ctypes
    from ctypes import wintypes

    ERROR_ALREADY_EXISTS = 183
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    handle = kernel32.CreateMutexW(None, False, config.MUTEX_NAME)
    if not handle:
        return False  # cannot tell; let the app start rather than block it
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        return True
    _instance_mutex = handle
    return False


def _remove_database() -> None:
    """Delete the database *and* its write-ahead log — leaving a stale -wal
    next to a fresh database is how you resurrect deleted rows."""
    path = config.db_path()
    targets = [path, path.with_name(path.name + "-wal"), path.with_name(path.name + "-shm")]
    locked = []
    for p in targets:
        if not p.exists():
            continue
        try:
            p.unlink()
            print(f"Removed: {p}")
        except OSError as exc:
            locked.append(f"{p} ({exc.strerror or exc})")
    if locked:
        raise RuntimeError(
            "Could not remove the database — something still has it open:\n  "
            + "\n  ".join(locked))


def _fatal(exc: BaseException) -> int:
    """Last-resort error reporting. A --noconsole build has no stderr, so an
    unhandled exception would otherwise mean the exe silently does nothing."""
    import traceback

    detail = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    print(detail, file=sys.stderr)
    try:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(APP_NAME, f"{APP_NAME} could not start:\n\n{exc}\n\n{detail[-800:]}")
        root.destroy()
    except Exception:
        pass
    return 2


def main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="snipit",
                                     description=f"{APP_NAME} — minimal snippet manager")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {APP_VERSION}")
    parser.add_argument("--reset-db", action="store_true",
                        help="delete the local database and reseed the sample snippets")
    args = parser.parse_args(argv)

    try:
        # Check for a running instance *first*: on Windows it holds the
        # database open, so resetting underneath it would fail on a file lock.
        if _already_running():
            if args.reset_db:
                print(f"{APP_NAME} is running — quit it from the tray icon "
                      "before using --reset-db.", file=sys.stderr)
                return 1
            _ping_running_instance()
            print(f"{APP_NAME} is already running — see the system tray.")
            return 1

        if args.reset_db:
            _remove_database()

        # A busy port is no longer fatal: we just lose the "bring the running
        # instance forward" signal, which beats refusing to start at all.
        srv = _try_bind_ipc()
        if srv is None:
            print(f"[{APP_NAME}] port {config.IPC_PORT} is busy — "
                  "running without single-instance signalling.", file=sys.stderr)

        app = App(ipc_socket=srv)
        return app.run()
    except Exception as exc:  # noqa: BLE001 - top-level guard for the packaged exe
        return _fatal(exc)


