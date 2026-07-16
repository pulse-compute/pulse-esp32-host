#!/usr/bin/env python3
"""Small R0 completeness check for required scaffold files."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = [
    "README.md",
    "firmware/CMakeLists.txt",
    "firmware/sdkconfig.defaults",
    "firmware/partitions.csv",
    "firmware/main/app_main.c",
    "firmware/main/shell_main.c",
    "firmware/components/wdc_abi/include/wdc_abi.h",
    "schemas/wdc_bundle_manifest.schema.json",
    "schemas/wdc_device_profile.schema.json",
    "specs/WDC-ESP32S3-001-contract.md",
    "specs/WDC-ESP32S3-002-roadmap.md",
    "specs/WDC-ABI-001.md",
    "specs/WDC-BUNDLE-001.md",
    "guest-sdk/rust/wdc_guest/Cargo.toml",
    "guest-sdk/rust/examples/noop_bundle/Cargo.toml",
    "guest-sdk/c/include/wdc_guest.h",
    "examples/device-profiles/relay-node-rev-c.json",
    "examples/bundles/relay-controller/manifest.json",
    "tests/contract/test_r0_contract.py",
]


def main() -> int:
    missing = [path for path in REQUIRED if not (ROOT / path).exists()]
    if missing:
        for path in missing:
            print(f"missing: {path}", file=sys.stderr)
        return 1
    result = subprocess.run([sys.executable, "-B", "-m", "unittest", "tests.contract.test_r0_contract"], cwd=ROOT, timeout=60)
    if result.returncode == 0:
        print("R0 check passed")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
