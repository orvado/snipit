"""Headless-ish UI smoke test: builds the real window, exercises search,
copy + auto-hide scheduling, then tears everything down."""
import _sandbox  # noqa: F401  (must precede snipit imports)
from _fakes import FakeCloud  # noqa: E402

import tkinter as tk  # noqa: E402
from pathlib import Path  # noqa: E402

from snipit.backup import BackupStore  # noqa: E402
from snipit.config import MAX_CONTENT_LEN  # noqa: E402
from snipit.db import Database  # noqa: E402
from snipit.ui import (  # noqa: E402
    CloudWindow,
    DetailWindow,
    EditWindow,
    SearchWindow,
    _looks_like_code,
)


def main():
    db = Database(_sandbox.db_path())

    root = tk.Tk()
    copied = []
    invoked = {"add": 0, "cloud": 0}

    def on_copy(row):
        copied.append(row["content"])

    ui = SearchWindow(root, db, actions={
        "copy": on_copy,
        "detail": lambda r: None,
        "add": lambda: invoked.update(add=invoked["add"] + 1),
        "edit": lambda: None,
        "delete": lambda: None,
        "escape": lambda: None,
        "hide": lambda: root.withdraw(),
        "cloud": lambda: invoked.update(cloud=invoked["cloud"] + 1),
    })

    root.update()  # force widget geometry so width math runs

    # progressive search
    ui.focus_search()
    root.update()
    ui._search_var.set("chat")
    root.update()
    ui.refresh()
    print("rows for 'chat':", ui.listbox.size())
    assert ui.listbox.size() >= 3, "expected chatgpt prompts to match 'chat'"

    ui._search_var.set("netsh")
    root.update()
    ui.refresh()
    print("rows for 'netsh':", ui.listbox.size())
    assert ui.listbox.size() == 1

    # copy selected
    ui.listbox.selection_clear(0, "end")
    ui.listbox.selection_set(0)
    ui.copy_selected()
    print("copied:", repr(copied[-1]))
    assert copied and "netsh" in copied[-1]

    copied_before = len(copied)
    ui.add_btn.focus_set()
    ui.add_btn.event_generate("<Return>")
    root.update()
    assert invoked["add"] == 1 and len(copied) == copied_before, \
        "Enter on Add must invoke Add instead of copying"
    ui.cloud_btn.focus_set()
    ui.cloud_btn.event_generate("<Return>")
    root.update()
    assert invoked["cloud"] == 1 and len(copied) == copied_before

    ui._search_var.set("chat")
    ui.refresh()
    ui.listbox.selection_clear(0, "end")
    ui.listbox.selection_set(1)
    selected_id = ui.selected_row()["id"]
    root.geometry("980x520")
    root.update()
    ui._resize_results()
    assert ui.selected_row()["id"] == selected_id, \
        "resize reformatting must preserve the selected snippet"

    # clear search back to placeholder
    ui.clear_search()
    root.update()
    print("placeholder on:", ui._placeholder_on, "| list size:", ui.listbox.size())
    assert ui._placeholder_on and not ui.has_search_text()

    # idle state must not read as a failed search
    print("idle count label:", repr(ui.count_lbl.cget("text")),
          "| status:", repr(ui.status.cget("text")[:20]))
    assert ui.count_lbl.cget("text").endswith("snippets"), \
        "an untouched search box is not a search with matches"
    assert "No matches" not in ui.status.cget("text")

    # detail window for a multi-line snippet
    row = db.search("rubber")[0]
    opened = {"edit": 0, "delete": 0}
    dlg = DetailWindow(root, row, actions={
        "copy": on_copy,
        "edit": lambda: opened.update(edit=opened["edit"] + 1),
        "delete": lambda: opened.update(delete=opened["delete"] + 1),
    })
    root.update()
    print("detail opened:", dlg.title(), "| code-like:", _looks_like_code(row["content"]))
    assert dlg.focus_get() == dlg.copy_btn, "Detail must focus its safe primary action"
    before_detail_copy = len(copied)
    dlg._on_copy_key()
    dlg._on_edit_key()
    dlg._on_delete_key()
    assert len(copied) == before_detail_copy + 1
    assert opened == {"edit": 1, "delete": 1}
    dlg.destroy()

    # edit window
    opened.clear()
    saved = []
    ew = EditWindow(root, on_save=lambda h, c: saved.append((h, c)),
                    initial_heading="h", initial_content="c1\n  c2", title="Edit snippet")
    root.update()
    ew._save()
    root.update()
    print("edit saved:", saved)
    assert saved and saved[0] == ("h", "c1\n  c2")

    # over-long content is refused, never silently trimmed
    ew2 = EditWindow(root, on_save=lambda h, c: saved.append((h, c)), title="New snippet")
    root.update()
    long = "x" * (MAX_CONTENT_LEN + 500)
    ew2.content_text.insert("1.0", long)
    root.update()          # <<Modified>> fires without any key being released
    text = ew2.content_text.get("1.0", "end-1c")
    print("pasted:", len(long), "| kept:", len(text),
          "| save button:", ew2._save_btn.cget("state"))
    assert len(text) == len(long), "content must not be truncated behind the user's back"
    assert str(ew2._save_btn.cget("state")) == "disabled", "over-long content must block Save"

    # trimming back under the limit re-enables Save
    ew2.content_text.delete("1.0", f"1.{600}")
    root.update()
    print("after trimming, save button:", ew2._save_btn.cget("state"))
    assert str(ew2._save_btn.cget("state")) == "normal"
    ew2.destroy()

    # cloud window: fake provider, backup click, list rendering
    cloud = FakeCloud()
    store = BackupStore(cloud, Path(db.path), Path(_sandbox.db_path("backups")), keep=3)
    restored = []
    win = CloudWindow(root, actions={
        "connect": lambda: None,
        "disconnect": lambda: None,
        "backup": lambda: store.backup(),
        "restore": lambda: restored.append(win.selected_backup()),
    }, provider=cloud, store=store)
    root.update()
    print("cloud status:", repr(win.status_lbl.cget("text")))
    assert "Connected" in win.status_lbl.cget("text")
    assert str(win.connect_btn.cget("state")) == "disabled", \
        "connect must be disabled once connected"
    win.actions["backup"]()
    root.update()
    assert any(p.name.startswith("snipit_backup_")
               for p in Path(_sandbox.db_path("backups")).glob("snipit_backup_*.db")), \
        "backup action must produce a local snapshot"
    win.set_backups(store.list_backups())
    root.update()
    print("backup list size:", win.backup_list.size())
    assert win.backup_list.size() >= 1
    assert win.selected_backup() == "", "nothing selected yet"
    assert str(win.restore_btn.cget("state")) == "disabled"
    win.backup_list.selection_set(0)
    win.backup_list.event_generate("<<ListboxSelect>>")
    root.update()
    assert win.selected_backup().startswith("snipit_backup_")
    assert str(win.restore_btn.cget("state")) == "normal"
    win._restore_key()
    assert restored == [win.selected_backup()]
    win.set_busy("backup")
    assert str(win.backup_btn.cget("state")) == "disabled"
    assert str(win.restore_btn.cget("state")) == "disabled"
    assert win.backup_btn.cget("text") == "Backing up…"
    win.set_busy(None)
    assert str(win.restore_btn.cget("state")) == "normal"
    win.destroy()

    root.destroy()
    db.close()
    print("UI SMOKE TEST PASSED")


if __name__ == "__main__":
    main()
