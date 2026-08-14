# SnipIt

A **very minimalist, lightweight text snippet manager** for Windows.

Keep frequently used snippets — Windows commands, chat prompts, code — one hotkey
away. Press **Ctrl+Alt+S**, type a few letters to progressively narrow the list,
press **Enter** to copy, and the window gets out of your way.

## Features

- **Progressive search** — every keystroke re-filters. Multiple space-separated
  terms must all match (AND) against the heading *or* the content.
- **Single-line results** — heading + content preview on one row for fast
  visual scanning; arrow keys / typing work right from the search box.
- **Global hotkey** — `Ctrl+Alt+S` summons the window from anywhere; it hides
  again only when it already has your attention, so the hotkey never makes a
  minimised or buried window disappear.
- **System tray** — lives quietly in the tray (Show / New snippet… / Quit).
- **Copy anywhere** — press `Enter` on a result, or use the Copy button in the
  detail window (essential for multi-line snippets). Copies are handed to
  Windows itself, so they survive quitting SnipIt and show up in clipboard
  history (`Win+V`).
- **Auto-hide after copy** — the window hides itself ~1.5 s after copying, with
  a visible "Copied ✓ — press Esc to cancel" notice. Esc cancels the auto-hide.
- **Detail window** — double-click (or Ctrl+Enter) any result for a read-only
  view with Copy / Edit / Delete. Code-ish snippets render in a monospace font.
- **Add / edit / delete** — `Ctrl+N`, `Ctrl+E`, `Ctrl+Del`; or the tray menu.
- **SQLite storage** — one small `.db` file in `%APPDATA%\SnipIt\`.
- **MRU results** — search results are ordered most-recently-used first:
  copying a snippet (or viewing it in the detail window) brings it to the
  top of the list; newly added snippets start at the top until something
  else is used.
- **Nothing is trimmed silently** — content up to **32,768 characters** saves
  as-is; anything longer blocks Save with a message rather than being cut down
  behind your back.
- **Single instance** — launching a second copy brings the running one forward.

## Install

Requires **Python 3.10+** on Windows.

```powershell
cd snipit
python -m pip install -r requirements.txt
```

## Run

```powershell
python -m snipit            # or: .\run.ps1
python -m snipit --version
python -m snipit --reset-db # wipe the database and reseed samples
```

First launch seeds 10 sample snippets (Windows commands + a few chat prompts) and
shows the window once so you can see it working. Afterwards it starts hidden in
the tray.

## Usage

| Action | Shortcut |
| --- | --- |
| Summon / hide | `Ctrl+Alt+S` (global) |
| Move selection | `↑` / `↓` |
| Copy selected | `Enter` |
| Snippet details | double-click or `Ctrl+Enter` |
| New snippet | `Ctrl+N` (also in tray menu) |
| Edit snippet | `Ctrl+E` |
| Delete snippet | `Ctrl+Del` (or `Del` when the search box is empty) |
| Clear search / hide | `Esc` (first clears, second hides) |
| Quit | tray icon → **Quit** |

Focus stays in the search box while you browse, so `Ctrl+Del` is the delete
that always works; plain `Del` edits your query whenever there is a query to
edit, and only deletes a snippet when the box is empty.

### Copy flow

1. Pick a snippet and press `Enter` (or click Copy in the detail window).
2. The snippet goes onto the Windows clipboard (`CF_UNICODETEXT`, CRLF line
   endings) and the status bar shows *"Copied ✓ — hiding in 1.5s · press Esc to
   keep open"*.
3. The window auto-hides after **1.5 s**. Press **Esc** within that window to
   cancel the auto-hide and keep working.

Because the text is handed to the OS rather than lent out by Tk, it is still
there after you quit SnipIt — and `Win+V` clipboard history picks it up.

## Configuration

Environment variables:

| Variable | Default | Purpose |
| --- | --- | --- |
| `SNIPIT_HOTKEY` | `ctrl+alt+s` | Global hotkey (`keyboard` library syntax, e.g. `ctrl+shift+space`) |
| `SNIPIT_DATA_DIR` | `%APPDATA%` | Where `SnipIt\snipit.db` lives |

Tweak `snipit/config.py` directly for `AUTO_CLOSE_MS`, `MAX_CONTENT_LEN`,
`MAX_RESULTS`, `CLIPBOARD_CRLF`, etc.

The content limit is a sanity check, not a performance guard: measured at 500
snippets averaging 8 KB, a three-term progressive search costs ~15 ms — well
under the 60 ms keystroke debounce — so raise `MAX_CONTENT_LEN` freely if you
keep longer snippets.

## Data

- Database: `%APPDATA%\SnipIt\snipit.db` (plus `-wal` / `-shm` while running)
- Schema: `snippets(id, heading, content, created_at, updated_at, last_used_at)`
  — `last_used_at` drives the MRU ordering (NULL = never used); content is
  `TEXT`; saves over `MAX_CONTENT_LEN` are refused, never truncated.
  Existing databases are migrated automatically on first run (the column is
  added and backfilled from `updated_at`).
- Delete the files (or use `--reset-db`, which also clears a stale `-wal`) to
  start over. Quit SnipIt from the tray first — it holds the database open.

## Build a standalone .exe (optional)

```powershell
.\build.ps1        # uses PyInstaller -> dist\snipit.exe (no console)
```

## Project layout

```
snipit/
  snipit/
    __init__.py
    __main__.py    # python -m snipit
    app.py         # wiring: db + ui + tray + hotkey + auto-close + IPC
    ui.py          # search window, detail dialog, add/edit dialog
    db.py          # SQLite CRUD + progressive search
    clipboard.py   # Win32 clipboard writes that outlive the process
    hotkey.py      # global hotkey (keyboard lib)
    tray.py        # system tray (pystray)
    config.py      # constants / data paths
  tests/           # smoke tests (no framework needed)
    _sandbox.py    # points the suite at a throwaway data dir
  launcher.py      # python launcher.py (also PyInstaller entry)
  run.ps1 / build.ps1 / requirements.txt
```

## Tests

```powershell
python tests\test_db.py
python tests\test_ui.py
python tests\test_app.py
python tests\test_ipc.py
python tests\test_clipboard.py
```

Every test runs against a temporary data directory (`tests/_sandbox.py`), so
your real database in `%APPDATA%` is never touched. The UI/app tests briefly
open a window and exercise the real tray + hotkey + clipboard paths — the
global hotkey is registered for a few seconds, and the clipboard is borrowed
and handed back.

## Known limitations

- The global hotkey uses a low-level keyboard hook, which Windows does not
  deliver while a **UAC-elevated** window has focus. Ctrl+Alt+S will not fire
  from an admin terminal unless SnipIt itself runs elevated.
- A PyInstaller one-file build that installs a keyboard hook is a common
  antivirus false positive; expect to whitelist `dist\snipit.exe`.
