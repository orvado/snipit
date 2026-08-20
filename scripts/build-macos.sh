#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.cargo/bin:$PATH"
echo "==> npm install --include=dev"
npm install --include=dev
echo "==> vite build"
./node_modules/.bin/vite build
echo "==> cargo build (Tauri bundle)"
cargo build --manifest-path src-tauri/Cargo.toml
echo "==> tauri build"
./node_modules/.bin/tauri build
echo "Done. Artifacts in src-tauri/target/release/bundle/"
