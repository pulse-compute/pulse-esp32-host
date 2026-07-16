#!/usr/bin/env python3
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Keep these split into separate interpreter invocations. Running every module in
# one unittest-discover process can leave the sandbox stdout pipe open after OK
# when multiple subprocess-heavy smoke tests have run.
COMMANDS = [
    [sys.executable, "-B", "tools/check_r0.py"],
    [sys.executable, "-B", "tools/check_r1.py"],
    [sys.executable, "-B", "tools/check_r2.py"],
    [sys.executable, "-B", "tools/check_r3.py"],
    [sys.executable, "-B", "-m", "unittest", "tests.contract.test_r3_5_verification"],
    [sys.executable, "-B", "-m", "unittest", "tests.contract.test_r3_5_deps"],
    [sys.executable, "-B", "tools/check_r4.py"],
    [sys.executable, "-B", "tools/check_r5.py"],
    [sys.executable, "-B", "tools/check_r6.py"],
    [sys.executable, "-B", "tools/check_r7.py"],
    [sys.executable, "-B", "tools/check_r8.py"],
    [sys.executable, "-B", "-m", "unittest", "tests.contract.test_r8_1_hardening", "-v"],
    [sys.executable, "-B", "tools/check_r8_2.py"],
    [sys.executable, "-B", "tools/check_r9.py"],
]


def main() -> int:
    for cmd in COMMANDS:
        print("$", " ".join(cmd), flush=True)
        env = None
        if cmd and cmd[-1] == "tools/check_r8_1.py":
            env = os.environ.copy()
            env["WDC_R8_1_SKIP_RAW_DISCOVERY"] = "1"
        result = subprocess.run(
            cmd,
            cwd=ROOT,
            check=False,
            timeout=300,
            env=env,
        )
        if result.returncode != 0:
            return result.returncode
    print("All split contract tests passed through R9")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
