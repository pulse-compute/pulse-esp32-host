#!/usr/bin/env python3
"""R8.1 hardening/refactor acceptance gate."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FW = ROOT / "firmware"

REQUIRED = [
    "tests/contract/test_r8_1_hardening.py",
    "firmware/components/wdc_ota/wdc_ota.c",
    "firmware/components/wdc_ota/include/wdc_ota.h",
    "firmware/components/wdc_bundle/wdc_bundle.c",
    "firmware/components/wdc_net/wdc_net.c",
    "tools/check_r8_1.py",
]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def files_and_symbols_check() -> dict[str, object]:
    missing = [rel for rel in REQUIRED if not (ROOT / rel).exists()]
    require(not missing, "missing R8.1 files: " + ", ".join(missing))

    config = (FW / "main/shell_config.h").read_text(encoding="utf-8")
    for token in [
        'WDC_SHELL_VERSION     "0.1.0-r9"',
        'WDC_SHELL_BUILD_STAGE "R9"',
        "WDC_ENABLE_EFFECTFUL_SELF_TESTS 0",
        "WDC_ENABLE_BOOT_DIAGNOSTIC_PROBES 0",
        "WDC_R8_NETWORK_SMOKE         WDC_ENABLE_EFFECTFUL_SELF_TESTS",
    ]:
        require(token in config, f"missing shell-config token: {token}")

    abi = (FW / "components/wdc_abi/include/wdc_abi.h").read_text(encoding="utf-8")
    for token in [
        'WDC_R8_2_SHELL_VERSION "0.1.0-r8.2"',
        'WDC_R8_2_BUILD_STAGE   "R8.2"',
        "WDC_CURRENT_SHELL_VERSION WDC_R9_SHELL_VERSION",
    ]:
        require(token in abi, f"missing ABI token: {token}")

    host_call = (FW / "components/wdc_abi/wdc_host_call.c").read_text(encoding="utf-8")
    for token in ["opcode_safe_without_authorizer", "WDC_ERR_CAPABILITY_DENIED", "s_authorizer == NULL"]:
        require(token in host_call, f"missing fail-closed host-call token: {token}")

    ota_h = (FW / "components/wdc_ota/include/wdc_ota.h").read_text(encoding="utf-8")
    for token in ["WDC_OTA_METADATA_JOURNAL_RECORDS", "wdc_ota_host_metadata_valid_record_count", "wdc_ota_host_corrupt_metadata_record"]:
        require(token in ota_h, f"missing journal token: {token}")

    bundle = (FW / "components/wdc_bundle/wdc_bundle.c").read_text(encoding="utf-8")
    for token in ["wasm_payload_has_required_exports", "section_id == 7u", "bundle has trailing unsigned bytes"]:
        require(token in bundle, f"missing strict bundle token: {token}")

    net = (FW / "components/wdc_net/wdc_net.c").read_text(encoding="utf-8")
    for token in ["mqtt_topic_prefix", "mqtt_subscribe_prefix", "http_url_prefix", "method_allowed", "WDC_ERR_CAPABILITY_DENIED"]:
        require(token in net, f"missing network policy token: {token}")

    return {"missing_files": 0, "symbol_groups": 6}


def unittest_check() -> dict[str, object]:
    result = subprocess.run(
        [sys.executable, "-B", "-m", "unittest", "tests.contract.test_r8_1_hardening", "-v"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=240,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stdout + result.stderr)
    return {"status": "PASS", "module": "tests.contract.test_r8_1_hardening"}


def raw_discovery_check() -> dict[str, object]:
    if os.environ.get("WDC_R8_1_SKIP_RAW_DISCOVERY") == "1":
        return {"status": "SKIPPED_ENV", "reason": "skipped by split milestone runner to avoid nested subprocess-heavy discovery"}
    result = subprocess.run(
        [sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-v"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=300,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stdout + result.stderr)
    tests_line = ""
    for line in (result.stdout + result.stderr).splitlines():
        if line.startswith("Ran ") and " tests" in line:
            tests_line = line
    return {"status": "PASS", "raw_unittest_discovery": tests_line or "passed"}


def main() -> int:
    result = {
        "schema": "wdc.r8_1.check.v1",
        "milestone": "R8.1",
        "status": "PASS",
        "checks": {
            "files_and_symbols": files_and_symbols_check(),
            "hardening_contract_tests": unittest_check(),
            "raw_unittest_discovery": raw_discovery_check(),
        },
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    print("R8.1 hardening check passed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"R8.1 check failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
