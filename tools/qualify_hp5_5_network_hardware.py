#!/usr/bin/env python3
"""Qualify HP5.5 source readiness without manufacturing physical evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

try:
    from tools import (
        build_hp5_5_network_hardware,
        hp5_5_fixture,
        qualify_admin_update,
        resolve_hp5_5_target_contracts,
    )
except ModuleNotFoundError:
    import build_hp5_5_network_hardware  # type: ignore[no-redef]
    import hp5_5_fixture  # type: ignore[no-redef]
    import qualify_admin_update  # type: ignore[no-redef]
    import resolve_hp5_5_target_contracts  # type: ignore[no-redef]


ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "specs/PULSE-ESP32-015-network-administration-physical-seal.json"
CAMPAIGN = ROOT / "tests/hardware-in-loop/hp5_5-network-admin/campaign.json"
SMOKE = ROOT / "tests/contract/hp5_5_update_profile_smoke.c"
BUNDLE = ROOT / "examples/bundles/relay-controller/dist/relay-controller-r8.wdcb"
TEMPLATE_MAIN = (
    ROOT
    / "tests/hardware-in-loop/hp5_5-network-admin/firmware/main/hp5_5_network_admin_main.c"
)
EXPECTED_ARTIFACTS = {
    "baseline": {
        "bundle_sha256": "8290f98d2ad364124480a4013cd3b49db26110bf63b511fe43b9bca489378354",
        "bytes": 2330,
        "sha256": "66494cde0275a2d412c2d44a43895ac0d112b1d2ab4fe0747dea8486f0fe3690",
        "version": 8,
    },
    "positive": {
        "bundle_sha256": "572bb838a11ef0cff407f8fec73d79b3a23e6f5af631b8714cbc2e856a38338f",
        "bytes": 2330,
        "sha256": "31ede939d45e64b493229661c4ca3d151ae49788d97f035d591343ae4bab1b22",
        "version": 9,
    },
    "fallback": {
        "bundle_sha256": "f62eadafcad9ac2c6cce37caaffab50b60634c24991957636b82d721004d5704",
        "bytes": 2333,
        "sha256": "c11e9429265b8264ad36e865f6bef15bb94addc60310e66f3c09be954c069810",
        "version": 10,
    },
}
EXPECTED_WASM = {
    "bytes": 287,
    "sha256": "55daa3d6501886edf188d427e93c4ac81e4bad09fb363ee8e9a5de4dd8849fe2",
}


class QualificationError(RuntimeError):
    """Raised when HP5.5 is not honestly ready for physical execution."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise QualificationError(f"JSON object required: {path}")
    return value


def validate_model_and_campaign() -> tuple[dict[str, Any], dict[str, Any]]:
    if (
        sha256(MODEL) != build_hp5_5_network_hardware.EXPECTED_MODEL_SHA256
        or sha256(CAMPAIGN) != build_hp5_5_network_hardware.EXPECTED_CAMPAIGN_SHA256
    ):
        raise QualificationError("HP5.5 model or campaign hash drifted")
    model = load_json(MODEL)
    campaign = load_json(CAMPAIGN)
    if (
        model.get("schema") != "pulse.esp32.hp5_5-network-administration-physical-seal.v1"
        or model.get("pass") != "HP5.5"
        or model.get("phase") != "NETWORK_ADMINISTRATION_PHYSICAL_SEAL"
        or model.get("status") != "READY_FOR_PHYSICAL_EXECUTION"
        or model.get("aggregate") != "HARDWARE_PENDING"
        or model.get("claim", {}).get("target_build_executed") is not False
        or model.get("claim", {}).get("dual_named_board_physical_execution") is not False
        or model.get("claim", {}).get("production_credentials_in_source") is not False
    ):
        raise QualificationError("HP5.5 model overclaims or changed identity")
    if (
        campaign.get("schema") != "pulse.esp32.hp5_5-network-admin-hardware-campaign.v1"
        or campaign.get("campaign_id") != "hp5_5-dual-network-admin-v1"
        or campaign.get("status") != "FROZEN"
        or campaign.get("execution_status") != "NOT_RUN"
        or len(campaign.get("board_lanes", [])) != 2
        or len(campaign.get("checkpoints", [])) != 29
        or campaign.get("promotion", {}).get("both_complete_named_board_runs")
            != "DUAL_NAMED_BOARD_HP5_NETWORK_ADMIN_OBSERVED"
    ):
        raise QualificationError("frozen HP5.5 physical campaign drifted")
    if model.get("authority_bindings", {}).get("campaign_sha256") != sha256(CAMPAIGN):
        raise QualificationError("HP5.5 model does not bind the campaign")
    return model, campaign


def validate_target_contracts() -> dict[str, Any]:
    resolution = resolve_hp5_5_target_contracts.verify()
    if (
        resolution.get("status") != "PASS"
        or resolution.get("historical_hp2_authorities_unchanged") is not True
        or len(resolution.get("lanes", [])) != 2
    ):
        raise QualificationError("HP5.5 target contracts did not replay exactly")
    for board_id in build_hp5_5_network_hardware.BOARD_CONFIGS:
        try:
            build_hp5_5_network_hardware.validate_source(board_id)
        except Exception as exc:
            raise QualificationError(
                f"HP5.5 source validation failed for {board_id}: {exc}"
            ) from exc
    return resolution


def validate_fixture() -> dict[str, Any]:
    inventory = hp5_5_fixture.artifact_inventory()
    wasm = hp5_5_fixture.make_http_responder_wasm()
    observed_wasm = {"bytes": len(wasm), "sha256": hashlib.sha256(wasm).hexdigest()}
    if inventory != EXPECTED_ARTIFACTS or observed_wasm != EXPECTED_WASM:
        raise QualificationError("deterministic HP5.5 Wasm or application artifacts drifted")
    if b"wdc_host_call" not in wasm or b"pulse.hp5_5" not in wasm:
        raise QualificationError("HP5.5 fixture is not a real paired-effect Wasm module")
    return {"wasm": observed_wasm, "artifacts": inventory}


def run_update_profile_smoke() -> dict[str, Any]:
    compiler = os.environ.get("CC", "gcc")
    with tempfile.TemporaryDirectory(prefix="pulse-hp5_5-profile-") as temp:
        executable = Path(temp) / "hp5_5_update_profile_smoke"
        command = qualify_admin_update._compile_command(compiler, executable)
        command = [str(SMOKE) if value == str(qualify_admin_update.SMOKE) else value for value in command]
        build = subprocess.run(
            command, cwd=ROOT, check=False, capture_output=True, text=True, timeout=120
        )
        if build.returncode != 0:
            raise QualificationError("HP5.5 native profile build failed:\n" + build.stderr)
        run = subprocess.run(
            [str(executable), str(BUNDLE)], cwd=ROOT, check=False,
            capture_output=True, text=True, timeout=120,
        )
        if run.returncode != 0:
            raise QualificationError(
                "HP5.5 native profile smoke failed:\n" + run.stdout + run.stderr
            )
    lines = [line for line in run.stdout.splitlines() if line.strip()]
    if len(lines) != 1:
        raise QualificationError("HP5.5 native profile smoke output drifted")
    result = json.loads(lines[0])
    if result != {
        "schema": "pulse.esp32.hp5_5-update-profile-smoke.v1",
        "status": "PASS",
        "cases": 4,
        "failures": 0,
    }:
        raise QualificationError("HP5.5 update profile result drifted")
    result["compiler"] = compiler
    return result


def validate_harness_surface() -> dict[str, Any]:
    required = [
        TEMPLATE_MAIN,
        ROOT / "tools/build_hp5_5_network_hardware.py",
        ROOT / "tools/run_hp5_5_network_client.py",
        ROOT / "tools/evaluate_hp5_5_network_board.py",
        ROOT / "tools/evaluate_hp5_5_network_hardware.py",
        ROOT / "tools/prepare_hp5_5_provision.py",
    ]
    for path in required:
        if not path.is_file() or path.is_symlink():
            raise QualificationError(f"HP5.5 harness source missing: {path}")
    main = TEMPLATE_MAIN.read_text(encoding="utf-8")
    for token in (
        "PULSE_HP55_BOOT ", "PULSE_HP55_CHECKPOINT ", "PULSE_HP55_STATS ",
        "PULSE_HP55_FINAL ", "PULSE_HP55_FATAL ", "wdc_http_platform_start",
        "wdc_runtime_load_static", "config.update.running_host_fingerprint",
        "wdc_admin_recovery_init", "wdc_app_slots_mark_trial",
        "esp_wifi_disconnect", "wifi_reconnect_self_test",
        "wdc_app_slots_evaluate_probation", "wdc_runtime_call_health",
        "s_pending_trial_slot",
        "target-boot-fingerprint", "resource-floors-under-pressure",
    ):
        if token not in main:
            raise QualificationError(f"HP5.5 physical fixture token missing: {token}")
    client = required[2].read_text(encoding="utf-8")
    for token in (
        "HTTPSConnection", "ssl.TLSVersion.TLSv1_2", "common-wasm-app-response",
        "admin-terminal-retained-after-client-loss", "stale-trial-fallback",
        "authorization-rate-and-session-recovery", "network-loss-no-rollback-or-cancel",
        "PROBATION_WAIT_SECONDS", "expired_status != 401",
        "negative_status != 409", "busy_status != 503",
        "replay_status != 409", "rate_status != 429",
    ):
        if token not in client:
            raise QualificationError(f"HP5.5 physical client token missing: {token}")
    aggregate = required[4].read_text(encoding="utf-8")
    if "DUAL_NAMED_BOARD_HP5_NETWORK_ADMIN_OBSERVED" not in aggregate:
        raise QualificationError("HP5.5 dual-board promotion gate is missing")
    return {
        path.relative_to(ROOT).as_posix(): {"sha256": sha256(path), "bytes": path.stat().st_size}
        for path in required
    }


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def qualify(out_dir: Path, source_archive: Path | None = None) -> dict[str, Any]:
    model, campaign = validate_model_and_campaign()
    targets = validate_target_contracts()
    fixture = validate_fixture()
    native = run_update_profile_smoke()
    harness = validate_harness_surface()
    predecessor: dict[str, Any] = {
        "status": "BOUND_NOT_REVERIFIED",
        "expected": build_hp5_5_network_hardware.EXPECTED_PREDECESSOR,
    }
    if source_archive is not None:
        predecessor = {
            "status": "PASS",
            "observed": build_hp5_5_network_hardware.verify_predecessor_archive(source_archive),
        }
    output = out_dir.expanduser().resolve()
    if output.exists():
        raise QualificationError("output directory must not already exist")
    output.mkdir(parents=True)
    artifacts = {
        "model.json": model,
        "campaign.json": campaign,
        "target-contract-resolution.json": targets,
        "fixture-inventory.json": fixture,
        "native-update-profile-smoke.json": native,
        "harness-source-seal.json": {
            "schema": "pulse.esp32.hp5_5-harness-source-seal.v1",
            "status": "PASS",
            "sources": harness,
            "predecessor_archive": predecessor,
        },
    }
    for name, value in artifacts.items():
        write_json(output / name, value)
    manifest = {
        "schema": "pulse.esp32.hp5_5-readiness-evidence-manifest.v1",
        "status": "PASS",
        "aggregate": "HARDWARE_PENDING",
        "artifacts": [
            {"path": name, "sha256": sha256(output / name), "size": (output / name).stat().st_size}
            for name in artifacts
        ],
        "physical_evidence_created": False,
    }
    write_json(output / "evidence-manifest.json", manifest)
    report = {
        "schema": "pulse.esp32.hp5_5-network-admin-readiness-qualification.v1",
        "pass": "HP5.5",
        "status": "PASS",
        "readiness": "READY_FOR_PHYSICAL_EXECUTION",
        "aggregate": "HARDWARE_PENDING",
        "named_board_lanes": 2,
        "checkpoints_per_board": 29,
        "native_profile_cases": 4,
        "historical_hp2_authorities_unchanged": True,
        "predecessor_archive_reverified": source_archive is not None,
        "target_build_executed": False,
        "physical_result_created": False,
        "production_credentials_in_source": False,
        "hp6_status": "BLOCKED_PENDING_HP5_5_PHYSICAL_ACCEPTANCE",
        "evidence_manifest_sha256": sha256(output / "evidence-manifest.json"),
    }
    write_json(output / "qualification-report.json", report)
    (output / "qualification-report.md").write_text(
        "# HP5.5 network/administration readiness\n\n"
        "Result: `READY_FOR_PHYSICAL_EXECUTION` (`PASS`).\n\n"
        "Both exact target contracts replay, historical HP2 authorities remain unchanged, "
        "the deterministic Wasm/update fixtures pass, and the strict build, client, "
        "per-board, and dual-board evidence tools are present.\n\n"
        "The aggregate remains `HARDWARE_PENDING`: no ESP-IDF target build or physical "
        "board result was manufactured by this host-native qualification. HP6 remains "
        "blocked until the two named-board reports are accepted.\n",
        encoding="utf-8",
    )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--source-archive", type=Path)
    args = parser.parse_args(argv)
    try:
        report = qualify(args.out_dir, args.source_archive)
    except (
        OSError, ValueError, KeyError, json.JSONDecodeError, subprocess.TimeoutExpired,
        QualificationError, build_hp5_5_network_hardware.HardwareBuildError,
        resolve_hp5_5_target_contracts.ResolutionError,
    ) as exc:
        print(f"HP5.5 readiness qualification failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
