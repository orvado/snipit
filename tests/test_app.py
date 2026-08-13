"""End-to-end app smoke test: builds the real App (tray, hotkey, IPC),
exercises the copy -> auto-hide -> Esc-cancel flow, then quits."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from snipit.app import App, _try_bind_ipc  # noqa: E402


def main():
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
        results["clipboard"] = root.clipboard_get()

    def step_escape_cancel():
        # cancel the pending auto-close like the user pressing Esc
        app.on_escape()
        results["cancelled"] = app._auto_hide_job is None

    def step_quit():
        results["viewable"] = root.state() != "withdrawn"
        app.quit()

    root.after(600, step_show_copy)
    root.after(1300, step_escape_cancel)
    root.after(2200, step_quit)

    first_content = app.db.search("")[0]["content"]
    rc = app.run()
    print("run() returned:", rc)
    print("results:", results)
    assert results.get("pending") is True, "auto-hide should have been scheduled"
    assert results.get("cancelled") is True, "Esc should cancel auto-hide"
    assert results.get("viewable") is True, "window should still be visible after cancel"
    assert results.get("clipboard") == first_content, "clipboard should hold the copied snippet"
    print("APP SMOKE TEST PASSED")


if __name__ == "__main__":
    main()
