#!/usr/bin/env python3
"""Qualify the HP2 host-build coherence and running-fingerprint boundary."""
from __future__ import annotations

import argparse
import copy
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Optional

try:
    from tools import host_build_contract
except ModuleNotFoundError:  # Direct execution from tools/.
    import host_build_contract  # type: ignore[no-redef]


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INTENT = ROOT / "examples/host-intents/portable-loopback-v1.json"
SMOKE_SOURCE = ROOT / "tests/contract/hp2_host_identity_smoke.c"
GENERATED_C = (
    ROOT
    / "firmware/components/wdc_host_identity/wdc_host_fingerprint_generated.c"
)
BOARD_IDS = (
    "aitrip-esp32s3-devkitc-1-n8r2",
    "seeed-xiao-esp32c6-4m",
)


class QualificationError(RuntimeError):
    """Raised when HP2 cannot produce an exact passing seal."""


def _prepare(path: Path) -> Path:
    output = path.expanduser().resolve()
    if output.exists():
        if not output.is_dir() or any(output.iterdir()):
            raise QualificationError("output directory must be absent or empty")
    else:
        output.mkdir(parents=True)
    return output


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _evidence(path: Path, output: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(output).as_posix(),
        "sha256": host_build_contract.sha256_file(path),
        "size": path.stat().st_size,
    }


def _run_smoke(output: Path, compiler: str) -> tuple[dict[str, Any], dict[str, Any]]:
    executable = output / "hp2-host-identity-smoke"
    compile_log = output / "compile.log"
    run_log = output / "run.log"
    command = [
        compiler,
        "-std=c11",
        "-Wall",
        "-Wextra",
        "-Werror",
        "-DWDC_HOST_TEST_TARGET_C6=1",
        "-Ifirmware/components/wdc_abi/include",
        "-Ifirmware/components/wdc_control/include",
        "-Ifirmware/components/wdc_host_identity/include",
        "tests/contract/hp2_host_identity_smoke.c",
        "firmware/components/wdc_control/wdc_control.c",
        "firmware/components/wdc_host_identity/wdc_host_identity.c",
        "firmware/components/wdc_host_identity/wdc_host_fingerprint_generated.c",
        "-o",
        str(executable),
    ]
    compile_process = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    compile_log.write_text(
        "$ " + " ".join(command) + "\n" + compile_process.stdout,
        encoding="utf-8",
    )
    if compile_process.returncode != 0:
        raise QualificationError("HP2 fingerprint smoke compilation failed")
    run_process = subprocess.run(
        [str(executable)],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    run_log.write_text("$ %s\n%s" % (executable, run_process.stdout), encoding="utf-8")
    if run_process.returncode != 0:
        raise QualificationError("HP2 fingerprint smoke execution failed")
    try:
        smoke = json.loads(run_process.stdout)
    except json.JSONDecodeError as exc:
        raise QualificationError("HP2 smoke did not emit one JSON object") from exc
    expected = {
        "schema": "pulse.esp32.hp2-host-identity-smoke.v1",
        "status": "PASS",
        "failures": 0,
        "case_count": 8,
    }
    if any(smoke.get(key) != value for key, value in expected.items()):
        raise QualificationError("HP2 smoke result is not the exact passing seal")
    if smoke.get("application_code_launched") is not False:
        raise QualificationError("HP2 prelaunch smoke entered application code")
    smoke_path = output / "synthetic-prelaunch.json"
    _write_json(smoke_path, smoke)
    return smoke, {
        "compile_log": _evidence(compile_log, output),
        "run_log": _evidence(run_log, output),
        "executable": _evidence(executable, output),
        "smoke": _evidence(smoke_path, output),
    }


def _expect_error(
    name: str,
    operation: Callable[[], object],
    observed: list[str],
) -> None:
    try:
        operation()
    except (host_build_contract.HostBuildContractError, ValueError):
        observed.append(name)
        return
    raise QualificationError("negative case did not fail closed: %s" % name)


def _negative_cases(
    catalog: dict[str, Any],
    intent: dict[str, Any],
    c6_lock: dict[str, Any],
    c6_fingerprint: dict[str, Any],
) -> list[str]:
    observed: list[str] = []

    drifted_catalog = copy.deepcopy(catalog)
    drifted_catalog["lane"]["version"] = "v5.5.0"
    _expect_error(
        "ambient-or-moving-lane",
        lambda: host_build_contract.make_plan(
            intent, "seeed-xiao-esp32c6-4m", drifted_catalog
        ),
        observed,
    )

    unknown_capability = copy.deepcopy(intent)
    unknown_capability["required_capabilities"].append("pulse.raw-idf.v1")
    _expect_error(
        "unknown-capability",
        lambda: host_build_contract.validate_intent(unknown_capability),
        observed,
    )

    tampered_lock = copy.deepcopy(c6_lock)
    tampered_lock["inputs"][0]["sha256"] = "0" * 64
    _expect_error(
        "locked-input-drift",
        lambda: host_build_contract.replay_lock(tampered_lock),
        observed,
    )

    tampered_fingerprint = copy.deepcopy(c6_fingerprint)
    tampered_fingerprint["build_lock_sha256"] = "0" * 64
    _expect_error(
        "fingerprint-lock-binding",
        lambda: host_build_contract.validate_fingerprint(tampered_fingerprint),
        observed,
    )

    c6_optimized = copy.deepcopy(intent)
    c6_optimized["placement"] = "target-optimized"
    c6_optimized["resources"]["target_optimization_bytes"] = 1
    c6_result = host_build_contract.check_running(c6_optimized, c6_fingerprint)
    if (
        c6_result["status"] != "FAIL"
        or c6_result["deployment"] != "HOST_BUILD_PLAN_REQUIRED"
        or c6_result["application_code_launched"] is not False
    ):
        raise QualificationError("C6 target-optimized request did not fail closed")
    observed.append("c6-target-optimization")

    wrong_target = copy.deepcopy(intent)
    wrong_target["allowed_boards"] = ["aitrip-esp32s3-devkitc-1-n8r2"]
    wrong_target["allowed_targets"] = ["esp32s3"]
    target_result = host_build_contract.check_running(wrong_target, c6_fingerprint)
    if target_result["status"] != "FAIL" or target_result["application_code_launched"] is not False:
        raise QualificationError("wrong-target application did not fail before launch")
    observed.append("wrong-board-and-target")

    plan = host_build_contract.make_plan(intent, "seeed-xiao-esp32c6-4m", catalog)
    tampered_plan = copy.deepcopy(plan)
    tampered_plan["host_plan"]["dependency_lock"] = (
        "firmware/locks/host-extension/idf-5.4.4/esp32s3/dependencies.lock"
    )
    tampered_plan["host_plan_sha256"] = host_build_contract.canonical_sha256(
        tampered_plan["host_plan"]
    )
    payload = dict(tampered_plan)
    payload.pop("plan_sha256")
    tampered_plan["plan_sha256"] = host_build_contract.canonical_sha256(payload)
    _expect_error(
        "plan-path-substitution",
        lambda: host_build_contract.make_lock_from_plan(tampered_plan, catalog),
        observed,
    )

    reversed_abi = copy.deepcopy(intent)
    reversed_abi["host_abi"]["min_minor"] = 2
    reversed_abi["host_abi"]["max_minor"] = 1
    _expect_error(
        "reversed-abi-range",
        lambda: host_build_contract.validate_intent(reversed_abi),
        observed,
    )
    return observed


def qualify(output: Path, compiler: str) -> dict[str, Any]:
    catalog = host_build_contract.load_json(host_build_contract.DEFAULT_CATALOG)
    intent = host_build_contract.load_json(DEFAULT_INTENT)
    resolved = host_build_contract.validate_catalog(catalog)
    host_build_contract.validate_intent(intent)
    copied_catalog = output / "host-build-catalog.json"
    copied_intent = output / "target-intent.json"
    shutil.copy2(host_build_contract.DEFAULT_CATALOG, copied_catalog)
    shutil.copy2(DEFAULT_INTENT, copied_intent)

    plan_evidence: dict[str, Any] = {}
    lock_evidence: dict[str, Any] = {}
    fingerprint_evidence: dict[str, Any] = {}
    locks: dict[str, dict[str, Any]] = {}
    fingerprints: dict[str, dict[str, Any]] = {}
    for board_id in BOARD_IDS:
        entry = resolved[board_id]["entry"]
        lock_path = ROOT / entry["build_lock"]
        fingerprint_path = ROOT / entry["fingerprint"]
        lock = host_build_contract.load_json(lock_path)
        fingerprint = host_build_contract.load_json(fingerprint_path)
        host_build_contract.replay_lock(lock, fingerprint)
        plan = host_build_contract.make_plan(
            intent,
            board_id,
            catalog,
            running_fingerprint=fingerprint,
        )
        if plan["selection"]["deployment"] != "APP_ONLY_DEPLOYMENT":
            raise QualificationError("compatible running host did not select app-only deployment")
        short = "s3" if entry["target"] == "esp32s3" else "c6"
        plan_path = output / (short + "-build-plan.json")
        lock_copy = output / (short + "-build-lock.json")
        fingerprint_copy = output / (short + "-running-fingerprint.json")
        _write_json(plan_path, plan)
        shutil.copy2(lock_path, lock_copy)
        shutil.copy2(fingerprint_path, fingerprint_copy)
        plan_evidence[short] = _evidence(plan_path, output)
        lock_evidence[short] = _evidence(lock_copy, output)
        fingerprint_evidence[short] = _evidence(fingerprint_copy, output)
        locks[short] = lock
        fingerprints[short] = fingerprint

    rendered = host_build_contract.render_generated_c(catalog)
    if GENERATED_C.read_text(encoding="utf-8") != rendered:
        raise QualificationError("committed running-fingerprint C is not lock-derived")
    generated_copy = output / "wdc_host_fingerprint_generated.c"
    generated_copy.write_text(rendered, encoding="utf-8")

    negative = _negative_cases(catalog, intent, locks["c6"], fingerprints["c6"])
    if len(negative) != 8:
        raise QualificationError("HP2 negative corpus is incomplete")
    smoke, smoke_evidence = _run_smoke(output, compiler)
    evidence = {
        "catalog": _evidence(copied_catalog, output),
        "intent": _evidence(copied_intent, output),
        "plans": plan_evidence,
        "locks": lock_evidence,
        "fingerprints": fingerprint_evidence,
        "generated_c": _evidence(generated_copy, output),
        **smoke_evidence,
    }
    report: dict[str, Any] = {
        "schema": "pulse.esp32.hp2-host-build-report.v1",
        "pass": "HP2",
        "phase": "HOST_PROFILE_BUILD_COHERENCE_LOCK_FINGERPRINT",
        "status": "PASS",
        "aggregate": "HOST_BUILD_COHERENCE_PROVEN",
        "claim_boundary": {
            "runtime_classification": "HOST_EXECUTED_SYNTHETIC_ONLY",
            "hardware_execution_this_pass": "NOT_RUN",
            "host_firmware_build_this_pass": "NOT_RUN_LOCK_RESOLUTION_ONLY",
            "external_provider": "NOT_IMPLEMENTED",
            "pulse_core_changes": "NONE",
        },
        "coverage": {
            "board_identities": 2,
            "host_profiles": 2,
            "build_plans": 2,
            "exact_build_locks": 2,
            "running_fingerprints": 2,
            "prelaunch_cases": smoke["case_count"],
            "negative_cases": len(negative),
            "negative_case_names": negative,
            "application_code_launched": False,
        },
        "coherence": {
            "lane": catalog["lane"],
            "silent_upgrade": False,
            "new_lock_operation": "EXPLICIT_ONLY",
            "c6_build_lock_sha256": fingerprints["c6"]["build_lock_sha256"],
            "c6_fingerprint_sha256": fingerprints["c6"]["fingerprint_sha256"],
            "s3_build_lock_sha256": fingerprints["s3"]["build_lock_sha256"],
            "s3_fingerprint_sha256": fingerprints["s3"]["fingerprint_sha256"],
        },
        "preserved_authorities": {
            "hp1_resource_authority_sha256": "cc3afbfc4ff7d4a7b5b5aca6ae0b5953a34065501bbfea36d4580a2d193fd84d",
            "native_extension_abi_sha256": "e92aaae33b4016f5e3d1ac41f34fac0b19569c7f0bbabba6ce3d4e2604f6e023",
            "common_wasm_sha256": "ef8b21a4b7a423923c09f5e38fc626ff7d1cda856c4935db7f191695a333e5c4",
        },
        "evidence": evidence,
    }
    report_path = output / "qualification-report.json"
    markdown_path = output / "qualification-report.md"
    _write_json(report_path, report)
    markdown_path.write_text(
        "# HP2 host build coherence qualification\n\n"
        "Status: **PASS**\n\n"
        "Aggregate: `HOST_BUILD_COHERENCE_PROVEN`\n\n"
        "Two named-board identities, two HP1 host profiles, two exact build "
        "locks, and two running fingerprints replay without silent upgrades. "
        "Eight prelaunch and eight negative cases pass.\n\n"
        "This is host-executed synthetic evidence. No firmware was built, "
        "flashed, or observed on hardware in HP2, and no external provider or "
        "Pulse-core configuration surface was implemented.\n",
        encoding="utf-8",
    )
    return report


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--cc", default="cc")
    args = parser.parse_args(argv)
    try:
        output = _prepare(args.out_dir)
        report = qualify(output, args.cc)
    except (
        OSError,
        ValueError,
        subprocess.SubprocessError,
        host_build_contract.HostBuildContractError,
        QualificationError,
    ) as exc:
        print("HP2 qualification failed: %s" % exc, file=sys.stderr)
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
