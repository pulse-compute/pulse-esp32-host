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
    qualify_admin_update,
)


ROOT = Path(__file__).resolve().parents[2]
MODEL = ROOT / "specs/PULSE-ESP32-011-exclusive-update-transaction.json"
DOC = ROOT / "docs/HP4_2_EXCLUSIVE_UPDATE_TRANSACTION.md"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _model() -> dict:
    return json.loads(MODEL.read_text(encoding="utf-8"))


class HP42AdminUpdateTests(unittest.TestCase):
    def test_identity_and_claim_are_narrow_and_exact(self) -> None:
        model = _model()
        self.assertEqual(
            (model["schema"], model["pass"], model["status"], model["aggregate"]),
            (
                "pulse.esp32.hp4_2-exclusive-update-transaction.v1",
                "HP4.2",
                "IMPLEMENTED",
                "HOST_EXCLUSIVE_UPDATE_TRANSACTION_IMPLEMENTED",
            ),
        )
        self.assertEqual(model["claim"], qualify_admin_update.EXPECTED_CLAIM)
        self.assertTrue(model["claim"]["host_update_transaction_implemented"])
        for key in [
            "host_firmware_ota_implemented",
            "network_transport_implemented",
            "partition_layout_changed",
            "physical_execution",
            "production_authenticator_implemented",
            "production_cryptography",
            "recovery_transaction_implemented",
            "serial_driver_implemented",
            "target_build_executed",
        ]:
            self.assertFalse(model["claim"][key])

    def test_command_boundary_enables_update_but_not_hp4_3(self) -> None:
        command = _model()["command_authority"]
        self.assertEqual(command["enabled_commands"], qualify_admin_update.EXPECTED_COMMANDS)
        self.assertEqual(command["enabled_mask"], 0x5F)
        self.assertEqual(
            command["hp4_3_commands_still_unsupported"],
            ["ENTER_RECOVERY", "REBOOT"],
        )
        header = _text(ROOT / "firmware/components/wdc_admin/include/wdc_admin.h")
        source = _text(ROOT / "firmware/components/wdc_admin/wdc_admin.c")
        self.assertIn("WDC_ADMIN_HP42_COMMAND_MASK", header)
        self.assertIn("request_update_shape_valid", source)
        self.assertIn("expected_total_bytes", source)
        self.assertIn("artifact_sha256", source)

    def test_exclusive_c6_admission_is_fixed_by_hp1(self) -> None:
        resource = _model()["resource_admission"]
        self.assertEqual(resource["fixed_control_reserve_bytes"], 98304)
        self.assertEqual(resource["exclusive_update_working_bytes"], 65536)
        self.assertEqual(resource["exclusive_required_internal_free_bytes"], 163840)
        self.assertEqual(resource["update_largest_allocation_bytes"], 65536)
        self.assertEqual(resource["largest_block_floor_bytes"], 32768)
        self.assertEqual(resource["required_largest_block_bytes"], 98304)
        self.assertFalse(resource["user_controlled_sizes_or_priorities"])
        header = _text(ROOT / "firmware/components/wdc_control/include/wdc_control.h")
        source = _text(ROOT / "firmware/components/wdc_control/wdc_control.c")
        self.assertIn("wdc_control_admit_exclusive_update", header)
        for token in [
            "fixed_control_reserve_bytes",
            "exclusive_update_working_bytes",
            "update_largest_allocation_bytes",
            "largest_block_floor_bytes",
        ]:
            self.assertIn(token, source)

    def test_quiesce_unload_precedes_admission_and_inactive_staging(self) -> None:
        source = _text(ROOT / "firmware/components/wdc_admin/wdc_admin_update.c")
        self.assertLess(source.index("quiesce_and_unload("), source.index("heap_snapshot_after_unload("))
        self.assertLess(source.index("heap_snapshot_after_unload("), source.index("wdc_control_admit_exclusive_update("))
        self.assertLess(source.index("wdc_control_admit_exclusive_update("), source.index("wdc_app_slots_stage_begin("))
        self.assertIn("wdc_app_slots_inactive_slot", source)
        self.assertIn("guest_loaded_after == 0u", source)
        self.assertIn("native_refinements_loaded_after == 0u", source)
        self.assertNotIn("WDC_ADMIN_MODE_RECOVERY,\n                             WDC_ADMIN_MODE_UPDATE", source)

    def test_streaming_and_transaction_bounds_are_exact(self) -> None:
        self.assertEqual(
            _model()["streaming"],
            {
                "expected_total_must_match": True,
                "maximum_chunk_bytes": 1024,
                "rate_bytes_per_window": 65536,
                "rate_chunks_per_window": 64,
                "rate_window_ms": 1000,
                "sequential_only": True,
                "stream_idle_deadline_ms": 30000,
                "transaction_deadline_ms": 900000,
                "working_buffer_bytes": 65536,
            },
        )
        header = _text(ROOT / "firmware/components/wdc_admin/include/wdc_admin_update.h")
        for token in [
            "WDC_ADMIN_UPDATE_WORKING_BYTES 65536u",
            "WDC_ADMIN_UPDATE_MAX_CHUNK_BYTES 1024u",
            "WDC_ADMIN_UPDATE_RATE_CHUNKS_PER_WINDOW 64u",
            "WDC_ADMIN_UPDATE_RATE_BYTES_PER_WINDOW 65536u",
            "WDC_ADMIN_UPDATE_STREAM_IDLE_DEADLINE_MS 30000u",
            "WDC_ADMIN_UPDATE_TRANSACTION_DEADLINE_MS 900000u",
        ]:
            self.assertIn(token, header)

    def test_complete_verification_and_durable_trial_order_are_explicit(self) -> None:
        model = _model()
        verification = model["verification"]
        self.assertEqual(verification["metadata_commits_on_success"], 3)
        self.assertTrue(verification["durable_trial_readback_required"])
        self.assertTrue(verification["activation_rechecks_authorization"])
        self.assertTrue(verification["activation_rechecks_replaceable_verifier"])
        source = _text(ROOT / "firmware/components/wdc_admin/wdc_admin_update.c")
        finish = source[
            source.index("static int32_t finish_update"):
            source.index("static bool durable_trial_matches")
        ]
        self.assertLess(finish.index("wdc_app_slots_stage_finish("), finish.index("verify_candidate("))
        self.assertIn("wdc_admin_verify_artifact(", source)
        activate = source[
            source.index("static int32_t activate_trial"):
            source.index("static int32_t explicit_abort")
        ]
        self.assertLess(activate.index("verify_candidate("), activate.index("wdc_app_slots_mark_trial("))
        self.assertLess(activate.index("wdc_app_slots_mark_trial("), activate.index("wdc_ota_read_metadata("))
        self.assertLess(activate.index("wdc_ota_read_metadata("), activate.index("WDC_ADMIN_MODE_REBOOT_HANDOFF"))

    def test_failure_and_abort_preserve_boot_authority(self) -> None:
        failure = _model()["failure_authority"]
        self.assertTrue(failure["inactive_slot_only"])
        self.assertEqual(failure["failure_mode"], "NORMAL")
        self.assertEqual(
            failure["boot_authority_before_trial_commit"],
            "active slot, last-good slot, and exact last-confirmed record remain unchanged",
        )
        self.assertFalse(failure["factory_host_partition_writable"])
        self.assertFalse(failure["application_code_launched"])
        source = _text(ROOT / "firmware/components/wdc_admin/wdc_admin_update.c")
        self.assertIn("authority_preserved", source)
        self.assertIn("wdc_app_slots_stage_abort", source)
        self.assertIn("WDC_ADMIN_MODE_NORMAL", source)

    def test_component_is_linked_and_private_without_dynamic_allocation(self) -> None:
        cmake = _text(ROOT / "firmware/components/wdc_admin/CMakeLists.txt")
        app_main = _text(ROOT / "firmware/main/app_main.c")
        source = _text(ROOT / "firmware/components/wdc_admin/wdc_admin_update.c")
        self.assertIn("wdc_admin_update.c", cmake)
        for dependency in [
            "wdc_activation",
            "wdc_app_slots",
            "wdc_bundle",
            "wdc_control",
            "wdc_host_identity",
            "wdc_ota",
        ]:
            self.assertIn(dependency, cmake)
        self.assertLess(app_main.index("wdc_admin_update_link_anchor"), app_main.index("pthread_create"))
        for token in ["malloc(", "calloc(", "realloc(", "free("]:
            self.assertNotIn(token, source)
        for component in ["wdc_app", "wdc_events", "wdc_extension", "wdc_net"]:
            self.assertNotIn(
                "wdc_admin",
                _text(ROOT / "firmware/components" / component / "CMakeLists.txt"),
            )

    def test_native_smoke_executes_all_update_cases(self) -> None:
        native = qualify_admin_update.validate(_model())["native"]
        self.assertEqual(native["status"], "PASS")
        self.assertEqual(native["case_count"], 15)
        self.assertEqual(native["failures"], 0)
        self.assertEqual(native["engine_static_bytes"], 3096)
        self.assertEqual(native["working_bytes"], 65536)
        self.assertEqual(native["chunk_bytes"], 1024)
        self.assertEqual(
            {case["name"] for case in native["cases"]},
            {
                "fixed-c6-exclusive-admission",
                "positive-quiesce-unload-before-update",
                "active-slot-never-staged",
                "quiesce-failure-preserves-authority",
                "exclusive-free-byte-denial",
                "exclusive-largest-block-denial",
                "chunk-bound-rejects-before-replay",
                "explicit-abort-preserves-authority",
                "stream-idle-timeout-aborts",
                "bounded-stream-rate-window",
                "complete-artifact-hash-mismatch-aborts",
                "security-floor-rollback-aborts",
                "replaceable-verifier-denial-aborts",
                "trial-journal-interruption-preserves-boot",
                "verified-trial-durable-reboot-handoff",
            },
        )

    def test_model_tampering_fails_closed(self) -> None:
        model = _model()
        widened = copy.deepcopy(model)
        widened["claim"]["production_cryptography"] = True
        with self.assertRaises(qualify_admin_update.QualificationError):
            qualify_admin_update._validate_model(widened)
        recovery = copy.deepcopy(model)
        recovery["command_authority"]["enabled_commands"].append("ENTER_RECOVERY")
        with self.assertRaises(qualify_admin_update.QualificationError):
            qualify_admin_update._validate_model(recovery)
        smaller_gate = copy.deepcopy(model)
        smaller_gate["resource_admission"]["exclusive_required_internal_free_bytes"] -= 1
        with self.assertRaises(qualify_admin_update.QualificationError):
            qualify_admin_update._validate_model(smaller_gate)

    def test_historical_contracts_and_hardware_seals_accept_exact_successor(self) -> None:
        hp40 = qualify_admin_contract.validate(qualify_admin_contract.load_model())
        self.assertEqual(hp40["source_reconciliation"]["current_successor"], "HP5.5")
        hp41 = qualify_admin_core.validate(qualify_admin_core.load_model())
        self.assertEqual(hp41["source"]["current_successor"], "HP5.5")
        for module in (build_hx45_s3_aitrip, build_hx45_c6_xiao):
            seal = module.validate_sealed_sources()
            self.assertEqual(seal["firmware"], module.EXPECTED_HP55_FIRMWARE_SOURCE)
            self.assertEqual(seal["current_successor"], "HP5.5")
        for board_id in build_hp3_5_slot_hardware.BOARD_CONFIGS:
            seal = build_hp3_5_slot_hardware.validate_inputs(board_id)[3]
            self.assertEqual(seal["current_successor"], "HP5.5")

    def test_qualifier_emits_manifested_host_native_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "qualification"
            report = qualify_admin_update.qualify(out)
            self.assertEqual(
                (
                    report["schema"],
                    report["aggregate"],
                    report["classification"],
                    report["status"],
                ),
                (
                    "pulse.esp32.hp4_2-admin-update-qualification.v1",
                    "HOST_EXCLUSIVE_UPDATE_TRANSACTION_IMPLEMENTED",
                    "HOST_NATIVE_UPDATE_TRANSACTION_ONLY",
                    "PASS",
                ),
            )
            self.assertEqual(report["native_case_count"], 15)
            self.assertEqual(report["engine_static_bytes"], 3096)
            self.assertEqual(report["exclusive_update_working_bytes"], 65536)
            self.assertEqual(report["maximum_stream_chunk_bytes"], 1024)
            self.assertFalse(report["target_build_executed"])
            self.assertFalse(report["physical_result_created"])
            self.assertFalse(report["production_cryptography"])
            self.assertFalse(report["recovery_transaction_implemented"])
            for name in [
                "exclusive-update-transaction-model.json",
                "native-update-transaction-smoke.json",
                "evidence-manifest.json",
                "qualification-report.json",
            ]:
                self.assertTrue((out / name).is_file())

    def test_docs_make_runner_and_gate_expose_hp4_2_without_hardware(self) -> None:
        self.assertTrue(DOC.is_file())
        makefile = _text(ROOT / "Makefile")
        runner = _text(ROOT / "tools/run_contract_tests.py")
        docs_checker = _text(ROOT / "tools/check_docs.py")
        workflow = _text(ROOT / ".github/workflows/idf-family-matrix.yml")
        self.assertIn("check-hp4-2", makefile)
        self.assertIn("tests.contract.test_hp4_2_admin_update", makefile)
        self.assertIn("administration-update-qualify", makefile)
        self.assertIn("tools/qualify_admin_update.py", makefile)
        self.assertIn("tests.contract.test_hp4_2_admin_update", runner)
        self.assertIn("docs/HP4_2_EXCLUSIVE_UPDATE_TRANSACTION.md", docs_checker)
        self.assertIn("specs/PULSE-ESP32-011-exclusive-update-transaction.json", docs_checker)
        self.assertNotIn("check-hp4-2", workflow)


if __name__ == "__main__":
    unittest.main()
