#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$ROOT/reports/logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/firmware_build.log"
: > "$LOG"
exec > >(tee -a "$LOG") 2>&1

export PATH="$HOME/.cargo/bin:$PATH"

if ! command -v idf.py >/dev/null 2>&1; then
  for candidate in "${IDF_PATH:-}/export.sh" "/opt/esp/esp-idf/export.sh" "$HOME/esp/esp-idf/export.sh"; do
    if [ -n "$candidate" ] && [ -f "$candidate" ]; then
      echo "[r3.5] sourcing ESP-IDF environment: $candidate"
      # shellcheck disable=SC1090
      . "$candidate"
      break
    fi
  done
fi

if ! command -v idf.py >/dev/null 2>&1; then
  echo "[r3.5] idf.py is not available; cannot build firmware"
  exit 78
fi

echo "[r3.5] ESP-IDF version"
idf.py --version || true

echo "[r3.5] firmware build started"
cd "$ROOT/firmware"
idf.py set-target esp32s3
idf.py build

echo "[r3.5] firmware build completed"
