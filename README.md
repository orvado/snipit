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
- **Global hotkey** — `Ctrl+Alt+S` summons *and* hides the window from anywhere.
- **System tray** — lives quietly in the tray (Show / New snippet… / Quit).
- **Copy anywhere** — press `Enter` on a result, or use the Copy button in the
  detail window (essential for multi-line snippets).
- **Auto-hide after copy** — the window hides itself ~1.5 s after copying, with
  a visible "Copied ✓ — press Esc to cancel" notice. Esc cancels the auto-hide.
- **Detail window** — double-click (or Ctrl+Enter) any result for a read-only
  view with Copy / Edit / Delete. Code-ish snippets render in a monospace font.
- **Add / edit / delete** — `Ctrl+N`, `Ctrl+E`, `Del`; or the tray menu.
- **SQLite storage** — one small `.db` file in `%APPDATA%\SnipIt\`.
- **Snippet guard** — content is capped at **1024 characters** by default to
  keep progressive search snappy (SQLite `TEXT` would allow far more).
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
| Delete snippet | `Del` |
| Clear search / hide | `Esc` (first clears, second hides) |
| Quit | tray icon → **Quit** |

### Copy flow

1. Pick a snippet and press `Enter` (or click Copy in the detail window).
2. The clipboard is set and the status bar shows *"Copied ✓ — hiding in 1s ·
   press Esc to keep open"*.
3. The window auto-hides after **1.5 s**. Press **Esc** within that window to
   cancel the auto-hide and keep working.

## Configuration

Environment variables:

| Variable | Default | Purpose |
| --- | --- | --- |
| `SNIPIT_HOTKEY` | `ctrl+alt+s` | Global hotkey (`keyboard` library syntax, e.g. `ctrl+shift+space`) |
| `SNIPIT_DATA_DIR` | `%APPDATA%` | Where `SnipIt\snipit.db` lives |

Tweak `snipit/config.py` directly for `AUTO_CLOSE_MS`, `MAX_CONTENT_LEN`,
`MAX_RESULTS`, etc.

## Data

- Database: `%APPDATA%\SnipIt\snipit.db`
- Schema: `snippets(id, heading, content, created_at, updated_at)` — content is
  `TEXT` (SQLite has no practical length limit), guarded to 1024 chars on save.
- Delete the file (or use `--reset-db`) to start over.

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
    hotkey.py      # global hotkey (keyboard lib)
    tray.py        # system tray (pystray)
    config.py      # constants / data paths
  tests/           # smoke tests (no framework needed)
  launcher.py      # python launcher.py (also PyInstaller entry)
  run.ps1 / build.ps1 / requirements.txt
```

## Tests

```powershell
python tests\test_db.py
python tests\test_ui.py
python tests\test_app.py
python tests\test_ipc.py
```

(The UI/app tests briefly open a window and exercise the real tray + hotkey +
clipboard paths; the global hotkey is registered for a few seconds.)
