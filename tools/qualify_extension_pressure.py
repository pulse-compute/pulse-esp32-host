#!/usr/bin/env python3
"""Qualify the HX5b sustained-pressure seal without overclaiming hardware."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

try:
    from tools import qualify_extension_faults, qualify_extension_runtime
except ModuleNotFoundError:  # Direct execution from tools/.
    import qualify_extension_faults  # type: ignore[no-redef]
    import qualify_extension_runtime  # type: ignore[no-redef]


ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "specs/PULSE-ESP32-005b-extension-pressure-seal.json"
SCHEMA = "pulse.esp32.host-extension-report.v1"
PHASE = "PRESSURE_HOST_SEALED"
PRESSURE_SCHEMA = "pulse.esp32.hx5b-pressure-evidence.v1"
EXPECTED_BOUNDS = {
    "completion_storm_iterations": 128,
    "hardware_effect_timeout_ms": 1000,
    "hardware_queue_accepted_events": 128,
    "hardware_queue_rounds": 8,
    "host_pressure_reservation_bytes": 262144,
    "native_fault_cycles": 64,
    "queue_capacity": 16,
    "queue_rounds": 64,
    "wasm_pressure_reservation_bytes": 4194304,
    "wasm_trap_cycles": 64,
}
EXPECTED_WORKLOADS = {
    "queue-saturation-recovery",
    "deadline-late-completion-storm",
    "duplicate-completion-recovery-storm",
    "bounded-latency-distribution",
    "repeated-wasm-trap-recovery",
    "repeated-native-fault-reset-cycles",
    "pressure-reservation-released",
}
EXPECTED_NATIVE_CASES = EXPECTED_WORKLOADS - {"repeated-wasm-trap-recovery"} | {
    "pressure-reservation-held"
}
EXPECTED_COMMON_WASM_SHA256 = (
    "ef8b21a4b7a423923c09f5e38fc626ff7d1cda856c4935db7f191695a333e5c4"
)
EXPECTED_TARGETS = {"esp32s3", "esp32c6"}


class QualificationError(RuntimeError):
    """Raised when HX5b pressure evidence is incomplete or overclaimed."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact(path: Path, root: Path) -> dict[str, Any]:
    return {
        "path": str(path.relative_to(root)),
        "sha256": _sha256(path),
        "size": path.stat().st_size,
    }


def _external_artifact(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "sha256": _sha256(path),
        "size": path.stat().st_size,
    }


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _run(command: list[str], log: Path) -> subprocess.CompletedProcess[str]:
    process = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    log.write_text(
        "$ " + " ".join(command) + "\n" + (process.stdout or ""),
        encoding="utf-8",
    )
    return process


def _load_model() -> dict[str, Any]:
    model = json.loads(MODEL.read_text(encoding="utf-8"))
    if (
        not isinstance(model, dict)
        or model.get("schema") != "pulse.esp32.hx5b-extension-pressure-seal.v1"
        or model.get("pass") != "HX5b"
        or model.get("phase") != PHASE
        or model.get("bounds") != EXPECTED_BOUNDS
    ):
        raise QualificationError("HX5b pressure model identity or bounds drifted")
    workloads = model.get("required_workloads")
    if (
        not isinstance(workloads, list)
        or {item.get("id") for item in workloads} != EXPECTED_WORKLOADS
        or any(not item.get("required_outcome") for item in workloads)
    ):
        raise QualificationError("HX5b workload inventory is incomplete")
    campaigns = model.get("hardware_campaigns")
    if (
        not isinstance(campaigns, list)
        or {item.get("target") for item in campaigns} != EXPECTED_TARGETS
        or any(item.get("pressure_marker") != "PULSE_HX45_PRESSURE" for item in campaigns)
    ):
        raise QualificationError("HX5b named-board campaign inventory drifted")
    excluded = " ".join(model.get("excluded", [])).lower()
    if "rax" not in excluded or "hx6" not in excluded or "peripheral" not in excluded:
        raise QualificationError("HX5b exclusion boundary is incomplete")
    return model


def _pressure_compile_command(compiler: str, executable: Path) -> list[str]:
    return [
        compiler,
        "-std=c11",
        "-Wall",
        "-Wextra",
        "-Werror",
        "-DPULSE_EXTENSION_HOST_TEST",
        "-Inative-sdk/c/include",
        "-Ifirmware/components/wdc_extension/include",
        "-Ifirmware/components/wdc_extension",
        "-Ifirmware/components/wdc_elf/include",
        "-Ifirmware/components/wdc_events/include",
        "-Ifirmware/components/wdc_abi/include",
        "tests/contract/hx5b_pressure_smoke.c",
        "firmware/components/wdc_extension/wdc_extension_host_services.c",
        "firmware/components/wdc_extension/wdc_extension_lifecycle.c",
        "firmware/components/wdc_events/wdc_event_queue.c",
        "-o",
        str(executable),
    ]


def _validate_native(result: dict[str, Any]) -> None:
    cases = {item.get("name"): item.get("status") for item in result.get("cases", [])}
    queue = result.get("queue", {})
    completions = result.get("completions", {})
    latency = result.get("latency_ticks", {})
    faults = result.get("native_faults", {})
    memory = result.get("memory_pressure", {})
    if (
        result.get("schema") != "pulse.esp32.hx5b-pressure-smoke.v1"
        or result.get("status") != "PASS"
        or result.get("failures") != 0
        or result.get("case_count") != len(EXPECTED_NATIVE_CASES)
        or cases != {name: "PASS" for name in EXPECTED_NATIVE_CASES}
        or queue
        != {
            "rounds": 64,
            "capacity": 16,
            "accepted": 1024,
            "rejected": 64,
            "recovered_rounds": 64,
            "high_water": 16,
        }
        or completions
        != {
            "iterations": 128,
            "late": 128,
            "duplicates": 128,
            "successful_recoveries": 128,
        }
        or latency
        != {
            "sample_count": 128,
            "minimum": 0,
            "p50": 3,
            "p95": 7,
            "maximum": 7,
        }
        or faults
        != {"cycles": 64, "faults": 64, "simulated_resets": 64}
        or memory.get("reserved_bytes") != 262144
        or memory.get("retained_bytes") != 0
        or not isinstance(memory.get("checksum"), int)
        or memory.get("checksum", 0) == 0
    ):
        raise QualificationError("HX5b native pressure corpus is incomplete")


def _validate_wasm(result: dict[str, Any]) -> None:
    if (
        result.get("schema") != "pulse.esp32.hx5b-wasm-pressure-smoke.v1"
        or result.get("status") != "PASS"
        or result.get("trap_cycles") != 64
        or result.get("traps") != 64
        or result.get("successful_recoveries") != 64
        or result.get("host_calls") != 64
        or result.get("pressure_reservation_bytes") != 4194304
        or not isinstance(result.get("pressure_checksum"), int)
        or result.get("pressure_checksum", 0) == 0
        or result.get("common_wasm_sha256") != EXPECTED_COMMON_WASM_SHA256
        or not isinstance(result.get("trap_wasm_sha256"), str)
        or len(result.get("trap_wasm_sha256", "")) != 64
    ):
        raise QualificationError("HX5b real-Wasm pressure corpus is incomplete")


def _run_pressure_smokes(out: Path) -> dict[str, Any]:
    compiler = shutil.which("cc")
    node = shutil.which("node")
    if compiler is None:
        raise QualificationError("host C compiler is unavailable")
    if node is None:
        raise QualificationError("Node.js is unavailable for real-Wasm pressure")
    evidence = out / "host-pressure-smoke"
    evidence.mkdir(parents=True)
    executable = evidence / "hx5b-pressure-smoke"
    compile_log = evidence / "compile.log"
    native_log = evidence / "native-run.log"
    wasm_log = evidence / "wasm-run.log"
    build = _run(_pressure_compile_command(compiler, executable), compile_log)
    if build.returncode != 0 or not executable.is_file():
        raise QualificationError("HX5b native pressure smoke compilation failed")
    native = _run([str(executable)], native_log)
    if native.returncode != 0:
        raise QualificationError("HX5b native pressure smoke execution failed")
    wasm = _run([node, "tests/contract/hx5b_wasm_pressure_smoke.mjs"], wasm_log)
    if wasm.returncode != 0:
        raise QualificationError("HX5b real-Wasm pressure smoke execution failed")
    try:
        native_result = json.loads(native.stdout)
        wasm_result = json.loads(wasm.stdout)
    except json.JSONDecodeError as exc:
        raise QualificationError("HX5b pressure smoke emitted invalid JSON") from exc
    _validate_native(native_result)
    _validate_wasm(wasm_result)
    return {
        "schema": PRESSURE_SCHEMA,
        "status": "PASS",
        "classification": "HOST_EXECUTED_SUSTAINED_PRESSURE",
        "native": native_result,
        "real_wasm": wasm_result,
        "artifacts": {
            "executable": _artifact(executable, out),
            "compile_log": _artifact(compile_log, out),
            "native_run_log": _artifact(native_log, out),
            "wasm_run_log": _artifact(wasm_log, out),
        },
    }


def _load_hardware_evaluation(path: Path, target: str) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise QualificationError(f"{target} hardware evaluation is missing")
    report = json.loads(resolved.read_text(encoding="utf-8"))
    board = report.get("board", {})
    pressure = report.get("pressure_seal", {})
    expected_schema = {
        "esp32s3": "pulse.esp32.hx45-s3-aitrip-hardware-report.v1",
        "esp32c6": "pulse.esp32.hx45-c6-xiao-hardware-report.v1",
    }[target]
    artifacts = report.get("artifacts", {})
    observations = report.get("observations", {})
    if (
        not isinstance(report, dict)
        or report.get("schema") != expected_schema
        or report.get("status") != "PASS"
        or report.get("runtime_result") != "NAMED_BOARD_OBSERVED"
        or not isinstance(board, dict)
        or board.get("target") != target
        or not isinstance(pressure, dict)
        or pressure.get("required") is not True
        or pressure.get("status") != "PASS"
        or pressure.get("campaign") != "HX5b"
        or not isinstance(artifacts, dict)
        or not isinstance(observations, dict)
        or len(observations.get("measured_clean_cycles", [])) != 5
        or not observations.get("heap_samples")
        or not isinstance(observations.get("firmware_size"), dict)
        or observations.get("fatal_serial_signatures") != []
    ):
        raise QualificationError(f"{target} evaluation is not passing HX5b pressure evidence")
    for label in ("serial_log", "build_report"):
        evidence = artifacts.get(label, {})
        if not isinstance(evidence, dict):
            raise QualificationError(
                f"{target} evaluation has invalid raw {label} evidence"
            )
        evidence_path_value = evidence.get("path")
        if not isinstance(evidence_path_value, str) or not evidence_path_value:
            raise QualificationError(
                f"{target} evaluation has invalid raw {label} path"
            )
        evidence_path = Path(evidence_path_value).expanduser()
        if (
            not evidence_path.is_file()
            or evidence.get("sha256") != _sha256(evidence_path)
            or evidence.get("size") != evidence_path.stat().st_size
        ):
            raise QualificationError(
                f"{target} evaluation has missing or stale raw {label} evidence"
            )
    return {
        "status": "PASS",
        "runtime_result": "NAMED_BOARD_OBSERVED",
        "board": board,
        "pressure_seal": pressure,
        "raw_artifacts": {
            "serial_log": artifacts["serial_log"],
            "build_report": artifacts["build_report"],
        },
        "artifact": _external_artifact(resolved),
    }


def _write_markdown(report: dict[str, Any], out: Path) -> None:
    native = report["pressure"]["native"]
    wasm = report["pressure"]["real_wasm"]
    lines = [
        "# HX5b extension pressure qualification",
        "",
        f"- Status: `{report['status']}`",
        f"- Phase: `{report['phase']}`",
        f"- Aggregate: `{report['aggregate']}`",
        f"- Host queue rounds: `{native['queue']['rounds']}`",
        f"- Late / duplicate completion iterations: `{native['completions']['iterations']}`",
        f"- Native fault/reset cycles: `{native['native_faults']['cycles']}`",
        f"- Real Wasm trap/recovery cycles: `{wasm['trap_cycles']}`",
        f"- Tracked retained host bytes: `{native['memory_pressure']['retained_bytes']}`",
        f"- Hardware execution: `{report['hardware']['execution_this_pass']}`",
        "",
        "## Pressure workloads",
        "",
        "| Workload | Status |",
        "|---|---|",
    ]
    for workload in report["model"]["required_workloads"]:
        lines.append(f"| `{workload['id']}` | `PASS` |")
    lines.extend(["", "## Claim boundary", "", report["claim_boundary"], ""])
    if report["hardware"]["execution_this_pass"] == "NOT_RUN":
        lines.extend(
            [
                "The opt-in AITRIP S3 and XIAO C6 pressure images and fail-closed "
                "evaluators are prepared, but no serial log is synthesized or inferred.",
                "",
            ]
        )
    (out / "qualification-report.md").write_text(
        "\n".join(lines), encoding="utf-8"
    )


def qualify(
    output: Path,
    *,
    s3_evaluation: Path | None = None,
    c6_evaluation: Path | None = None,
) -> dict[str, Any]:
    out = qualify_extension_runtime._prepare_output(output)  # noqa: SLF001
    model = _load_model()
    if (s3_evaluation is None) != (c6_evaluation is None):
        raise QualificationError(
            "supply both S3 and C6 HX5b evaluations or neither; a partial pair cannot close the gate"
        )

    hx5a_dir = out / "hx5a-baseline"
    hx5a = qualify_extension_faults.qualify(hx5a_dir)
    if (
        hx5a.get("status") != "PASS"
        or hx5a.get("aggregate") != "HOST_HARDENING_PROVEN"
        or hx5a.get("coverage", {}).get("executed_case_count") != 56
    ):
        raise QualificationError("the complete HX5a baseline did not re-execute exactly")
    pressure = _run_pressure_smokes(out)
    pressure_path = out / "hx5b-pressure-corpus.json"
    _write_json(pressure_path, pressure)

    hardware_results: dict[str, Any] = {}
    if s3_evaluation is not None and c6_evaluation is not None:
        hardware_results["esp32s3"] = _load_hardware_evaluation(
            s3_evaluation, "esp32s3"
        )
        hardware_results["esp32c6"] = _load_hardware_evaluation(
            c6_evaluation, "esp32c6"
        )
        hardware_status = "DUAL_NAMED_BOARD_OBSERVED"
        aggregate = "DUAL_ISA_PRESSURE_OBSERVED"
    else:
        hardware_status = "NOT_RUN"
        aggregate = "HOST_PRESSURE_PROVEN"

    source_hash, source_files = qualify_extension_runtime._tree_digest(  # noqa: SLF001
        ROOT, {"reports", "__pycache__"}
    )
    environment = {
        "schema": "pulse.esp32.hx5b-environment.v1",
        "python": sys.version,
        "platform": platform.platform(),
        "cwd": str(ROOT),
        "LANG": os.environ.get("LANG"),
        "LC_ALL": os.environ.get("LC_ALL"),
    }
    environment_path = out / "environment.json"
    _write_json(environment_path, environment)
    source = {
        "schema": "pulse.esp32.hx5b-source-identity.v1",
        "source_tree": {"sha256": source_hash, "file_count": source_files},
        "pressure_model": {
            "path": str(MODEL.relative_to(ROOT)),
            "sha256": _sha256(MODEL),
        },
    }
    source_path = out / "source.json"
    _write_json(source_path, source)

    native = pressure["native"]
    wasm = pressure["real_wasm"]
    report: dict[str, Any] = {
        "schema": SCHEMA,
        "pass": "HX5b",
        "status": "PASS",
        "phase": PHASE,
        "aggregate": aggregate,
        "scope": "SUSTAINED_PRESSURE_RECOVERY_AND_NAMED_BOARD_RERUN_GATE",
        "source_tree": {"sha256": source_hash, "file_count": source_files},
        "evidence": {
            "environment": _artifact(environment_path, out),
            "source": _artifact(source_path, out),
            "hx5a_baseline": _artifact(
                hx5a_dir / "qualification-report.json", out
            ),
            "pressure": _artifact(pressure_path, out),
        },
        "model": {
            "schema": model["schema"],
            "path": str(MODEL.relative_to(ROOT)),
            "sha256": _sha256(MODEL),
            "bounds": model["bounds"],
            "required_workloads": model["required_workloads"],
            "hardware_campaigns": model["hardware_campaigns"],
        },
        "baseline": {
            "status": hx5a["status"],
            "pass": hx5a["pass"],
            "executed_case_count": hx5a["coverage"]["executed_case_count"],
        },
        "pressure": pressure,
        "coverage": {
            "status": "PASS",
            "workload_count": len(EXPECTED_WORKLOADS),
            "host_case_count": native["case_count"],
            "queue_rounds": native["queue"]["rounds"],
            "completion_iterations": native["completions"]["iterations"],
            "native_fault_cycles": native["native_faults"]["cycles"],
            "wasm_trap_cycles": wasm["trap_cycles"],
            "bounded_operation_count": 1664,
            "all_workloads_recovered": True,
            "retained_bytes": native["memory_pressure"]["retained_bytes"],
        },
        "hardware": {
            "execution_this_pass": hardware_status,
            "required_targets": ["esp32s3", "esp32c6"],
            "results": hardware_results,
            "absent_artifact_policy": (
                "No serial log or target artifact is emitted when hardware is not run."
            ),
        },
        "excluded": model["excluded"],
        "claim_boundary": (
            "HX5b proves sustained host queue/completion pressure, real Wasm trap "
            "recovery, reset-simulated native faults, bounded deterministic timing, "
            "and zero tracked host retention. Named-board runtime is claimed only "
            "when both fail-closed HX5b evaluation reports are supplied. It adds no "
            "capability, ABI, provider, peripheral, RAX, HX6, or HX7 behavior."
        ),
    }
    report_path = out / "qualification-report.json"
    _write_json(report_path, report)
    _write_markdown(report, out)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--s3-evaluation", type=Path)
    parser.add_argument("--c6-evaluation", type=Path)
    args = parser.parse_args(argv)
    try:
        report = qualify(
            args.out_dir,
            s3_evaluation=args.s3_evaluation,
            c6_evaluation=args.c6_evaluation,
        )
    except (
        OSError,
        ValueError,
        json.JSONDecodeError,
        QualificationError,
        qualify_extension_faults.QualificationError,
        qualify_extension_runtime.QualificationError,
    ) as exc:
        print(f"HX5b qualification failed: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "status": report["status"],
                "phase": report["phase"],
                "aggregate": report["aggregate"],
                "hardware": report["hardware"]["execution_this_pass"],
                "out_dir": str(args.out_dir),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
