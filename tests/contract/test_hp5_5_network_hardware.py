from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import (
    build_hp5_5_network_hardware,
    evaluate_hp5_5_network_board,
    evaluate_hp5_5_network_hardware,
    hp5_5_fixture,
    prepare_hp5_5_provision,
    qualify_hp5_5_network_hardware,
    resolve_hp5_5_target_contracts,
)


ROOT = Path(__file__).resolve().parents[2]
CAMPAIGN_PATH = ROOT / "tests/hardware-in-loop/hp5_5-network-admin/campaign.json"
MODEL_PATH = ROOT / "specs/PULSE-ESP32-015-network-administration-physical-seal.json"
EMPTY_SHA = hashlib.sha256(b"").hexdigest()


def _json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _provision(path: Path) -> dict[str, bytes]:
    path.mkdir(parents=True)
    values = {
        "wifi-ssid.bin": b"hp55-test-ssid-unique",
        "wifi-password.bin": b"hp55-test-password-unique",
        "server-cert.pem": b"-----BEGIN CERTIFICATE-----\nhp55-unique-certificate\n-----END CERTIFICATE-----\n",
        "server-key.pem": b"-----BEGIN PRIVATE KEY-----\nhp55-unique-private-key\n-----END PRIVATE KEY-----\n",
        "admin-proof.bin": bytes(range(32)),
        "channel-binding.bin": bytes(range(32, 64)),
    }
    for name, value in values.items():
        (path / name).write_bytes(value)
    manifest = {
        "schema": "pulse.esp32.hp5_5-test-provision.v1",
        "status": "LOCAL_SECRET_MATERIAL",
        "publishable": False,
        "certificate_sha256": hashlib.sha256(values["server-cert.pem"]).hexdigest(),
        "admin_proof_sha256": hashlib.sha256(values["admin-proof.bin"]).hexdigest(),
        "channel_binding_sha256": values["channel-binding.bin"].hex(),
        "secret_files": [
            {"name": name, "size": len(value)} for name, value in values.items()
        ],
        "retention": {
            "source_archive": False,
            "logs": False,
            "reports": False,
            "evidence_manifest": False,
            "local_run_directory_only": True,
        },
    }
    _json(path / "provision-manifest.json", manifest)
    return values


def _evidence(path: Path, run: Path) -> dict:
    return {
        "path": path.relative_to(run).as_posix(),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "size": path.stat().st_size,
    }


def _make_run(base: Path, board_id: str, uid_seed: str) -> tuple[Path, Path]:
    campaign = json.loads(CAMPAIGN_PATH.read_text(encoding="utf-8"))
    lane = next(item for item in campaign["board_lanes"] if item["board_id"] == board_id)
    config = build_hp5_5_network_hardware.BOARD_CONFIGS[board_id]
    run = base / ("s3-run" if lane["target"] == "esp32s3" else "c6-run")
    provision = base / ("s3-provision" if lane["target"] == "esp32s3" else "c6-provision")
    run.mkdir(parents=True)
    secrets = _provision(provision)
    inputs = run / "inputs"
    project = run / "project"
    staged = run / "source"
    inputs.mkdir()
    project.mkdir()
    (staged / "firmware/components").mkdir(parents=True)
    (staged / "native-sdk").mkdir(parents=True)
    (staged / "firmware/components/contract-test.c").write_text(
        "/* synthetic evaluator contract source */\n", encoding="utf-8"
    )
    (staged / "native-sdk/contract-test.h").write_text(
        "/* synthetic evaluator contract header */\n", encoding="utf-8"
    )
    shutil.copy2(ROOT / config["board"], inputs / "board.json")
    shutil.copy2(ROOT / config["partitions"], inputs / "partitions.csv")
    shutil.copy2(ROOT / config["dependency_lock"], project / "dependencies.lock")
    clients = run / "client-fixtures"
    clients.mkdir()
    positive = hp5_5_fixture.make_artifact(9)
    fallback = hp5_5_fixture.make_artifact(10)
    (clients / "positive-v9.artifact").write_bytes(positive)
    (clients / "fallback-v10.artifact").write_bytes(fallback)
    build = run / "build"
    (build / "bootloader").mkdir(parents=True)
    (build / "partition_table").mkdir(parents=True)
    artifact_paths = {
        "application_elf": build / "pulse_hp5_5_network_admin.elf",
        "application_binary": build / "pulse_hp5_5_network_admin.bin",
        "application_map": build / "pulse_hp5_5_network_admin.map",
        "bootloader_binary": build / "bootloader/bootloader.bin",
        "partition_table_binary": build / "partition_table/partition-table.bin",
        "flasher_args": build / "flasher_args.json",
        "flash_args": build / "flash_args",
    }
    for index, path in enumerate(artifact_paths.values(), 1):
        path.write_bytes((f"hp55-artifact-{index}\n").encode("ascii"))
    sdkconfig = run / "sdkconfig"
    build_log = run / "build.log"
    defaults = (
        ROOT
        / "tests/hardware-in-loop/hp5_5-network-admin/firmware"
        / config["sdkconfig"]
    ).read_text(encoding="utf-8")
    target_symbol = (
        "CONFIG_IDF_TARGET_ESP32S3"
        if lane["target"] == "esp32s3"
        else "CONFIG_IDF_TARGET_ESP32C6"
    )
    sdkconfig.write_text(
        defaults
        + f'\nCONFIG_IDF_TARGET="{lane["target"]}"\n'
        + f"{target_symbol}=y\n",
        encoding="utf-8",
    )
    build_log.write_text("pinned HP5.5 contract-test build log\n", encoding="utf-8")
    predecessor = build_hp5_5_network_hardware.EXPECTED_PREDECESSOR
    inventory = hp5_5_fixture.artifact_inventory()
    report = {
        "schema": build_hp5_5_network_hardware.REPORT_SCHEMA,
        "status": "PASS",
        "evidence_origin": "SEALED_SOURCE_PHYSICAL_BUILD",
        "campaign_id": campaign["campaign_id"],
        "campaign_sha256": hashlib.sha256(CAMPAIGN_PATH.read_bytes()).hexdigest(),
        "model_sha256": hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest(),
        "board_id": board_id,
        "target": lane["target"],
        "flash_bytes": lane["flash_bytes"],
        "psram_bytes": lane["psram_bytes"],
        "plan_sha256": lane["plan_sha256"],
        "lock_sha256": lane["lock_sha256"],
        "fingerprint_sha256": lane["fingerprint_sha256"],
        "predecessor_archive": {
            "name": predecessor["name"],
            "sha256": predecessor["sha256"],
            "size": predecessor["size"],
            "archive_root": predecessor["root"],
            "manifested_files": predecessor["file_count"],
            "manifested_payload_bytes": predecessor["payload_bytes"],
        },
        "execution_source": build_hp5_5_network_hardware.EXPECTED_FIRMWARE,
        "board_identity": _evidence(inputs / "board.json", run),
        "partition_table": _evidence(inputs / "partitions.csv", run),
        "dependency_lock": _evidence(project / "dependencies.lock", run),
        "fixture_artifacts": inventory,
        "client_artifacts": {
            "positive": _evidence(clients / "positive-v9.artifact", run),
            "fallback": _evidence(clients / "fallback-v10.artifact", run),
        },
        "source_seals": build_hp5_5_network_hardware.staged_source_seals(
            run, project, staged
        ),
        "provision": {
            "publishable": False,
            "certificate_sha256": hashlib.sha256(secrets["server-cert.pem"]).hexdigest(),
            "admin_proof_sha256": hashlib.sha256(secrets["admin-proof.bin"]).hexdigest(),
            "channel_binding_sha256": secrets["channel-binding.bin"].hex(),
            "secret_scan_required": True,
            "secret_values_retained_in_report": False,
        },
        "staged_project": "project",
        "staged_repository": "source",
        "operator_contract": {
            "full_flash_backup_required": True,
            "fresh_full_flash_erase_required": True,
            "operator_attended": True,
            "restore_path_required": True,
            "serial_log_required": True,
            "network_transcript_required": True,
            "test_provision_nonpublishable": True,
        },
        "commands": build_hp5_5_network_hardware.operator_commands(board_id),
        "claim_boundary": {
            "build": "BUILD_PROVEN",
            "runtime": "HARDWARE_NOT_RUN",
            "aggregate": "HARDWARE_PENDING",
        },
        "firmware": {
            "status": "PASS",
            "result": "BUILD_PROVEN",
            "environment": {
                "schema": "pulse.esp32.idf-environment.v1",
                "status": "PASS",
                "version": "v5.4.4",
                "source_commit": "296b6eab9445fd720e71aecab961e2d3fbca9944",
                "platform_scope": "NAMED_BOARD_HP5_5_NETWORK_ADMIN_BUILD",
            },
            "commands": [["idf.py", "build"]],
            "sdkconfig": _evidence(sdkconfig, run),
            "size": {"diram_remain": lane["minimum_build_diram_remain_bytes"] + 4096},
            "headroom_gate": {
                "status": "PASS",
                "minimum_diram_remain_bytes": lane["minimum_build_diram_remain_bytes"],
                "observed_diram_remain_bytes": lane["minimum_build_diram_remain_bytes"] + 4096,
                "application_partition_bytes": 2 * 1024 * 1024,
                "application_binary_bytes": artifact_paths["application_binary"].stat().st_size,
            },
            "artifacts": {
                name: _evidence(path, run) for name, path in artifact_paths.items()
            },
            "build_log": _evidence(build_log, run),
        },
    }
    _json(run / "build-report.json", report)
    uid = hashlib.sha256(uid_seed.encode("ascii")).hexdigest()
    boot = {
        "schema": "pulse.esp32.hp5_5-boot.v1",
        "campaign_id": campaign["campaign_id"],
        "campaign_sha256": hashlib.sha256(CAMPAIGN_PATH.read_bytes()).hexdigest(),
        "board_id": board_id,
        "target": lane["target"],
        "flash_bytes": lane["flash_bytes"],
        "psram_bytes": lane["psram_bytes"],
        "physical_board_uid_sha256": uid,
        "plan_sha256": lane["plan_sha256"],
        "lock_sha256": lane["lock_sha256"],
        "fingerprint_sha256": lane["fingerprint_sha256"],
        "fingerprint_target": 1 if lane["target"] == "esp32s3" else 2,
    }
    stats = {
        "schema": "pulse.esp32.hp5_5-stats.v1",
        "internal_free": lane["minimum_runtime_internal_free_bytes"] + 8192,
        "internal_largest": lane["minimum_runtime_largest_block_bytes"] + 4096,
        "psram_free": lane["minimum_runtime_psram_free_bytes"] + (4096 if lane["psram_bytes"] else 0),
        "minimum_internal_free": lane["minimum_runtime_internal_free_bytes"] + 4096,
        "minimum_internal_largest": lane["minimum_runtime_largest_block_bytes"],
        "minimum_psram_free": lane["minimum_runtime_psram_free_bytes"],
        "wifi_connected": True,
        "reconnect_count": 2,
        "wifi_disconnect_observed": True,
        "wifi_reconnect_observed": True,
        "wifi_reconnect_elapsed_ms": 250,
        "app_response_losses": 1,
        "admin_response_losses": 1,
        "admin_terminal_losses": 1,
        "duplicate_rejections": 1,
        "app_timeouts": 1,
        "app_cancelled": 1,
        "app_trapped": 1,
    }
    final = {
        "schema": "pulse.esp32.hp5_5-final.v1",
        "status": "PASS",
        "campaign_id": campaign["campaign_id"],
        "board_id": board_id,
        "physical_board_uid_sha256": uid,
        "factory_host_partition_written": False,
        "host_firmware_ota": False,
    }
    boot_line = "PULSE_HP55_BOOT " + json.dumps(boot, sort_keys=True) + "\n"
    stats_line = "PULSE_HP55_STATS " + json.dumps(stats, sort_keys=True) + "\n"
    serial = (
        boot_line
        + "PULSE_HP55_CHECKPOINT " + json.dumps({
            "schema": "pulse.esp32.hp5_5-checkpoint.v1",
            "id": "target-boot-fingerprint",
            "detail": "physical target and running fingerprint matched",
        }, sort_keys=True) + "\n"
        + stats_line + boot_line + stats_line + boot_line + boot_line + boot_line
        + stats_line
        + "PULSE_HP55_FINAL " + json.dumps(final, sort_keys=True) + "\n"
    )
    (run / "serial.log").write_text(serial, encoding="utf-8")
    records = []
    for ordinal, checkpoint in enumerate(campaign["checkpoints"], 1):
        records.append({
            "schema": "pulse.esp32.hp5_5-network-transcript-record.v1",
            "campaign_id": campaign["campaign_id"],
            "board_id": board_id,
            "ordinal": ordinal,
            "checkpoint_ordinal": ordinal,
            "checkpoint_id": checkpoint["id"],
            "lane": "both",
            "operation": "contract-test-observation",
            "http_status": 200,
            "protocol_status": 0,
            "response_bytes": 0,
            "response_sha256": EMPTY_SHA,
            "detail": "bounded physical observation for " + checkpoint["id"],
        })
    (run / "network-transcript.jsonl").write_text(
        "".join(json.dumps(record, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )
    with (run / "full-flash-backup.bin").open("wb") as handle:
        handle.truncate(lane["flash_bytes"])
    return run, provision


def _evaluate_run(run: Path, provision: Path, marking: str) -> dict:
    target = json.loads((run / "build-report.json").read_text())["target"]
    return evaluate_hp5_5_network_board.evaluate(
        run, provision, marking,
        f"esptool.py --chip {target} -p TEST write_flash 0 full-flash-backup.bin",
        True, True,
    )


class HP55NetworkHardwareTests(unittest.TestCase):
    def test_model_campaign_and_readiness_qualifier_remain_honest(self) -> None:
        model, campaign = qualify_hp5_5_network_hardware.validate_model_and_campaign()
        self.assertEqual(model["aggregate"], "HARDWARE_PENDING")
        self.assertFalse(model["claim"]["dual_named_board_physical_execution"])
        self.assertEqual(len(campaign["checkpoints"]), 29)
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "qualification"
            report = qualify_hp5_5_network_hardware.qualify(output)
            self.assertEqual(report["readiness"], "READY_FOR_PHYSICAL_EXECUTION")
            self.assertEqual(report["aggregate"], "HARDWARE_PENDING")
            self.assertFalse(report["target_build_executed"])
            self.assertFalse(report["physical_result_created"])
            self.assertIn("BLOCKED", report["hp6_status"])

    def test_target_contracts_native_profiles_and_fixtures_are_exact(self) -> None:
        resolution = resolve_hp5_5_target_contracts.verify()
        self.assertTrue(resolution["historical_hp2_authorities_unchanged"])
        self.assertEqual(len(resolution["lanes"]), 2)
        native = qualify_hp5_5_network_hardware.run_update_profile_smoke()
        self.assertEqual((native["status"], native["cases"], native["failures"]), ("PASS", 4, 0))
        fixture = qualify_hp5_5_network_hardware.validate_fixture()
        self.assertEqual(fixture["artifacts"], qualify_hp5_5_network_hardware.EXPECTED_ARTIFACTS)
        rendered = build_hp5_5_network_hardware.c_array(
            "utf8_test", "é".encode(), string=True
        )
        self.assertIn("(char)0xc3", rendered)
        campaign = json.loads(CAMPAIGN_PATH.read_text(encoding="utf-8"))
        lane = campaign["board_lanes"][0]
        with self.assertRaises(evaluate_hp5_5_network_board.BoardEvaluationError):
            evaluate_hp5_5_network_board.validate_operator_inputs(
                lane,
                "AITRIP ESP32-S3-DevKitC-1 N8R2",
                "echo this-is-not-a-restore-command",
            )

    def test_both_secret_staged_projects_are_target_bound(self) -> None:
        campaign = json.loads(CAMPAIGN_PATH.read_text(encoding="utf-8"))
        blobs = {
            "ssid": b"hp55-stage-ssid",
            "password": b"hp55-stage-password",
            "certificate": b"certificate-test-bytes",
            "private_key": b"private-key-test-bytes",
            "admin_proof": bytes(range(32)),
            "channel_binding": bytes(range(32, 64)),
        }
        with tempfile.TemporaryDirectory() as temp:
            for lane in campaign["board_lanes"]:
                output = Path(temp) / lane["target"]
                output.mkdir()
                project, staged, inventory = build_hp5_5_network_hardware.stage_project(
                    output, lane["board_id"], campaign, lane,
                    hashlib.sha256(CAMPAIGN_PATH.read_bytes()).hexdigest(), blobs,
                )
                config = (project / "main/hp5_5_campaign_config.h").read_text()
                self.assertIn(lane["fingerprint_sha256"], config)
                self.assertIn(
                    str(lane["minimum_runtime_internal_free_bytes"]), config
                )
                self.assertEqual(inventory, hp5_5_fixture.artifact_inventory())
                generated = staged / "firmware/components/wdc_host_identity/wdc_host_fingerprint_generated.c"
                self.assertIn(lane["fingerprint_sha256"], generated.read_text())
                provision_source = (project / "main/hp5_5_provision.c").read_text()
                self.assertNotIn("hp55-stage-password", provision_source)
                self.assertIn("pulse_hp55_wifi_password_len = 19u", provision_source)

    def test_provision_helper_is_external_permissioned_and_secret_safe(self) -> None:
        openssl = shutil.which("openssl")
        self.assertIsNotNone(openssl)
        with tempfile.TemporaryDirectory() as temp, mock.patch.dict(
            os.environ,
            {"HP5_5_TEST_SSID": "hp55-test-network", "HP5_5_TEST_PASSWORD": "hp55-test-password"},
        ):
            output = Path(temp) / "provision"
            manifest = prepare_hp5_5_provision.prepare(
                output, ssid_env="HP5_5_TEST_SSID", password_env="HP5_5_TEST_PASSWORD",
                common_name="pulse-hp55.local", openssl=str(openssl),
            )
            self.assertFalse(manifest["publishable"])
            self.assertEqual(output.stat().st_mode & 0o777, 0o700)
            self.assertEqual(len(manifest["secret_files"]), 6)
            for item in manifest["secret_files"]:
                self.assertEqual((output / item["name"]).stat().st_mode & 0o777, 0o600)
            loaded, blobs = build_hp5_5_network_hardware.load_provision(output)
            self.assertEqual(loaded["certificate_sha256"], manifest["certificate_sha256"])
            self.assertNotIn(blobs["password"].decode(), json.dumps(manifest))
            with self.assertRaises(prepare_hp5_5_provision.ProvisionError):
                prepare_hp5_5_provision.prepare(
                    ROOT / "forbidden-in-source-provision",
                    ssid_env="HP5_5_TEST_SSID",
                    password_env="HP5_5_TEST_PASSWORD",
                    common_name="pulse-hp55.local",
                    openssl=str(openssl),
                )

    def test_per_board_and_dual_evaluators_accept_only_complete_distinct_lanes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            s3_run, s3_provision = _make_run(
                base, "aitrip-esp32s3-devkitc-1-n8r2", "physical-s3-uid"
            )
            c6_run, c6_provision = _make_run(
                base, "seeed-xiao-esp32c6-4m", "physical-c6-uid"
            )
            s3 = _evaluate_run(
                s3_run, s3_provision,
                "AITRIP ESP32-S3-DevKitC-1 N8R2 unit A",
            )
            c6 = _evaluate_run(
                c6_run, c6_provision,
                "Seeed Studio XIAO ESP32C6 4MB unit B",
            )
            self.assertEqual(s3["status"], "PASS")
            self.assertEqual(c6["status"], "PASS")
            output = base / "aggregate"
            aggregate = evaluate_hp5_5_network_hardware.evaluate(s3_run, c6_run, output)
            self.assertEqual(
                aggregate["aggregate"],
                "DUAL_NAMED_BOARD_HP5_NETWORK_ADMIN_OBSERVED",
            )
            self.assertEqual(aggregate["coverage"]["physical_named_boards"], 2)
            manifest = json.loads((output / "evidence-manifest.json").read_text())
            self.assertEqual(len(manifest["artifacts"]), 3)

    def test_reordered_unbound_secret_or_single_evidence_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            run, provision = _make_run(
                base, "aitrip-esp32s3-devkitc-1-n8r2", "negative-s3-uid"
            )
            lines = (run / "network-transcript.jsonl").read_text().splitlines()
            lines[0], lines[1] = lines[1], lines[0]
            (run / "network-transcript.jsonl").write_text("\n".join(lines) + "\n")
            with self.assertRaises(evaluate_hp5_5_network_board.BoardEvaluationError):
                _evaluate_run(
                    run, provision,
                    "AITRIP ESP32-S3-DevKitC-1 N8R2 negative",
                )

        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            run, provision = _make_run(
                base, "aitrip-esp32s3-devkitc-1-n8r2", "unbound-s3-uid"
            )
            build_path = run / "build-report.json"
            build = json.loads(build_path.read_text(encoding="utf-8"))
            build["plan_sha256"] = "0" * 64
            _json(build_path, build)
            with self.assertRaises(evaluate_hp5_5_network_board.BoardEvaluationError):
                _evaluate_run(
                    run, provision,
                    "AITRIP ESP32-S3-DevKitC-1 N8R2 unbound",
                )

        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            run, provision = _make_run(
                base, "seeed-xiao-esp32c6-4m", "negative-c6-uid"
            )
            secret = (provision / "admin-proof.bin").read_bytes()
            with (run / "serial.log").open("ab") as handle:
                handle.write(secret)
            with self.assertRaises(evaluate_hp5_5_network_board.BoardEvaluationError):
                _evaluate_run(
                    run, provision,
                    "Seeed Studio XIAO ESP32C6 4MB negative",
                )

        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            s3_run, s3_provision = _make_run(
                base, "aitrip-esp32s3-devkitc-1-n8r2", "single-s3-uid"
            )
            _evaluate_run(
                s3_run, s3_provision,
                "AITRIP ESP32-S3-DevKitC-1 N8R2 single",
            )
            with self.assertRaises(evaluate_hp5_5_network_hardware.EvaluationError):
                evaluate_hp5_5_network_hardware.evaluate(
                    s3_run, base / "missing-c6", base / "not-created"
                )

        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            s3_run, s3_provision = _make_run(
                base, "aitrip-esp32s3-devkitc-1-n8r2", "duplicate-board-uid"
            )
            c6_run, c6_provision = _make_run(
                base, "seeed-xiao-esp32c6-4m", "duplicate-board-uid"
            )
            _evaluate_run(
                s3_run, s3_provision,
                "AITRIP ESP32-S3-DevKitC-1 N8R2 duplicate identity",
            )
            _evaluate_run(
                c6_run, c6_provision,
                "Seeed Studio XIAO ESP32C6 4MB duplicate identity",
            )
            with self.assertRaises(evaluate_hp5_5_network_hardware.EvaluationError):
                evaluate_hp5_5_network_hardware.evaluate(
                    s3_run, c6_run, base / "duplicate-aggregate"
                )


if __name__ == "__main__":
    unittest.main()
