from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from tools import qualify_admin_contract, qualify_admin_core


ROOT = Path(__file__).resolve().parents[2]
MODEL = ROOT / "specs/PULSE-ESP32-010-protected-administration-core.json"
DOC = ROOT / "docs/HP4_1_PROTECTED_ADMINISTRATION_CORE.md"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _model() -> dict:
    return json.loads(MODEL.read_text(encoding="utf-8"))


class HP41AdministrationCoreTests(unittest.TestCase):
    def test_identity_and_claim_are_narrow_and_exact(self) -> None:
        model = _model()
        self.assertEqual(
            (model["schema"], model["pass"], model["status"], model["aggregate"]),
            (
                "pulse.esp32.hp4_1-protected-administration-core.v1",
                "HP4.1",
                "IMPLEMENTED",
                "HOST_PROTECTED_ADMINISTRATION_CORE_IMPLEMENTED",
            ),
        )
        self.assertEqual(model["claim"], qualify_admin_core.EXPECTED_CLAIM)
        for key in [
            "host_update_transaction_implemented",
            "network_transport_implemented",
            "physical_execution",
            "production_authenticator_implemented",
            "production_cryptography",
            "recovery_transaction_implemented",
            "serial_driver_implemented",
        ]:
            self.assertFalse(model["claim"][key])

    def test_hp4_0_records_and_hp1_storage_budget_are_compile_time_authority(self) -> None:
        model = _model()
        self.assertEqual(
            model["record_layouts"],
            {
                "authenticated_entry_bytes": 128,
                "request_bytes": 112,
                "terminal_bytes": 64,
                "audit_bytes": 160,
            },
        )
        storage = model["fixed_storage"]
        self.assertEqual(storage["hp1_administration_reserve_bytes"], 12288)
        self.assertEqual(storage["native_host_observed_combined_bytes"], 9784)
        self.assertLessEqual(storage["native_host_observed_combined_bytes"], 12288)
        header = _text(ROOT / "firmware/components/wdc_admin/include/wdc_admin.h")
        source = _text(ROOT / "firmware/components/wdc_admin/wdc_admin.c")
        for token in [
            "WDC_ADMIN_AUTHENTICATED_ENTRY_BYTES 128u",
            "WDC_ADMIN_REQUEST_BYTES 112u",
            "WDC_ADMIN_TERMINAL_BYTES 64u",
            "WDC_ADMIN_AUDIT_RECORD_BYTES 160u",
            "WDC_ADMIN_FIXED_STORAGE_BUDGET_BYTES 12288u",
        ]:
            self.assertIn(token, header)
        self.assertIn("_Static_assert(sizeof(WdcAdminCore)", source)
        self.assertIn("sizeof(WdcAdminCore) + sizeof(WdcAdminSerialAdapter)", source)

    def test_authorizer_and_serial_normalizer_have_one_way_authority(self) -> None:
        model = _model()
        authorizer = model["interfaces"]["authorizer"]
        serial = model["serial_normalizer"]
        self.assertTrue(authorizer["attended_serial_required"])
        self.assertTrue(authorizer["transport_cannot_emit_entry"])
        self.assertEqual(authorizer["replaceable_callback"], "WdcAdminAuthorizeFn")
        self.assertEqual(serial["transport"], "SERIAL_PHYSICAL_V1")
        self.assertEqual(serial["byte_order"], "LITTLE_ENDIAN")
        self.assertEqual(serial["length_prefix_bytes"], 4)
        self.assertEqual(serial["frame_maximum_bytes_including_prefix"], 2048)
        serial_source = _text(
            ROOT / "firmware/components/wdc_admin/wdc_admin_serial.c"
        )
        self.assertNotIn("wdc_admin_authorization_begin(", serial_source)
        self.assertNotIn("wdc_admin_authorization_finish(", serial_source)
        self.assertNotIn("WdcAdminAuthenticatedEntry", serial_source)
        self.assertIn("wdc_admin_submit", serial_source)

    def test_replay_capacity_command_and_terminal_ownership_are_atomic(self) -> None:
        model = _model()
        replay = model["rate_and_replay"]
        command = model["command_authority"]
        self.assertEqual(replay["first_sequence"], 1)
        self.assertTrue(replay["strictly_consecutive"])
        self.assertTrue(replay["capacity_and_replay_commit_together"])
        self.assertFalse(replay["rejected_commands_advance_sequence"])
        self.assertEqual(replay["authorization_failure_limit"], 8)
        self.assertEqual(replay["authorization_window_ms"], 60000)
        self.assertEqual(replay["authorization_backoff_ms"], 30000)
        self.assertEqual(command["default_hp4_1_enabled_commands"], ["STATUS"])
        self.assertEqual(command["maximum_inflight"], 1)
        self.assertEqual(command["preaccept_rejections"], qualify_admin_core.EXPECTED_REJECTIONS)
        self.assertEqual(len(command["frozen_command_vocabulary"]), 8)
        terminal = model["terminal_and_audit"]
        self.assertTrue(terminal["exactly_one_terminal_per_accepted_command"])
        self.assertEqual(terminal["duplicate_terminal_status"], "WDC_ERR_INVALID_STATE")

    def test_component_is_firmware_linked_before_application_thread(self) -> None:
        component_cmake = _text(
            ROOT / "firmware/components/wdc_admin/CMakeLists.txt"
        )
        main_cmake = _text(ROOT / "firmware/main/CMakeLists.txt")
        app_main = _text(ROOT / "firmware/main/app_main.c")
        self.assertIn("wdc_control", component_cmake)
        self.assertIn("wdc_admin", main_cmake)
        self.assertLess(
            app_main.index("wdc_admin_link_anchor"),
            app_main.index("pthread_create"),
        )
        self.assertTrue(_model()["claim"]["firmware_component_linked"])

    def test_application_guest_event_extension_and_network_surfaces_cannot_enter(self) -> None:
        model = _model()
        for component in model["negative_surface"][
            "application_components_with_no_wdc_admin_dependency"
        ]:
            cmake = _text(
                ROOT / "firmware/components" / component / "CMakeLists.txt"
            )
            self.assertNotIn("wdc_admin", cmake)
        for path in [
            ROOT / "firmware/components/wdc_abi/include/wdc_abi.h",
            ROOT / "guest-sdk/c/include/wdc_guest.h",
            ROOT / "guest-sdk/rust/wdc_guest/src/abi.rs",
            ROOT / "native-sdk/c/include/pulse_extension.h",
        ]:
            text = _text(path)
            self.assertNotIn("WDC_ADMIN", text)
            self.assertNotIn("wdc_admin", text)
            self.assertNotIn("pulse_admin", text)
        source = _text(ROOT / "firmware/components/wdc_admin/wdc_admin.c")
        serial = _text(
            ROOT / "firmware/components/wdc_admin/wdc_admin_serial.c"
        )
        for token in model["negative_surface"]["no_dynamic_allocation_tokens"]:
            self.assertNotIn(token, source)
            self.assertNotIn(token, serial)

    def test_replaceable_artifact_verifier_exists_without_crypto_claim(self) -> None:
        model = _model()
        verifier = model["interfaces"]["artifact_verifier"]
        self.assertEqual(verifier["replaceable_callback"], "WdcAdminArtifactVerifyFn")
        self.assertTrue(verifier["fail_closed_before_hp4_2"])
        self.assertFalse(verifier["production_cryptography_claim"])
        header = _text(ROOT / "firmware/components/wdc_admin/include/wdc_admin.h")
        source = _text(ROOT / "firmware/components/wdc_admin/wdc_admin.c")
        self.assertIn("WdcAdminArtifactVerifyFn", header)
        self.assertIn("wdc_admin_verify_artifact", header)
        self.assertIn("core->mode != WDC_ADMIN_MODE_UPDATE", source)

    def test_native_smoke_executes_all_core_cases(self) -> None:
        validation = qualify_admin_core.validate(_model())
        native = validation["native"]
        self.assertEqual(native["status"], "PASS")
        self.assertEqual(native["case_count"], 14)
        self.assertEqual(native["failures"], 0)
        self.assertEqual(native["rejections"], 10)
        self.assertEqual(native["core_static_bytes"], 7712)
        self.assertEqual(native["serial_static_bytes"], 2072)
        self.assertEqual(native["fixed_storage_bytes"], 9784)
        self.assertEqual(
            {case["name"] for case in native["cases"]},
            {
                "fixed-layout-and-storage-budget",
                "attended-replaceable-authority",
                "authorization-window-and-backoff",
                "preaccept-rejection-does-not-own-capacity",
                "application-pressure-cannot-consume-admin",
                "first-terminal-write-and-one-response",
                "serial-fragment-normalization",
                "serial-bytes-cannot-self-authorize",
                "serial-frame-bounds-reset",
                "inflight-deadline-terminal",
                "queued-expiry-still-owns-terminal",
                "authorization-epoch-high-water",
                "audit-overwrite-latches-loss",
                "replaceable-verifier-fails-closed-before-hp4-2",
            },
        )

    def test_model_tampering_fails_closed(self) -> None:
        model = _model()
        widened = copy.deepcopy(model)
        widened["claim"]["production_cryptography"] = True
        with self.assertRaises(qualify_admin_core.QualificationError):
            qualify_admin_core._validate_model(widened)
        update_enabled = copy.deepcopy(model)
        update_enabled["command_authority"]["default_hp4_1_enabled_commands"].append(
            "BEGIN_UPDATE"
        )
        with self.assertRaises(qualify_admin_core.QualificationError):
            qualify_admin_core._validate_model(update_enabled)
        widened_frame = copy.deepcopy(model)
        widened_frame["serial_normalizer"]["frame_maximum_bytes_including_prefix"] = 4096
        with self.assertRaises(qualify_admin_core.QualificationError):
            qualify_admin_core._validate_model(widened_frame)

    def test_hp4_0_history_remains_verifiable_through_successor(self) -> None:
        hp4_model = qualify_admin_contract.load_model()
        validation = qualify_admin_contract.validate(hp4_model)
        source = validation["source_reconciliation"]
        self.assertEqual(source["firmware"], qualify_admin_contract.EXPECTED_FIRMWARE)
        self.assertEqual(source["current_firmware"], qualify_admin_contract.hp5_5_source_authority.EXPECTED_FIRMWARE)
        self.assertEqual(source["current_successor"], "HP5.5")
        self.assertEqual(source["native_sdk"], qualify_admin_contract.EXPECTED_NATIVE_SDK)

    def test_qualifier_emits_manifested_host_native_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "qualification"
            report = qualify_admin_core.qualify(out)
            self.assertEqual(
                (
                    report["schema"],
                    report["aggregate"],
                    report["classification"],
                    report["status"],
                ),
                (
                    "pulse.esp32.hp4_1-admin-core-qualification.v1",
                    "HOST_PROTECTED_ADMINISTRATION_CORE_IMPLEMENTED",
                    "HOST_NATIVE_CORE_ONLY",
                    "PASS",
                ),
            )
            self.assertEqual(report["native_case_count"], 14)
            self.assertEqual(report["combined_fixed_storage_bytes"], 9784)
            self.assertFalse(report["application_code_executed"])
            self.assertFalse(report["target_build_executed"])
            self.assertFalse(report["physical_result_created"])
            self.assertFalse(report["production_cryptography"])
            for name in [
                "protected-administration-core-model.json",
                "native-core-smoke.json",
                "evidence-manifest.json",
                "qualification-report.json",
            ]:
                self.assertTrue((out / name).is_file())

    def test_docs_make_runner_and_gate_expose_hp4_1_without_hardware(self) -> None:
        self.assertTrue(DOC.is_file())
        makefile = _text(ROOT / "Makefile")
        runner = _text(ROOT / "tools/run_contract_tests.py")
        docs_checker = _text(ROOT / "tools/check_docs.py")
        workflow = _text(ROOT / ".github/workflows/idf-family-matrix.yml")
        self.assertIn("check-hp4-1", makefile)
        self.assertIn("tests.contract.test_hp4_1_administration_core", makefile)
        self.assertIn("administration-core-qualify", makefile)
        self.assertIn("tools/qualify_admin_core.py", makefile)
        self.assertIn("tests.contract.test_hp4_1_administration_core", runner)
        self.assertIn("docs/HP4_1_PROTECTED_ADMINISTRATION_CORE.md", docs_checker)
        self.assertIn("specs/PULSE-ESP32-010-protected-administration-core.json", docs_checker)
        self.assertNotIn("check-hp4-1", workflow)


if __name__ == "__main__":
    unittest.main()
