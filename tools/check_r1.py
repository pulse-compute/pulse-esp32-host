#!/usr/bin/env python3
"""R1 completeness check for the native shell skeleton."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = [
    "firmware/main/app_main.c",
    "firmware/main/shell_main.c",
    "firmware/main/shell_config.h",
    "firmware/components/wdc_diag/include/wdc_diag.h",
    "firmware/components/wdc_diag/wdc_diag.c",
    "firmware/components/wdc_events/include/wdc_events.h",
    "firmware/components/wdc_events/wdc_event_queue.c",
    "firmware/components/wdc_profile/include/wdc_profile.h",
    "firmware/components/wdc_profile/wdc_profile_static.c",
    "firmware/components/wdc_hal/include/wdc_gpio.h",
    "firmware/components/wdc_hal/wdc_gpio_espidf.c",
    "tests/contract/test_r1_native_shell.py",
]


def main() -> int:
    missing = [path for path in REQUIRED if not (ROOT / path).exists()]
    if missing:
        for path in missing:
            print(f"missing: {path}", file=sys.stderr)
        return 1
    result = subprocess.run([sys.executable, "-B", "-m", "unittest", "tests.contract.test_r1_native_shell"], cwd=ROOT, timeout=60)
    if result.returncode == 0:
        print("R1 check passed")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
