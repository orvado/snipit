# Build a standalone snipit.exe (no console window) with PyInstaller.
# Usage:  .\build.ps1
$ErrorActionPreference = "Stop"

python -m pip install --upgrade pyinstaller
python -m PyInstaller --noconfirm --clean --onefile --noconsole --name snipit launcher.py

Write-Host ""
Write-Host "Built: $PSScriptRoot\dist\snipit.exe"
