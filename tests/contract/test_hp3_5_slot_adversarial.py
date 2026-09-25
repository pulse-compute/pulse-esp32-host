from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tools import (
    build_hp3_5_slot_hardware,
    evaluate_hp3_5_slot_board,
    evaluate_hp3_5_slot_hardware,
    host_build_contract,
    qualify_app_slot_adversarial,
)


ROOT = Path(__file__).resolve().parents[2]
MODEL = ROOT / "specs/PULSE-ESP32-008a-application-slot-adversarial-seal.json"
PARENT = ROOT / "specs/PULSE-ESP32-008-application-slots.json"
CAMPAIGN = ROOT / "tests/hardware-in-loop/hp3_5-slot-power-loss/campaign.json"
CATALOG = ROOT / "firmware/host-build-catalog.json"
CLOSURE = ROOT / "evidence/hardware/hp3_5-index.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _promote_prepared_build(run_dir: Path) -> dict[str, object]:
    report_path = run_dir / "build-report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    artifacts: dict[str, dict[str, object]] = {}
    for name in (
        "application_elf",
        "application_binary",
        "application_map",
        "bootloader_binary",
        "partition_table_binary",
        "flasher_args",
        "flash_args",
    ):
        path = run_dir / "build" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((name + "\n").encode("utf-8"))
        artifacts[name] = {
            "path": str(path.relative_to(run_dir)),
            "sha256": _sha256(path),
            "size": path.stat().st_size,
        }
    report["status"] = "PASS"
    report["claim_boundary"]["build"] = "BUILD_PROVEN"
    report["firmware"] = {"status": "PASS", "artifacts": artifacts}
    backup = run_dir / "full-flash-before.bin"
    with backup.open("wb") as handle:
        handle.seek(report["flash_bytes"] - 1)
        handle.write(b"\0")
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report


def _write_passing_serial(
    run_dir: Path,
    campaign: dict[str, object],
    lane: dict[str, object],
    uid: str,
) -> None:
    board = {
        "schema": "pulse.esp32.hp3_5-slot-board-start.v1",
        "campaign_id": campaign["campaign_id"],
        "campaign_sha256": _sha256(CAMPAIGN),
        "board_id": lane["board_id"],
        "target": lane["target"],
        "flash_bytes": lane["flash_bytes"],
        "psram_bytes": lane["psram_bytes"],
        "physical_board_uid_sha256": uid,
        "partition_sha256": lane["partitions_sha256"],
        "bundle_sha256": build_hp3_5_slot_hardware.EXPECTED_BUNDLE_SHA256,
    }
    lines = ["PULSE_HP35_BOARD " + json.dumps(board, sort_keys=True)]
    for checkpoint in campaign["checkpoints"]:
        lines.append(
            "PULSE_HP35_CHECKPOINT "
            + json.dumps(
                {
                    "schema": "pulse.esp32.hp3_5-slot-checkpoint.v1",
                    "id": checkpoint["id"],
                    "status": "PASS",
                    "observation": "contract fixture observation",
                },
                sort_keys=True,
            )
        )
    lines.append(
        "PULSE_HP35_FINAL "
        + json.dumps(
            {
                "schema": "pulse.esp32.hp3_5-slot-final.v1",
                "status": "PASS",
                "checkpoint_count": 13,
                "invariants": {
                    "last_confirmed_destroyed": False,
                    "ambiguous_boot_authority": False,
                    "application_code_launched_before_authority": False,
                },
                "claim_boundary": {
                    "inactive_slot_only": True,
                    "factory_host_partition_written": False,
                    "host_firmware_ota": False,
                    "external_provider": False,
                    "rax": False,
                },
            },
            sort_keys=True,
        )
    )
    (run_dir / "serial.log").write_text("\n".join(lines) + "\n", encoding="utf-8")


class HP35SlotAdversarialTests(unittest.TestCase):
    def setUp(self) -> None:
        self.model = json.loads(MODEL.read_text(encoding="utf-8"))
        self.campaign = json.loads(CAMPAIGN.read_text(encoding="utf-8"))

    def test_frozen_addendum_and_strong_invariant(self) -> None:
        self.assertEqual(
            self.model["schema"],
            "pulse.esp32.hp3_5-application-slot-adversarial-seal.v1",
        )
        self.assertEqual(self.model["status"], "FROZEN")
        self.assertEqual(self.model["parent_authority"]["sha256"], _sha256(PARENT))
        invariant = self.model["strong_invariant"]
        self.assertFalse(invariant["last_confirmed_application_destroyed"])
        self.assertFalse(invariant["ambiguous_boot_authority"])
        self.assertEqual(
            invariant["interrupted_commit_authority"],
            "HIGHEST_COMPLETE_VALID_GENERATION",
        )

    def test_accepted_physical_closure_is_exact_and_external(self) -> None:
        closure = json.loads(CLOSURE.read_text(encoding="utf-8"))
        self.assertEqual(
            closure["schema"],
            "pulse.esp32.hp3_5-hardware-evidence-index.v1",
        )
        self.assertEqual(closure["status"], "PASS")
        self.assertEqual(
            closure["terminal_result"],
            "DUAL_NAMED_BOARD_SAFE_SUBSET_OBSERVED",
        )
        self.assertEqual(closure["campaign"]["sha256"], _sha256(CAMPAIGN))
        self.assertEqual(set(closure["lanes"]), {"esp32s3", "esp32c6"})
        for lane in closure["lanes"].values():
            self.assertEqual(lane["status"], "PASS")
            self.assertEqual(lane["evidence_origin"], "PHYSICAL_NAMED_BOARD")
            self.assertEqual(lane["checkpoint_count"], 13)
            self.assertEqual(len(lane["board_report_sha256"]), 64)
            self.assertEqual(len(lane["serial_log_sha256"]), 64)
        self.assertEqual(closure["coverage"]["physical_named_boards"], 2)
        self.assertFalse(closure["coverage"]["last_confirmed_destroyed"])
        self.assertFalse(closure["coverage"]["ambiguous_boot_authority"])
        self.assertFalse(
            closure["coverage"]["application_code_launched_before_authority"]
        )
        self.assertTrue(closure["claim_boundary"]["inactive_slot_only"])
        self.assertFalse(
            closure["claim_boundary"]["factory_host_partition_written"]
        )
        self.assertFalse(
            closure["evidence_archive"][
                "raw_full_flash_backups_source_distributed"
            ]
        )
        self.assertEqual(
            closure["source_authority"]["firmware_tree_sha256"],
            build_hp3_5_slot_hardware.EXPECTED_FIRMWARE_SOURCE["sha256"],
        )

    def test_exact_exhaustive_matrix(self) -> None:
        seal = self.model["synthetic_seal"]
        self.assertEqual(seal["total_cases"], 11657)
        self.assertEqual(seal["payload_write_cuts"], 2362)
        self.assertEqual(seal["slot_erase_cuts"], 6)
        self.assertEqual(seal["journal_interruption_cases"], 8240)
        self.assertEqual(seal["confirmation_reset_cases"], 1030)
        self.assertEqual(seal["journal_corruption_cases"], 3)
        self.assertEqual(seal["adversarial_semantic_cases"], 16)
        self.assertEqual(seal["repeated_trap_cycles"], 32)
        self.assertEqual(
            len(self.model["interruption_matrix"]["journal"]["state_transitions"]),
            8,
        )
        self.assertEqual(
            8240,
            8 * 2 * ((256 + 1) + (252 + 1) + (4 + 1)),
        )
        self.assertEqual(1030, 2 * ((256 + 1) + (252 + 1) + (4 + 1)))

    def test_private_fault_model_and_transactional_hardening(self) -> None:
        header = (ROOT / "firmware/components/wdc_ota/include/wdc_ota.h").read_text(encoding="utf-8")
        ota = (ROOT / "firmware/components/wdc_ota/wdc_ota.c").read_text(encoding="utf-8")
        slots = (ROOT / "firmware/components/wdc_app_slots/wdc_app_slots.c").read_text(encoding="utf-8")
        for token in (
            "WDC_OTA_HOST_FAULT_SLOT_ERASE",
            "WDC_OTA_HOST_FAULT_SLOT_WRITE",
            "WDC_OTA_HOST_FAULT_METADATA_ERASE",
            "WDC_OTA_HOST_FAULT_METADATA_BODY_WRITE",
            "WDC_OTA_HOST_FAULT_METADATA_MARKER_WRITE",
            "wdc_ota_host_power_cycle",
        ):
            self.assertIn(token, header)
        self.assertIn("host_fault_take", ota)
        self.assertIn("session->written_bytes += tear_after", ota)
        self.assertIn("wdc_ota_read_metadata(&durable)", slots)
        self.assertIn("memcpy(metadata, &durable, sizeof(*metadata))", slots)
        self.assertIn("prepare_reject_boot_slot", slots)
        self.assertIn("metadata->last_good_slot = alternate", slots)

    def test_target_full_slot_erase_is_bounded_and_cooperative(self) -> None:
        ota = (
            ROOT / "firmware/components/wdc_ota/wdc_ota.c"
        ).read_text(encoding="utf-8")
        component = (
            ROOT / "firmware/components/wdc_ota/CMakeLists.txt"
        ).read_text(encoding="utf-8")
        target_path = ota.split("#ifdef ESP_PLATFORM", 1)[1].split("#else", 1)[0]
        self.assertIn("erase_offset < partition->size", target_path)
        self.assertIn("remaining < (16u * 1024u)", target_path)
        self.assertIn("vTaskDelay(1u)", target_path)
        self.assertNotIn(
            "esp_partition_erase_range(partition, 0u, partition->size)",
            target_path,
        )
        self.assertIn("freertos", component)

    def test_physical_baseline_arms_before_committing_and_names_interrupts(self) -> None:
        harness = (
            ROOT
            / "tests/hardware-in-loop/hp3_5-slot-power-loss/firmware/main/"
            "hp3_5_slot_hardware_main.c"
        ).read_text(encoding="utf-8")
        no_state = harness.split("if (!have_state)", 1)[1].split(
            "switch ((Hp35Phase)state.phase)", 1
        )[0]
        self.assertIn("PULSE_HP35_ARMING", no_state)
        self.assertIn("vTaskDelay(pdMS_TO_TICKS(HP35_BASELINE_ARM_DELAY_MS))", no_state)
        self.assertLess(no_state.index("vTaskDelay"), no_state.index("init_baseline"))
        self.assertIn("HP35_BASELINE_ARM_DELAY_MS 10000u", harness)
        self.assertIn("HP35_STATE_SCHEMA 2u", harness)
        self.assertIn("PULSE_HP35_BASELINE_INTERRUPTED", harness)
        for step in (
            "HP35_BASELINE_STAGE_ARTIFACT",
            "HP35_BASELINE_MARK_TRIAL",
            "HP35_BASELINE_SELECT_BOOT",
            "HP35_BASELINE_CONFIRM",
            "HP35_BASELINE_HASH",
            "HP35_BASELINE_VERIFY",
        ):
            self.assertIn(step, harness)

    def test_physical_artifact_identity_is_derived_from_embedded_bundle(self) -> None:
        harness = (
            ROOT
            / "tests/hardware-in-loop/hp3_5-slot-power-loss/firmware/main/"
            "hp3_5_slot_hardware_main.c"
        ).read_text(encoding="utf-8")
        build_artifact = harness.split("static void build_artifact(void)", 1)[1].split(
            "static WdcControlHeapSnapshot heap_snapshot", 1
        )[0]
        self.assertIn("wdc_bundle_parse_header(pulse_hp35_bundle", build_artifact)
        self.assertIn("wdc_bundle_parse_manifest_summary", build_artifact)
        self.assertIn(
            "header.application_version = manifest.bundle_version", build_artifact
        )
        self.assertIn(
            "header.security_counter = manifest.security_counter", build_artifact
        )
        self.assertIn("manifest.bundle_id", build_artifact)
        self.assertNotIn("com.pulse.hp3_5.physical-campaign", build_artifact)

    def test_persisted_crc_copies_preserve_padding_bytes(self) -> None:
        ota = (ROOT / "firmware/components/wdc_ota/wdc_ota.c").read_text(
            encoding="utf-8"
        )
        app_slots = (
            ROOT / "firmware/components/wdc_app_slots/wdc_app_slots.c"
        ).read_text(encoding="utf-8")
        bundle = (ROOT / "firmware/components/wdc_bundle/wdc_bundle.c").read_text(
            encoding="utf-8"
        )
        identity = (
            ROOT / "firmware/components/wdc_host_identity/wdc_host_identity.c"
        ).read_text(encoding="utf-8")
        harness = (
            ROOT
            / "tests/hardware-in-loop/hp3_5-slot-power-loss/firmware/main/"
            "hp3_5_slot_hardware_main.c"
        ).read_text(encoding="utf-8")

        self.assertIn("memcpy(&copy, record, sizeof(copy));", ota)
        self.assertIn(
            "memcpy(&record->metadata, metadata, sizeof(record->metadata));",
            ota,
        )
        self.assertIn(
            "memcpy(out_metadata, &best->metadata, sizeof(*out_metadata));",
            ota,
        )
        self.assertNotIn("WdcOtaMetadataRecord copy = *record", ota)
        self.assertNotIn("record->metadata = *metadata", ota)
        self.assertIn("memcpy(&copy, header, sizeof(copy));", app_slots)
        self.assertIn("memcpy(&copy, metadata, sizeof(copy));", bundle)
        self.assertIn("memcpy(&copy, fingerprint, sizeof(copy));", identity)
        self.assertIn("PULSE_HP35_STAGE_FAILURE", harness)
        self.assertIn("memcpy(&copy, record, sizeof(copy));", harness)

    def test_qualifier_emits_exact_host_seal(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            out = Path(temp_name) / "evidence"
            report = qualify_app_slot_adversarial.qualify(out, "cc")
            smoke = json.loads(
                (out / "synthetic-slot-adversarial-seal.json").read_text(
                    encoding="utf-8"
                )
            )
            manifest = json.loads(
                (out / "evidence-manifest.json").read_text(encoding="utf-8")
            )
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(
            report["aggregate"], "HOST_SLOT_ADVERSARIAL_POWER_LOSS_SEALED"
        )
        self.assertEqual(report["coverage"]["host_cases"], 11657)
        self.assertTrue(report["coverage"]["last_confirmed_preserved"])
        self.assertFalse(report["coverage"]["ambiguous_boot_authority"])
        self.assertEqual(report["physical_safe_subset"]["status"], "READY_NOT_RUN")
        self.assertEqual(
            report["claim_boundary"]["hardware_execution_this_pass"], "NOT_RUN"
        )
        self.assertEqual(smoke["failures"], 0)
        self.assertEqual(smoke["total_cases"], 11657)
        self.assertEqual(manifest["status"], "PASS")

    def test_physical_gate_is_two_board_and_rejects_synthetic_origin(self) -> None:
        evaluate_hp3_5_slot_hardware._validate_campaign(self.campaign)
        self.assertEqual(len(self.campaign["board_lanes"]), 2)
        self.assertEqual(len(self.campaign["checkpoints"]), 13)
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            s3 = root / "s3"
            c6 = root / "c6"
            s3.mkdir()
            c6.mkdir()
            (s3 / "serial.log").write_text("synthetic\n", encoding="utf-8")
            (c6 / "serial.log").write_text("synthetic\n", encoding="utf-8")
            for run, size in ((s3, 8 * 1024 * 1024), (c6, 4 * 1024 * 1024)):
                with (run / "full-flash-before.bin").open("wb") as handle:
                    handle.seek(size - 1)
                    handle.write(b"\0")
            synthetic = {
                "schema": "pulse.esp32.hp3_5-slot-board-evidence.v1",
                "status": "PASS",
                "evidence_origin": "SYNTHETIC",
            }
            (s3 / "board-report.json").write_text(
                json.dumps(synthetic), encoding="utf-8"
            )
            (c6 / "board-report.json").write_text(
                json.dumps(synthetic), encoding="utf-8"
            )
            with self.assertRaises(evaluate_hp3_5_slot_hardware.EvaluationError):
                evaluate_hp3_5_slot_hardware.evaluate(s3, c6, root / "out")

    def test_named_board_build_prepares_canonical_hp3_layouts(self) -> None:
        component_cmake = (
            ROOT
            / "tests/hardware-in-loop/hp3_5-slot-power-loss/firmware/main/CMakeLists.txt"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "idf_build_get_property(HP35_IDF_TARGET IDF_TARGET)",
            component_cmake,
        )
        self.assertIn(
            'if(HP35_IDF_TARGET STREQUAL "esp32s3")', component_cmake
        )
        self.assertIn("PRIV_REQUIRES", component_cmake)
        self.assertIn("${HP35_TARGET_REQUIRES}", component_cmake)
        self.assertNotIn("if(CONFIG_IDF_TARGET_ESP32S3)", component_cmake)
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            for board_id in build_hp3_5_slot_hardware.BOARD_CONFIGS:
                run = root / board_id
                report = build_hp3_5_slot_hardware.qualify_build(
                    board_id=board_id,
                    out_dir=run,
                    prepare_only=True,
                    idf_path=None,
                    idf_py=None,
                    timeout=30,
                )
                lane = next(
                    item
                    for item in self.campaign["board_lanes"]
                    if item["board_id"] == board_id
                )
                self.assertEqual(report["status"], "PREPARED")
                self.assertEqual(report["campaign_sha256"], _sha256(CAMPAIGN))
                self.assertEqual(report["partition_table"]["sha256"], lane["partitions_sha256"])
                partitions = (run / "project/partitions.csv").read_text(encoding="utf-8")
                self.assertIn("wasm_a", partitions)
                self.assertIn("wasm_b", partitions)
                self.assertIn("wasm_meta", partitions)
                self.assertTrue(
                    (run / "source/native-sdk/c/include/pulse_extension.h").is_file()
                )
                self.assertEqual(
                    report["sealed_sources"]["native_sdk"],
                    build_hp3_5_slot_hardware.EXPECTED_NATIVE_SDK_SOURCE,
                )
                header = (run / "project/main/hp3_5_campaign_config.h").read_text(
                    encoding="utf-8"
                )
                self.assertIn(_sha256(CAMPAIGN), header)
                self.assertIn(board_id, header)

    def test_board_report_producer_feeds_positive_dual_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            reports = []
            for index, lane in enumerate(self.campaign["board_lanes"], 1):
                run = root / lane["target"]
                build_hp3_5_slot_hardware.qualify_build(
                    board_id=lane["board_id"],
                    out_dir=run,
                    prepare_only=True,
                    idf_path=None,
                    idf_py=None,
                    timeout=30,
                )
                _promote_prepared_build(run)
                _write_passing_serial(run, self.campaign, lane, f"{index:064x}")
                reports.append(
                    evaluate_hp3_5_slot_board.evaluate(run, f"fixture-marking-{index}")
                )
            self.assertTrue(all(item["status"] == "PASS" for item in reports))
            dual = evaluate_hp3_5_slot_hardware.evaluate(
                root / "esp32s3", root / "esp32c6", root / "dual"
            )
            self.assertEqual(dual["status"], "PASS")
            self.assertEqual(
                dual["aggregate"], "DUAL_NAMED_BOARD_SAFE_SUBSET_OBSERVED"
            )

    def test_board_report_producer_rejects_fatal_or_reordered_serial(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            run = Path(temp_name) / "s3"
            lane = self.campaign["board_lanes"][0]
            build_hp3_5_slot_hardware.qualify_build(
                board_id=lane["board_id"],
                out_dir=run,
                prepare_only=True,
                idf_path=None,
                idf_py=None,
                timeout=30,
            )
            _promote_prepared_build(run)
            _write_passing_serial(run, self.campaign, lane, "a" * 64)
            with (run / "serial.log").open("a", encoding="utf-8") as handle:
                handle.write(
                    'PULSE_HP35_FATAL {"schema":"pulse.esp32.hp3_5-slot-fatal.v1",'
                    '"status":"FAIL","message":"fixture","error":-1}\n'
                )
            with self.assertRaises(evaluate_hp3_5_slot_board.BoardEvaluationError):
                evaluate_hp3_5_slot_board.evaluate(run, "fixture")

    def test_locks_wiring_docs_and_exclusions(self) -> None:
        catalog = host_build_contract.load_json(CATALOG)
        resolved = host_build_contract.validate_catalog(catalog)
        for selected in resolved.values():
            entry = selected["entry"]
            lock = host_build_contract.load_json(ROOT / entry["build_lock"])
            fingerprint = host_build_contract.load_json(ROOT / entry["fingerprint"])
            self.assertEqual(
                host_build_contract.replay_lock(lock, fingerprint), fingerprint
            )
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        runner = (ROOT / "tools/run_contract_tests.py").read_text(encoding="utf-8")
        checker = (ROOT / "tools/check_docs.py").read_text(encoding="utf-8")
        self.assertIn("check-hp3-5", makefile)
        self.assertIn("app-slots-adversarial-qualify", makefile)
        self.assertIn("hp3_5-s3-aitrip-build", makefile)
        self.assertIn("hp3_5-c6-xiao-build", makefile)
        self.assertIn("evaluate_hp3_5_slot_board.py", makefile)
        self.assertIn("hp3_5-hardware-evaluate", makefile)
        self.assertIn("tests.contract.test_hp3_5_slot_adversarial", runner)
        self.assertIn("docs/HP3_5_APPLICATION_SLOT_ADVERSARIAL_SEAL.md", checker)
        self.assertEqual(
            set(self.model["excluded"]),
            {
                "RAX",
                "HOST_FIRMWARE_OTA",
                "MQTT_OR_TRANSPORT_IMPLEMENTATION",
                "EXTERNAL_PROVIDER",
                "PULSE_CORE_CHANGES",
                "PROTECTED_REMOTE_ADMINISTRATION",
            },
        )


if __name__ == "__main__":
    unittest.main()
