#!/usr/bin/env python3
"""Create one HP3.5 physical board report from a sealed build and serial log."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

try:
    from tools import build_hp3_5_slot_hardware
except ModuleNotFoundError:  # Direct execution from tools/.
    import build_hp3_5_slot_hardware  # type: ignore[no-redef]


ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN = ROOT / "tests/hardware-in-loop/hp3_5-slot-power-loss/campaign.json"
BOARD_MARKER = "PULSE_HP35_BOARD "
CHECKPOINT_MARKER = "PULSE_HP35_CHECKPOINT "
FINAL_MARKER = "PULSE_HP35_FINAL "
FATAL_MARKER = "PULSE_HP35_FATAL "


class BoardEvaluationError(RuntimeError):
    """Raised when one run cannot support physical named-board evidence."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise BoardEvaluationError(f"JSON object required: {path}")
    return value


def _hex64(value: Any, name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise BoardEvaluationError(f"{name} must be lowercase SHA-256")
    return value


def _resolve_evidence(run_dir: Path, evidence: dict[str, Any], name: str) -> Path:
    if set(evidence) != {"path", "sha256", "size"}:
        raise BoardEvaluationError(f"{name} file evidence fields are not exact")
    relative = evidence.get("path")
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise BoardEvaluationError(f"{name} evidence path must be relative")
    path = (run_dir / relative).resolve()
    try:
        path.relative_to(run_dir)
    except ValueError as exc:
        raise BoardEvaluationError(f"{name} evidence escapes run directory") from exc
    if not path.is_file():
        raise BoardEvaluationError(f"{name} evidence file is missing: {path}")
    expected_sha = _hex64(evidence.get("sha256"), f"{name}.sha256")
    if _sha256(path) != expected_sha or path.stat().st_size != evidence.get("size"):
        raise BoardEvaluationError(f"{name} evidence hash or size mismatch: {path}")
    return path


def _parse_markers(serial_text: str, marker: str) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for line_number, line in enumerate(serial_text.splitlines(), 1):
        if marker not in line:
            continue
        payload = line.split(marker, 1)[1].strip()
        try:
            value = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise BoardEvaluationError(
                f"malformed {marker.strip()} JSON on serial line {line_number}: {exc}"
            ) from exc
        if not isinstance(value, dict):
            raise BoardEvaluationError(
                f"{marker.strip()} must contain a JSON object on line {line_number}"
            )
        values.append(value)
    return values


def _validate_build(run_dir: Path, report: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    campaign = _load_json(CAMPAIGN)
    campaign_sha = _sha256(CAMPAIGN)
    if campaign_sha != build_hp3_5_slot_hardware.EXPECTED_CAMPAIGN_SHA256:
        raise BoardEvaluationError("local frozen HP3.5 campaign hash drifted")
    if (
        report.get("schema") != build_hp3_5_slot_hardware.REPORT_SCHEMA
        or report.get("status") != "PASS"
        or report.get("evidence_origin") != "SEALED_BUILD"
        or report.get("campaign_id") != campaign.get("campaign_id")
        or report.get("campaign_sha256") != campaign_sha
    ):
        raise BoardEvaluationError("build report is not a passing sealed HP3.5 build")
    board_id = report.get("board_id")
    if board_id not in build_hp3_5_slot_hardware.BOARD_CONFIGS:
        raise BoardEvaluationError("build report names an unsupported board")
    lanes = {
        lane.get("board_id"): lane
        for lane in campaign.get("board_lanes", [])
        if isinstance(lane, dict)
    }
    lane = lanes.get(board_id)
    if lane is None:
        raise BoardEvaluationError("build board is absent from the frozen campaign")
    for field in ("board_id", "target", "flash_bytes", "psram_bytes"):
        if report.get(field) != lane.get(field):
            raise BoardEvaluationError(f"build report board identity mismatch: {field}")
    board_evidence = report.get("board_identity")
    partition_evidence = report.get("partition_table")
    bundle_evidence = report.get("bundle")
    if not all(isinstance(item, dict) for item in (board_evidence, partition_evidence, bundle_evidence)):
        raise BoardEvaluationError("build input evidence objects are required")
    _resolve_evidence(run_dir, board_evidence, "board_identity")
    _resolve_evidence(run_dir, partition_evidence, "partition_table")
    _resolve_evidence(run_dir, bundle_evidence, "bundle")
    if board_evidence.get("sha256") != lane.get("board_sha256"):
        raise BoardEvaluationError("build used a non-canonical board identity")
    if partition_evidence.get("sha256") != lane.get("partitions_sha256"):
        raise BoardEvaluationError("build used a non-canonical partition table")
    if bundle_evidence.get("sha256") != build_hp3_5_slot_hardware.EXPECTED_BUNDLE_SHA256:
        raise BoardEvaluationError("build used a non-sealed application bundle")
    historical_sources = {
        "firmware": build_hp3_5_slot_hardware.EXPECTED_FIRMWARE_SOURCE,
        "native_sdk": build_hp3_5_slot_hardware.EXPECTED_NATIVE_SDK_SOURCE,
    }
    hp41_successor_sources = {
        "firmware": build_hp3_5_slot_hardware.EXPECTED_HP41_FIRMWARE_SOURCE,
        "native_sdk": build_hp3_5_slot_hardware.EXPECTED_NATIVE_SDK_SOURCE,
        "historical_campaign_firmware":
            build_hp3_5_slot_hardware.EXPECTED_FIRMWARE_SOURCE,
        "current_successor": "HP4.1",
    }
    hp42_successor_sources = {
        "firmware": build_hp3_5_slot_hardware.EXPECTED_HP42_FIRMWARE_SOURCE,
        "native_sdk": build_hp3_5_slot_hardware.EXPECTED_NATIVE_SDK_SOURCE,
        "historical_campaign_firmware":
            build_hp3_5_slot_hardware.EXPECTED_FIRMWARE_SOURCE,
        "current_successor": "HP4.2",
    }
    hp43_successor_sources = {
        "firmware": build_hp3_5_slot_hardware.EXPECTED_HP43_FIRMWARE_SOURCE,
        "native_sdk": build_hp3_5_slot_hardware.EXPECTED_NATIVE_SDK_SOURCE,
        "historical_campaign_firmware":
            build_hp3_5_slot_hardware.EXPECTED_FIRMWARE_SOURCE,
        "current_successor": "HP4.3",
    }
    hp44_successor_sources = {
        "firmware": build_hp3_5_slot_hardware.EXPECTED_HP44_FIRMWARE_SOURCE,
        "native_sdk": build_hp3_5_slot_hardware.EXPECTED_NATIVE_SDK_SOURCE,
        "historical_campaign_firmware":
            build_hp3_5_slot_hardware.EXPECTED_FIRMWARE_SOURCE,
        "current_successor": "HP4.4",
    }
    hp5_successor_sources = {
        "firmware": build_hp3_5_slot_hardware.EXPECTED_HP5_FIRMWARE_SOURCE,
        "native_sdk": build_hp3_5_slot_hardware.EXPECTED_NATIVE_SDK_SOURCE,
        "historical_campaign_firmware":
            build_hp3_5_slot_hardware.EXPECTED_FIRMWARE_SOURCE,
        "current_successor": "HP5",
    }
    hp55_successor_sources = {
        "firmware": build_hp3_5_slot_hardware.EXPECTED_HP55_FIRMWARE_SOURCE,
        "native_sdk": build_hp3_5_slot_hardware.EXPECTED_NATIVE_SDK_SOURCE,
        "historical_campaign_firmware":
            build_hp3_5_slot_hardware.EXPECTED_FIRMWARE_SOURCE,
        "current_successor": "HP5.5",
    }
    if report.get("sealed_sources") not in (
        historical_sources,
        hp41_successor_sources,
        hp42_successor_sources,
        hp43_successor_sources,
        hp44_successor_sources,
        hp5_successor_sources,
        hp55_successor_sources,
    ):
        raise BoardEvaluationError("build firmware source seal mismatch")
    harness = report.get("harness_sources")
    expected_harness = build_hp3_5_slot_hardware.tree_evidence(
        build_hp3_5_slot_hardware.TEMPLATE
    )
    if not isinstance(harness, dict) or harness.get("tree") != expected_harness:
        raise BoardEvaluationError("build harness source seal mismatch")
    generated = report.get("generated_sources")
    if not isinstance(generated, dict):
        raise BoardEvaluationError("generated build source evidence is required")
    for key in ("campaign_config", "bundle_blob"):
        value = generated.get(key)
        if not isinstance(value, dict):
            raise BoardEvaluationError(f"generated source evidence missing: {key}")
        _resolve_evidence(run_dir, value, f"generated_sources.{key}")
    firmware = report.get("firmware")
    if not isinstance(firmware, dict) or firmware.get("status") != "PASS":
        raise BoardEvaluationError("build firmware evidence is not PASS")
    artifacts = firmware.get("artifacts")
    if not isinstance(artifacts, dict):
        raise BoardEvaluationError("build artifact evidence is required")
    for key in (
        "application_elf",
        "application_binary",
        "application_map",
        "bootloader_binary",
        "partition_table_binary",
        "flasher_args",
        "flash_args",
    ):
        value = artifacts.get(key)
        if not isinstance(value, dict):
            raise BoardEvaluationError(f"build artifact evidence missing: {key}")
        _resolve_evidence(run_dir, value, f"firmware.artifacts.{key}")
    operator_contract = report.get("operator_contract")
    if operator_contract != {
        "full_flash_backup_required": True,
        "fresh_full_flash_erase_required": True,
        "operator_attended": True,
        "restore_path_required": True,
        "serial_log_required": True,
    }:
        raise BoardEvaluationError("build operator safety contract drifted")
    return campaign, lane


def evaluate(run_dir: Path, marking: str) -> dict[str, Any]:
    run = run_dir.expanduser().resolve()
    report_path = run / "build-report.json"
    serial_path = run / "serial.log"
    backup_path = run / "full-flash-before.bin"
    missing = [
        str(path)
        for path in (report_path, serial_path, backup_path)
        if not path.is_file()
    ]
    if missing:
        raise BoardEvaluationError("required run artifact missing: " + ", ".join(missing))
    if not marking.strip():
        raise BoardEvaluationError("module or board marking is required")
    build_report = _load_json(report_path)
    campaign, lane = _validate_build(run, build_report)
    if backup_path.stat().st_size != lane["flash_bytes"]:
        raise BoardEvaluationError(
            "full-flash backup size is %d, expected %d: %s"
            % (backup_path.stat().st_size, lane["flash_bytes"], backup_path)
        )
    serial_text = serial_path.read_text(encoding="utf-8", errors="strict")
    fatals = _parse_markers(serial_text, FATAL_MARKER)
    if fatals:
        raise BoardEvaluationError(f"target emitted HP3.5 fatal evidence: {fatals[-1]}")
    board_markers = _parse_markers(serial_text, BOARD_MARKER)
    checkpoints = _parse_markers(serial_text, CHECKPOINT_MARKER)
    finals = _parse_markers(serial_text, FINAL_MARKER)
    if not board_markers:
        raise BoardEvaluationError("serial log contains no HP3.5 board identity marker")
    if not finals:
        raise BoardEvaluationError("serial log contains no completed HP3.5 final marker")
    expected_board_fields = {
        "schema",
        "campaign_id",
        "campaign_sha256",
        "board_id",
        "target",
        "flash_bytes",
        "psram_bytes",
        "physical_board_uid_sha256",
        "partition_sha256",
        "bundle_sha256",
    }
    first_board = board_markers[0]
    for marker in board_markers:
        if set(marker) != expected_board_fields or marker != first_board:
            raise BoardEvaluationError("serial board identity markers are not exact and stable")
    if (
        first_board.get("schema") != "pulse.esp32.hp3_5-slot-board-start.v1"
        or first_board.get("campaign_id") != campaign["campaign_id"]
        or first_board.get("campaign_sha256") != _sha256(CAMPAIGN)
        or first_board.get("partition_sha256") != lane["partitions_sha256"]
        or first_board.get("bundle_sha256")
        != build_hp3_5_slot_hardware.EXPECTED_BUNDLE_SHA256
    ):
        raise BoardEvaluationError("serial campaign or sealed input identity mismatch")
    for field in ("board_id", "target", "flash_bytes", "psram_bytes"):
        if first_board.get(field) != lane[field]:
            raise BoardEvaluationError(f"physical board marker mismatch: {field}")
    uid = _hex64(
        first_board.get("physical_board_uid_sha256"),
        "physical_board_uid_sha256",
    )
    expected_ids = [item["id"] for item in campaign["checkpoints"]]
    if len(checkpoints) != len(expected_ids):
        raise BoardEvaluationError(
            f"serial checkpoint count is {len(checkpoints)}, expected {len(expected_ids)}"
        )
    if [item.get("id") for item in checkpoints] != expected_ids:
        raise BoardEvaluationError("serial checkpoint order or identity mismatch")
    for item in checkpoints:
        if set(item) != {"schema", "id", "status", "observation"}:
            raise BoardEvaluationError("serial checkpoint fields are not exact")
        if (
            item.get("schema") != "pulse.esp32.hp3_5-slot-checkpoint.v1"
            or item.get("status") != "PASS"
            or not isinstance(item.get("observation"), str)
            or not item["observation"]
        ):
            raise BoardEvaluationError("every serial checkpoint must be a nonempty PASS")
    expected_final = {
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
    }
    if any(item != expected_final for item in finals):
        raise BoardEvaluationError("serial final marker is not the exact HP3.5 PASS contract")
    report = {
        "schema": "pulse.esp32.hp3_5-slot-board-evidence.v1",
        "status": "PASS",
        "evidence_origin": "PHYSICAL_NAMED_BOARD",
        "campaign_id": campaign["campaign_id"],
        "campaign_sha256": _sha256(CAMPAIGN),
        "board_id": lane["board_id"],
        "target": lane["target"],
        "flash_bytes": lane["flash_bytes"],
        "psram_bytes": lane["psram_bytes"],
        "module_or_board_marking": marking.strip(),
        "physical_board_uid_sha256": uid,
        "serial_log_sha256": _sha256(serial_path),
        "checkpoints": [
            {
                "id": item["id"],
                "status": item["status"],
                "observation": item["observation"],
            }
            for item in checkpoints
        ],
        "invariants": expected_final["invariants"],
        "claim_boundary": expected_final["claim_boundary"],
    }
    destination = run / "board-report.json"
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if destination.exists() and destination.read_text(encoding="utf-8") != rendered:
        raise BoardEvaluationError(
            f"refusing to replace a different board report: {destination}"
        )
    destination.write_text(rendered, encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--module-or-board-marking", required=True)
    args = parser.parse_args(argv)
    try:
        report = evaluate(args.run_dir, args.module_or_board_marking)
    except (OSError, ValueError, json.JSONDecodeError, BoardEvaluationError) as exc:
        print(f"HP3.5 board evaluation failed: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "status": report["status"],
                "board_id": report["board_id"],
                "board_report": str(
                    args.run_dir.expanduser().resolve() / "board-report.json"
                ),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
