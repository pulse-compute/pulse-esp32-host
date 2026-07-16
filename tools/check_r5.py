#!/usr/bin/env python3
"""R5 safety-enforced hardware MVP check."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = [
    "firmware/components/wdc_safety/CMakeLists.txt",
    "firmware/components/wdc_safety/wdc_safety.c",
    "firmware/components/wdc_safety/include/wdc_safety.h",
    "tests/contract/test_r5_safety_hardware.py",
]


def main() -> int:
    missing = [path for path in REQUIRED if not (ROOT / path).exists()]
    if missing:
        for path in missing:
            print(f"missing: {path}", file=sys.stderr)
        return 1

    result = subprocess.run(
        [sys.executable, "-B", "-m", "unittest", "tests.contract.test_r5_safety_hardware", "-v"],
        cwd=ROOT,
        timeout=120,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        print("R5 check passed")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
