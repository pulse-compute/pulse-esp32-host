#!/usr/bin/env python3
"""Qualify the HP3.5 application-slot adversarial and power-loss seal."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

try:
    from tools import host_build_contract
except ModuleNotFoundError:  # Direct execution from tools/.
    import host_build_contract  # type: ignore[no-redef]


ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "specs/PULSE-ESP32-008a-application-slot-adversarial-seal.json"
PARENT_MODEL = ROOT / "specs/PULSE-ESP32-008-application-slots.json"
BUNDLE = ROOT / "examples/bundles/relay-controller/dist/relay-controller-r8.wdcb"
SMOKE_SOURCE = ROOT / "tests/ota-power-loss/hp3_5_slot_adversarial_smoke.c"
CAMPAIGN = ROOT / "tests/hardware-in-loop/hp3_5-slot-power-loss/campaign.json"
HARDWARE_EVALUATOR = ROOT / "tools/evaluate_hp3_5_slot_hardware.py"
CATALOG = ROOT / "firmware/host-build-catalog.json"
BOARD_IDS = (
    "aitrip-esp32s3-devkitc-1-n8r2",
    "seeed-xiao-esp32c6-4m",
)


class QualificationError(RuntimeError):
    """Raised when the frozen HP3.5 contract or evidence drifts."""


def _prepare(path: Path) -> Path:
    output = path.expanduser().resolve()
    if output.exists():
        if not output.is_dir() or any(output.iterdir()):
            raise QualificationError("output directory must be absent or empty")
    else:
        output.mkdir(parents=True)
    return output


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _evidence(path: Path, output: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(output).as_posix(),
        "sha256": _sha256(path),
        "size": path.stat().st_size,
    }


def _load_models() -> tuple[dict[str, Any], dict[str, Any]]:
    model = json.loads(MODEL.read_text(encoding="utf-8"))
    campaign = json.loads(CAMPAIGN.read_text(encoding="utf-8"))
    if (
        model.get("schema")
        != "pulse.esp32.hp3_5-application-slot-adversarial-seal.v1"
        or model.get("pass") != "HP3.5"
        or model.get("phase") != "APPLICATION_SLOT_ADVERSARIAL_POWER_LOSS_SEAL"
        or model.get("status") != "FROZEN"
        or model.get("parent_authority", {}).get("sha256") != _sha256(PARENT_MODEL)
    ):
        raise QualificationError("HP3.5 frozen model drifted")
    fault = model.get("deterministic_fault_model", {})
    if (
        fault.get("operations")
        != [
            "SLOT_ERASE",
            "SLOT_WRITE",
            "METADATA_ERASE",
            "METADATA_BODY_WRITE",
            "METADATA_MARKER_WRITE",
        ]
        or fault.get("metadata_record_bytes") != 256
        or fault.get("metadata_body_bytes") != 252
        or fault.get("metadata_marker_bytes") != 4
        or fault.get("journal_records") != 2
    ):
        raise QualificationError("HP3.5 deterministic fault model drifted")
    seal = model.get("synthetic_seal", {})
    expected_counts = {
        "total_cases": 11657,
        "payload_write_cuts": 2362,
        "slot_erase_cuts": 6,
        "journal_interruption_cases": 8240,
        "confirmation_reset_cases": 1030,
        "journal_corruption_cases": 3,
        "adversarial_semantic_cases": 16,
        "repeated_trap_cycles": 32,
    }
    if any(seal.get(name) != value for name, value in expected_counts.items()):
        raise QualificationError("HP3.5 exact synthetic seal drifted")
    if expected_counts["journal_interruption_cases"] != (
        8 * 2 * ((256 + 1) + (252 + 1) + (4 + 1))
    ):
        raise QualificationError("internal journal matrix formula drifted")
    if expected_counts["confirmation_reset_cases"] != (
        2 * ((256 + 1) + (252 + 1) + (4 + 1))
    ):
        raise QualificationError("internal confirmation matrix formula drifted")
    if (
        campaign.get("schema")
        != "pulse.esp32.hp3_5-slot-hardware-campaign.v1"
        or campaign.get("status") != "FROZEN"
        or campaign.get("execution_status") != "NOT_RUN"
        or len(campaign.get("checkpoints", [])) != 13
        or [item.get("board_id") for item in campaign.get("board_lanes", [])]
        != list(BOARD_IDS)
    ):
        raise QualificationError("HP3.5 physical safe-subset campaign drifted")
    return model, campaign


def _validate_sources() -> list[str]:
    header = (ROOT / "firmware/components/wdc_ota/include/wdc_ota.h").read_text(encoding="utf-8")
    ota = (ROOT / "firmware/components/wdc_ota/wdc_ota.c").read_text(encoding="utf-8")
    slots = (ROOT / "firmware/components/wdc_app_slots/wdc_app_slots.c").read_text(encoding="utf-8")
    smoke = SMOKE_SOURCE.read_text(encoding="utf-8")
    evaluator = HARDWARE_EVALUATOR.read_text(encoding="utf-8")
    checks = {
        "five-deterministic-fault-operations": all(
            token in header
            for token in (
                "WDC_OTA_HOST_FAULT_SLOT_ERASE",
                "WDC_OTA_HOST_FAULT_SLOT_WRITE",
                "WDC_OTA_HOST_FAULT_METADATA_ERASE",
                "WDC_OTA_HOST_FAULT_METADATA_BODY_WRITE",
                "WDC_OTA_HOST_FAULT_METADATA_MARKER_WRITE",
            )
        ),
        "one-shot-indexed-fault-plan": (
            "trigger_index" in header
            and "host_fault_take" in ota
            and "s_host_fault.armed = false" in ota
        ),
        "partial-payload-persistence": (
            "session->written_bytes += tear_after" in ota
            and "session->active = 0u" in ota
        ),
        "journal-marker-last": (
            ota.find("WDC_OTA_HOST_FAULT_METADATA_BODY_WRITE")
            < ota.find("WDC_OTA_HOST_FAULT_METADATA_MARKER_WRITE")
        ),
        "ram-resynchronized-to-durable-authority": (
            "wdc_ota_read_metadata(&durable)" in slots
            and "memcpy(metadata, &durable, sizeof(*metadata))" in slots
        ),
        "confirmed-fallback-single-commit": (
            "prepare_reject_boot_slot" in slots
            and "metadata->last_good_slot = alternate" in slots
        ),
        "every-payload-prefix": "cut <= s_artifact_bytes" in smoke,
        "both-journal-records": (
            "target < WDC_OTA_METADATA_JOURNAL_RECORDS" in smoke
        ),
        "every-journal-prefix": (
            "cut <= limit" in smoke and "JOURNAL_TRANSITIONS 8u" in smoke
        ),
        "confirmation-reset-matrix": "run_confirmation_matrix" in smoke,
        "required-adversarial-semantics": all(
            token in smoke
            for token in (
                "Invalid signature",
                "Readiness deadline timeout",
                "REPEATED_TRAP_CYCLES",
                "WDC_ACTIVATION_RESET_APPLICATION_WATCHDOG",
                "WDC_ACTIVATION_RESET_HOST_WATCHDOG",
            )
        ),
        "physical-evidence-rejects-synthetic": (
            '"PHYSICAL_NAMED_BOARD"' in evaluator
            and "serial log hash mismatch" in evaluator
            and "physical_board_uid_sha256" in evaluator
        ),
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise QualificationError("HP3.5 source checks failed: %s" % ", ".join(failed))
    return list(checks)


def _compile_command(compiler: str, executable: Path) -> list[str]:
    return [
        compiler,
        "-std=c11",
        "-Wall",
        "-Wextra",
        "-Werror",
        "-DWDC_HOST_TEST_TARGET_C6=1",
        "-Ifirmware/components/wdc_abi/include",
        "-Ifirmware/components/wdc_caps/include",
        "-Ifirmware/components/wdc_profile/include",
        "-Ifirmware/components/wdc_bundle/include",
        "-Ifirmware/components/wdc_control/include",
        "-Ifirmware/components/wdc_host_identity/include",
        "-Ifirmware/components/wdc_ota/include",
        "-Ifirmware/components/wdc_activation/include",
        "-Ifirmware/components/wdc_app_slots/include",
        "tests/ota-power-loss/hp3_5_slot_adversarial_smoke.c",
        "firmware/components/wdc_abi/wdc_errors.c",
        "firmware/components/wdc_abi/wdc_cbor.c",
        "firmware/components/wdc_abi/wdc_pointer.c",
        "firmware/components/wdc_abi/wdc_host_call.c",
        "firmware/components/wdc_caps/wdc_caps.c",
        "firmware/components/wdc_bundle/wdc_bundle.c",
        "firmware/components/wdc_control/wdc_control.c",
        "firmware/components/wdc_host_identity/wdc_host_identity.c",
        "firmware/components/wdc_host_identity/wdc_host_fingerprint_generated.c",
        "firmware/components/wdc_ota/wdc_ota.c",
        "firmware/components/wdc_activation/wdc_activation.c",
        "firmware/components/wdc_app_slots/wdc_app_slots.c",
        "firmware/components/wdc_profile/wdc_profile_static.c",
        "-o",
        str(executable),
    ]


def _run(command: list[str], log: Path) -> subprocess.CompletedProcess[str]:
    process = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    log.write_text("$ " + " ".join(command) + "\n" + (process.stdout or ""), encoding="utf-8")
    return process


def _run_smoke(
    output: Path, compiler: str, model: dict[str, Any]
) -> tuple[dict[str, Any], list[Path]]:
    executable = output / "hp3_5-slot-adversarial-smoke"
    compile_log = output / "compile.log"
    run_log = output / "run.log"
    build = _run(_compile_command(compiler, executable), compile_log)
    if build.returncode != 0 or not executable.is_file():
        raise QualificationError("HP3.5 smoke compilation failed")
    run = _run([str(executable), str(BUNDLE)], run_log)
    if run.returncode != 0:
        raise QualificationError("HP3.5 adversarial smoke failed")
    try:
        smoke = json.loads(run.stdout)
    except json.JSONDecodeError as exc:
        raise QualificationError("HP3.5 smoke emitted invalid JSON") from exc
    seal = model["synthetic_seal"]
    expected = {
        "schema": seal["schema"],
        "status": "PASS",
        "failures": 0,
        "total_cases": seal["total_cases"],
        "artifact_bytes": 2361,
        "metadata_record_bytes": 256,
        "metadata_body_bytes": 252,
        "payload_write_cuts": seal["payload_write_cuts"],
        "slot_erase_cuts": seal["slot_erase_cuts"],
        "journal_transitions": 8,
        "journal_target_records": 2,
        "journal_interruption_cases": seal["journal_interruption_cases"],
        "confirmation_reset_cases": seal["confirmation_reset_cases"],
        "journal_corruption_cases": seal["journal_corruption_cases"],
        "adversarial_semantic_cases": seal["adversarial_semantic_cases"],
        "repeated_trap_cycles": seal["repeated_trap_cycles"],
        "last_confirmed_preserved": True,
        "ambiguous_boot_authority": False,
        "application_code_launched": False,
    }
    if smoke != expected:
        raise QualificationError("HP3.5 smoke result is not the exact passing seal")
    smoke_path = output / "synthetic-slot-adversarial-seal.json"
    _write_json(smoke_path, smoke)
    return smoke, [compile_log, run_log, executable, smoke_path]


def qualify(out_dir: Path, compiler: str = "cc") -> dict[str, Any]:
    output = _prepare(out_dir)
    model, campaign = _load_models()
    if shutil.which(compiler) is None:
        raise QualificationError("host C compiler is unavailable")
    source_checks = _validate_sources()
    catalog = host_build_contract.load_json(CATALOG)
    resolved = host_build_contract.validate_catalog(catalog)
    if set(resolved) != set(BOARD_IDS):
        raise QualificationError("HP3.5 named-board set drifted")

    copied: list[Path] = []
    for source, name in (
        (MODEL, "application-slot-adversarial-model.json"),
        (CAMPAIGN, "physical-safe-subset-campaign.json"),
        (HARDWARE_EVALUATOR, "evaluate_hp3_5_slot_hardware.py"),
        (SMOKE_SOURCE, "hp3_5_slot_adversarial_smoke.c"),
        (BUNDLE, "input-bundle.wdcb"),
    ):
        target = output / name
        shutil.copy2(source, target)
        copied.append(target)

    lock_bindings: dict[str, dict[str, str]] = {}
    for board_id in BOARD_IDS:
        entry = resolved[board_id]["entry"]
        lock_path = ROOT / entry["build_lock"]
        fingerprint_path = ROOT / entry["fingerprint"]
        lock = host_build_contract.load_json(lock_path)
        fingerprint = host_build_contract.load_json(fingerprint_path)
        host_build_contract.replay_lock(lock, fingerprint)
        short = "s3" if entry["target"] == "esp32s3" else "c6"
        for source, name in (
            (lock_path, short + "-build-lock.json"),
            (fingerprint_path, short + "-running-fingerprint.json"),
            (ROOT / entry["partitions"], short + "-partitions.csv"),
        ):
            target = output / name
            shutil.copy2(source, target)
            copied.append(target)
        lock_bindings[short] = {
            "build_lock_sha256": fingerprint["build_lock_sha256"],
            "fingerprint_sha256": fingerprint["fingerprint_sha256"],
            "profile_id": fingerprint["compatibility_surface"]["host_profile_id"],
        }

    smoke, smoke_files = _run_smoke(output, compiler, model)
    copied.extend(smoke_files)
    report: dict[str, Any] = {
        "schema": "pulse.esp32.hp3_5-application-slot-adversarial-report.v1",
        "pass": "HP3.5",
        "phase": "APPLICATION_SLOT_ADVERSARIAL_POWER_LOSS_SEAL",
        "status": "PASS",
        "aggregate": "HOST_SLOT_ADVERSARIAL_POWER_LOSS_SEALED",
        "coverage": {
            "host_cases": smoke["total_cases"],
            "payload_write_cuts": smoke["payload_write_cuts"],
            "slot_erase_cuts": smoke["slot_erase_cuts"],
            "journal_transitions": smoke["journal_transitions"],
            "journal_target_records": smoke["journal_target_records"],
            "journal_interruption_cases": smoke["journal_interruption_cases"],
            "confirmation_reset_cases": smoke["confirmation_reset_cases"],
            "journal_corruption_cases": smoke["journal_corruption_cases"],
            "adversarial_semantic_cases": smoke["adversarial_semantic_cases"],
            "repeated_trap_cycles": smoke["repeated_trap_cycles"],
            "source_contract_checks": source_checks,
            "last_confirmed_preserved": True,
            "ambiguous_boot_authority": False,
            "application_code_launched": False,
        },
        "host_build_bindings": lock_bindings,
        "physical_safe_subset": {
            "status": "READY_NOT_RUN",
            "campaign_id": campaign["campaign_id"],
            "campaign_sha256": _sha256(CAMPAIGN),
            "required_named_boards": list(BOARD_IDS),
            "checkpoints_per_board": len(campaign["checkpoints"]),
            "promotion_requires": "BOTH_PHYSICAL_NAMED_BOARD_REPORTS_PASS",
        },
        "claim_boundary": {
            "runtime_classification": "HOST_EXECUTED_EXHAUSTIVE_SIMULATION",
            "hardware_execution_this_pass": "NOT_RUN",
            "firmware_build_this_pass": "NOT_RUN_LOCK_REPLAY_ONLY",
            "physical_power_loss": "SAFE_SUBSET_PROTOCOL_READY_NOT_OBSERVED",
            "external_provider": "NOT_IMPLEMENTED",
            "protected_remote_administration": "NOT_IMPLEMENTED",
            "rax": "NOT_IMPLEMENTED",
            "mqtt_or_transport": "NOT_IMPLEMENTED",
            "host_firmware_ota": "NOT_IMPLEMENTED",
            "pulse_core_changes": "NONE",
        },
        "preserved_authorities": model["preserved_authorities"],
    }
    report_path = output / "qualification-report.json"
    markdown_path = output / "qualification-report.md"
    _write_json(report_path, report)
    markdown_path.write_text(
        "# HP3.5 application-slot adversarial qualification\n\n"
        "Status: **PASS (host seal)**\n\n"
        "Aggregate: `HOST_SLOT_ADVERSARIAL_POWER_LOSS_SEALED`\n\n"
        "The deterministic host model passed 11,657 interruption and fault "
        "cases without destroying the last confirmed application, creating "
        "ambiguous boot authority, or entering application code before the "
        "host gate. Both journal records and every payload/body/marker prefix "
        "were exercised.\n\n"
        "The thirteen-checkpoint safe physical campaign is frozen for both "
        "named boards, but no hardware was executed in this qualification. "
        "Dual-board physical promotion therefore remains pending.\n",
        encoding="utf-8",
    )
    manifest_inputs = [*copied, report_path, markdown_path]
    manifest = {
        "schema": "pulse.esp32.hp3_5-evidence-manifest.v1",
        "status": "PASS",
        "artifacts": [_evidence(path, output) for path in sorted(manifest_inputs)],
    }
    _write_json(output / "evidence-manifest.json", manifest)
    return report


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--cc", default="cc")
    args = parser.parse_args(argv)
    try:
        report = qualify(args.out_dir, args.cc)
    except (
        OSError,
        ValueError,
        json.JSONDecodeError,
        subprocess.SubprocessError,
        host_build_contract.HostBuildContractError,
        QualificationError,
    ) as exc:
        print("HP3.5 qualification failed: %s" % exc, file=sys.stderr)
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
