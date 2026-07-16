#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${WDC_LOG_DIR:-$ROOT/reports/logs}"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/bootstrap_idf.log"
: > "$LOG"
exec > >(tee -a "$LOG") 2>&1

ESP_ROOT="${ESP_ROOT:-$ROOT/.deps/esp}"
IDF_REF="${ESP_IDF_REF:-release/v5.4}"
IDF_REPO="${ESP_IDF_REPO:-https://github.com/espressif/esp-idf.git}"
IDF_TIMEOUT="${WDC_IDF_BOOTSTRAP_TIMEOUT_SECONDS:-120}"
export IDF_PATH="${IDF_PATH:-$ESP_ROOT/esp-idf}"
export IDF_TOOLS_PATH="${IDF_TOOLS_PATH:-$ESP_ROOT/tools}"

echo "[r3.5] ESP-IDF bootstrap started"
echo "[r3.5] IDF_PATH=$IDF_PATH"
echo "[r3.5] IDF_TOOLS_PATH=$IDF_TOOLS_PATH"
echo "[r3.5] ESP_IDF_REF=$IDF_REF"
echo "[r3.5] bootstrap network low-speed timeout=${IDF_TIMEOUT}s"

if command -v idf.py >/dev/null 2>&1; then
  echo "[r3.5] idf.py already on PATH"
  idf.py --version || true
  exit 0
fi

if [ ! -d "$IDF_PATH/.git" ]; then
  if ! command -v git >/dev/null 2>&1; then
    echo "[r3.5] git is required to clone ESP-IDF"
    exit 78
  fi
  mkdir -p "$(dirname "$IDF_PATH")"
  echo "[r3.5] cloning ESP-IDF: $IDF_REPO @ $IDF_REF"
  if ! GIT_TERMINAL_PROMPT=0 git -c http.lowSpeedLimit=1 -c http.lowSpeedTime="$IDF_TIMEOUT" clone --depth 1 --branch "$IDF_REF" "$IDF_REPO" "$IDF_PATH"; then
    echo "[r3.5] ESP-IDF git clone failed or timed out"
    exit 77
  fi
else
  echo "[r3.5] ESP-IDF source already present"
fi

cd "$IDF_PATH"
echo "[r3.5] initializing ESP-IDF submodules"
if ! GIT_TERMINAL_PROMPT=0 git -c http.lowSpeedLimit=1 -c http.lowSpeedTime="$IDF_TIMEOUT" submodule update --init --recursive --depth 1; then
  echo "[r3.5] ESP-IDF submodule update failed or timed out"
  exit 77
fi

echo "[r3.5] running ESP-IDF install for esp32s3"
if ! ./install.sh esp32s3; then
  echo "[r3.5] ESP-IDF install failed or timed out"
  exit 77
fi

echo "[r3.5] checking idf.py through export.sh"
# shellcheck disable=SC1091
. "$IDF_PATH/export.sh"
idf.py --version

echo "[r3.5] ESP-IDF bootstrap completed"
