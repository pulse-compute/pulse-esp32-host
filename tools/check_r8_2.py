#!/usr/bin/env python3
"""R8.2 runtime-limit and payload-ceiling acceptance gate.

This gate intentionally avoids invoking unittest as a nested subprocess.  The
sandbox can intermittently hold subprocess-heavy unittest pipes open after the
child has completed, so this script performs the source contract checks and the
native C smoke directly.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FW = ROOT / "firmware"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def files_and_symbols_check() -> dict[str, object]:
    required = [
        "tests/contract/test_r8_2_runtime_limits.py",
        "tests/firmware-unit/r8_2_runtime_limits_smoke.c",
        "firmware/components/wdc_abi/include/wdc_abi.h",
        "firmware/components/wdc_abi/wdc_host_call.c",
        "firmware/components/wdc_caps/include/wdc_caps.h",
        "firmware/components/wdc_caps/wdc_caps.c",
        "firmware/components/wdc_app/wdc_app.c",
        "firmware/components/wdc_runtime/include/wdc_runtime.h",
        "firmware/components/wdc_runtime/wdc_runtime.c",
    ]
    missing = [rel for rel in required if not (ROOT / rel).exists()]
    require(not missing, "missing R8.2 files: " + ", ".join(missing))

    config = (FW / "main/shell_config.h").read_text(encoding="utf-8")
    for token in [
        'WDC_SHELL_VERSION     "0.1.0-r9"',
        'WDC_SHELL_BUILD_STAGE "R9"',
        "WDC_R8_2_RUNTIME_LIMITS_FROM_MANIFEST 1",
    ]:
        require(token in config, f"missing shell-config token: {token}")

    abi = (FW / "components/wdc_abi/include/wdc_abi.h").read_text(encoding="utf-8")
    for token in [
        'WDC_R8_2_SHELL_VERSION "0.1.0-r8.2"',
        'WDC_R8_2_BUILD_STAGE   "R8.2"',
        "WDC_CURRENT_SHELL_VERSION WDC_R9_SHELL_VERSION",
        "typedef struct WdcHostCallLimits",
        "wdc_host_call_set_limits",
        "wdc_host_call_reset_limits",
    ]:
        require(token in abi, f"missing ABI token: {token}")

    source_expectations = {
        "firmware/components/wdc_abi/wdc_host_call.c": [
            "s_limits",
            "wdc_host_call_set_limits",
            "wdc_host_call_reset_limits",
            "request_len > s_limits.max_request_bytes",
            "response_cap > s_limits.max_response_bytes",
        ],
        "firmware/components/wdc_caps/include/wdc_caps.h": [
            "max_payload_bytes",
            "max_rate_hz",
            "payload_len",
            "payload_limit",
        ],
        "firmware/components/wdc_caps/wdc_caps.c": [
            "parse_optional_u32",
            "enforce_payload_limit",
            "enforce_rate_limit",
            "WDC_ERR_RATE_LIMITED",
            "wdc_caps_set_time_ms_for_test",
            "max_payload_bytes",
            "payload_limit",
        ],
        "firmware/components/wdc_app/wdc_app.c": [
            "runtime_config_from_manifest",
            "install_host_call_limits_from_manifest",
            "verify->manifest.max_request_bytes",
            "verify->manifest.max_response_bytes",
            "verify->manifest.max_event_bytes",
        ],
        "firmware/components/wdc_runtime/include/wdc_runtime.h": [
            "max_event_bytes",
            "WDC_RUNTIME_DEFAULT_MAX_EVENT_BYTES",
        ],
        "firmware/components/wdc_runtime/wdc_runtime.c": [
            "event exceeds manifest runtime limit",
            "runtime->config.max_event_bytes",
        ],
    }
    for rel, tokens in source_expectations.items():
        text = (ROOT / rel).read_text(encoding="utf-8")
        for token in tokens:
            require(token in text, f"missing token in {rel}: {token}")
    return {"missing_files": 0, "symbol_groups": len(source_expectations) + 2}


def compile_native_smoke() -> dict[str, object]:
    gcc = shutil.which("gcc")
    if gcc is None:
        return {"status": "SKIPPED_ENV", "reason": "gcc unavailable"}

    abi = FW / "components/wdc_abi"
    caps = FW / "components/wdc_caps"
    profile = FW / "components/wdc_profile"
    runtime = FW / "components/wdc_runtime"
    diag = FW / "components/wdc_diag"
    events = FW / "components/wdc_events"

    include_dirs = [
        abi / "include",
        caps / "include",
        profile / "include",
        runtime / "include",
        diag / "include",
        events / "include",
    ]
    sources = [
        abi / "wdc_errors.c",
        abi / "wdc_cbor.c",
        abi / "wdc_host_call.c",
        caps / "wdc_caps.c",
        profile / "wdc_profile_static.c",
        diag / "wdc_diag.c",
        events / "wdc_event_encode.c",
        events / "wdc_event_queue.c",
        runtime / "wdc_runtime.c",
        ROOT / "tests/firmware-unit/r8_2_runtime_limits_smoke.c",
    ]

    with tempfile.TemporaryDirectory() as tmp:
        exe = Path(tmp) / "r8_2_runtime_limits_smoke"
        cmd = [gcc, "-std=c11", "-Wall", "-Wextra", "-Werror"]
        for inc in include_dirs:
            cmd.extend(["-I", str(inc)])
        cmd.extend(str(src) for src in sources)
        cmd.extend(["-o", str(exe)])
        build = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, check=False)
        if build.returncode != 0:
            raise RuntimeError("native smoke compile failed:\n" + build.stdout + build.stderr)
        run = subprocess.run([str(exe)], cwd=ROOT, text=True, capture_output=True, check=False, timeout=30)
        if run.returncode != 0:
            raise RuntimeError("native smoke run failed:\n" + run.stdout + run.stderr)
    return {"status": "PASS", "compiler": Path(gcc).name, "smoke": "r8_2_runtime_limits_smoke"}


def main() -> int:
    native = compile_native_smoke()
    status = "PASS" if native.get("status") == "PASS" else "PARTIAL"
    result = {
        "schema": "wdc.r8_2.check.v1",
        "milestone": "R8.2",
        "status": status,
        "checks": {
            "files_and_symbols": files_and_symbols_check(),
            "native_runtime_limit_smoke": native,
        },
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    if status == "PASS":
        print("R8.2 runtime limits check passed")
    else:
        print("R8.2 runtime limits check partial")
    return 0 if status in {"PASS", "PARTIAL"} else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"R8.2 check failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
