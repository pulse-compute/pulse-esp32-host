#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys


def main() -> int:
    result = subprocess.run([sys.executable, "-m", "unittest", "tests.contract.test_r3_abi"], check=False)
    if result.returncode == 0:
        print("R3 check passed")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
