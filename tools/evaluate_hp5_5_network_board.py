#!/usr/bin/env python3
"""Evaluate one real named-board HP5.5 network/admin run."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

try:
    from tools import build_hp5_5_network_hardware
except ModuleNotFoundError:
    import build_hp5_5_network_hardware  # type: ignore[no-redef]


ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN = ROOT / "tests/hardware-in-loop/hp5_5-network-admin/campaign.json"
BOOT_MARKER = "PULSE_HP55_BOOT "
CHECKPOINT_MARKER = "PULSE_HP55_CHECKPOINT "
STATS_MARKER = "PULSE_HP55_STATS "
FINAL_MARKER = "PULSE_HP55_FINAL "
FATAL_MARKER = "PULSE_HP55_FATAL "


class BoardEvaluationError(RuntimeError):
    """Raised when one run cannot support named-board physical evidence."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise BoardEvaluationError(f"JSON object required: {path}")
    return value


def hex64(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise BoardEvaluationError(f"{label} must be lowercase SHA-256")
    return value


def resolve_evidence(run: Path, evidence: Any, label: str) -> Path:
    if not isinstance(evidence, dict) or set(evidence) != {"path", "sha256", "size"}:
        raise BoardEvaluationError(f"{label} evidence fields are not exact")
    relative = evidence.get("path")
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise BoardEvaluationError(f"{label} evidence path must be relative")
    path = (run / relative).resolve()
    try:
        path.relative_to(run)
    except ValueError as exc:
        raise BoardEvaluationError(f"{label} evidence escapes the run directory") from exc
    if (
        not path.is_file()
        or path.stat().st_size != evidence.get("size")
        or sha256(path) != hex64(evidence.get("sha256"), f"{label}.sha256")
    ):
        raise BoardEvaluationError(f"{label} evidence hash or size mismatch")
    return path


def parse_markers(text: str, marker: str) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), 1):
        if marker not in line:
            continue
        try:
            value = json.loads(line.split(marker, 1)[1].strip())
        except json.JSONDecodeError as exc:
            raise BoardEvaluationError(
                f"malformed {marker.strip()} JSON on line {line_number}"
            ) from exc
        if not isinstance(value, dict):
            raise BoardEvaluationError(f"{marker.strip()} must contain an object")
        values.append(value)
    return values


def validate_build(run: Path, report: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    campaign = load_json(CAMPAIGN)
    required_report_fields = {
        "schema", "status", "evidence_origin", "campaign_id",
        "campaign_sha256", "model_sha256", "board_id", "target",
        "flash_bytes", "psram_bytes", "plan_sha256", "lock_sha256",
        "fingerprint_sha256", "predecessor_archive", "execution_source",
        "board_identity", "partition_table", "dependency_lock",
        "fixture_artifacts", "client_artifacts", "source_seals", "provision",
        "staged_project", "staged_repository", "operator_contract",
        "commands", "claim_boundary", "firmware",
    }
    if (
        set(report) != required_report_fields
        or sha256(CAMPAIGN) != build_hp5_5_network_hardware.EXPECTED_CAMPAIGN_SHA256
        or report.get("schema") != build_hp5_5_network_hardware.REPORT_SCHEMA
        or report.get("status") != "PASS"
        or report.get("evidence_origin") != "SEALED_SOURCE_PHYSICAL_BUILD"
        or report.get("campaign_id") != campaign.get("campaign_id")
        or report.get("campaign_sha256") != sha256(CAMPAIGN)
        or report.get("model_sha256") != build_hp5_5_network_hardware.EXPECTED_MODEL_SHA256
        or report.get("execution_source") != build_hp5_5_network_hardware.EXPECTED_FIRMWARE
        or report.get("claim_boundary", {}).get("build") != "BUILD_PROVEN"
        or report.get("claim_boundary", {}).get("runtime") != "HARDWARE_NOT_RUN"
    ):
        raise BoardEvaluationError("build report is not a proven HP5.5 build")
    board_id = report.get("board_id")
    if board_id not in build_hp5_5_network_hardware.BOARD_CONFIGS:
        raise BoardEvaluationError("build report names an unsupported board")
    lanes = {item.get("board_id"): item for item in campaign.get("board_lanes", [])}
    lane = lanes.get(board_id)
    if lane is None:
        raise BoardEvaluationError("build board is absent from the frozen campaign")
    for field in (
        "board_id", "target", "flash_bytes", "psram_bytes",
        "plan_sha256", "lock_sha256", "fingerprint_sha256",
    ):
        if report.get(field) != lane.get(field):
            raise BoardEvaluationError(f"build board/target contract mismatch: {field}")
    expected_predecessor = {
        "name": build_hp5_5_network_hardware.EXPECTED_PREDECESSOR["name"],
        "sha256": build_hp5_5_network_hardware.EXPECTED_PREDECESSOR["sha256"],
        "size": build_hp5_5_network_hardware.EXPECTED_PREDECESSOR["size"],
        "archive_root": build_hp5_5_network_hardware.EXPECTED_PREDECESSOR["root"],
        "manifested_files": build_hp5_5_network_hardware.EXPECTED_PREDECESSOR["file_count"],
        "manifested_payload_bytes": build_hp5_5_network_hardware.EXPECTED_PREDECESSOR["payload_bytes"],
    }
    if report.get("predecessor_archive") != expected_predecessor:
        raise BoardEvaluationError("build does not bind the sealed HP5 predecessor")
    board = resolve_evidence(run, report.get("board_identity"), "board_identity")
    partitions = resolve_evidence(run, report.get("partition_table"), "partition_table")
    dependency = resolve_evidence(run, report.get("dependency_lock"), "dependency_lock")
    config = build_hp5_5_network_hardware.BOARD_CONFIGS[board_id]
    if (
        sha256(board) != lane.get("board_sha256")
        or sha256(partitions) != lane.get("partitions_sha256")
        or sha256(dependency) != config["dependency_lock_sha256"]
    ):
        raise BoardEvaluationError("canonical build input authority drifted")
    firmware = report.get("firmware")
    if not isinstance(firmware, dict) or firmware.get("status") != "PASS":
        raise BoardEvaluationError("firmware build evidence is not PASS")
    if set(firmware) != {
        "status", "result", "environment", "commands", "sdkconfig", "size",
        "headroom_gate", "artifacts", "build_log",
    } or firmware.get("result") != "BUILD_PROVEN":
        raise BoardEvaluationError("firmware build report fields are not exact")
    headroom = firmware.get("headroom_gate", {})
    size_report = firmware.get("size")
    if (
        not isinstance(headroom, dict)
        or set(headroom) != {
            "status", "minimum_diram_remain_bytes",
            "observed_diram_remain_bytes", "application_partition_bytes",
            "application_binary_bytes",
        }
        or headroom.get("status") != "PASS"
        or headroom.get("minimum_diram_remain_bytes")
            != build_hp5_5_network_hardware.BOARD_CONFIGS[board_id][
                "minimum_diram_remain_bytes"
            ]
        or not isinstance(headroom.get("observed_diram_remain_bytes"), int)
        or isinstance(headroom.get("observed_diram_remain_bytes"), bool)
        or headroom["observed_diram_remain_bytes"]
            < lane.get("minimum_build_diram_remain_bytes", 0)
        or headroom.get("application_partition_bytes") != 2 * 1024 * 1024
        or not isinstance(headroom.get("application_binary_bytes"), int)
        or isinstance(headroom.get("application_binary_bytes"), bool)
        or headroom["application_binary_bytes"] < 1
        or headroom["application_binary_bytes"]
            > headroom["application_partition_bytes"]
        or not isinstance(size_report, dict)
        or not isinstance(size_report.get("diram_remain"), int)
        or isinstance(size_report.get("diram_remain"), bool)
        or size_report.get("diram_remain")
            != headroom["observed_diram_remain_bytes"]
    ):
        raise BoardEvaluationError("firmware build headroom gate failed")
    artifacts = firmware.get("artifacts")
    if not isinstance(artifacts, dict):
        raise BoardEvaluationError("firmware artifact inventory is missing")
    resolved_artifacts: dict[str, Path] = {}
    for name in (
        "application_elf", "application_binary", "application_map",
        "bootloader_binary", "partition_table_binary", "flasher_args", "flash_args",
    ):
        resolved_artifacts[name] = resolve_evidence(
            run, artifacts.get(name), f"firmware.{name}"
        )
    if (
        resolved_artifacts["application_binary"].stat().st_size
        != headroom["application_binary_bytes"]
    ):
        raise BoardEvaluationError("application binary size and headroom report differ")
    sdkconfig = resolve_evidence(
        run, firmware.get("sdkconfig"), "firmware.sdkconfig"
    )
    try:
        build_hp5_5_network_hardware.validate_sdkconfig(sdkconfig, board_id)
    except build_hp5_5_network_hardware.HardwareBuildError as exc:
        raise BoardEvaluationError("retained sdkconfig drifted") from exc
    resolve_evidence(run, firmware.get("build_log"), "firmware.build_log")
    environment = firmware.get("environment", {})
    if (
        environment.get("schema") != "pulse.esp32.idf-environment.v1"
        or environment.get("status") != "PASS"
        or environment.get("version") != campaign["environment"]["idf_version"]
        or environment.get("source_commit") != campaign["environment"]["idf_source_commit"]
        or environment.get("platform_scope") != "NAMED_BOARD_HP5_5_NETWORK_ADMIN_BUILD"
    ):
        raise BoardEvaluationError("firmware was not built in the frozen ESP-IDF lane")
    if report.get("fixture_artifacts") != build_hp5_5_network_hardware.hp5_5_fixture.artifact_inventory():
        raise BoardEvaluationError("deterministic HP5.5 fixture artifacts drifted")
    client_artifacts = report.get("client_artifacts")
    if not isinstance(client_artifacts, dict) or set(client_artifacts) != {"positive", "fallback"}:
        raise BoardEvaluationError("client artifact inventory is not exact")
    for role in ("positive", "fallback"):
        path = resolve_evidence(run, client_artifacts[role], f"client_artifacts.{role}")
        expected = report["fixture_artifacts"][role]
        if path.stat().st_size != expected["bytes"] or sha256(path) != expected["sha256"]:
            raise BoardEvaluationError(f"client {role} artifact drifted")
    expected_source_seals = build_hp5_5_network_hardware.staged_source_seals(
        run, run / "project", run / "source"
    )
    if report.get("source_seals") != expected_source_seals:
        raise BoardEvaluationError("physical link source seal drifted")
    if report.get("operator_contract") != {
        "full_flash_backup_required": True,
        "fresh_full_flash_erase_required": True,
        "operator_attended": True,
        "restore_path_required": True,
        "serial_log_required": True,
        "network_transcript_required": True,
        "test_provision_nonpublishable": True,
    }:
        raise BoardEvaluationError("operator safety contract drifted")
    if (
        report.get("staged_project") != "project"
        or report.get("staged_repository") != "source"
        or report.get("commands")
            != build_hp5_5_network_hardware.operator_commands(board_id)
    ):
        raise BoardEvaluationError("path-neutral operator command contract drifted")
    return campaign, lane


def validate_provision(provision: Path, report: dict[str, Any]) -> None:
    manifest, _blobs = build_hp5_5_network_hardware.load_provision(provision)
    expected = {
        "publishable": False,
        "certificate_sha256": manifest["certificate_sha256"],
        "admin_proof_sha256": manifest["admin_proof_sha256"],
        "channel_binding_sha256": manifest["channel_binding_sha256"],
        "secret_scan_required": True,
        "secret_values_retained_in_report": False,
    }
    if report.get("provision") != expected:
        raise BoardEvaluationError("evaluation provision does not match the built firmware")


def validate_transcript(
    path: Path, campaign: dict[str, Any], lane: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[str]]:
    records: list[dict[str, Any]] = []
    expected_fields = {
        "schema", "campaign_id", "board_id", "ordinal",
        "checkpoint_ordinal", "checkpoint_id", "lane", "operation",
        "http_status", "protocol_status", "response_bytes",
        "response_sha256", "detail",
    }
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line:
            raise BoardEvaluationError("transcript contains an empty record")
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise BoardEvaluationError(f"malformed transcript line {line_number}") from exc
        if not isinstance(record, dict) or set(record) != expected_fields:
            raise BoardEvaluationError("transcript record fields are not exact")
        if (
            record.get("schema") != "pulse.esp32.hp5_5-network-transcript-record.v1"
            or record.get("campaign_id") != campaign["campaign_id"]
            or record.get("board_id") != lane["board_id"]
            or record.get("ordinal") != line_number
            or not isinstance(record.get("operation"), str)
            or not record["operation"]
            or record.get("lane") not in {
                "application", "administration", "both", "firmware"
            }
            or (
                record.get("http_status") is not None
                and (
                    not isinstance(record["http_status"], int)
                    or isinstance(record["http_status"], bool)
                    or not 100 <= record["http_status"] <= 599
                )
            )
            or (
                record.get("protocol_status") is not None
                and (
                    not isinstance(record["protocol_status"], int)
                    or isinstance(record["protocol_status"], bool)
                )
            )
            or not isinstance(record.get("response_bytes"), int)
            or isinstance(record.get("response_bytes"), bool)
            or record["response_bytes"] < 0
            or ((record.get("checkpoint_id") is None)
                != (record.get("checkpoint_ordinal") is None))
        ):
            raise BoardEvaluationError("transcript identity or ordinal drifted")
        hex64(record.get("response_sha256"), "transcript.response_sha256")
        if (
            not isinstance(record.get("detail"), str)
            or (record.get("checkpoint_id") is not None and not record["detail"])
        ):
            raise BoardEvaluationError("transcript detail must be a string")
        records.append(record)
    if not records:
        raise BoardEvaluationError("network transcript is empty")
    checkpoints = [record for record in records if record.get("checkpoint_id") is not None]
    ids = [record["checkpoint_id"] for record in checkpoints]
    if len(ids) != len(set(ids)):
        raise BoardEvaluationError("transcript checkpoint IDs are duplicated")
    if [record.get("checkpoint_ordinal") for record in checkpoints] != list(
        range(1, len(checkpoints) + 1)
    ):
        raise BoardEvaluationError("transcript checkpoint ordinals are not contiguous")
    campaign_ids = [item["id"] for item in campaign["checkpoints"]]
    positions = []
    for identifier in ids:
        if identifier not in campaign_ids:
            raise BoardEvaluationError("transcript contains an unknown checkpoint")
        positions.append(campaign_ids.index(identifier))
    if positions != sorted(positions):
        raise BoardEvaluationError("transcript checkpoints were reordered")
    return records, ids


def scan_secrets(provision: Path, retained: list[Path]) -> dict[str, Any]:
    secret_names = (
        "wifi-ssid.bin", "wifi-password.bin", "server-cert.pem",
        "server-key.pem", "admin-proof.bin", "channel-binding.bin",
    )
    secrets: list[tuple[str, bytes]] = []
    for name in secret_names:
        path = provision / name
        if not path.is_file():
            raise BoardEvaluationError(f"provision secret is missing: {name}")
        value = path.read_bytes()
        if value:
            secrets.append((name, value))
    for evidence in retained:
        data = evidence.read_bytes()
        for name, value in secrets:
            if value in data:
                raise BoardEvaluationError(
                    f"nonpublishable provision value {name} leaked into {evidence.name}"
                )
    return {
        "status": "PASS",
        "secret_values_checked": len(secrets),
        "retained_files_checked": len(retained),
        "raw_secret_values_retained": False,
    }


def validate_operator_inputs(
    lane: dict[str, Any], marking: str, restore_command: str
) -> tuple[str, str]:
    normalized_marking = re.sub(r"[^A-Z0-9]", "", marking.upper())
    required_marking_tokens = {
        "esp32s3": ("AITRIP", "ESP32S3", "DEVKITC1", "N8R2"),
        "esp32c6": ("XIAO", "ESP32C6"),
    }[lane["target"]]
    if any(token not in normalized_marking for token in required_marking_tokens):
        raise BoardEvaluationError(
            "operator marking does not identify the exact named-board lane"
        )
    restore = restore_command.strip()
    lower_restore = restore.lower()
    if (
        "esptool" not in lower_restore
        or "write_flash" not in lower_restore
        or "full-flash-backup.bin" not in lower_restore
        or re.search(
            rf"--chip(?:=|\s+){re.escape(lane['target'])}(?:\s|$)",
            lower_restore,
        )
        is None
        or re.search(r"(?:^|\s)(?:0|0x0+)(?:\s|$)", lower_restore) is None
    ):
        raise BoardEvaluationError(
            "restore command must bind esptool, the lane chip, offset zero, and the full backup"
        )
    return marking.strip(), restore


def evaluate(
    run_dir: Path,
    provision_dir: Path,
    marking: str,
    restore_command: str,
    fresh_erase_attested: bool,
    operator_attended: bool,
) -> dict[str, Any]:
    run = run_dir.expanduser().resolve()
    provision = provision_dir.expanduser().resolve()
    report_path = run / "build-report.json"
    serial_path = run / "serial.log"
    transcript_path = run / "network-transcript.jsonl"
    backup_path = run / "full-flash-backup.bin"
    for path in (report_path, serial_path, transcript_path, backup_path):
        if not path.is_file():
            raise BoardEvaluationError(f"required run artifact is missing: {path}")
    if not marking.strip() or not restore_command.strip():
        raise BoardEvaluationError("board marking and restore command are required")
    if not fresh_erase_attested or not operator_attended:
        raise BoardEvaluationError("fresh erase and attended operation must be attested")
    build = load_json(report_path)
    campaign, lane = validate_build(run, build)
    marking, restore_command = validate_operator_inputs(
        lane, marking, restore_command
    )
    validate_provision(provision, build)
    if backup_path.stat().st_size != lane["flash_bytes"]:
        raise BoardEvaluationError("full-flash backup size does not match the named board")
    serial_text = serial_path.read_text(encoding="utf-8", errors="strict")
    lower_serial = serial_text.lower()
    for forbidden in (
        "guru meditation", "abort() was called", "task watchdog got triggered",
        "stack canary watchpoint triggered", "brownout detector was triggered",
    ):
        if forbidden in lower_serial:
            raise BoardEvaluationError(f"target log contains a fatal runtime token: {forbidden}")
    if parse_markers(serial_text, FATAL_MARKER):
        raise BoardEvaluationError("target emitted an HP5.5 fatal marker")
    boots = parse_markers(serial_text, BOOT_MARKER)
    serial_checkpoints = parse_markers(serial_text, CHECKPOINT_MARKER)
    stats = parse_markers(serial_text, STATS_MARKER)
    finals = parse_markers(serial_text, FINAL_MARKER)
    if len(boots) != 5 or len(stats) < 3 or len(finals) != 1:
        raise BoardEvaluationError(
            "serial log must retain five boots, three stats snapshots, and one final"
        )
    uid: str | None = None
    fingerprint_target = 1 if lane["target"] == "esp32s3" else 2
    expected_boot_fields = {
        "schema", "campaign_id", "campaign_sha256", "board_id", "target",
        "flash_bytes", "psram_bytes", "physical_board_uid_sha256",
        "plan_sha256", "lock_sha256", "fingerprint_sha256", "fingerprint_target",
    }
    for boot in boots:
        if set(boot) != expected_boot_fields or (
            boot.get("schema") != "pulse.esp32.hp5_5-boot.v1"
            or boot.get("campaign_id") != campaign["campaign_id"]
            or boot.get("campaign_sha256") != sha256(CAMPAIGN)
            or boot.get("fingerprint_target") != fingerprint_target
        ):
            raise BoardEvaluationError("serial boot identity fields drifted")
        for field in (
            "board_id", "target", "flash_bytes", "psram_bytes",
            "plan_sha256", "lock_sha256", "fingerprint_sha256",
        ):
            if boot.get(field) != lane[field]:
                raise BoardEvaluationError(f"serial boot target binding mismatch: {field}")
        observed_uid = hex64(boot.get("physical_board_uid_sha256"), "physical board UID")
        if uid is None:
            uid = observed_uid
        elif uid != observed_uid:
            raise BoardEvaluationError("physical board UID changed across expected reboots")
    assert uid is not None
    for item in serial_checkpoints:
        if (
            set(item) != {"schema", "id", "detail"}
            or item.get("schema") != "pulse.esp32.hp5_5-checkpoint.v1"
            or not isinstance(item.get("detail"), str)
            or not item["detail"]
        ):
            raise BoardEvaluationError("serial checkpoint fields drifted")
    records, transcript_ids = validate_transcript(transcript_path, campaign, lane)
    serial_ids = {item["id"] for item in serial_checkpoints}
    expected_ids = [item["id"] for item in campaign["checkpoints"]]
    if set(expected_ids) != serial_ids.union(transcript_ids):
        missing = sorted(set(expected_ids) - serial_ids.union(transcript_ids))
        raise BoardEvaluationError("physical checkpoint coverage is incomplete: " + ", ".join(missing))
    required_stats = {
        "schema", "internal_free", "internal_largest", "psram_free",
        "minimum_internal_free", "minimum_internal_largest", "minimum_psram_free",
        "wifi_connected", "reconnect_count", "app_response_losses",
        "wifi_disconnect_observed", "wifi_reconnect_observed",
        "wifi_reconnect_elapsed_ms",
        "admin_response_losses", "admin_terminal_losses", "duplicate_rejections",
        "app_timeouts", "app_cancelled", "app_trapped",
    }
    numeric_stats = required_stats - {
        "schema", "wifi_connected", "wifi_disconnect_observed",
        "wifi_reconnect_observed",
    }
    for item in stats:
        if (
            set(item) != required_stats
            or item.get("schema") != "pulse.esp32.hp5_5-stats.v1"
            or not all(
                isinstance(item.get(field), int)
                and not isinstance(item.get(field), bool)
                and item[field] >= 0
                for field in numeric_stats
            )
            or item.get("wifi_connected") is not True
            or item.get("wifi_disconnect_observed") is not True
            or item.get("wifi_reconnect_observed") is not True
            or item.get("wifi_reconnect_elapsed_ms", 30001) > 30000
            or item["internal_free"] < item["minimum_internal_free"]
            or item["internal_largest"] < item["minimum_internal_largest"]
            or item["psram_free"] < item["minimum_psram_free"]
            or item.get("reconnect_count", 99) > 8
            or item.get("admin_response_losses", 0)
                < item.get("admin_terminal_losses", 0)
        ):
            raise BoardEvaluationError("an HP5.5 serial stats snapshot drifted")
    aggregate_stats = {
        "minimum_internal_free": min(item["minimum_internal_free"] for item in stats),
        "minimum_internal_largest": min(item["minimum_internal_largest"] for item in stats),
        "minimum_psram_free": min(item["minimum_psram_free"] for item in stats),
        "app_response_losses": max(item["app_response_losses"] for item in stats),
        "admin_terminal_losses": max(item["admin_terminal_losses"] for item in stats),
        "duplicate_rejections": max(item["duplicate_rejections"] for item in stats),
        "app_timeouts": max(item["app_timeouts"] for item in stats),
        "app_cancelled": max(item["app_cancelled"] for item in stats),
        "app_trapped": max(item["app_trapped"] for item in stats),
    }
    if (
        aggregate_stats["minimum_internal_free"]
            < lane["minimum_runtime_internal_free_bytes"]
        or aggregate_stats["minimum_internal_largest"]
            < lane["minimum_runtime_largest_block_bytes"]
        or aggregate_stats["minimum_psram_free"]
            < lane["minimum_runtime_psram_free_bytes"]
        or aggregate_stats["app_response_losses"] < 1
        or aggregate_stats["admin_terminal_losses"] < 1
        or aggregate_stats["duplicate_rejections"] < 1
        or aggregate_stats["app_timeouts"] < 1
        or aggregate_stats["app_cancelled"] < 1
        or aggregate_stats["app_trapped"] < 1
    ):
        raise BoardEvaluationError("runtime resource or containment counters did not pass")
    expected_final = {
        "schema": "pulse.esp32.hp5_5-final.v1",
        "status": "PASS",
        "campaign_id": campaign["campaign_id"],
        "board_id": lane["board_id"],
        "physical_board_uid_sha256": uid,
        "factory_host_partition_written": False,
        "host_firmware_ota": False,
    }
    if finals != [expected_final]:
        raise BoardEvaluationError("serial final marker is not the exact HP5.5 boundary")
    secret_scan = scan_secrets(provision, [report_path, serial_path, transcript_path])
    observations = []
    details_by_id: dict[str, list[str]] = {identifier: [] for identifier in expected_ids}
    for item in serial_checkpoints:
        if item["id"] in details_by_id:
            details_by_id[item["id"]].append("firmware: " + item["detail"])
    for record in records:
        identifier = record.get("checkpoint_id")
        if identifier in details_by_id:
            details_by_id[identifier].append("client: " + record["detail"])
    for identifier in expected_ids:
        if not details_by_id[identifier]:
            raise BoardEvaluationError(f"checkpoint has no observation: {identifier}")
        observations.append({
            "id": identifier,
            "status": "PASS",
            "observations": details_by_id[identifier],
        })
    report = {
        "schema": "pulse.esp32.hp5_5-network-admin-board-evidence.v1",
        "pass": "HP5.5",
        "status": "PASS",
        "evidence_origin": "PHYSICAL_NAMED_BOARD",
        "campaign_id": campaign["campaign_id"],
        "campaign_sha256": sha256(CAMPAIGN),
        "model_sha256": build_hp5_5_network_hardware.EXPECTED_MODEL_SHA256,
        "board_id": lane["board_id"],
        "target": lane["target"],
        "flash_bytes": lane["flash_bytes"],
        "psram_bytes": lane["psram_bytes"],
        "plan_sha256": lane["plan_sha256"],
        "lock_sha256": lane["lock_sha256"],
        "fingerprint_sha256": lane["fingerprint_sha256"],
        "physical_board_uid_sha256": uid,
        "module_or_board_marking": marking,
        "operator_attestation": {
            "operator_attended": True,
            "fresh_full_flash_erase": True,
            "restore_command_recorded": restore_command,
            "full_flash_backup_local_only": True,
        },
        "evidence": {
            "build_report_sha256": sha256(report_path),
            "serial_log_sha256": sha256(serial_path),
            "network_transcript_sha256": sha256(transcript_path),
            "full_flash_backup_sha256": sha256(backup_path),
            "full_flash_backup_bytes": backup_path.stat().st_size,
            "full_flash_backup_publishable": False,
        },
        "secret_scan": secret_scan,
        "runtime_floors": {
            "minimum_internal_free_bytes": aggregate_stats["minimum_internal_free"],
            "minimum_internal_largest_block_bytes": aggregate_stats["minimum_internal_largest"],
            "minimum_psram_free_bytes": aggregate_stats["minimum_psram_free"],
        },
        "checkpoints": observations,
        "claim_boundary": {
            "factory_host_partition_written": False,
            "host_firmware_ota": False,
            "bootloader_ota": False,
            "partition_table_ota": False,
            "production_authenticator": False,
            "test_provision_publishable": False,
        },
    }
    destination = run / "board-report.json"
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if destination.exists() and destination.read_text(encoding="utf-8") != rendered:
        raise BoardEvaluationError("refusing to replace a different board report")
    destination.write_text(rendered, encoding="utf-8")
    # The board report itself must also remain secret-free.
    scan_secrets(provision, [destination])
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--provision-dir", type=Path, required=True)
    parser.add_argument("--module-or-board-marking", required=True)
    parser.add_argument("--restore-command", required=True)
    parser.add_argument("--fresh-erase-attested", action="store_true")
    parser.add_argument("--operator-attended", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = evaluate(
            args.run_dir, args.provision_dir, args.module_or_board_marking,
            args.restore_command, args.fresh_erase_attested,
            args.operator_attended,
        )
    except (OSError, ValueError, KeyError, json.JSONDecodeError, BoardEvaluationError) as exc:
        print(f"HP5.5 board evaluation failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({
        "status": report["status"], "board_id": report["board_id"],
        "board_report": str(args.run_dir.expanduser().resolve() / "board-report.json"),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
