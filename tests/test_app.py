"""End-to-end app smoke test: builds the real App (tray, hotkey, IPC),
exercises the copy -> auto-hide -> Esc-cancel flow, then quits.

Runs against a throwaway data directory (see _sandbox) — it used to seed and
mutate the live database in %APPDATA%.
"""
import _sandbox  # noqa: F401  (must precede snipit imports)

from snipit import clipboard  # noqa: E402
from snipit.app import App, _try_bind_ipc  # noqa: E402


def main():
    _sandbox.borrow_clipboard()   # copies outlive us now; give it back on exit

    srv = _try_bind_ipc()
    assert srv is not None, "IPC socket should bind"

    app = App(ipc_socket=srv)
    root = app.root

    results = {}

    def step_show_copy():
        app.show()
        row = app.db.search("")[0]
        app.copy(row)
        results["pending"] = app._auto_hide_job is not None
        # Read it back through Win32, not Tk: that is what every other
        # application sees, and what used to be missing.
        results["clipboard"] = clipboard.paste().replace("\r\n", "\n")

    def step_escape_cancel():
        # cancel the pending auto-close like the user pressing Esc
        app.on_escape()
        results["cancelled"] = app._auto_hide_job is None

    def step_cloud_restore():
        # drive backup + restore through the real App with a fake provider
        from pathlib import Path
        from snipit.backup import BackupStore
        from _fakes import FakeCloud

        cloud = FakeCloud()
        app.backup_store = BackupStore(cloud, Path(app.db.path),
                                       Path(_sandbox.db_path("backups")), keep=3)
        app.cloud_provider = cloud
        before = app.db.count()
        app.backup_store.backup()
        app.db.add("cloud-restore-probe", "unique probe content")
        tmp = app.backup_store.prepare_restore(app.db.path)
        app._apply_restore(tmp)
        results["restored"] = (app.db.count() == before
                               and not app.db.search("cloud-restore-probe"))
        results["ui_refreshed"] = app.ui.listbox.size() == app.db.count()

    def step_quit():
        results["viewable"] = root.state() != "withdrawn"
        app.quit()

    root.after(600, step_show_copy)
    root.after(1300, step_escape_cancel)
    root.after(2200, step_cloud_restore)
    root.after(3100, step_quit)

    first_content = app.db.search("")[0]["content"]
    rc = app.run()
    print("run() returned:", rc)
    print("results:", results)
    assert results.get("pending") is True, "auto-hide should have been scheduled"
    assert results.get("cancelled") is True, "Esc should cancel auto-hide"
    assert results.get("viewable") is True, "window should still be visible after cancel"
    assert results.get("clipboard") == first_content, "clipboard should hold the copied snippet"
    assert results.get("restored") is True, \
        "restore must swap in the snapshot and drop post-backup edits"
    assert results.get("ui_refreshed") is True, "ui must re-render against the restored db"
    print("APP SMOKE TEST PASSED")


if __name__ == "__main__":
    main()
