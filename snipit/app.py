"""SnipIt application wiring: database, UI, tray, hotkey, auto-close, IPC."""
from __future__ import annotations

import queue
import secrets
import socket
import sys
import threading
import time
import tkinter as tk
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from tkinter import messagebox
from urllib.parse import urlparse

from . import clipboard, config
from .backup import BackupStore
from .cloud import GoogleDriveProvider
from .config import APP_NAME, APP_VERSION, AUTO_CLOSE_MS
from .db import Database
from .hotkey import Hotkey
from .oauth import (
    TokenStore,
    build_authorize_url,
    exchange_code,
    make_code_verifier,
    parse_redirect,
    refresh_access_token,
)
from .tray import TrayIcon
from .ui import CloudWindow, DetailWindow, EditWindow, SearchWindow
from .ui import DANGER, NOTICE, OK


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
            "cloud": self.open_cloud,
        })
        self.detail = None
        self._auto_hide_job = None
        self._cloud_win = None
        self._connecting = False
        self.cloud_provider = None
        self.backup_store = None
        self._restore_cloud_session()

    # ------------------------------------------------------------- run/quit
    def run(self) -> int:
        self._start_ipc_thread()
        self.tray = TrayIcon(self._tray_show, self._tray_new, self._tray_quit,
                             self._tray_cloud, self._tray_backup)
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
        self.db.mark_used(row["id"])   # copying makes this the MRU snippet
        self.ui.refresh()              # so it floats to the top immediately
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
        self.db.mark_used(row["id"])   # viewing a snippet also counts as a use
        self.ui.refresh()
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

    # ------------------------------------------------------------- cloud
    def _restore_cloud_session(self) -> None:
        """Re-attach to a previously connected account (no UI side effects)."""
        if not config.GOOGLE_CLIENT_ID:
            return
        tok = TokenStore(config.cloud_token_path()).load()
        if tok.get("refresh_token"):
            self._attach_cloud(GoogleDriveProvider(
                config.GOOGLE_CLIENT_ID, self._cloud_token_getter()))

    def _attach_cloud(self, provider) -> None:
        self.cloud_provider = provider
        self.backup_store = BackupStore(provider, config.db_path(), config.backups_dir())

    def _cloud_token_getter(self):
        """Returns a callable yielding a fresh access token, refreshing as
        needed from the stored refresh token."""
        store = TokenStore(config.cloud_token_path())
        cid = config.GOOGLE_CLIENT_ID

        def getter() -> str:
            tok = store.load()
            if not tok.get("refresh_token"):
                raise RuntimeError("cloud not connected")
            if tok.get("access_token") and tok.get("expires_at", 0) > time.time() + 60:
                return tok["access_token"]
            fresh = refresh_access_token(None, tok["refresh_token"], cid)
            fresh["refresh_token"] = tok["refresh_token"]  # refresh may omit it
            fresh["expires_at"] = time.time() + fresh.get("expires_in", 3600)
            store.save(fresh)
            return fresh["access_token"]

        return getter

    def open_cloud(self) -> None:
        if self._cloud_win is not None and self._cloud_win.winfo_exists():
            self._cloud_win.lift()
            return
        self._ensure_visible()
        self._cloud_win = CloudWindow(self.root, actions={
            "connect": self.connect_cloud,
            "disconnect": self.disconnect_cloud,
            "backup": self.backup_now,
            "restore": self.restore_cloud,
        }, provider=self.cloud_provider, store=self.backup_store)
        self._cloud_list()

    def _cloud_list(self) -> None:
        store, win = self.backup_store, self._cloud_win
        if store is None or win is None or not win.winfo_exists():
            return

        def work() -> None:
            try:
                metas = store.list_backups()
            except Exception as exc:
                self._queue.put(lambda: self._cloud_error(f"list failed: {exc}"))
                return
            self._queue.put(lambda: win.set_backups(metas))

        threading.Thread(target=work, daemon=True, name="snipit-cloud-list").start()

    def _cloud_error(self, msg: str) -> None:
        self.ui.notify(msg, color=DANGER)
        win = self._cloud_win
        if win is not None and win.winfo_exists():
            win.set_status(msg)

    def connect_cloud(self) -> None:
        if self._connecting:
            self.ui.notify("Sign-in already in progress…", color=NOTICE)
            return
        if not config.GOOGLE_CLIENT_ID:
            self.ui.notify("Cloud not configured — set SNIPIT_GOOGLE_CLIENT_ID "
                           "(see README)", color=NOTICE)
            return
        self._connecting = True
        win = self._cloud_win
        if win is not None and win.winfo_exists():
            win.set_status("Waiting for browser sign-in…")

        def work() -> None:
            try:
                tokens = _run_connect_dance(
                    config.GOOGLE_CLIENT_ID, config.CLOUD_SCOPES,
                    on_redirect=lambda: self._queue.put(self._signin_stage))
                TokenStore(config.cloud_token_path()).save(tokens)
            except Exception as exc:
                print(f"[SnipIt] OAuth connect failed: {exc}", file=sys.stderr)
                self._queue.put(lambda: self._connect_failed(str(exc)))
                return
            print("[SnipIt] OAuth: connected", file=sys.stderr)
            self._queue.put(self._cloud_connected)

        threading.Thread(target=work, daemon=True, name="snipit-cloud-connect").start()

    def _signin_stage(self) -> None:
        """Main thread: the browser callback arrived; exchange is running."""
        win = self._cloud_win
        if win is not None and win.winfo_exists():
            win.set_status("Signed in — exchanging code…")

    def _connect_failed(self, msg: str) -> None:
        self._connecting = False
        self._cloud_error(f"connect failed: {msg}")

    def _cloud_connected(self) -> None:
        self._connecting = False
        self._attach_cloud(GoogleDriveProvider(
            config.GOOGLE_CLIENT_ID, self._cloud_token_getter()))
        self.ui.notify("Cloud connected ✓", color=OK)
        win = self._cloud_win
        if win is not None and win.winfo_exists():
            win.attach(self.cloud_provider, self.backup_store)
            self._cloud_list()

    def disconnect_cloud(self) -> None:
        try:
            config.cloud_token_path().unlink(missing_ok=True)
        except OSError:
            pass
        self.cloud_provider = None
        self.backup_store = None
        self.ui.notify("Cloud disconnected", color=NOTICE)
        win = self._cloud_win
        if win is not None and win.winfo_exists():
            win.attach(None, None)
            win.set_backups([])

    def backup_now(self) -> None:
        store = self.backup_store
        if store is None:
            self.ui.notify("Cloud not connected", color=NOTICE)
            return

        def work() -> None:
            try:
                name = store.backup()
            except Exception as exc:
                self._queue.put(lambda: self._cloud_error(f"backup failed: {exc}"))
                return
            self._queue.put(lambda: self._backup_done(name))

        threading.Thread(target=work, daemon=True, name="snipit-cloud-backup").start()

    def _backup_done(self, name: str) -> None:
        self.ui.notify("Backed up to cloud ✓", color=OK)
        win = self._cloud_win
        if win is not None and win.winfo_exists():
            win.set_status(f"Backed up — {name}")
            self._cloud_list()

    def restore_cloud(self) -> None:
        win = self._cloud_win
        name = win.selected_backup() if win is not None else ""
        if not name:
            self.ui.notify("Select a backup to restore", color=NOTICE)
            return
        if not messagebox.askyesno(
                APP_NAME,
                f"Restore “{name}”?\n\nLocal changes made after this backup "
                "will be lost.\nA safety snapshot of the current database is "
                "kept in the backups folder.",
                parent=self.root):
            return
        store = self.backup_store
        db_path = self.db.path

        def work() -> None:
            try:
                tmp = store.prepare_restore(db_path)
            except Exception as exc:
                self._queue.put(lambda: self._restore_failed(str(exc)))
                return
            self._queue.put(lambda: self._apply_restore(tmp))

        threading.Thread(target=work, daemon=True, name="snipit-cloud-restore").start()

    def _restore_failed(self, msg: str) -> None:
        self.ui.notify(f"Restore failed: {msg}", color=DANGER)
        # Make sure a working Database is attached no matter what.
        try:
            self.db.close()
        except Exception:
            pass
        self.db = Database(config.db_path())
        self.ui.db = self.db
        self.ui.refresh()

    def _apply_restore(self, tmp) -> None:
        try:
            new_db = self.backup_store.apply_restore(
                self.db, tmp, open_factory=Database)
        except Exception as exc:
            tmp.unlink(missing_ok=True)
            self._restore_failed(str(exc))
            return
        self._finish_restore(new_db)

    def _finish_restore(self, new_db) -> None:
        self.db = new_db
        self.ui.db = new_db
        self.ui.refresh()
        self.ui.notify("Restored from cloud backup ✓", color=OK)
        win = self._cloud_win
        if win is not None and win.winfo_exists():
            win.set_status("Restored from cloud backup ✓")
            self._cloud_list()

    # ------------------------------------------------------------- tray/hotkey
    def _tray_show(self) -> None:
        self._queue.put(self.show)

    def _tray_new(self) -> None:
        self._queue.put(self.open_add)

    def _tray_quit(self) -> None:
        self._queue.put(self.quit)

    def _tray_cloud(self) -> None:
        self._queue.put(self.open_cloud)

    def _tray_backup(self) -> None:
        self._queue.put(self.backup_now)

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
                    # Callbacks run on the UI thread; a failure must not
                    # vanish silently (the status bar is the user's only
                    # surface when running from the tray).
                    print(f"[SnipIt] callback error: {exc}", file=sys.stderr)
                    traceback.print_exc()
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
def _free_port() -> int:
    """Pick a free loopback port for the OAuth redirect server."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _run_connect_dance(client_id: str, scopes: list[str],
                       open_browser=webbrowser.open,
                       exchange_transport=None,
                       on_redirect=None,
                       timeout_s: float = 120.0) -> dict:
    """OAuth authorize-in-browser dance: bind the loopback server, open the
    browser, wait for the redirect, exchange the code. Returns tokens.

    ``open_browser`` and ``exchange_transport`` are injectable for tests;
    ``on_redirect`` (if given) is called once the callback arrives, before
    the token exchange, so callers can advance their UI status.
    The redirect URI uses the ``localhost`` hostname (Google's own desktop
    library does the same): proxy/VPN clients commonly exclude ``localhost``
    from their bypass list but not the raw ``127.0.0.1`` IP, and a proxy
    that intercepts the loopback navigation makes the dance fail silently.
    The server binds ``::1`` first (the usual first ``localhost`` resolution
    on Windows) with a ``127.0.0.1`` fallback.
    """
    verifier = make_code_verifier()
    state = secrets.token_urlsafe(16)
    port = _free_port()
    redirect_uri = f"http://localhost:{port}"
    url = build_authorize_url(client_id, redirect_uri, state, verifier, scopes)

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            try:
                code = parse_redirect(urlparse(self.path).query, state)
            except ValueError:
                self.send_error(400, "OAuth state mismatch")
                return
            self.server.auth_code = code
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                "<h2>SnipIt</h2><p>Signed in — you can close this window.</p>"
                .encode("utf-8"))

        def log_message(self, *args):
            pass

    try:
        server = HTTPServer(("::1", port), _Handler)
    except OSError:                       # no IPv6 loopback -> IPv4
        server = HTTPServer(("127.0.0.1", port), _Handler)
    server.auth_code = None
    # handle_request() blocks waiting for a connection; a timeout makes the
    # deadline below real, so a redirect that never arrives cannot hang the
    # connect flow forever (previously it stayed on "Waiting for browser
    # sign-in…" indefinitely).
    server.timeout = 0.5
    try:
        print(f"[SnipIt] OAuth: opening browser, waiting for callback at "
              f"{redirect_uri}", file=sys.stderr)
        open_browser(url)
        deadline = time.monotonic() + timeout_s
        while server.auth_code is None and time.monotonic() < deadline:
            try:
                server.handle_request()
            except OSError:
                continue   # a browser abort must not kill the dance
        if server.auth_code is None:
            raise TimeoutError(
                "sign-in timed out — the browser never reached the local "
                "callback page (if you use a proxy/VPN, make sure "
                "localhost is excluded from it)")
        print("[SnipIt] OAuth: callback received, exchanging code…",
              file=sys.stderr)
        if on_redirect is not None:
            on_redirect()
        return exchange_code(exchange_transport, server.auth_code, verifier,
                             redirect_uri, client_id)
    finally:
        server.server_close()


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


