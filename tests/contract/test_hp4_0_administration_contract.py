from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from tools import qualify_admin_contract


ROOT = Path(__file__).resolve().parents[2]
MODEL = ROOT / "specs/PULSE-ESP32-009-protected-administration.json"
DOC = ROOT / "docs/HP4_0_PROTECTED_ADMINISTRATION_CONTRACT.md"
ADR = ROOT / "docs/adr/0014-protected-host-administration-authority.md"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _model() -> dict:
    return json.loads(MODEL.read_text(encoding="utf-8"))


def _assert_layout(
    case: unittest.TestCase,
    layout: list[dict],
    expected: list[tuple[int, int, str]],
    total_bytes: int,
) -> None:
    observed = [(entry["offset"], entry["size"], entry["field"]) for entry in layout]
    case.assertEqual(observed, expected)
    occupied: set[int] = set()
    for offset, size, _field in expected:
        span = set(range(offset, offset + size))
        case.assertFalse(occupied & span)
        occupied |= span
    case.assertEqual(occupied, set(range(total_bytes)))


class HP40AdministrationContractTests(unittest.TestCase):
    def test_identity_claim_and_authorized_source_reconciliation_are_exact(self) -> None:
        model = _model()
        self.assertEqual(
            (model["schema"], model["pass"], model["status"]),
            ("pulse.esp32.hp4_0-protected-administration-contract.v1", "HP4.0", "FROZEN"),
        )
        self.assertEqual(
            model["claim"],
            {
                "aggregate": "HOST_ADMINISTRATION_CONTRACT_FROZEN",
                "application_code_executed": False,
                "classification": "HOST_MODEL_ONLY",
                "firmware_implemented": False,
                "network_transport_implemented": False,
                "physical_execution": False,
                "production_cryptography": False,
                "serial_driver_implemented": False,
            },
        )
        reconciliation = model["source_reconciliation"]
        self.assertEqual(
            (
                reconciliation["predecessor_v8_archive_sha256"],
                reconciliation["predecessor_v8_manifest_file_count"],
                reconciliation["predecessor_v8_manifest_payload_bytes"],
            ),
            (
                "7be285c47d268721e4a419074d8a551a7db59968bed8738a8ab7ee0c979c4a9a",
                438,
                3022784,
            ),
        )
        self.assertEqual(
            (
                reconciliation["accepted_base_archive_sha256"],
                reconciliation["accepted_base_manifest_file_count"],
                reconciliation["accepted_base_manifest_payload_bytes"],
                reconciliation["classification"],
            ),
            (
                "928b74de36f5d25d48caecb08a3412314b02f0aece7c804046b5b7942466d00f",
                440,
                3033334,
                "AUTHORIZED_HP3_5_CLOSURE_SEAL_SUCCESSOR",
            ),
        )
        validation = qualify_admin_contract.validate(model)
        self.assertEqual(validation["source_reconciliation"]["firmware"], qualify_admin_contract.EXPECTED_FIRMWARE)
        self.assertEqual(validation["source_reconciliation"]["native_sdk"], qualify_admin_contract.EXPECTED_NATIVE_SDK)

    def test_authenticated_entry_request_terminal_and_audit_layouts_are_exact(self) -> None:
        model = _model()
        _assert_layout(
            self,
            model["session_contract"]["authenticated_entry_layout"],
            [
                (0, 4, "struct_size"),
                (4, 2, "version_major"),
                (6, 2, "version_minor"),
                (8, 4, "transport_kind"),
                (12, 4, "authorization_method"),
                (16, 4, "privilege_mask"),
                (20, 4, "flags"),
                (24, 8, "authorization_epoch"),
                (32, 8, "issued_monotonic_ms"),
                (40, 8, "expires_monotonic_ms"),
                (48, 8, "session_nonce"),
                (56, 32, "principal_sha256"),
                (88, 32, "channel_binding_sha256"),
                (120, 8, "reserved"),
            ],
            128,
        )
        _assert_layout(
            self,
            model["request_record"]["layout"],
            [
                (0, 4, "struct_size"),
                (4, 2, "version_major"),
                (6, 2, "version_minor"),
                (8, 4, "command"),
                (12, 4, "flags"),
                (16, 4, "payload_bytes"),
                (20, 4, "slot"),
                (24, 4, "expected_total_bytes"),
                (28, 4, "reserved0"),
                (32, 8, "request_id"),
                (40, 8, "deadline_ms"),
                (48, 8, "authorization_epoch"),
                (56, 8, "session_nonce"),
                (64, 8, "command_sequence"),
                (72, 32, "artifact_sha256"),
                (104, 8, "reserved1"),
            ],
            112,
        )
        self.assertEqual(model["command_contract"]["terminal_record_bytes"], 64)
        self.assertEqual(model["audit"]["record_bytes"], 160)
        validation = qualify_admin_contract.validate(model)
        self.assertEqual(
            validation["layouts"],
            {"authenticated_entry": 14, "request": 16, "terminal": 14, "audit": 21},
        )

    def test_session_replay_capacity_and_terminal_ownership_are_fail_closed(self) -> None:
        model = _model()
        session = model["session_contract"]
        replay = session["replay"]
        self.assertEqual(
            session["authorization_states"],
            ["UNAUTHENTICATED", "CHALLENGE_ISSUED", "AUTHORIZED", "EXPIRED", "REVOKED", "CLOSED"],
        )
        self.assertEqual(replay["first_sequence"], 1)
        for token in [
            "strictly consecutive",
            "commit together",
            "do not advance",
            "STALE_REPLAY",
            "OUT_OF_ORDER",
        ]:
            self.assertIn(token, " ".join(str(value) for value in replay.values()))
        bounds = model["request_bounds"]
        self.assertEqual(bounds["maximum_sessions"], 1)
        self.assertEqual(bounds["maximum_inflight_commands_per_session"], 1)
        self.assertEqual(bounds["maximum_frame_bytes"], 2048)
        self.assertEqual(bounds["maximum_stream_chunk_bytes"], 1024)
        command = model["command_contract"]
        self.assertEqual(command["accepted_lifecycle"], ["RECEIVED", "ACCEPTED", "IN_PROGRESS", "TERMINAL"])
        self.assertTrue(command["exactly_one_terminal_per_accepted_command"])
        self.assertEqual(
            command["terminal_results"],
            ["SUCCEEDED", "FAILED", "TIMED_OUT", "CANCELLED", "ABORTED", "REBOOT_HANDOFF"],
        )
        self.assertIn("no ticket", command["preaccept_rule"])
        self.assertIn("first terminal write wins", command["terminal_rule"])

    def test_state_machine_is_closed_guarded_and_returns_durable_authority_to_hp3(self) -> None:
        model = _model()
        machine = model["state_machine"]
        self.assertEqual(machine["states"], qualify_admin_contract.EXPECTED_STATES)
        transitions = machine["legal_transitions"]
        self.assertEqual([entry["id"] for entry in transitions], qualify_admin_contract.EXPECTED_TRANSITION_IDS)
        self.assertFalse(any(entry["from"] == "NORMAL" and entry["to"] == "UPDATE" for entry in transitions))
        self.assertFalse(any(entry["from"] == "RECOVERY" and entry["to"] == "NORMAL" for entry in transitions))
        self.assertFalse(any(entry["from"] == "REBOOT_HANDOFF" for entry in transitions))
        self.assertEqual(machine["durable_authority"], "HP3 journal only; HP4 mode and intent never shadow slot or boot authority")
        result = qualify_admin_contract.validate(model)["state_machine"]
        self.assertEqual(result["scenario_count"], 5)
        self.assertEqual(result["guard_denial_cases"], 62)
        self.assertTrue(result["reboot_handoff_terminal"])
        self.assertEqual(result["scenarios"][0]["visited"], ["NORMAL", "QUIESCE", "UPDATE", "REBOOT_HANDOFF"])

    def test_guard_or_transition_tampering_fails_without_a_false_model_pass(self) -> None:
        model = _model()
        direct = copy.deepcopy(model)
        direct["state_machine"]["legal_transitions"][0]["to"] = "UPDATE"
        with self.assertRaises(qualify_admin_contract.QualificationError):
            qualify_admin_contract.validate(direct)
        missing_guard = copy.deepcopy(model)
        missing_guard["state_machine"]["legal_transitions"][7]["guards"].remove("trial_journal_commit_durable")
        with self.assertRaises(qualify_admin_contract.QualificationError):
            qualify_admin_contract.validate(missing_guard)
        wrong_source = copy.deepcopy(model)
        wrong_source["state_machine"]["legal_transitions"][1]["control_source"] = "UPDATE"
        with self.assertRaises(qualify_admin_contract.QualificationError):
            qualify_admin_contract.validate(wrong_source)
        widened_claim = copy.deepcopy(model)
        widened_claim["claim"]["firmware_implemented"] = True
        with self.assertRaises(qualify_admin_contract.QualificationError):
            qualify_admin_contract.validate(widened_claim)

    def test_hp1_hp2_hp3_authorities_are_bound_without_application_escape(self) -> None:
        model = _model()
        authority = model["authority_bindings"]
        self.assertEqual(authority["hp1"]["fixed_control_reserve_bytes"], 98304)
        self.assertEqual(authority["hp1"]["exclusive_update_working_bytes"], 65536)
        self.assertEqual(authority["hp1"]["administration"]["control_source"], "ADMINISTRATION")
        self.assertEqual(authority["hp1"]["update_control_source"], "UPDATE")
        self.assertEqual(authority["hp1"]["recovery"]["control_source"], "RECOVERY")
        self.assertTrue(authority["hp1"]["application_cannot_select_source_or_priority"])
        self.assertFalse(authority["hp3"]["factory_host_writable"])
        self.assertTrue(authority["hp3"]["active_and_last_confirmed_slots_are_never_staging_targets"])
        self.assertTrue(authority["hp3"]["slot_model_unchanged"])
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

    def test_serial_is_first_but_never_transport_authority(self) -> None:
        model = _model()
        serial = model["serial_transport"]
        self.assertEqual(serial["concrete_transport"], "SERIAL_PHYSICAL_V1")
        self.assertEqual(
            serial["transport_kinds"],
            ["SERIAL_PHYSICAL_V1", "AUTHENTICATED_EXTERNAL_V1_RESERVED"],
        )
        self.assertIn("never authorization authority", serial["authority"])
        self.assertIn("replaceable authorizer", serial["entry_rule"])
        self.assertIn("HP5", serial["future_transport"])
        self.assertIn("not production cryptography", serial["production_rule"])
        deferred = " ".join(model["deferred"])
        for token in ["Wi-Fi", "MQTT", "provider", "RAX", "host-firmware", "partition", "physical"]:
            self.assertIn(token, deferred)

    def test_docs_and_adr_freeze_scope_and_next_implementation_boundary(self) -> None:
        doc = _text(DOC)
        adr = _text(ADR)
        for token in [
            "`HOST_ADMINISTRATION_CONTRACT_FROZEN`",
            "`HOST_MODEL_ONLY`",
            "`NORMAL`, `QUIESCE`, `UPDATE`, `RECOVERY`",
            "There is no direct `NORMAL -> UPDATE` edge.",
            "98,304-byte fixed control reserve",
            "65,536-byte",
            "`SERIAL_PHYSICAL_V1`",
            "HP3 boot selector",
            "HP4.1",
            "does not add a firmware component",
        ]:
            self.assertIn(token, doc)
        for token in [
            "Accepted for HP4.0 through HP4.4.",
            "host-private plane",
            "one atomic acceptance step",
            "volatile five-state machine",
            "`NORMAL -> UPDATE`",
            "returns durable selection to HP3",
            "HP4.0 freezes this decision",
        ]:
            self.assertIn(token, adr)

    def test_qualifier_emits_exact_host_model_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "qualification"
            report = qualify_admin_contract.qualify(out)
            self.assertEqual(
                (
                    report["schema"],
                    report["phase"],
                    report["aggregate"],
                    report["status"],
                    report["classification"],
                ),
                (
                    "pulse.esp32.hp4_0-administration-contract-qualification.v1",
                    "PROTECTED_ADMINISTRATION_CONTRACT",
                    "HOST_ADMINISTRATION_CONTRACT_FROZEN",
                    "PASS",
                    "HOST_MODEL_ONLY",
                ),
            )
            self.assertEqual(report["state_count"], 5)
            self.assertEqual(report["transition_count"], 12)
            self.assertEqual(report["scenario_count"], 5)
            self.assertEqual(report["guard_denial_cases"], 62)
            self.assertFalse(report["application_code_executed"])
            self.assertFalse(report["firmware_source_changed"])
            self.assertFalse(report["physical_result_created"])
            for name in [
                "protected-administration-model.json",
                "transition-evaluation.json",
                "evidence-manifest.json",
                "qualification-report.json",
            ]:
                self.assertTrue((out / name).is_file())

    def test_make_runner_and_docs_gate_expose_hp4_0_without_hardware_workflow(self) -> None:
        makefile = _text(ROOT / "Makefile")
        runner = _text(ROOT / "tools/run_contract_tests.py")
        docs_checker = _text(ROOT / "tools/check_docs.py")
        workflow = _text(ROOT / ".github/workflows/idf-family-matrix.yml")
        self.assertIn("check-hp4-0", makefile)
        self.assertIn("tests.contract.test_hp4_0_administration_contract", makefile)
        self.assertIn("administration-contract-qualify", makefile)
        self.assertIn("tools/qualify_admin_contract.py", makefile)
        self.assertIn("tests.contract.test_hp4_0_administration_contract", runner)
        self.assertIn("docs/HP4_0_PROTECTED_ADMINISTRATION_CONTRACT.md", docs_checker)
        self.assertIn("docs/adr/0014-protected-host-administration-authority.md", docs_checker)
        self.assertIn("specs/PULSE-ESP32-009-protected-administration.json", docs_checker)
        self.assertNotIn("check-hp4-0", workflow)


if __name__ == "__main__":
    unittest.main()
