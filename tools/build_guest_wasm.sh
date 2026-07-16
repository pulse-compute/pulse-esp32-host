#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$ROOT/reports/logs"
OUT_DIR="$ROOT/build/guest-wasm"
mkdir -p "$LOG_DIR" "$OUT_DIR"
LOG="$LOG_DIR/rust_guest_build.log"
: > "$LOG"
exec > >(tee -a "$LOG") 2>&1

TARGET="${WDC_RUST_TARGET:-wasm32-unknown-unknown}"
export PATH="$HOME/.cargo/bin:$PATH"

echo "[r3.5] guest WASM build started"
if ! command -v cargo >/dev/null 2>&1; then
  echo "[r3.5] cargo is not available"
  exit 78
fi
if ! command -v rustc >/dev/null 2>&1; then
  echo "[r3.5] rustc is not available"
  exit 78
fi

if command -v rustup >/dev/null 2>&1; then
  if ! rustup target list --installed | grep -q "^$TARGET$"; then
    echo "[r3.5] rust target $TARGET is not installed"
    exit 78
  fi
fi

cd "$ROOT/guest-sdk/rust"
cargo build -p wdc_noop_bundle --target "$TARGET" --release
cargo build -p wdc_relay_toggle_bundle --target "$TARGET" --release

NOOP="$ROOT/guest-sdk/rust/target/$TARGET/release/wdc_noop_bundle.wasm"
RELAY="$ROOT/guest-sdk/rust/target/$TARGET/release/wdc_relay_toggle_bundle.wasm"
for wasm in "$NOOP" "$RELAY"; do
  if [ ! -f "$wasm" ]; then
    echo "[r3.5] expected WASM artifact missing: $wasm"
    exit 1
  fi
  base="$(basename "$wasm")"
  cp "$wasm" "$OUT_DIR/$base"
  import_args=()
  case "$base" in
    wdc_noop_bundle.wasm) import_args+=(--require-import wdc:wdc_log) ;;
    wdc_relay_toggle_bundle.wasm) import_args+=(--require-import wdc:wdc_host_call) ;;
  esac
  /usr/bin/python3 -B "$ROOT/tools/wasm_inspect.py" "$wasm" \
    --json-out "$OUT_DIR/${base%.wasm}.inspect.json" \
    "${import_args[@]}" \
    --require-export wdc_module_init \
    --require-export wdc_module_on_event \
    --require-export wdc_module_health \
    --require-export wdc_module_shutdown
done

echo "[r3.5] guest WASM build completed"
