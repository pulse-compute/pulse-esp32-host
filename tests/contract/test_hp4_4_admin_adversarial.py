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
    qualify_admin_adversarial,
    qualify_admin_contract,
    qualify_admin_core,
    qualify_admin_recovery,
    qualify_admin_update,
)


ROOT = Path(__file__).resolve().parents[2]


def _model() -> dict:
    return qualify_admin_adversarial.load_model()


def _text(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


class HP44AdminAdversarialTests(unittest.TestCase):
    def test_identity_claim_and_hp4_closure_are_exact(self) -> None:
        model = _model()
        self.assertEqual(
            (
                model["schema"], model["pass"], model["phase"],
                model["status"], model["aggregate"],
            ),
            (
                "pulse.esp32.hp4_4-administration-adversarial-seal.v1",
                "HP4.4",
                "ADMINISTRATION_ADVERSARIAL_SEAL",
                "SEALED",
                "HOST_ADMINISTRATION_ADVERSARIAL_SEALED",
            ),
        )
        self.assertEqual(model["claim"], qualify_admin_adversarial.EXPECTED_CLAIM)
        for key in (
            "application_code_executed", "factory_host_writable",
            "host_firmware_ota_implemented", "network_transport_implemented",
            "partition_layout_changed", "physical_execution",
            "production_authenticator_implemented", "production_cryptography",
            "serial_driver_implemented", "target_build_executed",
        ):
            self.assertFalse(model["claim"][key])

    def test_matrix_counts_and_exhaustive_formulas_are_exact(self) -> None:
        matrix = _model()["matrix"]
        self.assertEqual(
            matrix["categories"],
            [
                {"case_count": count, "name": name}
                for name, count in qualify_admin_adversarial.EXPECTED_CATEGORIES
            ],
        )
        self.assertEqual(sum(item["case_count"] for item in matrix["categories"]), 3523)
        self.assertEqual(matrix["new_native_case_count"], 3523)
        self.assertEqual(matrix["inherited_native_case_count"], 41)
        self.assertEqual(matrix["aggregate_native_case_count"], 3564)
        self.assertIn("= 2362", matrix["safe_stream_formula"])
        self.assertIn("= 1030", matrix["journal_formula"])

    def test_sequence_exhaustion_is_rejected_before_acceptance_mutation(self) -> None:
        finding = _model()["finding"]
        self.assertEqual(finding["name"], "COMMAND_SEQUENCE_EXHAUSTION_REJECTED_PREACCEPT")
        self.assertEqual(finding["disposition"], "FIXED_AND_REGRESSION_LOCKED")
        self.assertEqual(finding["rejection"], "WDC_ADMIN_REJECTION_RATE_LIMITED")
        source = _text("firmware/components/wdc_admin/wdc_admin.c")
        guard = "if (core->next_command_sequence == UINT64_MAX)"
        stale = "if (request->command_sequence > core->next_command_sequence)"
        allocation = "core->next_command_sequence += 1u;"
        self.assertIn(guard, source)
        self.assertLess(source.index(stale), source.index(guard))
        self.assertLess(source.index(guard), source.index(allocation))
        self.assertIn("replay high-water cannot wrap", source)

    def test_authority_and_source_history_bind_the_exact_hp4_3_predecessor(self) -> None:
        model = _model()
        self.assertEqual(
            model["source_history"],
            qualify_admin_adversarial.EXPECTED_SOURCE_HISTORY,
        )
        validation = qualify_admin_adversarial._validate_source_history(model)
        self.assertEqual(validation["firmware"], qualify_admin_adversarial.hp5_5_source_authority.EXPECTED_FIRMWARE)
        self.assertEqual(validation["sealed_firmware"], qualify_admin_adversarial.EXPECTED_FIRMWARE)
        self.assertEqual(validation["current_successor"], "HP5.5")
        self.assertEqual(validation["native_sdk"], qualify_admin_adversarial.EXPECTED_NATIVE_SDK)
        self.assertEqual(
            validation["predecessor"]["archive_sha256"],
            "78407faf0981ac1d8d39f449136c613ee9aa4ca92ca168715ea0aed1b5f38eee",
        )
        self.assertEqual(len(model["authority_bindings"]), 9)

    def test_administration_remains_private_fixed_and_host_owned(self) -> None:
        qualify_admin_adversarial._validate_component_surface()
        production = "".join(
            _text(relative)
            for relative in (
                "firmware/components/wdc_admin/wdc_admin.c",
                "firmware/components/wdc_admin/wdc_admin_update.c",
                "firmware/components/wdc_admin/wdc_admin_recovery.c",
            )
        )
        for token in ("malloc(", "calloc(", "realloc(", "free("):
            self.assertNotIn(token, production)
        for relative in (
            "guest-sdk/c/include/wdc_guest.h",
            "guest-sdk/rust/wdc_guest/src/abi.rs",
            "native-sdk/c/include/pulse_extension.h",
        ):
            surface = _text(relative)
            self.assertNotIn("wdc_admin", surface)
            self.assertNotIn("WDC_ADMIN", surface)

    def test_native_adversarial_smoke_executes_every_new_case(self) -> None:
        native = qualify_admin_adversarial._run_native_smoke()
        self.assertEqual(native["status"], "PASS")
        self.assertEqual(native["case_count"], 3523)
        self.assertEqual(native["failures"], 0)
        self.assertEqual(native["safe_stream_cut_cases"], 2362)
        self.assertEqual(native["journal_interruption_cases"], 1030)
        self.assertEqual(len(native["categories"]), 11)
        self.assertTrue(native["sequence_wrap_prevented"])
        self.assertTrue(native["last_confirmed_preserved"])
        self.assertFalse(native["ambiguous_boot_authority"])

    def test_inherited_hp4_native_suite_remains_green(self) -> None:
        inherited = qualify_admin_adversarial._run_inherited_native()
        self.assertEqual(inherited["status"], "PASS")
        self.assertEqual(inherited["case_count"], 41)
        self.assertEqual(
            {phase: result["case_count"] for phase, result in inherited["phases"].items()},
            {"HP4.1": 14, "HP4.2": 15, "HP4.3": 12},
        )

    def test_model_tampering_fails_closed(self) -> None:
        model = _model()
        for mutator in (
            lambda value: value["claim"].update({"physical_execution": True}),
            lambda value: value["matrix"].update({"new_native_case_count": 3522}),
            lambda value: value["finding"].update({"rejection": "WDC_ADMIN_REJECTION_NONE"}),
            lambda value: value["verification"]["inherited_native_cases"].update({"HP4.3": 11}),
        ):
            changed = copy.deepcopy(model)
            mutator(changed)
            with self.assertRaises(qualify_admin_adversarial.QualificationError):
                qualify_admin_adversarial._validate_model(changed)

    def test_historical_contracts_accept_only_the_exact_hp4_4_successor(self) -> None:
        hp40 = qualify_admin_contract.validate(qualify_admin_contract.load_model())
        hp41 = qualify_admin_core.validate(qualify_admin_core.load_model())
        hp42 = qualify_admin_update.validate(qualify_admin_update.load_model())
        hp43 = qualify_admin_recovery.validate(qualify_admin_recovery.load_model())
        self.assertEqual(hp40["source_reconciliation"]["current_successor"], "HP5.5")
        self.assertEqual(hp41["source"]["current_successor"], "HP5.5")
        self.assertEqual(hp42["source"]["current_successor"], "HP5.5")
        self.assertEqual(hp43["source"]["current_successor"], "HP5.5")
        for module in (build_hx45_s3_aitrip, build_hx45_c6_xiao):
            seal = module.validate_sealed_sources()
            self.assertEqual(seal["firmware"], module.EXPECTED_HP55_FIRMWARE_SOURCE)
            self.assertEqual(seal["current_successor"], "HP5.5")
        for board_id in build_hp3_5_slot_hardware.BOARD_CONFIGS:
            seal = build_hp3_5_slot_hardware.validate_inputs(board_id)[3]
            self.assertEqual(seal["firmware"], build_hp3_5_slot_hardware.EXPECTED_HP55_FIRMWARE_SOURCE)
            self.assertEqual(seal["current_successor"], "HP5.5")

    def test_qualifier_emits_manifested_host_native_closure(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "qualification"
            report = qualify_admin_adversarial.qualify(out)
            self.assertEqual(
                (report["schema"], report["aggregate"], report["status"]),
                (
                    "pulse.esp32.hp4_4-administration-adversarial-qualification.v1",
                    "HOST_ADMINISTRATION_ADVERSARIAL_SEALED",
                    "PASS",
                ),
            )
            self.assertEqual(report["new_native_case_count"], 3523)
            self.assertEqual(report["inherited_native_case_count"], 41)
            self.assertEqual(report["aggregate_native_case_count"], 3564)
            self.assertTrue(report["hp4_closed"])
            self.assertEqual(report["next_pass"], "HP5")
            self.assertFalse(report["physical_result_created"])
            for name in (
                "administration-adversarial-seal-model.json",
                "native-adversarial-smoke.json",
                "inherited-native-suite.json",
                "evidence-manifest.json",
                "qualification-report.json",
            ):
                self.assertTrue((out / name).is_file())
            manifest = json.loads((out / "evidence-manifest.json").read_text())
            self.assertEqual(manifest["status"], "PASS")
            self.assertEqual(len(manifest["artifacts"]), 3)

    def test_docs_make_and_runner_expose_hp4_4_without_physical_claim(self) -> None:
        makefile = _text("Makefile")
        runner = _text("tools/run_contract_tests.py")
        testing = _text("docs/TESTING.md")
        status = _text("docs/STATUS.md")
        self.assertIn("check-hp4-4", makefile)
        self.assertIn("tools/qualify_admin_adversarial.py", makefile)
        self.assertIn("tests.contract.test_hp4_4_admin_adversarial", runner)
        self.assertIn("HP4.4 administration adversarial seal", testing)
        self.assertIn("HOST_ADMINISTRATION_ADVERSARIAL_SEALED", status)
        self.assertIn("HP5", status)
        self.assertNotIn("HP4_4_OUT_DIR", _text(".github/workflows/idf-family-matrix.yml"))


if __name__ == "__main__":
    unittest.main()
