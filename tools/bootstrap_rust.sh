#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${WDC_LOG_DIR:-$ROOT/reports/logs}"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/bootstrap_rust.log"
: > "$LOG"
exec > >(tee -a "$LOG") 2>&1

TARGET="${WDC_RUST_TARGET:-wasm32-unknown-unknown}"
RUSTUP_TIMEOUT="${WDC_RUSTUP_TIMEOUT_SECONDS:-90}"
RUSTUP_CONNECT_TIMEOUT="${WDC_RUSTUP_CONNECT_TIMEOUT_SECONDS:-10}"
APT_TIMEOUT="${WDC_APT_TIMEOUT_SECONDS:-90}"
export PATH="$HOME/.cargo/bin:$PATH"
ATTEMPTED_NETWORK=0

echo "[r3.5] rust bootstrap started"
echo "[r3.5] target: $TARGET"

if command -v cargo >/dev/null 2>&1 && command -v rustc >/dev/null 2>&1; then
  echo "[r3.5] cargo/rustc already available"
else
  if command -v rustup >/dev/null 2>&1; then
    echo "[r3.5] rustup exists, but cargo/rustc are missing; continuing with rustup self repair"
  elif command -v curl >/dev/null 2>&1; then
    ATTEMPTED_NETWORK=1
    echo "[r3.5] attempting rustup minimal toolchain with curl, bounded to ${RUSTUP_TIMEOUT}s"
    RUSTUP_INIT="${TMPDIR:-/tmp}/wdc-rustup-init.sh"
    if curl --connect-timeout "$RUSTUP_CONNECT_TIMEOUT" --max-time "$RUSTUP_TIMEOUT" --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs -o "$RUSTUP_INIT" && sh "$RUSTUP_INIT" -y --profile minimal --default-toolchain stable; then
      export PATH="$HOME/.cargo/bin:$PATH"
    else
      echo "[r3.5] rustup curl install failed or timed out"
      if [ "${WDC_RUST_APT_FALLBACK:-0}" = "1" ] && command -v apt-get >/dev/null 2>&1; then
        ATTEMPTED_NETWORK=1
        echo "[r3.5] falling back to bounded apt-get install cargo rustc rustup"
        if ! timeout "$APT_TIMEOUT" apt-get update; then
          echo "[r3.5] apt-get update failed or timed out"
          exit 77
        fi
        if ! timeout "$APT_TIMEOUT" env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends cargo rustc rustup ca-certificates curl; then
          echo "[r3.5] apt-get install failed or timed out"
          exit 77
        fi
        export PATH="$HOME/.cargo/bin:$PATH"
      else
        echo "[r3.5] apt fallback disabled; set WDC_RUST_APT_FALLBACK=1 to attempt apt package install"
        exit 77
      fi
    fi
  elif command -v apt-get >/dev/null 2>&1; then
    echo "[r3.5] curl unavailable; trying bounded apt-get install cargo rustc rustup"
    ATTEMPTED_NETWORK=1
    if ! timeout "$APT_TIMEOUT" apt-get update; then
      echo "[r3.5] apt-get update failed or timed out"
      exit 77
    fi
    if ! timeout "$APT_TIMEOUT" env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends cargo rustc rustup ca-certificates curl; then
      echo "[r3.5] apt-get install failed or timed out"
      exit 77
    fi
    export PATH="$HOME/.cargo/bin:$PATH"
  else
    echo "[r3.5] no curl/rustup/apt-get path available"
    exit 78
  fi
fi

if ! command -v cargo >/dev/null 2>&1 || ! command -v rustc >/dev/null 2>&1; then
  echo "[r3.5] cargo/rustc still unavailable after bootstrap"
  if [ "$ATTEMPTED_NETWORK" = "1" ]; then
    exit 77
  fi
  exit 78
fi

cargo --version
rustc --version

if command -v rustup >/dev/null 2>&1; then
  if ! rustup target add "$TARGET"; then
    echo "[r3.5] rustup target add failed or timed out"
    exit 77
  fi
  rustup target list --installed | grep -q "^$TARGET$"
else
  echo "[r3.5] rustup not present; checking whether rustc can address $TARGET"
  rustc --print target-libdir --target "$TARGET" >/dev/null || exit 78
fi

echo "[r3.5] rust bootstrap completed"
