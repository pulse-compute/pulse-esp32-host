#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MATRIX="${WDC_IDF_MATRIX:-$ROOT/firmware/idf-family-matrix.json}"
LOG_DIR="${WDC_LOG_DIR:-$ROOT/reports/logs}"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/bootstrap_idf.log"
: > "$LOG"
exec > >(tee -a "$LOG") 2>&1

if ! python3 -B "$ROOT/tools/check_idf_matrix.py" --matrix "$MATRIX" >/dev/null; then
  echo "[if2] canonical IDF matrix is invalid"
  exit 1
fi

LANE_VALUES="$(python3 -B - "$MATRIX" <<'PY'
import json
import sys
from pathlib import Path

matrix = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
lane_id, lane = next(iter(matrix["lanes"].items()))
attempted = {entry["target"] for entry in matrix["realizations"].values()}
ordered_targets = [target for target in ("esp32", "esp32s3", "esp32c3", "esp32c6") if target in attempted]
print("\t".join((lane_id, lane["version"], lane["source_commit"], lane["platform"], lane["container_image"], ",".join(ordered_targets))))
PY
)"
IFS=$'\t' read -r LANE_ID IDF_REF IDF_COMMIT IDF_PLATFORM IDF_IMAGE IDF_TARGETS <<< "$LANE_VALUES"

if [ -n "${ESP_IDF_REF:-}" ] && [ "$ESP_IDF_REF" != "$IDF_REF" ]; then
  echo "[if2] ESP_IDF_REF=$ESP_IDF_REF conflicts with matrix lane $IDF_REF"
  exit 1
fi

ESP_ROOT="${ESP_ROOT:-$ROOT/.deps/esp}"
IDF_REPO="${ESP_IDF_REPO:-https://github.com/espressif/esp-idf.git}"
IDF_TIMEOUT="${WDC_IDF_BOOTSTRAP_TIMEOUT_SECONDS:-120}"

if [ -z "${IDF_PATH:-}" ] && command -v idf.py >/dev/null 2>&1; then
  AMBIENT_IDF_PY="$(command -v idf.py)"
  export IDF_PATH="$(cd "$(dirname "$AMBIENT_IDF_PY")/.." && pwd)"
else
  export IDF_PATH="${IDF_PATH:-$ESP_ROOT/esp-idf}"
fi
export IDF_TOOLS_PATH="${IDF_TOOLS_PATH:-$ESP_ROOT/tools}"

echo "[if2] ESP-IDF lane bootstrap started"
echo "[if2] lane=$LANE_ID version=$IDF_REF commit=$IDF_COMMIT"
echo "[if2] platform=$IDF_PLATFORM image=$IDF_IMAGE"
echo "[if2] attempted targets=$IDF_TARGETS"
echo "[if2] IDF_PATH=$IDF_PATH"
echo "[if2] IDF_TOOLS_PATH=$IDF_TOOLS_PATH"
echo "[if2] bootstrap network low-speed timeout=${IDF_TIMEOUT}s"

if [ ! -d "$IDF_PATH/.git" ]; then
  if [ -e "$IDF_PATH" ]; then
    echo "[if2] IDF_PATH exists but is not an ESP-IDF git checkout"
    exit 1
  fi
  if ! command -v git >/dev/null 2>&1; then
    echo "[if2] git is required to clone ESP-IDF"
    exit 78
  fi
  mkdir -p "$(dirname "$IDF_PATH")"
  echo "[if2] cloning ESP-IDF: $IDF_REPO @ $IDF_REF"
  if ! GIT_TERMINAL_PROMPT=0 git -c http.lowSpeedLimit=1 -c http.lowSpeedTime="$IDF_TIMEOUT" clone --depth 1 --branch "$IDF_REF" "$IDF_REPO" "$IDF_PATH"; then
    echo "[if2] ESP-IDF git clone failed or timed out"
    exit 77
  fi
else
  echo "[if2] ESP-IDF source already present; moving it is prohibited"
fi

OBSERVED_COMMIT="$(git -C "$IDF_PATH" rev-parse HEAD)"
if [ "$OBSERVED_COMMIT" != "$IDF_COMMIT" ]; then
  echo "[if2] ESP-IDF commit mismatch: expected $IDF_COMMIT, observed $OBSERVED_COMMIT"
  exit 1
fi

echo "[if2] initializing exact-commit ESP-IDF submodules"
if ! GIT_TERMINAL_PROMPT=0 git -C "$IDF_PATH" -c http.lowSpeedLimit=1 -c http.lowSpeedTime="$IDF_TIMEOUT" submodule update --init --recursive --depth 1; then
  echo "[if2] ESP-IDF submodule update failed or timed out"
  exit 77
fi

echo "[if2] installing toolchains for attempted target union: $IDF_TARGETS"
if ! "$IDF_PATH/install.sh" "$IDF_TARGETS"; then
  echo "[if2] ESP-IDF install failed"
  exit 77
fi

echo "[if2] activating and verifying the canonical lane"
# shellcheck disable=SC1091
. "$IDF_PATH/export.sh"
IDF_PY="$(command -v idf.py)"
python3 -B "$ROOT/tools/verify_idf_environment.py" \
  --matrix "$MATRIX" \
  --idf-path "$IDF_PATH" \
  --idf-py "$IDF_PY"

echo "[if2] ESP-IDF lane bootstrap completed"
