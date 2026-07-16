#!/usr/bin/env python3
"""R4 completeness check for profile, capability, and event runtime boundaries."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = [
    "firmware/components/wdc_caps/CMakeLists.txt",
    "firmware/components/wdc_caps/wdc_caps.c",
    "firmware/components/wdc_caps/include/wdc_caps.h",
    "firmware/components/wdc_events/include/wdc_events.h",
    "firmware/components/wdc_events/wdc_event_encode.c",
    "firmware/components/wdc_events/wdc_event_queue.c",
    "tests/contract/test_r4_events_caps.py",
]


def main() -> int:
    missing = [path for path in REQUIRED if not (ROOT / path).exists()]
    if missing:
        for path in missing:
            print(f"missing: {path}", file=sys.stderr)
        return 1

    result = subprocess.run(
        [sys.executable, "-B", "-m", "unittest", "tests.contract.test_r4_events_caps", "-v"],
        cwd=ROOT,
        timeout=120,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    if result.returncode == 0:
        print("R4 check passed")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
