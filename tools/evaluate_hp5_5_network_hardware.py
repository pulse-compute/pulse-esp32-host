#!/usr/bin/env python3
"""Aggregate two accepted named-board HP5.5 network/admin reports."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

try:
    from tools import build_hp5_5_network_hardware
except ModuleNotFoundError:
    import build_hp5_5_network_hardware  # type: ignore[no-redef]


ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN = ROOT / "tests/hardware-in-loop/hp5_5-network-admin/campaign.json"
MODEL = ROOT / "specs/PULSE-ESP32-015-network-administration-physical-seal.json"
BOARD_SCHEMA = "pulse.esp32.hp5_5-network-admin-board-evidence.v1"
AGGREGATE = "DUAL_NAMED_BOARD_HP5_NETWORK_ADMIN_OBSERVED"


class EvaluationError(RuntimeError):
    """Raised when evidence cannot support the HP5.5 physical aggregate."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise EvaluationError(f"JSON object required: {path}")
    return value


def hex64(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise EvaluationError(f"{label} must be lowercase SHA-256")
    return value


def prepare_output(path: Path) -> Path:
    output = path.expanduser().resolve()
    try:
        output.relative_to(ROOT)
    except ValueError:
        pass
    else:
        raise EvaluationError("dual-board evidence output must remain outside source")
    if output.exists():
        if not output.is_dir() or any(output.iterdir()):
            raise EvaluationError("output directory must be absent or empty")
    else:
        output.mkdir(parents=True)
    return output


def validate_campaign() -> tuple[dict[str, Any], dict[str, Any]]:
    if (
        sha256(CAMPAIGN) != build_hp5_5_network_hardware.EXPECTED_CAMPAIGN_SHA256
        or sha256(MODEL) != build_hp5_5_network_hardware.EXPECTED_MODEL_SHA256
    ):
        raise EvaluationError("HP5.5 campaign or model hash drifted")
    campaign = load_json(CAMPAIGN)
    model = load_json(MODEL)
    if (
        campaign.get("schema") != "pulse.esp32.hp5_5-network-admin-hardware-campaign.v1"
        or campaign.get("campaign_id") != "hp5_5-dual-network-admin-v1"
        or campaign.get("pass") != "HP5.5"
        or campaign.get("status") != "FROZEN"
        or campaign.get("execution_status") != "NOT_RUN"
        or campaign.get("promotion") != {
            "both_complete_named_board_runs": AGGREGATE,
            "single_missing_synthetic_or_unbound_run": "HARDWARE_PENDING",
        }
    ):
        raise EvaluationError("frozen HP5.5 campaign identity drifted")
    lanes = campaign.get("board_lanes")
    checkpoints = campaign.get("checkpoints")
    if (
        not isinstance(lanes, list)
        or len(lanes) != 2
        or {lane.get("target") for lane in lanes} != {"esp32s3", "esp32c6"}
        or not isinstance(checkpoints, list)
        or len(checkpoints) != 29
        or len({item.get("id") for item in checkpoints}) != 29
    ):
        raise EvaluationError("HP5.5 requires two exact lanes and 29 unique checkpoints")
    if (
        model.get("schema") != "pulse.esp32.hp5_5-network-administration-physical-seal.v1"
        or model.get("status") != "READY_FOR_PHYSICAL_EXECUTION"
        or model.get("aggregate") != "HARDWARE_PENDING"
        or model.get("claim", {}).get("dual_named_board_physical_execution") is not False
        or model.get("physical_campaign", {}).get("expected_aggregate") != AGGREGATE
    ):
        raise EvaluationError("source model is not the honest pre-execution HP5.5 authority")
    guardrails = campaign.get("guardrails", {})
    for field in (
        "named_board_identity_required",
        "operator_attested_marking_required",
        "full_flash_backup_required",
        "fresh_full_flash_erase_required",
        "restore_path_required",
        "test_provisioning_external_to_source",
        "secrets_forbidden_in_retained_evidence",
        "new_target_contracts_required",
        "historical_hp2_authorities_must_remain_unchanged",
        "application_and_admin_listener_separation_required",
        "exclusive_update_required_on_both_targets",
    ):
        if guardrails.get(field) is not True:
            raise EvaluationError(f"required HP5.5 guardrail missing: {field}")
    for field in (
        "factory_host_partition_write_allowed",
        "host_firmware_ota",
        "bootloader_ota",
        "partition_table_ota",
        "partition_redesign",
        "external_provider",
        "mqtt",
        "rax",
    ):
        if guardrails.get(field) is not False:
            raise EvaluationError(f"forbidden HP5.5 scope enabled: {field}")
    return campaign, model


def evidence_file(run: Path, name: str, digest: Any, size: int | None = None) -> Path:
    path = run / name
    if not path.is_file() or sha256(path) != hex64(digest, f"{name}.sha256"):
        raise EvaluationError(f"retained lane evidence mismatch: {path}")
    if size is not None and path.stat().st_size != size:
        raise EvaluationError(f"retained lane evidence size mismatch: {path}")
    return path


def serial_board_uids(path: Path) -> set[str]:
    """Recover the independently retained boot UID binding from a lane log."""

    values: list[str] = []
    marker = "PULSE_HP55_BOOT "
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8", errors="strict").splitlines(), 1
    ):
        if marker not in line:
            continue
        try:
            record = json.loads(line.split(marker, 1)[1].strip())
        except json.JSONDecodeError as exc:
            raise EvaluationError(
                f"malformed retained boot marker on line {line_number}"
            ) from exc
        if not isinstance(record, dict):
            raise EvaluationError("retained boot marker must contain an object")
        values.append(
            hex64(record.get("physical_board_uid_sha256"), "serial physical board UID")
        )
    if len(values) != 5 or len(set(values)) != 1:
        raise EvaluationError("retained serial log must bind five boots to one board UID")
    return set(values)


def validate_lane(
    run_dir: Path,
    expected: dict[str, Any],
    campaign: dict[str, Any],
) -> tuple[dict[str, Any], Path]:
    run = run_dir.expanduser().resolve()
    report_path = run / "board-report.json"
    if not report_path.is_file():
        raise EvaluationError(
            f"missing board-report.json in {run}; run the per-board evaluator first"
        )
    report = load_json(report_path)
    required_fields = {
        "schema", "pass", "status", "evidence_origin", "campaign_id",
        "campaign_sha256", "model_sha256", "board_id", "target",
        "flash_bytes", "psram_bytes", "plan_sha256", "lock_sha256",
        "fingerprint_sha256", "physical_board_uid_sha256",
        "module_or_board_marking", "operator_attestation", "evidence",
        "secret_scan", "runtime_floors", "checkpoints", "claim_boundary",
    }
    if set(report) != required_fields or (
        report.get("schema") != BOARD_SCHEMA
        or report.get("pass") != "HP5.5"
        or report.get("status") != "PASS"
        or report.get("evidence_origin") != "PHYSICAL_NAMED_BOARD"
        or report.get("campaign_id") != campaign["campaign_id"]
        or report.get("campaign_sha256") != sha256(CAMPAIGN)
        or report.get("model_sha256") != sha256(MODEL)
    ):
        raise EvaluationError("lane report is not exact passing physical HP5.5 evidence")
    for field in (
        "board_id", "target", "flash_bytes", "psram_bytes",
        "plan_sha256", "lock_sha256", "fingerprint_sha256",
    ):
        if report.get(field) != expected.get(field):
            raise EvaluationError(f"named-board lane binding mismatch: {field}")
    uid = hex64(report.get("physical_board_uid_sha256"), "physical_board_uid_sha256")
    marking = report.get("module_or_board_marking")
    if not isinstance(marking, str) or not marking.strip():
        raise EvaluationError("operator-attested module or board marking is missing")
    attestation = report.get("operator_attestation")
    if not isinstance(attestation, dict):
        raise EvaluationError("operator attestation is incomplete")
    restore_command = attestation.get("restore_command_recorded")
    if attestation != {
        "operator_attended": True,
        "fresh_full_flash_erase": True,
        "restore_command_recorded": restore_command,
        "full_flash_backup_local_only": True,
    } or not isinstance(restore_command, str) or not restore_command.strip():
        raise EvaluationError("operator attestation is incomplete")
    evidence = report.get("evidence")
    if not isinstance(evidence, dict) or set(evidence) != {
        "build_report_sha256", "serial_log_sha256", "network_transcript_sha256",
        "full_flash_backup_sha256", "full_flash_backup_bytes",
        "full_flash_backup_publishable",
    } or evidence.get("full_flash_backup_publishable") is not False:
        raise EvaluationError("lane evidence inventory fields drifted")
    evidence_file(run, "build-report.json", evidence.get("build_report_sha256"))
    serial_path = evidence_file(run, "serial.log", evidence.get("serial_log_sha256"))
    if serial_board_uids(serial_path) != {uid}:
        raise EvaluationError("lane report UID does not match its retained serial boots")
    evidence_file(
        run, "network-transcript.jsonl", evidence.get("network_transcript_sha256")
    )
    if evidence.get("full_flash_backup_bytes") != expected["flash_bytes"]:
        raise EvaluationError("full-flash backup byte count does not match lane")
    evidence_file(
        run, "full-flash-backup.bin", evidence.get("full_flash_backup_sha256"),
        expected["flash_bytes"],
    )
    if report.get("secret_scan") != {
        "status": "PASS",
        "secret_values_checked": 6,
        "retained_files_checked": 3,
        "raw_secret_values_retained": False,
    }:
        raise EvaluationError("lane retained-evidence secret scan did not pass exactly")
    floors = report.get("runtime_floors")
    if not isinstance(floors, dict) or set(floors) != {
        "minimum_internal_free_bytes", "minimum_internal_largest_block_bytes",
        "minimum_psram_free_bytes",
    }:
        raise EvaluationError("runtime floor fields drifted")
    for observed, minimum in (
        (floors.get("minimum_internal_free_bytes"), expected["minimum_runtime_internal_free_bytes"]),
        (floors.get("minimum_internal_largest_block_bytes"), expected["minimum_runtime_largest_block_bytes"]),
        (floors.get("minimum_psram_free_bytes"), expected["minimum_runtime_psram_free_bytes"]),
    ):
        if not isinstance(observed, int) or isinstance(observed, bool) or observed < minimum:
            raise EvaluationError("runtime floor did not meet the named-board requirement")
    expected_ids = [item["id"] for item in campaign["checkpoints"]]
    checkpoints = report.get("checkpoints")
    if (
        not isinstance(checkpoints, list)
        or [item.get("id") for item in checkpoints if isinstance(item, dict)] != expected_ids
        or len(checkpoints) != len(expected_ids)
    ):
        raise EvaluationError("lane checkpoint order or count drifted")
    for item in checkpoints:
        if (
            not isinstance(item, dict)
            or set(item) != {"id", "status", "observations"}
            or item.get("status") != "PASS"
            or not isinstance(item.get("observations"), list)
            or not item["observations"]
            or any(not isinstance(value, str) or not value for value in item["observations"])
        ):
            raise EvaluationError("every physical checkpoint needs a nonempty PASS observation")
    if report.get("claim_boundary") != {
        "factory_host_partition_written": False,
        "host_firmware_ota": False,
        "bootloader_ota": False,
        "partition_table_ota": False,
        "production_authenticator": False,
        "test_provision_publishable": False,
    }:
        raise EvaluationError("lane report exceeded the HP5.5 claim boundary")
    return ({
        "board_id": report["board_id"],
        "target": report["target"],
        "module_or_board_marking": marking.strip(),
        "physical_board_uid_sha256": uid,
        "plan_sha256": report["plan_sha256"],
        "lock_sha256": report["lock_sha256"],
        "fingerprint_sha256": report["fingerprint_sha256"],
        "board_report_sha256": sha256(report_path),
        "build_report_sha256": evidence["build_report_sha256"],
        "serial_log_sha256": evidence["serial_log_sha256"],
        "network_transcript_sha256": evidence["network_transcript_sha256"],
        "full_flash_backup_sha256": evidence["full_flash_backup_sha256"],
        "checkpoints": len(checkpoints),
        "runtime_floors": floors,
    }, report_path)


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def evaluate(s3_run: Path, c6_run: Path, out_dir: Path) -> dict[str, Any]:
    campaign, _model = validate_campaign()
    lanes = {lane["target"]: lane for lane in campaign["board_lanes"]}
    s3, s3_report = validate_lane(s3_run, lanes["esp32s3"], campaign)
    c6, c6_report = validate_lane(c6_run, lanes["esp32c6"], campaign)
    if s3["physical_board_uid_sha256"] == c6["physical_board_uid_sha256"]:
        raise EvaluationError("the two physical board identities must be distinct")
    if s3["module_or_board_marking"] == c6["module_or_board_marking"]:
        raise EvaluationError("the two operator-attested board markings must be distinct")
    output = prepare_output(out_dir)
    report = {
        "schema": "pulse.esp32.hp5_5-network-admin-dual-board-evaluation.v1",
        "pass": "HP5.5",
        "status": "PASS",
        "evidence_origin": "DUAL_PHYSICAL_NAMED_BOARD",
        "aggregate": AGGREGATE,
        "campaign_id": campaign["campaign_id"],
        "campaign_sha256": sha256(CAMPAIGN),
        "model_sha256": sha256(MODEL),
        "lanes": [s3, c6],
        "coverage": {
            "physical_named_boards": 2,
            "distinct_physical_board_uids": 2,
            "checkpoints_per_board": 29,
            "application_tls_port": campaign["environment"]["application_port"],
            "administration_tls_port": campaign["environment"]["administration_port"],
            "idf_version": campaign["environment"]["idf_version"],
        },
        "claim_boundary": {
            "factory_host_partition_written": False,
            "host_firmware_ota": False,
            "bootloader_ota": False,
            "partition_table_ota": False,
            "production_authenticator": False,
            "external_provider": False,
            "mqtt": False,
            "rax": False,
        },
        "promotion": {
            "hp5_5_physical_barrier": "ACCEPTED",
            "hp6_entry": "UNBLOCKED_BY_HP5_5_ONLY",
        },
    }
    aggregate_path = output / "dual-board-evaluation.json"
    write_json(aggregate_path, report)
    retained = []
    for source, name in (
        (s3_report, "s3-board-report.json"),
        (c6_report, "c6-board-report.json"),
    ):
        target = output / name
        target.write_bytes(source.read_bytes())
        retained.append(target)
    artifacts = [aggregate_path, *retained]
    manifest = {
        "schema": "pulse.esp32.hp5_5-network-admin-evidence-manifest.v1",
        "status": "PASS",
        "aggregate": AGGREGATE,
        "artifacts": [
            {"path": path.name, "sha256": sha256(path), "size": path.stat().st_size}
            for path in artifacts
        ],
        "nonpublishable_artifacts_excluded": [
            "full-flash-backup.bin", "test-provision", "staged-project"
        ],
    }
    write_json(output / "evidence-manifest.json", manifest)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--s3-run", type=Path, required=True)
    parser.add_argument("--c6-run", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = evaluate(args.s3_run, args.c6_run, args.out_dir)
    except (OSError, ValueError, KeyError, json.JSONDecodeError, EvaluationError) as exc:
        print(f"HP5.5 dual-board evaluation failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({
        "status": report["status"],
        "aggregate": report["aggregate"],
        "out_dir": str(args.out_dir.expanduser().resolve()),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
