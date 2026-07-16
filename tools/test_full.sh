#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-/usr/bin/python3 -B}"
# shellcheck disable=SC2086
exec $PYTHON "$ROOT/tools/test_full.py" --repo-root "$ROOT" "$@"
