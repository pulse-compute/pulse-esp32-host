#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CELL="${WDC_IDF_CELL:-esp32s3-reference}"
MATRIX="${WDC_IDF_MATRIX:-$ROOT/firmware/idf-family-matrix.json}"
OUT_DIR="${WDC_IDF_OUT_DIR:-$ROOT/reports/idf-family/$CELL}"
TIMEOUT="${WDC_IDF_TIMEOUT_SECONDS:-1800}"
LOG_DIR="${WDC_LOG_DIR:-$ROOT/reports/logs}"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/firmware_build.log"
: > "$LOG"
exec > >(tee -a "$LOG") 2>&1

echo "[if3] building matrix cell $CELL in an isolated project"
echo "[if3] evidence directory: $OUT_DIR"
python3 -B "$ROOT/tools/build_idf_cell.py" \
  --matrix "$MATRIX" \
  --cell "$CELL" \
  --out-dir "$OUT_DIR" \
  --timeout "$TIMEOUT"

echo "[if3] cell build passed; inspect $OUT_DIR/cell-report.json"
