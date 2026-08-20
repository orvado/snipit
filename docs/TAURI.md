# SnipIt — Tauri Multi-Platform Build

This document covers the Tauri 2 desktop app (macOS + Windows) on the `tauri-multiplatform` branch.
The original Python app (`snipit/`, `tests/`, `build.ps1`) is untouched — both builds coexist on this branch.

## Prerequisites

- **Rust** 1.77+ (`rustup` / `cargo` on PATH; `~/.cargo/bin`)
- **Node.js** 18+ and npm
- **Platform deps for Tauri**
  - macOS: Xcode Command Line Tools (`xcode-select --install`)
  - Windows: WebView2 (ships with Windows 10/11), Visual Studio Build Tools

## Quick Start

### macOS

```bash
./scripts/build-macos.sh
# or for development with hot reload:
npm install --include=dev
npm run tauri dev
```

On first run, macOS will prompt for Accessibility permission to register the global hotkey
(`Ctrl+Alt+S` by default, overridable via `SNIPIT_HOTKEY`). If denied, the tray remains the fallback.

### Windows

```powershell
.\scripts\build-windows.ps1
# or for development:
npm install --include=dev
npm run tauri dev
```

The Tauri Windows build reuses the same data directory as the Python app:
`%APPDATA%\SnipIt\snipit.db`. Existing snippets carry over. **Do not run the Python app
and the Tauri app at the same time against the same database.**

## Data Locations

| Platform | Data dir | DB |
|----------|----------|----|
| macOS | `~/Library/Application Support/SnipIt/` | `snipit.db` |
| Windows | `%APPDATA%\SnipIt\` | `snipit.db` |
| Any (override) | `$SNIPIT_DATA_DIR/SnipIt/` | `snipit.db` |

Backups: `<data_dir>/backups/`. Cloud token: `<data_dir>/cloud_token.json`.

`SNIPIT_DATA_DIR` overrides the platform default and is honored by both the Python and Tauri builds.

## Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `SNIPIT_HOTKEY` | `ctrl+alt+s` | Global hotkey (Tauri syntax, e.g. `Ctrl+Shift+Space`) |
| `SNIPIT_DATA_DIR` | platform default | Base directory for `SnipIt/` data folder |
| `SNIPIT_GOOGLE_CLIENT_ID` | *(empty = cloud disabled)* | Google OAuth client ID |
| `SNIPIT_GOOGLE_CLIENT_SECRET` | *(empty)* | Needed only for "Web application" OAuth clients |
| `NODE_ENV` | `development` | Set to `production` skips dev deps — run `npm install --include=dev` on CI |

## Python Build (Unchanged)

```powershell
python -m pip install -r requirements.txt
python tests\test_db.py
python tests\test_ui.py
.\build.ps1        # dist\snipit.exe
```

## Verification

```bash
export PATH="$HOME/.cargo/bin:$PATH"
cargo check --manifest-path src-tauri/Cargo.toml
./node_modules/.bin/tsc --noEmit
./node_modules/.bin/vite build
```

## Bundled Artifacts

After `tauri build`, installers live under `src-tauri/target/release/bundle/`:

- macOS: `dmg/SnipIt_<version>_aarch64.dmg`, `macos/SnipIt.app`
- Windows: `msi/SnipIt_<version>_x64_en-US.msi`, `nsis/SnipIt_<version>_x64-setup.exe`
