from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FW = ROOT / "firmware"
TOOL = ROOT / "tools/wdc_bundle_tool.py"
EXAMPLE_BUNDLE = ROOT / "examples/bundles/relay-controller/dist/relay-controller-r6.wdcb"


class R7ActivationRollbackTests(unittest.TestCase):
    def test_r7_files_and_symbols_exist(self) -> None:
        files = [
            "firmware/components/wdc_activation/CMakeLists.txt",
            "firmware/components/wdc_activation/wdc_activation.c",
            "firmware/components/wdc_activation/include/wdc_activation.h",
            "firmware/components/wdc_ota/include/wdc_ota.h",
            "tools/check_r7.py",
        ]
        for rel in files:
            self.assertTrue((ROOT / rel).exists(), rel)

        abi = (FW / "components/wdc_abi/include/wdc_abi.h").read_text(encoding="utf-8")
        for token in [
            'WDC_R7_SHELL_VERSION "0.1.0-r7"',
            'WDC_R7_BUILD_STAGE   "R7"',
            "WDC_CURRENT_SHELL_VERSION WDC_R9_SHELL_VERSION",
            "WDC_SLOT_RUNNING_PENDING",
        ]:
            self.assertIn(token, abi)

        activation = (FW / "components/wdc_activation/include/wdc_activation.h").read_text(encoding="utf-8")
        for token in [
            "WdcActivationPolicy",
            "WdcActivationDecision",
            "wdc_activation_prepare_pending",
            "wdc_activation_on_boot",
            "wdc_activation_confirm",
            "wdc_activation_record_fault",
        ]:
            self.assertIn(token, activation)

        ota = (FW / "components/wdc_ota/include/wdc_ota.h").read_text(encoding="utf-8")
        for token in ["wdc_ota_read_metadata", "wdc_ota_write_metadata"]:
            self.assertIn(token, ota)

        shell = (FW / "main/shell_main.c").read_text(encoding="utf-8")
        for token in [
            "wdc_shell_run_r7_activation_self_test",
            "wdc_activation_on_boot",
            "R7 activation/rollback self-test passed",
        ]:
            self.assertIn(token, shell)

    def test_r7_bundle_tool_activation_flow(self) -> None:
        from types import SimpleNamespace
        from tools import wdc_bundle_tool as tool

        def call(func, **kwargs):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = func(SimpleNamespace(**kwargs))
            self.assertEqual(rc, 0, buf.getvalue())
            return json.loads(buf.getvalue())

        with tempfile.TemporaryDirectory() as tmp:
            slots = Path(tmp) / "slots"
            common = {"bundle": str(EXAMPLE_BUNDLE), "slots_dir": str(slots), "key": None, "allow_unverified": False}
            call(tool.cmd_install, slot="a", **common)
            a_pending = call(tool.cmd_activate, slot="a", slots_dir=str(slots), allow_fail=False)
            self.assertEqual(a_pending["decision"], "slot_marked_pending")
            a_boot = call(tool.cmd_boot, slots_dir=str(slots), max_candidate_boots=1, write_no_bundle=False)
            self.assertEqual(a_boot["decision"], "boot_pending")
            self.assertEqual(a_boot["selected_slot"], "a")
            a_confirm = call(tool.cmd_confirm, slots_dir=str(slots), slot=None, allow_fail=False)
            self.assertEqual(a_confirm["decision"], "confirmed")
            self.assertEqual(a_confirm["metadata"]["last_good_slot"], "a")
            self.assertEqual(a_confirm["metadata"]["slot_a_state"], "confirmed")

            call(tool.cmd_install, slot="b", **common)
            b_pending = call(tool.cmd_activate, slot="b", slots_dir=str(slots), allow_fail=False)
            self.assertEqual(b_pending["metadata"]["slot_b_state"], "pending")
            b_boot = call(tool.cmd_boot, slots_dir=str(slots), max_candidate_boots=1, write_no_bundle=False)
            self.assertEqual(b_boot["decision"], "boot_pending")
            self.assertEqual(b_boot["selected_slot"], "b")
            rollback = call(tool.cmd_boot, slots_dir=str(slots), max_candidate_boots=1, write_no_bundle=False)
            self.assertEqual(rollback["decision"], "rollback_to_last_good")
            self.assertEqual(rollback["selected_slot"], "a")
            self.assertEqual(rollback["metadata"]["slot_b_state"], "failed")
            self.assertEqual(rollback["metadata"]["last_failure_reason"], -18)
            self.assertEqual(rollback["metadata"]["active_slot"], "a")

            call(tool.cmd_install, slot="b", **common)
            call(tool.cmd_activate, slot="b", slots_dir=str(slots), allow_fail=False)
            call(tool.cmd_boot, slots_dir=str(slots), max_candidate_boots=1, write_no_bundle=False)
            b_confirm = call(tool.cmd_confirm, slots_dir=str(slots), slot=None, allow_fail=False)
            self.assertEqual(b_confirm["metadata"]["slot_b_state"], "confirmed")
            self.assertEqual(b_confirm["metadata"]["last_good_slot"], "b")
            self.assertEqual(b_confirm["metadata"]["candidate_boot_count"], 0)
            self.assertEqual(b_confirm["metadata"]["last_failure_reason"], 0)

    def test_r7_native_activation_state_machine_smoke(self) -> None:
        if shutil.which("gcc") is None:
            self.skipTest("gcc not available")

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
                assert(metadata.active_slot == WDC_BUNDLE_SLOT_B);
                assert(metadata.slot_b.state == WDC_SLOT_PENDING);

                assert(wdc_activation_on_boot(&metadata, &policy, &decision) == WDC_OK);
                assert(decision.kind == WDC_ACTIVATION_DECISION_RUN_CANDIDATE);
                assert(decision.slot_to_run == WDC_BUNDLE_SLOT_B);
                assert(decision.probation);
                assert(metadata.slot_b.state == WDC_SLOT_RUNNING_PENDING);
                assert(metadata.candidate_boot_count == 1u);

                assert(wdc_activation_on_boot(&metadata, &policy, &decision) == WDC_OK);
                assert(decision.kind == WDC_ACTIVATION_DECISION_ROLLBACK_TO_LAST_GOOD);
                assert(decision.slot_to_run == WDC_BUNDLE_SLOT_A);
                assert(decision.candidate_slot == WDC_BUNDLE_SLOT_B);
                assert(metadata.active_slot == WDC_BUNDLE_SLOT_A);
                assert(metadata.slot_b.state == WDC_SLOT_FAILED);
                assert(metadata.candidate_fault_count == 1u);
                assert(metadata.last_failure_reason == WDC_ERR_NOT_SYNCHRONIZED);

                seed(&metadata.slot_b, WDC_SLOT_VERIFIED, 3u, 0xb3u);
                assert(wdc_bundle_metadata_seal(&metadata) == WDC_OK);
                assert(wdc_activation_prepare_pending(&metadata, WDC_BUNDLE_SLOT_B, &policy) == WDC_OK);
                assert(wdc_activation_on_boot(&metadata, &policy, &decision) == WDC_OK);
                assert(wdc_activation_confirm(&metadata, WDC_BUNDLE_SLOT_B, 1u) == WDC_OK);
                assert(metadata.active_slot == WDC_BUNDLE_SLOT_B);
                assert(metadata.last_good_slot == WDC_BUNDLE_SLOT_B);
                assert(metadata.slot_b.state == WDC_SLOT_CONFIRMED);
                assert(metadata.candidate_boot_count == 0u);
                assert(metadata.candidate_fault_count == 0u);

                assert(wdc_ota_write_metadata(&metadata) == WDC_OK);
                WdcBundleMetadataV1 loaded;
                assert(wdc_ota_read_metadata(&loaded) == WDC_OK);
                assert(loaded.active_slot == WDC_BUNDLE_SLOT_B);
                assert(loaded.last_good_slot == WDC_BUNDLE_SLOT_B);
                assert(loaded.slot_b.state == WDC_SLOT_CONFIRMED);
                return 0;
            }
            '''
        )

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            test_c = tmp_path / "r7_native_activation_smoke.c"
            test_c.write_text(program, encoding="utf-8")
            exe = tmp_path / "r7_native_activation_smoke"
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
                test_c,
            ]
            subprocess.run(
                ["gcc", "-std=c11", "-Wall", "-Wextra", "-Werror", *include_args, *map(str, sources), "-o", str(exe)],
                check=True,
            )
            subprocess.run([str(exe)], check=True)


if __name__ == "__main__":
    unittest.main()
