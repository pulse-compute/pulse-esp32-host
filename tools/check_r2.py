#!/usr/bin/env python3
"""R2 completeness check for the runtime vertical slice."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = [
    "firmware/components/wdc_runtime/include/wdc_runtime.h",
    "firmware/components/wdc_runtime/include/wdc_static_wasm.h",
    "firmware/components/wdc_runtime/wdc_runtime.c",
    "firmware/components/wdc_runtime/wdc_static_wasm.c",
    "firmware/components/wdc_runtime/CMakeLists.txt",
    "firmware/components/wdc_runtime/idf_component.yml",
    "firmware/components/wdc_runtime/test_vectors/wdc_static_hello_wasm.wasm",
    "tools/gen_r2_wasm.py",
    "tests/contract/test_r2_runtime.py",
]


def main() -> int:
    missing = [path for path in REQUIRED if not (ROOT / path).exists()]
    if missing:
        for path in missing:
            print(f"missing: {path}", file=sys.stderr)
        return 1

    result = subprocess.run(
        [sys.executable, "-B", "-m", "unittest", "tests.contract.test_r2_runtime"],
        cwd=ROOT,
        timeout=30,
    )
    if result.returncode != 0:
        return result.returncode
    print("R2 check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
