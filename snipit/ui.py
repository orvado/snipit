"""tkinter user interface for SnipIt.

Layout: one small always-on-top window — a search box on top, a single-line
results list below, and a status/hint bar. Dialogs (detail / add / edit) are
separate Toplevel windows.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont
from tkinter import messagebox

from .config import (
    APP_NAME,
    MAX_CONTENT_LEN,
    MAX_HEADING_LEN,
    MAX_RESULTS,
    MARGIN_TOP,
    WINDOW_HEIGHT,
    WINDOW_WIDTH,
)

# ---------------------------------------------------------------- palette
ACCENT = "#2f6fed"
ACCENT_D = "#1e56c9"
BG = "#f6f7f9"
FG = "#1c1e21"
MUTED = "#626975"
BORDER = "#d8dbe0"
SELECT = "#dbe7ff"
FG_SELECT = "#0b1b3a"
DANGER = "#c0392b"
NOTICE = "#b4550d"
OK = "#1e8e3e"
WHITE = "#ffffff"

PLACEHOLDER = "Type a title or phrase"


def _looks_like_code(content: str) -> bool:
    """Cheap heuristic: prefer a monospace font for code-ish snippets."""
    lines = content.splitlines()
    if len(lines) > 1 and sum(1 for ln in lines[1:] if ln[:1] in (" ", "\t")):
        return True
    tokens = ("{", "}", "=>", "::", "def ", "function ", "SELECT ", "INSERT ",
              "class ", "import ", "#include", "&&", "||", "#!/")
    return any(t in content for t in tokens)


def _center_window(window, parent, include_size: bool = False) -> None:
    window.update_idletasks()
    width, height = window.winfo_reqwidth(), window.winfo_reqheight()
    screen_width = window.winfo_screenwidth()
    screen_height = window.winfo_screenheight()
    x = parent.winfo_rootx() + (parent.winfo_width() - width) // 2
    y = parent.winfo_rooty() + (parent.winfo_height() - height) // 2
    x = min(max(0, x), max(0, screen_width - width))
    y = min(max(0, y), max(0, screen_height - height))
    size = f"{width}x{height}" if include_size else ""
    window.geometry(f"{size}+{x}+{y}")


# ---------------------------------------------------------------- fonts
BODY_FONT = SMALL_FONT = TITLE_FONT = CODE_FONT = LIST_FONT = None


def _init_fonts(root: tk.Tk) -> None:
    global BODY_FONT, SMALL_FONT, TITLE_FONT, CODE_FONT, LIST_FONT
    size = int(tkfont.nametofont("TkDefaultFont").cget("size")) or 9
    BODY_FONT = tkfont.nametofont("TkDefaultFont")
    SMALL_FONT = tkfont.Font(root=root, size=size)
    TITLE_FONT = tkfont.Font(root=root, size=size + 3, weight="bold")
    CODE_FONT = tkfont.Font(root=root, family="Consolas", size=size)
    LIST_FONT = tkfont.Font(root=root, family="Consolas", size=size)


# ================================================================ SearchWindow
class SearchWindow:
    HINT = ("Enter to copy · Double-click or Ctrl+Enter for details · Ctrl+N new · "
            "Ctrl+E edit · Ctrl+Del delete · Esc hide")

    def __init__(self, root: tk.Tk, db, actions: dict):
        self.root = root
        self.db = db
        self.actions = actions

        self.results = []          # sqlite rows aligned 1:1 with listbox items
        self._search_job = None
        self._resize_job = None
        self._render_width = 0
        self._notice_job = None
        self._placeholder = None

        _init_fonts(root)
        self._setup_window()
        self._build_widgets()
        self._bind_keys()
        self.refresh()

    # ------------------------------------------------------------- window
    def _setup_window(self) -> None:
        root = self.root
        root.title(APP_NAME)
        root.configure(bg=BG)
        root.minsize(430, 260)
        root.attributes("-topmost", True)
        root.protocol("WM_DELETE_WINDOW", self.actions["hide"])
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        w, h = min(WINDOW_WIDTH, max(320, sw - 24)), min(WINDOW_HEIGHT, max(240, sh - 120))
        x = (sw - w) // 2
        y = min(MARGIN_TOP, max(0, sh - h - 80))
        root.geometry(f"{w}x{h}+{x}+{y}")

    # ------------------------------------------------------------- widgets
    def _build_widgets(self) -> None:
        root = self.root

        tk.Label(root, text="Search snippets", bg=BG, fg=FG, anchor="w",
                 font=BODY_FONT).pack(fill="x", padx=12, pady=(10, 4))

        top = tk.Frame(root, bg=BG)
        top.pack(fill="x", padx=12, pady=(0, 6))

        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", lambda *a: self._on_search_changed())

        self.search_entry = tk.Entry(
            top, textvariable=self._search_var, font=BODY_FONT, relief="flat",
            highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT,
            bg=WHITE, fg=FG, insertbackground=FG,
        )
        self.search_entry.pack(side="left", fill="x", expand=True, ipady=5)

        # A hint drawn *over* the entry rather than stuffed into its variable:
        # keeping the query variable truthful is what makes the status bar,
        # the match count and the "is anything typed?" checks correct.
        self._placeholder = tk.Label(self.search_entry, text=PLACEHOLDER, bg=WHITE,
                                     fg=MUTED, font=BODY_FONT, anchor="w", cursor="xterm")
        self._placeholder.bind("<Button-1>", lambda e: self.search_entry.focus_set())
        self._sync_placeholder()

        self.clear_btn = tk.Button(
            top, text="Clear", command=self._clear_search, relief="flat", bg=BG,
            activebackground=BORDER, fg=MUTED, activeforeground=FG,
            font=BODY_FONT, cursor="hand2", padx=8, highlightthickness=2,
            highlightbackground=BG, highlightcolor=ACCENT,
        )
        self.clear_btn.pack(side="left", padx=(4, 0))

        self.cloud_btn = tk.Button(
            top, text="Cloud", command=self.actions["cloud"], relief="flat", bg=BG,
            activebackground=BORDER, fg=MUTED, activeforeground=FG,
            font=BODY_FONT, cursor="hand2", padx=8, highlightthickness=2,
            highlightbackground=BG, highlightcolor=ACCENT,
        )
        self.cloud_btn.pack(side="left", padx=(4, 0))

        self.add_btn = tk.Button(
            top, text="Add snippet", command=self.actions["add"], relief="flat",
            bg=ACCENT, fg=WHITE, activebackground=ACCENT_D, activeforeground=WHITE,
            font=BODY_FONT, cursor="hand2", padx=10, highlightthickness=2,
            highlightbackground=BG, highlightcolor=ACCENT,
        )
        self.add_btn.pack(side="left", padx=(4, 0))
        for button in (self.clear_btn, self.cloud_btn, self.add_btn):
            button.bind("<Return>", lambda e, target=button: self._invoke_button(target))

        # ---- results list
        list_frame = tk.Frame(root, bg=BG)
        list_frame.pack(fill="both", expand=True, padx=12, pady=(0, 6))

        self.listbox = tk.Listbox(
            list_frame, activestyle="none", borderwidth=0, highlightthickness=1,
            highlightbackground=BORDER, selectmode="browse", bg=WHITE, fg=FG,
            font=LIST_FONT, selectbackground=SELECT, selectforeground=FG_SELECT,
            exportselection=False, relief="flat", highlightcolor=ACCENT,
        )
        scroll = tk.Scrollbar(list_frame, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=scroll.set)
        self.listbox.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        # ---- status bar
        status_frame = tk.Frame(root, bg=BG)
        status_frame.pack(fill="x", padx=12, pady=(0, 8))
        self.status = tk.Label(status_frame, text=self.HINT, anchor="w", bg=BG,
                               fg=MUTED, font=SMALL_FONT)
        self.status.pack(side="left", fill="x")
        self.count_lbl = tk.Label(status_frame, text="", anchor="e", bg=BG,
                                  fg=MUTED, font=SMALL_FONT)
        self.count_lbl.pack(side="right")

    # ------------------------------------------------------------- keys
    def _bind_keys(self) -> None:
        self.root.bind("<Escape>", lambda e: self.actions["escape"]())
        self.root.bind("<Control-Return>", lambda e: self.open_detail())
        self.root.bind("<Control-n>", lambda e: self.actions["add"]())
        self.root.bind("<Control-e>", lambda e: self.actions["edit"]())
        # Focus lives in the search box, so a delete shortcut that only works
        # in the listbox is a delete shortcut that never fires.
        self.root.bind("<Control-Delete>", lambda e: self._delete_selected())

        self.search_entry.bind("<Return>", self._copy_selected)
        self.search_entry.bind("<Down>", lambda e: self._move_selection(1))
        self.search_entry.bind("<Up>", lambda e: self._move_selection(-1))
        # Widget bindings run before the Entry class binding, so this sees the
        # query as it was *before* the keystroke: Del still edits text whenever
        # there is text to edit, and only deletes a snippet when there isn't.
        self.search_entry.bind("<Delete>", self._on_entry_delete)
        # Handle it here (returning "break") so the Entry cannot also eat a
        # word of the query on the way past.
        self.search_entry.bind("<Control-Delete>", lambda e: self._delete_selected())

        self.listbox.bind("<Return>", self._copy_selected)
        self.listbox.bind("<Double-Button-1>", lambda e: self.open_detail())
        self.listbox.bind("<Delete>", lambda e: self._delete_selected())
        self.listbox.bind("<Configure>", self._schedule_resize)

    @staticmethod
    def _invoke_button(button) -> str:
        button.invoke()
        return "break"

    def _copy_selected(self, _event=None) -> str:
        self.copy_selected()
        return "break"

    def _delete_selected(self) -> str:
        self.actions["delete"]()
        return "break"

    def _on_entry_delete(self, _event):
        if self._search_var.get():
            return None  # let the Entry delete a character
        return self._delete_selected()

    # ------------------------------------------------------------- search
    def _on_search_changed(self) -> None:
        self._sync_placeholder()
        self._schedule_search()

    def _schedule_search(self) -> None:
        if self._search_job:
            self.root.after_cancel(self._search_job)
        self._search_job = self.root.after(60, self.refresh)

    def refresh(self) -> None:
        if self._search_job:
            self.root.after_cancel(self._search_job)
            self._search_job = None
        query = self._search_var.get()
        self.results = self.db.search(query, MAX_RESULTS)
        self._render_results()
        if self.results:
            self.listbox.selection_set(0)
            self.listbox.activate(0)
        self._update_status()

    def _schedule_resize(self, event=None) -> None:
        width = event.width if event is not None else self.listbox.winfo_width()
        if abs(width - self._render_width) < 8:
            return
        if self._resize_job:
            self.root.after_cancel(self._resize_job)
        self._resize_job = self.root.after(80, self._resize_results)

    def _resize_results(self) -> None:
        self._resize_job = None
        self._render_results(preserve_selection=True)

    def _render_results(self, preserve_selection: bool = False) -> None:
        selected = self.selected_row() if preserve_selection else None
        top = self.listbox.nearest(0) if preserve_selection and self.listbox.size() else 0
        width = self.listbox.winfo_width()
        if width <= 1:
            width = WINDOW_WIDTH - 40
        self._render_width = width
        font = tkfont.Font(root=self.root, font=self.listbox.cget("font"))
        max_chars = max(24, int((width - 28) / max(font.measure("0"), 1)))
        self.listbox.delete(0, "end")
        for i, row in enumerate(self.results):
            self.listbox.insert("end", self._format_row(i, row, max_chars))
        if selected is not None:
            self.select_id(selected["id"])
            if self.listbox.size():
                self.listbox.yview(top)

    @staticmethod
    def _format_row(index: int, row, max_chars: int) -> str:
        heading = (row["heading"] or "").strip() or "(no title)"
        preview = " ".join(row["content"].split())
        line = f"{index + 1:>3}. {heading}  │  {preview}"
        if len(line) > max_chars:
            line = line[: max_chars - 1].rstrip() + "…"
        return line

    # ------------------------------------------------------------- status
    def _update_status(self) -> None:
        if self._notice_job:
            return
        query = self._search_var.get().strip()
        n = len(self.results)
        if query:
            self.count_lbl.config(text=f"{n} match" + ("es" if n != 1 else ""), fg=MUTED)
        else:
            self.count_lbl.config(text=f"{n} snippet" + ("s" if n != 1 else ""), fg=MUTED)
        if n == 0 and query:
            self.status.config(text="No matches — try fewer terms", fg=DANGER)
        elif n == 0:
            self.status.config(text="No snippets yet — press Ctrl+N to add one", fg=MUTED)
        else:
            self.status.config(text=self.HINT, fg=MUTED)

    def notify(self, text: str, color: str = NOTICE, ms: int = 2200) -> None:
        if self._notice_job:
            self.root.after_cancel(self._notice_job)
        self.status.config(text=text, fg=color)
        self._notice_job = self.root.after(ms, self._notice_done)

    def _notice_done(self) -> None:
        self._notice_job = None
        self._update_status()

    # ------------------------------------------------------------- actions
    def selected_row(self):
        sel = self.listbox.curselection()
        if not sel or not self.results:
            return None
        return self.results[sel[0]]

    def copy_selected(self) -> None:
        row = self.selected_row()
        if row:
            self.actions["copy"](row)

    def open_detail(self, row=None) -> None:
        row = row or self.selected_row()
        if row:
            self.actions["detail"](row)

    def select_id(self, sid: int) -> None:
        for i, row in enumerate(self.results):
            if row["id"] == sid:
                self.listbox.selection_clear(0, "end")
                self.listbox.selection_set(i)
                self.listbox.activate(i)
                self.listbox.see(i)
                return

    def _move_selection(self, delta: int) -> None:
        n = self.listbox.size()
        if not n:
            return
        cur = self.listbox.curselection()
        idx = cur[0] if cur else 0
        idx = max(0, min(n - 1, idx + delta))
        self.listbox.selection_clear(0, "end")
        self.listbox.selection_set(idx)
        self.listbox.activate(idx)
        self.listbox.see(idx)

    # ------------------------------------------------------------- placeholder
    @property
    def _placeholder_on(self) -> bool:
        return not self._search_var.get()

    def _sync_placeholder(self) -> None:
        if self._placeholder is None:
            return
        if self._search_var.get():
            self._placeholder.place_forget()
        else:
            self._placeholder.place(x=6, rely=0.5, anchor="w")

    def _clear_search(self) -> None:
        self.clear_search()

    def focus_search(self) -> None:
        self.search_entry.focus_set()
        self.search_entry.select_range(0, "end")

    def has_search_text(self) -> bool:
        return bool(self._search_var.get().strip())

    def clear_search(self) -> None:
        self._search_var.set("")
        self.refresh()


# ================================================================ DetailWindow
class DetailWindow(tk.Toplevel):
    """Read-only view of a snippet with Copy / Edit / Delete / Close."""

    def __init__(self, root: tk.Tk, row, actions: dict):
        super().__init__(root)
        self.row = row
        self.actions = actions
        self.title("Snippet details")
        self.configure(bg=BG)
        self.transient(root)
        self.resizable(True, True)
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self._build()
        self._center_over(root)
        self.bind("<Return>", self._on_copy_key)
        self.bind("<Control-e>", self._on_edit_key)
        self.bind("<Delete>", self._on_delete_key)
        self.bind("<Control-Delete>", self._on_delete_key)
        self.bind("<Escape>", lambda e: self.destroy())
        self.grab_set()
        self.copy_btn.focus_set()

    def _build(self) -> None:
        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=12, pady=12)

        heading = (self.row["heading"] or "").strip() or "(no title)"
        tk.Label(body, text=heading, bg=BG, fg=FG, anchor="w", justify="left",
                 font=TITLE_FONT).pack(fill="x")

        content = self.row["content"]
        n_lines = len(content.splitlines())
        tk.Label(body, text=f"{n_lines} line{'s' if n_lines != 1 else ''} · {len(content)} chars",
                 bg=BG, fg=MUTED, anchor="w", font=SMALL_FONT).pack(fill="x", pady=(2, 8))

        frame = tk.Frame(body, bg=WHITE, highlightthickness=1, highlightbackground=BORDER)
        frame.pack(fill="both", expand=True)
        font = CODE_FONT if _looks_like_code(content) else BODY_FONT
        text = tk.Text(frame, wrap="word", font=font, bg=WHITE, fg=FG, relief="flat",
                       borderwidth=0, padx=8, pady=8)
        text.insert("1.0", content)
        text.configure(state="disabled")
        scroll = tk.Scrollbar(frame, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        btns = tk.Frame(body, bg=BG)
        btns.pack(fill="x", pady=(10, 0))
        self.copy_btn = tk.Button(
            btns, text="Copy", command=self._on_copy, relief="flat",
            bg=ACCENT, fg=WHITE, activebackground=ACCENT_D, activeforeground=WHITE,
            font=BODY_FONT, cursor="hand2", padx=14, pady=3)
        self.copy_btn.pack(side="left")
        self.edit_btn = tk.Button(
            btns, text="Edit…", command=self._on_edit, relief="flat",
            bg=BORDER, fg=FG, activebackground=SELECT, font=BODY_FONT,
            cursor="hand2", padx=12, pady=3)
        self.edit_btn.pack(side="left", padx=(6, 0))
        self.delete_btn = tk.Button(
            btns, text="Delete", command=self._on_delete, relief="flat",
            bg=BG, fg=DANGER, activebackground=SELECT, font=BODY_FONT,
            cursor="hand2", padx=12, pady=3)
        self.delete_btn.pack(side="left", padx=(6, 0))
        self.close_btn = tk.Button(
            btns, text="Close", command=self.destroy, relief="flat",
            bg=BG, fg=MUTED, activebackground=SELECT, font=BODY_FONT,
            cursor="hand2", padx=12, pady=3)
        self.close_btn.pack(side="right")

    def _on_copy(self) -> None:
        self.actions["copy"](self.row)

    def _on_edit(self) -> None:
        self.actions["edit"]()

    def _on_delete(self) -> None:
        self.actions["delete"]()

    def _on_copy_key(self, _event=None) -> str:
        self._on_copy()
        return "break"

    def _on_edit_key(self, _event=None) -> str:
        self._on_edit()
        return "break"

    def _on_delete_key(self, _event=None) -> str:
        self._on_delete()
        return "break"

    def _center_over(self, parent) -> None:
        _center_window(self, parent)

# ================================================================ CloudWindow
class CloudWindow(tk.Toplevel):
    """Backup/restore control: connect state, back up now, restore list.

    The window itself does no network work — the app fetches the backup
    list and pushes it in via set_backups().
    """

    def __init__(self, root: tk.Tk, actions: dict, provider=None, store=None):
        super().__init__(root)
        self.actions = actions
        self.provider = provider
        self.store = store
        self._busy = None
        self._backup_names = []
        self.title("Cloud backup")
        self.configure(bg=BG)
        self.transient(root)
        self.resizable(True, True)
        self.minsize(470, 280)
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self._build()
        self._center_over(root)
        self.bind("<Escape>", lambda e: self.destroy())
        self.backup_list.bind("<Return>", self._restore_key)
        self.backup_list.bind("<Double-Button-1>", self._restore_key)
        self.grab_set()
        if self.provider is not None and self.store is not None:
            self.backup_list.focus_set()
        else:
            self.connect_btn.focus_set()

    def _build(self) -> None:
        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=12, pady=12)

        self.status_lbl = tk.Label(body, text="", bg=BG, fg=FG, anchor="w",
                                   font=BODY_FONT, wraplength=340, justify="left")
        self.status_lbl.pack(fill="x")

        account_actions = tk.Frame(body, bg=BG)
        account_actions.pack(fill="x", pady=(10, 0))
        self.connect_btn = tk.Button(
            account_actions, text="Connect…", command=self.actions["connect"], relief="flat",
            bg=ACCENT, fg=WHITE, activebackground=ACCENT_D, activeforeground=WHITE,
            font=BODY_FONT, cursor="hand2", padx=10, highlightthickness=2,
            highlightbackground=BG, highlightcolor=ACCENT)
        self.connect_btn.pack(side="left")
        self.disconnect_btn = tk.Button(
            account_actions, text="Disconnect", command=self.actions["disconnect"], relief="flat",
            bg=BG, fg=MUTED, activebackground=SELECT, font=BODY_FONT,
            cursor="hand2", padx=10, highlightthickness=2,
            highlightbackground=BG, highlightcolor=ACCENT)
        self.disconnect_btn.pack(side="left", padx=(6, 0))
        self.close_btn = tk.Button(
            account_actions, text="Close", command=self.destroy, relief="flat",
            bg=BG, fg=MUTED, activebackground=SELECT, font=BODY_FONT,
            cursor="hand2", padx=10, highlightthickness=2,
            highlightbackground=BG, highlightcolor=ACCENT)
        self.close_btn.pack(side="right")

        backup_actions = tk.Frame(body, bg=BG)
        backup_actions.pack(fill="x", pady=(8, 0))
        self.backup_btn = tk.Button(
            backup_actions, text="Back up now", command=self.actions["backup"], relief="flat",
            bg=BG, fg=FG, activebackground=SELECT, font=BODY_FONT,
            cursor="hand2", padx=10, highlightthickness=2,
            highlightbackground=BG, highlightcolor=ACCENT)
        self.backup_btn.pack(side="left")
        self.restore_btn = tk.Button(
            backup_actions, text="Restore selected", command=self.actions["restore"], relief="flat",
            bg=BG, fg=DANGER, activebackground=SELECT, font=BODY_FONT,
            cursor="hand2", padx=10, highlightthickness=2,
            highlightbackground=BG, highlightcolor=ACCENT)
        self.restore_btn.pack(side="left", padx=(6, 0))

        list_frame = tk.Frame(body, bg=WHITE, highlightthickness=1,
                              highlightbackground=BORDER)
        list_frame.pack(fill="both", expand=True, pady=(10, 0))
        self.backup_list = tk.Listbox(
            list_frame, activestyle="none", borderwidth=0, highlightthickness=0,
            bg=WHITE, fg=FG, font=LIST_FONT, selectbackground=SELECT,
            selectforeground=FG_SELECT, exportselection=False,
        )
        scroll = tk.Scrollbar(list_frame, orient="vertical", command=self.backup_list.yview)
        self.backup_list.configure(yscrollcommand=scroll.set)
        self.backup_list.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.backup_list.bind("<<ListboxSelect>>", lambda e: self._refresh_state())
        self._refresh_state()
        self.set_status(
            "Connected. Cloud backup is ready."
            if self.provider is not None and self.store is not None
            else "Not connected. Connect with your Google account.")

    def attach(self, provider, store) -> None:
        """Update the connected provider/store and re-render button state."""
        self.provider = provider
        self.store = store
        self._refresh_state()

    def _refresh_state(self) -> None:
        connected = self.provider is not None and self.store is not None
        idle = self._busy is None
        selected = bool(self.backup_list.curselection())
        self.connect_btn.config(
            text="Connecting…" if self._busy == "connect" else "Connect…",
            state="normal" if not connected and idle else "disabled")
        self.disconnect_btn.config(
            state="normal" if connected and idle else "disabled")
        self.backup_btn.config(
            text="Backing up…" if self._busy == "backup" else "Back up now",
            state="normal" if connected and idle else "disabled")
        self.restore_btn.config(
            text="Restoring…" if self._busy == "restore" else "Restore selected",
            state="normal" if connected and idle and selected else "disabled")

    def set_busy(self, operation=None) -> None:
        self._busy = operation
        self._refresh_state()

    def set_status(self, text: str, color: str = FG) -> None:
        self.status_lbl.config(text=text, fg=color)

    def set_backups(self, metas) -> None:
        selected = self.selected_backup()
        self.backup_list.delete(0, "end")
        self._backup_names = [m.name for m in metas]
        for m in metas:
            self.backup_list.insert("end", f"{m.name}   ({m.size:,} B)")
        if selected in self._backup_names:
            index = self._backup_names.index(selected)
            self.backup_list.selection_set(index)
            self.backup_list.activate(index)
            self.backup_list.see(index)
        self._refresh_state()

    def selected_backup(self) -> str:
        sel = self.backup_list.curselection()
        if not sel or sel[0] >= len(self._backup_names):
            return ""
        return self._backup_names[sel[0]]

    def _restore_key(self, _event=None) -> str:
        if str(self.restore_btn.cget("state")) == "normal":
            self.actions["restore"]()
        return "break"

    def _center_over(self, parent) -> None:
        _center_window(self, parent)


# ================================================================ EditWindow
class EditWindow(tk.Toplevel):
    """Used for both adding and editing a snippet."""

    def __init__(self, root: tk.Tk, on_save, initial_heading: str = "",
                 initial_content: str = "", title: str = "Snippet"):
        super().__init__(root)
        self._on_save = on_save
        self._in_modified = False
        self.title(title)
        self.configure(bg=BG)
        self.transient(root)
        self.resizable(True, True)
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self._build(initial_heading, initial_content)
        self._center_over(root)
        self.grab_set()

    def _build(self, heading: str, content: str) -> None:
        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=12, pady=12)

        tk.Label(body, text="Heading (optional)", bg=BG, fg=MUTED, anchor="w",
                 font=SMALL_FONT).pack(fill="x")
        self._heading_var = tk.StringVar(value=heading)
        self.heading_entry = tk.Entry(
            body, textvariable=self._heading_var, font=BODY_FONT, relief="flat",
            highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT,
            bg=WHITE, fg=FG, insertbackground=FG,
        )
        # Refuse the keystroke at the limit rather than trimming behind the
        # user's back when they hit Save.
        self.heading_entry.config(
            validate="key",
            validatecommand=(self.register(lambda p: len(p) <= MAX_HEADING_LEN), "%P"))
        self.heading_entry.pack(fill="x", ipady=4, pady=(2, 10))

        tk.Label(body, text=f"Content  (up to {MAX_CONTENT_LEN:,} chars)", bg=BG, fg=MUTED,
                 anchor="w", font=SMALL_FONT).pack(fill="x")
        frame = tk.Frame(body, bg=WHITE, highlightthickness=1, highlightbackground=BORDER)
        frame.pack(fill="both", expand=True)
        self.content_text = tk.Text(frame, wrap="word", font=CODE_FONT, bg=WHITE, fg=FG,
                                    relief="flat", borderwidth=0, padx=8, pady=8, undo=True)
        self.content_text.insert("1.0", content)
        scroll = tk.Scrollbar(frame, orient="vertical", command=self.content_text.yview)
        self.content_text.configure(yscrollcommand=scroll.set)
        self.content_text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        self._counter = tk.Label(body, text="", bg=BG, fg=MUTED, anchor="e", font=SMALL_FONT)
        self._counter.pack(fill="x", pady=(4, 0))

        btns = tk.Frame(body, bg=BG)
        btns.pack(fill="x", pady=(10, 0))
        self._save_btn = tk.Button(btns, text="Save  (Ctrl+Enter)", command=self._save,
                                   relief="flat", bg=ACCENT, fg=WHITE,
                                   activebackground=ACCENT_D, activeforeground=WHITE,
                                   font=BODY_FONT, cursor="hand2", padx=14, pady=3)
        self._save_btn.pack(side="right")
        tk.Button(btns, text="Cancel  (Esc)", command=self.destroy, relief="flat",
                  bg=BG, fg=MUTED, activebackground=SELECT, font=BODY_FONT,
                  cursor="hand2", padx=12, pady=3).pack(side="right", padx=(0, 8))

        # <<Modified>> rather than <KeyRelease>: a right-click or middle-click
        # paste never releases a key, and that is exactly when a big snippet
        # arrives.
        self.content_text.bind("<<Modified>>", self._on_modified)
        self.content_text.bind("<Control-Return>", lambda e: self._save())
        self.heading_entry.bind("<Return>", lambda e: self.content_text.focus_set())
        self.heading_entry.bind("<Control-Return>", lambda e: self._save())
        self.bind("<Escape>", lambda e: self.destroy())
        self.heading_entry.focus_set()
        self.content_text.edit_reset()   # the seeded text is not an undo step
        self.content_text.edit_modified(False)
        self._on_type()

    def _on_modified(self, _event=None) -> None:
        if self._in_modified:
            return
        self._in_modified = True
        try:
            self.content_text.edit_modified(False)  # re-arm the flag
        finally:
            self._in_modified = False
        self._on_type()

    def _on_type(self, _event=None) -> None:
        # Never rewrite the buffer here: truncating on the fly silently ate
        # pasted snippets and left the undo stack unable to bring them back.
        n = len(self.content_text.get("1.0", "end-1c"))
        over = n > MAX_CONTENT_LEN
        self._counter.config(
            text=f"{n:,} / {MAX_CONTENT_LEN:,}" + ("  — too long to save" if over else ""),
            fg=DANGER if over else MUTED)
        empty = not self.content_text.get("1.0", "end-1c").strip()
        self._save_btn.config(state="disabled" if over or empty else "normal")

    def _save(self) -> None:
        text = self.content_text.get("1.0", "end-1c")
        if not text.strip():
            return
        if len(text) > MAX_CONTENT_LEN:
            messagebox.showwarning(
                APP_NAME,
                f"This snippet is {len(text):,} characters; the limit is "
                f"{MAX_CONTENT_LEN:,}.\n\nNothing has been saved or trimmed — "
                "shorten it (or raise MAX_CONTENT_LEN in config.py) and save again.",
                parent=self)
            return
        heading = self._heading_var.get().strip()[:MAX_HEADING_LEN]
        self._on_save(heading, text)
        self.destroy()

    def _center_over(self, parent) -> None:
        _center_window(self, parent, include_size=True)





