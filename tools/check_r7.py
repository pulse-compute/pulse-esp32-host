#!/usr/bin/env python3
"""Pure-Python R7 A/B activation and rollback check."""
from __future__ import annotations

import contextlib
import io
import json
import shutil
import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
FW = ROOT / "firmware"
EXAMPLE_BUNDLE = ROOT / "examples/bundles/relay-controller/dist/relay-controller-r6.wdcb"

sys.path.insert(0, str(ROOT))
from tools import wdc_bundle_tool as tool  # noqa: E402

REQUIRED = [
    "firmware/components/wdc_activation/CMakeLists.txt",
    "firmware/components/wdc_activation/wdc_activation.c",
    "firmware/components/wdc_activation/include/wdc_activation.h",
    "tests/contract/test_r7_activation_rollback.py",
]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def call_tool(func, **kwargs):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = func(SimpleNamespace(**kwargs))
    require(rc == 0, f"tool call failed rc={rc}: {func.__name__}")
    return json.loads(buf.getvalue())


def files_and_symbols_check() -> dict[str, object]:
    missing = [path for path in REQUIRED if not (ROOT / path).exists()]
    require(not missing, "missing R7 files: " + ", ".join(missing))
    abi = (FW / "components/wdc_abi/include/wdc_abi.h").read_text(encoding="utf-8")
    for token in [
        'WDC_R7_SHELL_VERSION "0.1.0-r7"',
        'WDC_R7_BUILD_STAGE   "R7"',
        "WDC_CURRENT_SHELL_VERSION WDC_R9_SHELL_VERSION",
        "WDC_SLOT_RUNNING_PENDING",
    ]:
        require(token in abi, f"missing ABI token: {token}")
    activation = (FW / "components/wdc_activation/include/wdc_activation.h").read_text(encoding="utf-8")
    for token in [
        "WdcActivationPolicy",
        "WdcActivationDecision",
        "wdc_activation_prepare_pending",
        "wdc_activation_on_boot",
        "wdc_activation_confirm",
        "wdc_activation_record_fault",
    ]:
        require(token in activation, f"missing activation token: {token}")
    ota = (FW / "components/wdc_ota/include/wdc_ota.h").read_text(encoding="utf-8")
    for token in ["wdc_ota_read_metadata", "wdc_ota_write_metadata"]:
        require(token in ota, f"missing OTA token: {token}")
    return {"missing_files": 0, "symbol_groups": 3}


def activation_tool_flow_check() -> dict[str, object]:
    with tempfile.TemporaryDirectory() as tmp:
        slots = Path(tmp) / "slots"
        common = {"bundle": str(EXAMPLE_BUNDLE), "slots_dir": str(slots), "key": None, "allow_unverified": False}
        call_tool(tool.cmd_install, slot="a", **common)
        a_pending = call_tool(tool.cmd_activate, slot="a", slots_dir=str(slots), allow_fail=False)
        require(a_pending["decision"] == "slot_marked_pending", "slot A was not marked pending")
        a_boot = call_tool(tool.cmd_boot, slots_dir=str(slots), max_candidate_boots=1, write_no_bundle=False)
        require(a_boot["decision"] == "boot_pending" and a_boot["selected_slot"] == "a", "slot A did not enter probation")
        a_confirm = call_tool(tool.cmd_confirm, slots_dir=str(slots), slot=None, allow_fail=False)
        require(a_confirm["metadata"]["last_good_slot"] == "a", "slot A was not confirmed last-good")

        call_tool(tool.cmd_install, slot="b", **common)
        call_tool(tool.cmd_activate, slot="b", slots_dir=str(slots), allow_fail=False)
        b_boot = call_tool(tool.cmd_boot, slots_dir=str(slots), max_candidate_boots=1, write_no_bundle=False)
        require(b_boot["decision"] == "boot_pending" and b_boot["selected_slot"] == "b", "slot B did not enter probation")
        rollback = call_tool(tool.cmd_boot, slots_dir=str(slots), max_candidate_boots=1, write_no_bundle=False)
        require(rollback["decision"] == "rollback_to_last_good", "unconfirmed reset did not roll back")
        require(rollback["selected_slot"] == "a", "rollback did not select slot A")
        require(rollback["metadata"]["slot_b_state"] == "failed", "failed candidate was not marked failed")
        require(rollback["metadata"]["last_failure_reason"] == -18, "failure reason was not unconfirmed reset")

        call_tool(tool.cmd_install, slot="b", **common)
        call_tool(tool.cmd_activate, slot="b", slots_dir=str(slots), allow_fail=False)
        call_tool(tool.cmd_boot, slots_dir=str(slots), max_candidate_boots=1, write_no_bundle=False)
        b_confirm = call_tool(tool.cmd_confirm, slots_dir=str(slots), slot=None, allow_fail=False)
        require(b_confirm["metadata"]["slot_b_state"] == "confirmed", "slot B did not confirm")
        require(b_confirm["metadata"]["last_good_slot"] == "b", "slot B was not last-good after confirm")
        return {
            "rollback_decision": rollback["decision"],
            "confirmed_slot": b_confirm["metadata"]["last_good_slot"],
            "metadata_generation": b_confirm["metadata"]["metadata_generation"],
        }


def native_smoke_check() -> dict[str, object]:
    if shutil.which("gcc") is None:
        return {"status": "SKIPPED_ENV", "reason": "gcc not available"}
    program = textwrap.dedent(
        r'''
        #include <assert.h>
        #include <stdint.h>
        #include <string.h>
        #include "wdc_abi.h"
        #include "wdc_activation.h"
        #include "wdc_bundle.h"
        #include "wdc_ota.h"

        static void seed(WdcBundleSlotRecord *record, WdcSlotState state, uint32_t version, uint8_t fill) {
            memset(record, 0, sizeof(*record));
            record->state = state;
            record->bundle_version = version;
            record->security_counter = version;
            memset(record->payload_sha256, fill, WDC_BUNDLE_SHA256_BYTES);
        }

        int main(void) {
            WdcBundleMetadataV1 metadata;
            wdc_bundle_metadata_init(&metadata);
            seed(&metadata.slot_a, WDC_SLOT_CONFIRMED, 1u, 0xa1u);
            metadata.active_slot = WDC_BUNDLE_SLOT_A;
            metadata.last_good_slot = WDC_BUNDLE_SLOT_A;
            assert(wdc_bundle_metadata_seal(&metadata) == WDC_OK);
            seed(&metadata.slot_b, WDC_SLOT_VERIFIED, 2u, 0xb2u);
            assert(wdc_bundle_metadata_seal(&metadata) == WDC_OK);

            WdcActivationPolicy policy = wdc_activation_default_policy();
            policy.max_candidate_boots = 1u;
            policy.required_health_checks = 1u;
            WdcActivationDecision decision;
            assert(wdc_activation_prepare_pending(&metadata, WDC_BUNDLE_SLOT_B, &policy) == WDC_OK);
            assert(wdc_activation_on_boot(&metadata, &policy, &decision) == WDC_OK);
            assert(decision.kind == WDC_ACTIVATION_DECISION_RUN_CANDIDATE);
            assert(metadata.slot_b.state == WDC_SLOT_RUNNING_PENDING);
            assert(wdc_activation_on_boot(&metadata, &policy, &decision) == WDC_OK);
            assert(decision.kind == WDC_ACTIVATION_DECISION_ROLLBACK_TO_LAST_GOOD);
            assert(decision.slot_to_run == WDC_BUNDLE_SLOT_A);
            assert(metadata.slot_b.state == WDC_SLOT_FAILED);
            assert(metadata.last_failure_reason == WDC_ERR_NOT_SYNCHRONIZED);
            seed(&metadata.slot_b, WDC_SLOT_VERIFIED, 3u, 0xb3u);
            assert(wdc_bundle_metadata_seal(&metadata) == WDC_OK);
            assert(wdc_activation_prepare_pending(&metadata, WDC_BUNDLE_SLOT_B, &policy) == WDC_OK);
            assert(wdc_activation_on_boot(&metadata, &policy, &decision) == WDC_OK);
            assert(wdc_activation_confirm(&metadata, WDC_BUNDLE_SLOT_B, 1u) == WDC_OK);
            assert(metadata.last_good_slot == WDC_BUNDLE_SLOT_B);
            assert(metadata.slot_b.state == WDC_SLOT_CONFIRMED);
            assert(wdc_ota_write_metadata(&metadata) == WDC_OK);
            WdcBundleMetadataV1 loaded;
            assert(wdc_ota_read_metadata(&loaded) == WDC_OK);
            assert(loaded.last_good_slot == WDC_BUNDLE_SLOT_B);
            return 0;
        }
        '''
    )
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        src = tmp_path / "r7_native.c"
        exe = tmp_path / "r7_native"
        src.write_text(program, encoding="utf-8")
        include_args = [
            "-I", str(FW / "components/wdc_abi/include"),
            "-I", str(FW / "components/wdc_activation/include"),
            "-I", str(FW / "components/wdc_bundle/include"),
            "-I", str(FW / "components/wdc_caps/include"),
            "-I", str(FW / "components/wdc_profile/include"),
            "-I", str(FW / "components/wdc_ota/include"),
        ]
        sources = [
            FW / "components/wdc_abi/wdc_errors.c",
            FW / "components/wdc_abi/wdc_cbor.c",
            FW / "components/wdc_abi/wdc_pointer.c",
            FW / "components/wdc_abi/wdc_host_call.c",
            FW / "components/wdc_caps/wdc_caps.c",
            FW / "components/wdc_profile/wdc_profile_static.c",
            FW / "components/wdc_bundle/wdc_bundle.c",
            FW / "components/wdc_ota/wdc_ota.c",
            FW / "components/wdc_activation/wdc_activation.c",
            src,
        ]
        subprocess.run(["gcc", "-std=c11", "-Wall", "-Wextra", "-Werror", *include_args, *map(str, sources), "-o", str(exe)], cwd=ROOT, check=True, timeout=120)
        subprocess.run([str(exe)], check=True, timeout=120)
    return {"status": "PASS", "native_smoke": "activation_state_machine"}


def main() -> int:
    result = {
        "schema": "wdc.r7.check.v1",
        "milestone": "R7",
        "status": "PASS",
        "checks": {
            "files_and_symbols": files_and_symbols_check(),
            "activation_tool_flow": activation_tool_flow_check(),
            "native_smoke": native_smoke_check(),
        },
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    print("R7 check passed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"R7 check failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
