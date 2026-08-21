#!/usr/bin/env bash
# Cross-platform build (macOS/Linux). Windows users run build.ps1 or build.py
set -e
python3 -m pip install --upgrade pyinstaller
python3 -m PyInstaller --noconfirm --clean --onefile --name snipit launcher.py
echo ""
echo "Built: $(pwd)/dist/snipit"
if [[ "$(uname)" == "Darwin" ]]; then
  echo "Run: ./dist/snipit"
  echo "For a .app bundle, use: python build.py --app (requires setup.py + py2app)"
fi
