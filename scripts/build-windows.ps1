# Build SnipIt Tauri app on Windows
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot | Resolve-Path | Select-Object -ExpandProperty Path)
# Ensure Rust is on PATH
$env:PATH = "$env:USERPROFILE\.cargo\bin;$env:PATH"
Write-Host "==> npm install --include=dev"
npm install --include=dev
Write-Host "==> vite build"
.\node_modules\.bin\vite build
Write-Host "==> cargo check"
cargo check --manifest-path src-tauri/Cargo.toml
Write-Host "==> tauri build"
.\node_modules\.bin\tauri build
Write-Host "Done. Artifacts in src-tauri\target\release\bundle\"
