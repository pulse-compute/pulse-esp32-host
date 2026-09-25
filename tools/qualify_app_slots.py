#!/usr/bin/env python3
"""Qualify the HP3 Pulse application-slot and fallback authority."""
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
MODEL = ROOT / "specs/PULSE-ESP32-008-application-slots.json"
BUNDLE = ROOT / "examples/bundles/relay-controller/dist/relay-controller-r8.wdcb"
CATALOG = ROOT / "firmware/host-build-catalog.json"
SMOKE_SOURCE = ROOT / "tests/contract/hp3_app_slots_smoke.c"
BOARD_IDS = (
    "aitrip-esp32s3-devkitc-1-n8r2",
    "seeed-xiao-esp32c6-4m",
)


class QualificationError(RuntimeError):
    """Raised when the frozen HP3 contract or evidence drifts."""


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


def _load_model() -> dict[str, Any]:
    model = json.loads(MODEL.read_text(encoding="utf-8"))
    if (
        model.get("schema") != "pulse.esp32.hp3-application-slot-authority.v1"
        or model.get("pass") != "HP3"
        or model.get("phase") != "APPLICATION_SLOT_AUTHORITY_FALLBACK"
        or model.get("status") != "FROZEN"
        or model.get("artifact", {}).get("header_bytes") != 192
        or model.get("artifact", {}).get("rax") is not False
        or model.get("slots", {}).get("count") != 2
        or model.get("slots", {}).get("esp32c6_slot_bytes") != 917504
        or model.get("slots", {}).get("esp32s3_slot_bytes") != 2097152
        or model.get("confirmation", {}).get("owner") != "HOST"
        or model.get("synthetic_seal", {}).get("case_count") != 14
    ):
        raise QualificationError("HP3 frozen model drifted")
    if model.get("states") != [
        "EMPTY", "STAGED", "VERIFIED", "TRIAL", "CONFIRMED", "REJECTED"
    ]:
        raise QualificationError("HP3 state authority drifted")
    return model


def _partition_rows(path: Path) -> list[tuple[str, str, str, str, str, str]]:
    rows: list[tuple[str, str, str, str, str, str]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        cells = tuple(cell.strip() for cell in line.split(","))
        if len(cells) != 6:
            raise QualificationError("malformed partition row in %s" % path)
        rows.append(cells)  # type: ignore[arg-type]
    return rows


def _validate_partitions(resolved: dict[str, Any]) -> dict[str, int]:
    expected = {
        "aitrip-esp32s3-devkitc-1-n8r2": [
            ("nvs", "data", "nvs", "0x9000", "24K", ""),
            ("phy_init", "data", "phy", "0xf000", "4K", ""),
            ("factory", "app", "factory", "0x10000", "2M", ""),
            ("wasm_a", "0x40", "0x00", "0x210000", "2M", "encrypted"),
            ("wasm_b", "0x40", "0x01", "0x410000", "2M", "encrypted"),
            ("wasm_meta", "0x40", "0x02", "0x610000", "64K", "encrypted"),
        ],
        "seeed-xiao-esp32c6-4m": [
            ("nvs", "data", "nvs", "0x9000", "24K", ""),
            ("phy_init", "data", "phy", "0xf000", "4K", ""),
            ("factory", "app", "factory", "0x10000", "2M", ""),
            ("wasm_a", "0x40", "0x00", "0x210000", "896K", "encrypted"),
            ("wasm_b", "0x40", "0x01", "0x2f0000", "896K", "encrypted"),
            ("wasm_meta", "0x40", "0x02", "0x3d0000", "64K", "encrypted"),
        ],
    }
    slots: dict[str, int] = {}
    for board_id, wanted in expected.items():
        partition_path = ROOT / resolved[board_id]["entry"]["partitions"]
        observed = _partition_rows(partition_path)
        if observed != wanted:
            raise QualificationError("HP3 partition authority drifted: %s" % board_id)
        for row in observed:
            if row[0] in ("ota_0", "ota_1", "otadata"):
                raise QualificationError("host-firmware OTA entered HP3 layout")
        slots[board_id] = 2
    return slots


def _validate_sources() -> list[str]:
    header = (ROOT / "firmware/components/wdc_app_slots/include/wdc_app_slots.h").read_text(encoding="utf-8")
    slots = (ROOT / "firmware/components/wdc_app_slots/wdc_app_slots.c").read_text(encoding="utf-8")
    ota = (ROOT / "firmware/components/wdc_ota/wdc_ota.c").read_text(encoding="utf-8")
    activation = (ROOT / "firmware/components/wdc_activation/wdc_activation.c").read_text(encoding="utf-8")
    app = (ROOT / "firmware/components/wdc_app/wdc_app.c").read_text(encoding="utf-8")
    abi = (ROOT / "firmware/components/wdc_abi/include/wdc_abi.h").read_text(encoding="utf-8")
    required_header = (
        "WDC_APP_ARTIFACT_HEADER_BYTES 192u",
        "WDC_APP_SLOT_PORTABLE_MINIMUM_BYTES (896u * 1024u)",
        "WdcPulseAppArtifactHeaderV1",
        "security_version_floor",
        "production_mode",
    )
    if any(token not in header for token in required_header):
        raise QualificationError("fixed application artifact API drifted")
    if any("WDC_SLOT_" + state not in abi for state in (
        "EMPTY", "STAGED", "VERIFIED", "TRIAL", "CONFIRMED", "REJECTED"
    )):
        raise QualificationError("canonical slot states drifted")
    source_checks = {
        "inactive-slot-only": "slot != wdc_app_slots_inactive_slot(metadata)" in slots,
        "streamed-flash-hashing": "stream_hash(" in slots and "wdc_sha256_update" in slots,
        "staged-then-verified": (
            "record->state = WDC_SLOT_STAGED" in slots
            and "record->state = WDC_SLOT_VERIFIED" in slots
        ),
        "security-floor": "security_counter < policy->security_version_floor" in slots,
        "production-artifact-authority": "artifact_authority_verify" in slots,
        "boot-prelaunch-gate": "wdc_host_prelaunch_check" in slots,
        "journal-marker-last": (
            "offsetof(WdcOtaMetadataRecord, commit_marker)" in ota
            and "sizeof(next.commit_marker)" in ota
        ),
        "host-probation": (
            "readiness_observed" in activation
            and "resource_floors_preserved" in activation
            and "administration_responsive" in activation
        ),
        "managed-entry-order": (
            app.find("wdc_app_slots_boot(") >= 0
            and app.find("wdc_app_slots_boot(") < app.rfind("wdc_runtime_call_init(runtime)")
        ),
        "no-application-self-confirmation": "wdc_activation_confirm(" not in app,
    }
    failed = [name for name, passed in source_checks.items() if not passed]
    if failed:
        raise QualificationError("HP3 source checks failed: %s" % ", ".join(failed))
    return list(source_checks)


def _compile_command(compiler: str, executable: Path) -> list[str]:
    return [
        compiler, "-std=c11", "-Wall", "-Wextra", "-Werror",
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
        "tests/contract/hp3_app_slots_smoke.c",
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
        "-o", str(executable),
    ]


def _run(command: list[str], log: Path) -> subprocess.CompletedProcess[str]:
    process = subprocess.run(
        command, cwd=ROOT, text=True, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, check=False,
    )
    log.write_text("$ " + " ".join(command) + "\n" + (process.stdout or ""), encoding="utf-8")
    return process


def _run_smoke(output: Path, compiler: str) -> tuple[dict[str, Any], list[Path]]:
    executable = output / "hp3-app-slots-smoke"
    compile_log = output / "compile.log"
    run_log = output / "run.log"
    build = _run(_compile_command(compiler, executable), compile_log)
    if build.returncode != 0 or not executable.is_file():
        raise QualificationError("HP3 smoke compilation failed")
    run = _run([str(executable), str(BUNDLE)], run_log)
    if run.returncode != 0:
        raise QualificationError("HP3 smoke execution failed")
    try:
        smoke = json.loads(run.stdout)
    except json.JSONDecodeError as exc:
        raise QualificationError("HP3 smoke emitted invalid JSON") from exc
    expected = {
        "schema": "pulse.esp32.hp3-app-slots-smoke.v1",
        "status": "PASS",
        "cases": 14,
        "failures": 0,
        "artifact_header_bytes": 192,
        "portable_slot_bytes": 917504,
        "application_code_launched": False,
        "last_confirmed_preserved": True,
        "recovery_explicit": True,
    }
    if smoke != expected:
        raise QualificationError("HP3 smoke result is not the exact passing seal")
    smoke_path = output / "synthetic-application-slots.json"
    _write_json(smoke_path, smoke)
    return smoke, [compile_log, run_log, executable, smoke_path]


def qualify(out_dir: Path, compiler: str = "cc") -> dict[str, Any]:
    output = _prepare(out_dir)
    model = _load_model()
    if shutil.which(compiler) is None:
        raise QualificationError("host C compiler is unavailable")
    catalog = host_build_contract.load_json(CATALOG)
    resolved = host_build_contract.validate_catalog(catalog)
    if set(resolved) != set(BOARD_IDS):
        raise QualificationError("HP3 board set drifted")
    slot_counts = _validate_partitions(resolved)
    source_checks = _validate_sources()

    copied: list[Path] = []
    for source, name in (
        (MODEL, "application-slot-model.json"),
        (BUNDLE, "input-bundle.wdcb"),
        (SMOKE_SOURCE, "hp3_app_slots_smoke.c"),
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
            (ROOT / entry["host_profile"], short + "-host-profile.json"),
            (ROOT / entry["partitions"], short + "-partitions.csv"),
            (lock_path, short + "-build-lock.json"),
            (fingerprint_path, short + "-running-fingerprint.json"),
        ):
            target = output / name
            shutil.copy2(source, target)
            copied.append(target)
        lock_bindings[short] = {
            "build_lock_sha256": fingerprint["build_lock_sha256"],
            "fingerprint_sha256": fingerprint["fingerprint_sha256"],
            "profile_id": fingerprint["compatibility_surface"]["host_profile_id"],
        }

    smoke, smoke_files = _run_smoke(output, compiler)
    copied.extend(smoke_files)
    report: dict[str, Any] = {
        "schema": "pulse.esp32.hp3-application-slot-report.v1",
        "pass": "HP3",
        "phase": "APPLICATION_SLOT_AUTHORITY_FALLBACK",
        "status": "PASS",
        "aggregate": "PULSE_APPLICATION_SLOT_AUTHORITY_PROVEN",
        "coverage": {
            "targets": 2,
            "slots_per_target": slot_counts,
            "journal_records": model["metadata"]["journal_records"],
            "synthetic_cases": smoke["cases"],
            "source_contract_checks": source_checks,
            "application_code_launched": False,
            "last_confirmed_preserved": True,
            "recovery_explicit": True,
        },
        "artifact": {
            "format": model["artifact"]["format"],
            "header_bytes": smoke["artifact_header_bytes"],
            "portable_slot_bytes": smoke["portable_slot_bytes"],
            "input_bundle_sha256": _sha256(BUNDLE),
            "rax": False,
        },
        "host_build_bindings": lock_bindings,
        "claim_boundary": {
            "runtime_classification": "HOST_EXECUTED_SYNTHETIC_ONLY",
            "hardware_execution_this_pass": "NOT_RUN",
            "firmware_build_this_pass": "NOT_RUN_LOCK_REPLAY_ONLY",
            "physical_power_loss_campaign": "DEFERRED_HP3_5",
            "production_artifact_authority": "CONTRACT_ONLY",
            "external_provider": "NOT_IMPLEMENTED",
            "rax": "NOT_IMPLEMENTED",
            "host_firmware_ota": "NOT_IMPLEMENTED",
            "pulse_core_changes": "NONE",
        },
        "preserved_authorities": model["preserved_authorities"],
    }
    report_path = output / "qualification-report.json"
    markdown_path = output / "qualification-report.md"
    _write_json(report_path, report)
    markdown_path.write_text(
        "# HP3 application-slot qualification\n\n"
        "Status: **PASS**\n\n"
        "Aggregate: `PULSE_APPLICATION_SLOT_AUTHORITY_PROVEN`\n\n"
        "Two target layouts, two exact HP2 lock/fingerprint bindings, ten "
        "source-contract checks, and fourteen synthetic application-slot "
        "cases pass. The slot gate did not enter application code, preserved "
        "the last confirmed application, and produced explicit recovery.\n\n"
        "This is host-executed synthetic evidence. No firmware build, target "
        "execution, production signing deployment, or physical power-loss "
        "campaign is claimed. Exhaustive interruption work is HP3.5.\n",
        encoding="utf-8",
    )
    manifest_inputs = [*copied, report_path, markdown_path]
    manifest = {
        "schema": "pulse.esp32.hp3-evidence-manifest.v1",
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
        subprocess.SubprocessError,
        host_build_contract.HostBuildContractError,
        QualificationError,
    ) as exc:
        print("HP3 qualification failed: %s" % exc, file=sys.stderr)
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
