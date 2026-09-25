#!/usr/bin/env python3
"""Evaluate the two named-board HP3.5 safe slot/power-loss reports."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Optional


ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN = ROOT / "tests/hardware-in-loop/hp3_5-slot-power-loss/campaign.json"


class EvaluationError(RuntimeError):
    """Raised when evidence cannot support the dual-board physical claim."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise EvaluationError("JSON object required: %s" % path)
    return value


def _hex64(value: Any, name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise EvaluationError("%s must be lowercase SHA-256" % name)
    return value


def _prepare(path: Path) -> Path:
    output = path.expanduser().resolve()
    if output.exists():
        if not output.is_dir() or any(output.iterdir()):
            raise EvaluationError("output directory must be absent or empty")
    else:
        output.mkdir(parents=True)
    return output


def _validate_campaign(campaign: dict[str, Any]) -> None:
    if (
        campaign.get("schema")
        != "pulse.esp32.hp3_5-slot-hardware-campaign.v1"
        or campaign.get("campaign_id") != "hp3_5-safe-inactive-slot-v1"
        or campaign.get("status") != "FROZEN"
        or campaign.get("execution_status") != "NOT_RUN"
    ):
        raise EvaluationError("HP3.5 physical campaign drifted")
    lanes = campaign.get("board_lanes")
    checkpoints = campaign.get("checkpoints")
    if not isinstance(lanes, list) or len(lanes) != 2:
        raise EvaluationError("exactly two named-board lanes are required")
    if not isinstance(checkpoints, list) or len(checkpoints) != 13:
        raise EvaluationError("exactly thirteen safe checkpoints are required")
    if len({item.get("id") for item in checkpoints}) != len(checkpoints):
        raise EvaluationError("campaign checkpoint IDs must be unique")
    guardrails = campaign.get("guardrails", {})
    for field in (
        "named_board_identity_required",
        "canonical_partition_hash_required",
        "inactive_slot_only",
        "operator_attended",
        "full_flash_backup_required",
        "restore_path_required",
    ):
        if guardrails.get(field) is not True:
            raise EvaluationError("required physical guardrail missing: %s" % field)
    for field in (
        "confirmed_slot_write_allowed",
        "factory_host_partition_write_allowed",
        "host_firmware_ota",
        "gpio_or_external_loads",
        "network_or_provider",
    ):
        if guardrails.get(field) is not False:
            raise EvaluationError("forbidden physical scope enabled: %s" % field)


def _validate_lane(
    run_dir: Path,
    expected_lane: dict[str, Any],
    campaign: dict[str, Any],
    campaign_sha256: str,
) -> dict[str, Any]:
    resolved_run = run_dir.expanduser().resolve()
    report_path = resolved_run / "board-report.json"
    serial_path = resolved_run / "serial.log"
    backup_path = resolved_run / "full-flash-before.bin"
    if (
        not report_path.is_file()
        or not serial_path.is_file()
        or not backup_path.is_file()
    ):
        raise EvaluationError(
            "run directory is incomplete: "
            "board_report=%s (is_file=%s); serial_log=%s (is_file=%s); "
            "full_flash_backup=%s (is_file=%s). "
            "Run tools/evaluate_hp3_5_slot_board.py for this lane first."
            % (
                report_path,
                report_path.is_file(),
                serial_path,
                serial_path.is_file(),
                backup_path,
                backup_path.is_file(),
            )
        )
    if backup_path.stat().st_size != expected_lane["flash_bytes"]:
        raise EvaluationError(
            "full-flash backup size mismatch: %s has %d bytes, expected %d"
            % (
                backup_path,
                backup_path.stat().st_size,
                expected_lane["flash_bytes"],
            )
        )
    report = _load_json(report_path)
    required_fields = {
        "schema",
        "status",
        "evidence_origin",
        "campaign_id",
        "campaign_sha256",
        "board_id",
        "target",
        "flash_bytes",
        "psram_bytes",
        "module_or_board_marking",
        "physical_board_uid_sha256",
        "serial_log_sha256",
        "checkpoints",
        "invariants",
        "claim_boundary",
    }
    if set(report) != required_fields:
        raise EvaluationError("board report fields are not exact: %s" % report_path)
    if (
        report.get("schema") != "pulse.esp32.hp3_5-slot-board-evidence.v1"
        or report.get("status") != "PASS"
        or report.get("evidence_origin") != "PHYSICAL_NAMED_BOARD"
        or report.get("campaign_id") != campaign["campaign_id"]
        or report.get("campaign_sha256") != campaign_sha256
    ):
        raise EvaluationError("report is not passing physical HP3.5 evidence: %s" % report_path)
    for field in ("board_id", "target", "flash_bytes", "psram_bytes"):
        if report.get(field) != expected_lane[field]:
            raise EvaluationError("named-board identity mismatch for %s" % field)
    marking = report.get("module_or_board_marking")
    if not isinstance(marking, str) or not marking.strip():
        raise EvaluationError("module or board marking is required")
    _hex64(report.get("physical_board_uid_sha256"), "physical_board_uid_sha256")
    if _hex64(report.get("serial_log_sha256"), "serial_log_sha256") != _sha256(serial_path):
        raise EvaluationError("serial log hash mismatch: %s" % serial_path)
    expected_ids = [item["id"] for item in campaign["checkpoints"]]
    observed = report.get("checkpoints")
    if not isinstance(observed, list) or len(observed) != len(expected_ids):
        raise EvaluationError("checkpoint count mismatch")
    if [item.get("id") for item in observed] != expected_ids:
        raise EvaluationError("checkpoint order or identity mismatch")
    for item in observed:
        if set(item) != {"id", "status", "observation"}:
            raise EvaluationError("checkpoint fields are not exact")
        if item.get("status") != "PASS" or not isinstance(item.get("observation"), str):
            raise EvaluationError("every physical checkpoint must pass with an observation")
    if report.get("invariants") != {
        "last_confirmed_destroyed": False,
        "ambiguous_boot_authority": False,
        "application_code_launched_before_authority": False,
    }:
        raise EvaluationError("strong slot invariants were not observed")
    if report.get("claim_boundary") != {
        "inactive_slot_only": True,
        "factory_host_partition_written": False,
        "host_firmware_ota": False,
        "external_provider": False,
        "rax": False,
    }:
        raise EvaluationError("physical report exceeded the HP3.5 claim boundary")
    return {
        "board_id": report["board_id"],
        "target": report["target"],
        "module_or_board_marking": marking.strip(),
        "physical_board_uid_sha256": report["physical_board_uid_sha256"],
        "serial_log_sha256": report["serial_log_sha256"],
        "checkpoint_count": len(observed),
        "report_sha256": _sha256(report_path),
    }


def evaluate(s3_run: Path, c6_run: Path, out_dir: Path) -> dict[str, Any]:
    campaign = _load_json(CAMPAIGN)
    _validate_campaign(campaign)
    output = _prepare(out_dir)
    campaign_sha256 = _sha256(CAMPAIGN)
    lanes = {item["target"]: item for item in campaign["board_lanes"]}
    s3 = _validate_lane(s3_run, lanes["esp32s3"], campaign, campaign_sha256)
    c6 = _validate_lane(c6_run, lanes["esp32c6"], campaign, campaign_sha256)
    if s3["physical_board_uid_sha256"] == c6["physical_board_uid_sha256"]:
        raise EvaluationError("physical board identities must be distinct")
    report: dict[str, Any] = {
        "schema": "pulse.esp32.hp3_5-slot-dual-board-evaluation.v1",
        "pass": "HP3.5",
        "status": "PASS",
        "aggregate": "DUAL_NAMED_BOARD_SAFE_SUBSET_OBSERVED",
        "campaign_sha256": campaign_sha256,
        "lanes": [s3, c6],
        "coverage": {
            "physical_named_boards": 2,
            "checkpoints_per_board": 13,
            "last_confirmed_destroyed": False,
            "ambiguous_boot_authority": False,
            "application_code_launched_before_authority": False,
        },
        "claim_boundary": {
            "exhaustive_matrix": "HOST_ONLY",
            "physical_campaign": "SAFE_SUBSET_ONLY",
            "host_firmware_ota": "NOT_IMPLEMENTED",
            "external_provider": "NOT_IMPLEMENTED",
            "rax": "NOT_IMPLEMENTED",
        },
    }
    report_path = output / "dual-board-evaluation.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest = {
        "schema": "pulse.esp32.hp3_5-slot-dual-board-manifest.v1",
        "status": "PASS",
        "artifacts": [
            {
                "path": report_path.name,
                "sha256": _sha256(report_path),
                "size": report_path.stat().st_size,
            }
        ],
    }
    (output / "evidence-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--s3-run", type=Path, required=True)
    parser.add_argument("--c6-run", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = evaluate(args.s3_run, args.c6_run, args.out_dir)
    except (OSError, ValueError, json.JSONDecodeError, EvaluationError) as exc:
        print("HP3.5 hardware evaluation failed: %s" % exc, file=sys.stderr)
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
