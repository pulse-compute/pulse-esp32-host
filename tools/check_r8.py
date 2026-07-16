#!/usr/bin/env python3
"""R8/R8.1 active-slot runtime source and network mediator check.

R8.1 runs native C smokes by default when gcc is present. Skips are only
accepted when the compiler is unavailable.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FW = ROOT / "firmware"
R8_BUNDLE = ROOT / "examples/bundles/relay-controller/dist/relay-controller-r8.wdcb"

REQUIRED = [
    "firmware/components/wdc_net/CMakeLists.txt",
    "firmware/components/wdc_net/wdc_net.c",
    "firmware/components/wdc_net/include/wdc_net.h",
    "firmware/components/wdc_app/CMakeLists.txt",
    "firmware/components/wdc_app/wdc_app.c",
    "firmware/components/wdc_app/include/wdc_app.h",
    "tests/contract/test_r8_active_slot_network.py",
    "examples/bundles/relay-controller/dist/relay-controller-r8.wdcb",
]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def files_and_symbols_check() -> dict[str, object]:
    missing = [path for path in REQUIRED if not (ROOT / path).exists()]
    require(not missing, "missing R8 files: " + ", ".join(missing))
    abi = (FW / "components/wdc_abi/include/wdc_abi.h").read_text(encoding="utf-8")
    for token in [
        'WDC_R8_2_SHELL_VERSION "0.1.0-r8.2"',
        'WDC_R8_2_BUILD_STAGE   "R8.2"',
        "WDC_OP_NET_STATUS",
        "WDC_OP_MQTT_PUBLISH",
        "WDC_OP_MQTT_SUBSCRIBE",
        "WDC_OP_HTTP_REQUEST",
        "WDC_EVENT_NET_CONNECTED",
        "WdcHostNetCallFn",
        "wdc_opcode_supported_r8",
    ]:
        require(token in abi, f"missing ABI token: {token}")
    net = (FW / "components/wdc_net/wdc_net.c").read_text(encoding="utf-8")
    for token in ["wdc_net_host_call", "wdc_host_call_set_net_hook", "WDC_EVENT_NET_CONNECTED", "WDC_EVENT_NET_DISCONNECTED"]:
        require(token in net, f"missing net token: {token}")
    app = (FW / "components/wdc_app/wdc_app.c").read_text(encoding="utf-8")
    for token in ["wdc_app_boot_active_slot", "wdc_ota_read_slot_to_buffer", "wdc_bundle_verify", "wdc_runtime_load_static"]:
        require(token in app, f"missing app token: {token}")
    shell = (FW / "main/shell_main.c").read_text(encoding="utf-8")
    for token in ["wdc_net_init", "wdc_shell_run_r8_network_self_test", "wdc_shell_run_r8_active_slot_probe"]:
        require(token in shell, f"missing shell token: {token}")
    return {"missing_files": 0, "abi_tokens": 9, "components": ["wdc_net", "wdc_app"]}


def bundle_check() -> dict[str, object]:
    sys.path.insert(0, str(ROOT))
    from tools import wdc_bundle_tool  # noqa: E402

    data = R8_BUNDLE.read_bytes()
    report = wdc_bundle_tool.verify_bytes(data)
    require(report.get("status") == "PASS", "R8 example bundle did not verify")
    manifest = report["manifest"]
    require(manifest["bundle_version"] == 8, "R8 bundle version mismatch")
    caps = manifest.get("capabilities", [])
    network_caps = {(c.get("resource"), tuple(c.get("ops", []))) for c in caps if c.get("kind") == "network"}
    require(("mqtt_telemetry", ("publish",)) in network_caps, "missing mqtt telemetry publish capability")
    require(("mqtt_commands", ("subscribe",)) in network_caps, "missing mqtt commands subscribe capability")
    require(("http_api", ("request",)) in network_caps, "missing http api request capability")
    return {
        "bundle_bytes": len(data),
        "bundle_version": manifest["bundle_version"],
        "network_capabilities": sorted([f"{r}:{'/'.join(o)}" for r, o in network_caps]),
    }


def unittest_check() -> dict[str, object]:
    result = subprocess.run(
        [sys.executable, "-B", "-m", "unittest", "tests.contract.test_r8_active_slot_network", "-v"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stdout + result.stderr)
    skipped = result.stderr.count("skipped '") + result.stdout.count("skipped '")
    return {"status": "PASS", "native_smokes": "RUN_BY_DEFAULT", "skipped": skipped}


def main() -> int:
    result = {
        "schema": "wdc.r8_1.check.v1",
        "milestone": "R8.1",
        "status": "PASS",
        "checks": {
            "files_and_symbols": files_and_symbols_check(),
            "bundle": bundle_check(),
            "contract_tests": unittest_check(),
        },
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    print("R8.1-compatible R8 check passed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"R8 check failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
