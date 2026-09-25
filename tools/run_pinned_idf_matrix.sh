#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MATRIX="${WDC_IDF_MATRIX:-$ROOT/firmware/idf-family-matrix.json}"
OUT_DIR="${WDC_IDF_MATRIX_OUT_DIR:-reports/idf-family/matrix-qualification}"
TIMEOUT="${WDC_IDF_TIMEOUT_SECONDS:-1800}"

python3 -B "$ROOT/tools/check_idf_matrix.py" --matrix "$MATRIX" --check-locks >/dev/null

IMAGE="$(python3 -B - "$MATRIX" <<'PY'
import json
import sys

matrix = json.load(open(sys.argv[1], encoding="utf-8"))
reference = matrix["realizations"]["esp32s3-reference"]
print(matrix["lanes"][reference["lane"]]["container_image"])
PY
)"

case "$OUT_DIR" in
  /*|*../*|../*|..)
    echo "ERROR: WDC_IDF_MATRIX_OUT_DIR must be a normalized path relative to the repository" >&2
    exit 1
    ;;
esac

if [[ -n "${WDC_CONTAINER_RUNTIME:-}" ]]; then
  RUNTIME="$WDC_CONTAINER_RUNTIME"
elif command -v docker >/dev/null 2>&1; then
  RUNTIME="docker"
elif command -v podman >/dev/null 2>&1; then
  RUNTIME="podman"
else
  echo "ERROR: no Docker or Podman runtime is installed; pinned IDF qualification cannot start" >&2
  exit 1
fi

RUNTIME_PATH="$(command -v "$RUNTIME" 2>/dev/null || true)"
case "$(basename "$RUNTIME_PATH")" in
  docker|podman) ;;
  *)
    echo "ERROR: WDC_CONTAINER_RUNTIME must resolve to Docker or Podman" >&2
    exit 1
    ;;
esac

echo "[if6] runtime: $(basename "$RUNTIME_PATH")"
echo "[if6] image: $IMAGE"
echo "[if6] evidence: $OUT_DIR"

exec "$RUNTIME_PATH" run --rm --platform linux/amd64 \
  -e "PULSE_IDF_CONTAINER_IMAGE=$IMAGE" \
  -e "PULSE_IDF_EXECUTION_ADAPTER=$(basename "$RUNTIME_PATH")" \
  -e "WDC_IDF_MATRIX_OUT_DIR=$OUT_DIR" \
  -e "WDC_IDF_TIMEOUT_SECONDS=$TIMEOUT" \
  -v "$ROOT:/work" \
  -w /work \
  "$IMAGE" \
  make idf-family-qualify
