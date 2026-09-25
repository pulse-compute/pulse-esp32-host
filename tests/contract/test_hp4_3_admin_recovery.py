from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from tools import (
    build_hp3_5_slot_hardware,
    build_hx45_c6_xiao,
    build_hx45_s3_aitrip,
    qualify_admin_contract,
    qualify_admin_core,
    qualify_admin_recovery,
    qualify_admin_update,
)


ROOT = Path(__file__).resolve().parents[2]


def _model() -> dict:
    return qualify_admin_recovery.load_model()


def _text(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


class HP43AdminRecoveryTests(unittest.TestCase):
    def test_identity_and_claim_are_narrow_and_exact(self) -> None:
        model = _model()
        self.assertEqual(
            (model["schema"], model["pass"], model["status"], model["aggregate"]),
            (
                "pulse.esp32.hp4_3-host-only-recovery.v1",
                "HP4.3",
                "IMPLEMENTED",
                "HOST_ONLY_RECOVERY_IMPLEMENTED",
            ),
        )
        self.assertEqual(model["claim"], qualify_admin_recovery.EXPECTED_CLAIM)
        self.assertFalse(model["claim"]["application_code_executed"])
        self.assertFalse(model["claim"]["factory_host_writable"])
        self.assertFalse(model["claim"]["physical_execution"])
        self.assertFalse(model["claim"]["production_cryptography"])

    def test_no_viable_and_administrative_entry_are_both_host_owned(self) -> None:
        entry = _model()["entry"]
        self.assertIn("HP3 BOOT_RECOVERY", entry["automatic"])
        self.assertIn("metadata active/last-good NONE", entry["automatic"])
        self.assertIn("positive guest and native-refinement", entry["administrative"])
        self.assertTrue(entry["no_reboot_loop"])
        source = _text("firmware/components/wdc_admin/wdc_admin_recovery.c")
        self.assertIn("boot_recovery_evidence_valid", source)
        self.assertIn("WDC_ADMIN_AUDIT_RECOVERY_ENTRY", source)
        self.assertLess(source.index("quiesce_and_unload"), source.index("WDC_ADMIN_MODE_RECOVERY"))

    def test_command_status_and_resource_bounds_are_exact(self) -> None:
        model = _model()
        self.assertEqual(
            model["command_authority"]["enabled_commands"],
            qualify_admin_recovery.EXPECTED_COMMANDS,
        )
        self.assertEqual(model["command_authority"]["enabled_mask"], 255)
        self.assertEqual(model["host_only"]["status_response_bytes"], 64)
        self.assertEqual(model["host_only"]["recovery_reserve_bytes"], 16384)
        self.assertEqual(model["verification"]["working_buffer_bytes"], 65536)
        header = _text("firmware/components/wdc_admin/include/wdc_admin_recovery.h")
        admin = _text("firmware/components/wdc_admin/include/wdc_admin.h")
        self.assertIn("#define WDC_ADMIN_HP43_COMMAND_MASK WDC_ADMIN_COMMAND_MASK_ALL", admin)
        self.assertIn("#define WDC_ADMIN_RECOVERY_STATUS_BYTES 64u", header)
        self.assertIn("#define WDC_ADMIN_RECOVERY_RESERVE_BYTES 16384u", header)

    def test_recovery_update_failures_return_to_recovery(self) -> None:
        model = _model()
        self.assertEqual(
            model["candidate_staging"]["failure_mode"],
            "RECOVERY for every recovery-origin abort, timeout, resource denial, stream failure, verifier denial, or journal failure before handoff",
        )
        source = _text("firmware/components/wdc_admin/wdc_admin_update.c")
        header = _text("firmware/components/wdc_admin/include/wdc_admin_update.h")
        self.assertIn("recovery_origin", header)
        self.assertIn("static WdcAdminMode idle_mode", source)
        self.assertIn("wdc_admin_update_set_idle_mode", source)
        self.assertIn("WDC_ADMIN_MODE_RECOVERY", source)

    def test_safe_reboot_is_read_only_and_returns_to_hp3(self) -> None:
        reboot = _model()["reboot"]
        self.assertEqual(reboot["handoff_owner"], "HP3 boot selection and probation")
        self.assertFalse(reboot["application_code_launched_during_validation"])
        app_slots = _text("firmware/components/wdc_app_slots/wdc_app_slots.c")
        recovery = _text("firmware/components/wdc_admin/wdc_admin_recovery.c")
        self.assertIn("wdc_app_slots_validate_reboot_candidate", app_slots)
        self.assertIn("wdc_app_slots_validate_reboot_candidate", recovery)
        function = app_slots[app_slots.index("int32_t wdc_app_slots_validate_reboot_candidate"):]
        function = function[:function.index("int32_t wdc_app_slots_boot")]
        self.assertNotIn("commit_metadata", function)
        self.assertNotIn("wdc_ota_write_metadata", function)

    def test_component_is_private_linked_and_fixed_storage(self) -> None:
        recovery = _text("firmware/components/wdc_admin/wdc_admin_recovery.c")
        cmake = _text("firmware/components/wdc_admin/CMakeLists.txt")
        app_main = _text("firmware/main/app_main.c")
        self.assertIn("wdc_admin_recovery.c", cmake)
        self.assertIn("wdc_admin_recovery_link_anchor", app_main)
        self.assertLess(app_main.index("wdc_admin_recovery_link_anchor"), app_main.index("pthread_create"))
        for token in ("malloc(", "calloc(", "realloc(", "free("):
            self.assertNotIn(token, recovery)
        for relative in (
            "guest-sdk/c/include/wdc_guest.h",
            "guest-sdk/rust/wdc_guest/src/abi.rs",
            "native-sdk/c/include/pulse_extension.h",
        ):
            text = _text(relative)
            self.assertNotIn("wdc_admin", text)
            self.assertNotIn("WDC_ADMIN", text)

    def test_native_smoke_executes_all_recovery_cases(self) -> None:
        native = qualify_admin_recovery._run_native_smoke()
        self.assertEqual(native["status"], "PASS")
        self.assertEqual(native["case_count"], 12)
        self.assertEqual(native["failures"], 0)
        self.assertEqual(native["engine_static_bytes"], 3112)
        self.assertEqual(native["recovery_status_bytes"], 64)
        self.assertEqual(native["recovery_reserve_bytes"], 16384)
        self.assertEqual(len(native["cases"]), 12)

    def test_model_tampering_fails_closed(self) -> None:
        model = _model()
        widened = copy.deepcopy(model)
        widened["claim"]["production_cryptography"] = True
        with self.assertRaises(qualify_admin_recovery.QualificationError):
            qualify_admin_recovery._validate_model(widened)
        reboot = copy.deepcopy(model)
        reboot["reboot"]["application_code_launched_during_validation"] = True
        with self.assertRaises(qualify_admin_recovery.QualificationError):
            qualify_admin_recovery._validate_model(reboot)
        reserve = copy.deepcopy(model)
        reserve["host_only"]["recovery_reserve_bytes"] += 1
        with self.assertRaises(qualify_admin_recovery.QualificationError):
            qualify_admin_recovery._validate_model(reserve)

    def test_historical_seals_accept_exact_hp4_3_successor(self) -> None:
        hp40 = qualify_admin_contract.validate(qualify_admin_contract.load_model())
        hp41 = qualify_admin_core.validate(qualify_admin_core.load_model())
        hp42 = qualify_admin_update.validate(qualify_admin_update.load_model())
        self.assertEqual(hp40["source_reconciliation"]["current_successor"], "HP5.5")
        self.assertEqual(hp41["source"]["current_successor"], "HP5.5")
        self.assertEqual(hp42["source"]["current_successor"], "HP5.5")
        for module in (build_hx45_s3_aitrip, build_hx45_c6_xiao):
            seal = module.validate_sealed_sources()
            self.assertEqual(seal["firmware"], module.EXPECTED_HP55_FIRMWARE_SOURCE)
            self.assertEqual(seal["current_successor"], "HP5.5")
        for board_id in build_hp3_5_slot_hardware.BOARD_CONFIGS:
            seal = build_hp3_5_slot_hardware.validate_inputs(board_id)[3]
            self.assertEqual(seal["firmware"], build_hp3_5_slot_hardware.EXPECTED_HP55_FIRMWARE_SOURCE)
            self.assertEqual(seal["current_successor"], "HP5.5")

    def test_qualifier_emits_manifested_host_native_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "qualification"
            report = qualify_admin_recovery.qualify(out)
            self.assertEqual(
                (report["schema"], report["aggregate"], report["classification"], report["status"]),
                (
                    "pulse.esp32.hp4_3-admin-recovery-qualification.v1",
                    "HOST_ONLY_RECOVERY_IMPLEMENTED",
                    "HOST_NATIVE_RECOVERY_TRANSACTION_ONLY",
                    "PASS",
                ),
            )
            self.assertEqual(report["native_case_count"], 12)
            self.assertEqual(report["engine_static_bytes"], 3112)
            self.assertFalse(report["target_build_executed"])
            self.assertFalse(report["physical_result_created"])
            for name in (
                "host-only-recovery-model.json",
                "native-host-only-recovery-smoke.json",
                "evidence-manifest.json",
                "qualification-report.json",
            ):
                self.assertTrue((out / name).is_file())
            manifest = json.loads((out / "evidence-manifest.json").read_text())
            self.assertEqual(manifest["status"], "PASS")

    def test_docs_make_runner_and_gate_expose_hp4_3_without_hardware(self) -> None:
        makefile = _text("Makefile")
        runner = _text("tools/run_contract_tests.py")
        testing = _text("docs/TESTING.md")
        status = _text("docs/STATUS.md")
        self.assertIn("check-hp4-3", makefile)
        self.assertIn("tools/qualify_admin_recovery.py", makefile)
        self.assertIn("tests.contract.test_hp4_3_admin_recovery", runner)
        self.assertIn("HP4.3 host-only recovery", testing)
        self.assertIn("HOST_ONLY_RECOVERY_IMPLEMENTED", status)
        self.assertNotIn("HP4_3_OUT_DIR", _text(".github/workflows/idf-family-matrix.yml"))


if __name__ == "__main__":
    unittest.main()
