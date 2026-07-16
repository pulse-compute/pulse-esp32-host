#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "$ROOT/reports/logs"

echo "[r3.5] initial dependency check"
python3 "$ROOT/tools/check_deps.py" --json-out "$ROOT/reports/deps_initial.json" --md-out "$ROOT/reports/deps_initial.md" || true

echo "[r3.5] bootstrapping Rust/WASM toolchain"
"$ROOT/tools/bootstrap_rust.sh"

echo "[r3.5] bootstrapping ESP-IDF"
"$ROOT/tools/bootstrap_idf.sh"

echo "[r3.5] final dependency check"
python3 "$ROOT/tools/check_deps.py" --json-out "$ROOT/reports/deps_final.json" --md-out "$ROOT/reports/deps_final.md" || true
