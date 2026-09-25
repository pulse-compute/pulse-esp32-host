#!/usr/bin/env python3
"""Qualify HP1 host-kernel resource authority with synthetic sources."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "specs/PULSE-ESP32-006-host-kernel-resource-authority.json"
PHASE = "HOST_KERNEL_RESOURCE_AUTHORITY"
EXPECTED_CASES = {
    "fixed-priority-and-reserve-authority",
    "isr-fixed-capture-notification",
    "priority-preemption-under-application-pressure",
    "terminal-completion-exactly-once",
    "per-class-capacity-reservation",
    "c6-portable-admission",
    "admission-denials-fail-closed",
    "s3-psram-explicit-nonportable",
    "synthetic-pressure-no-retention",
}
EXPECTED_PRIORITIES = {
    "application": 5,
    "capability": 7,
    "network": 9,
    "administration": 11,
    "safety_recovery": 13,
}


class QualificationError(RuntimeError):
    """Raised when HP1 source or synthetic evidence drifts."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact(path: Path, root: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": _sha256(path),
        "size": path.stat().st_size,
    }


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _load_model() -> dict[str, Any]:
    try:
        model = json.loads(MODEL.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise QualificationError(f"cannot read HP1 model: {exc}") from exc
    if (
        not isinstance(model, dict)
        or model.get("schema")
        != "pulse.esp32.hp1-host-kernel-resource-authority.v1"
        or model.get("pass") != "HP1"
        or model.get("phase") != PHASE
        or model.get("status") != "FROZEN"
    ):
        raise QualificationError("HP1 model identity drifted")
    priorities = model.get("priority_classes")
    expected = [
        ("SAFETY_RECOVERY", 13, 4096, 8, "LATCH_RECOVERY_REJECT_NEWEST"),
        ("ADMINISTRATION", 11, 6144, 8, "TERMINAL_REJECT_NEWEST"),
        ("NETWORK", 9, 6144, 8, "TERMINAL_REJECT_NEWEST"),
        ("CAPABILITY", 7, 4096, 16, "TERMINAL_REJECT_NEWEST"),
        ("APPLICATION", 5, 8192, 16, "TERMINAL_REJECT_NEWEST"),
    ]
    observed = [
        (
            item.get("class"),
            item.get("freertos_priority"),
            item.get("stack_bytes"),
            item.get("queue_capacity"),
            item.get("overflow"),
        )
        for item in priorities or []
        if isinstance(item, dict)
    ]
    if observed != expected:
        raise QualificationError("HP1 priority or queue authority drifted")
    c6 = model.get("profiles", {}).get("c6_minimum", {})
    if (
        c6.get("profile_id") != "esp32c6-no-psram-minimum-v1"
        or c6.get("psram_supported") is not False
        or c6.get("fixed_control_reserve_bytes") != 98304
        or c6.get("exclusive_update_working_bytes") != 65536
        or c6.get("largest_block_floor_bytes") != 32768
        or c6.get("maximum_application_internal_bytes") != 131072
        or sum(c6.get("reserve_breakdown", {}).values()) != 90112
        or c6.get("kernel_static_bytes") != 8192
    ):
        raise QualificationError("HP1 C6 minimum profile drifted")
    if c6["kernel_static_bytes"] + sum(c6["reserve_breakdown"].values()) != 98304:
        raise QualificationError("HP1 C6 reserve breakdown does not close")
    seal = model.get("synthetic_seal", {})
    if seal != {
        "admission_denials": 8,
        "case_count": 9,
        "isr_captures": 8,
        "isr_overflows": 1,
        "pressure_accepted": 320,
        "pressure_retained": 0,
        "pressure_rounds": 64,
        "pressure_terminal": 320,
    }:
        raise QualificationError("HP1 synthetic seal drifted")
    return model


def _compile_command(compiler: str, executable: Path) -> list[str]:
    return [
        compiler,
        "-std=c11",
        "-Wall",
        "-Wextra",
        "-Werror",
        "-Ifirmware/components/wdc_abi/include",
        "-Ifirmware/components/wdc_control/include",
        "tests/contract/hp1_control_kernel_smoke.c",
        "firmware/components/wdc_control/wdc_control.c",
        "-o",
        str(executable),
    ]


def _run(command: list[str], log: Path) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    log.write_text(
        "$ " + " ".join(command) + "\n" + (result.stdout or ""),
        encoding="utf-8",
    )
    return result


def _validate_smoke(smoke: dict[str, Any]) -> None:
    cases = {
        item.get("name"): item.get("status")
        for item in smoke.get("cases", [])
        if isinstance(item, dict)
    }
    if (
        smoke.get("schema") != "pulse.esp32.hp1-control-kernel-smoke.v1"
        or smoke.get("status") != "PASS"
        or smoke.get("failures") != 0
        or smoke.get("case_count") != len(EXPECTED_CASES)
        or cases != {name: "PASS" for name in EXPECTED_CASES}
        or smoke.get("priorities") != EXPECTED_PRIORITIES
        or smoke.get("isr")
        != {"capacity": 8, "captures": 8, "notifications": 8, "overflows": 1}
        or smoke.get("queues")
        != {"application_high_water": 16, "terminal_overflow_rejections": 1}
        or smoke.get("c6_admission")
        != {
            "denial_count": 8,
            "fixed_reserve_bytes": 98304,
            "remaining_internal_free_bytes": 62520,
            "remaining_largest_block_bytes": 122880,
            "required_internal_free_bytes": 192512,
            "required_largest_block_bytes": 98304,
        }
        or smoke.get("s3_optimization")
        != {"portable": False, "required_psram_free_bytes": 393216}
        or smoke.get("pressure")
        != {"accepted": 320, "retained": 0, "rounds": 64, "terminal": 320}
    ):
        raise QualificationError("HP1 synthetic control-kernel smoke is incomplete")


def _render_markdown(report: dict[str, Any]) -> str:
    coverage = report["coverage"]
    c6 = report["c6_admission_witness"]
    return "\n".join(
        [
            "# HP1 host-kernel resource authority",
            "",
            f"Status: **{report['status']}**",
            "",
            "HP1 fixes host-owned ISR capture, priority, bounded queue, terminal ",
            "completion, control reserve, and application-admission authority.",
            "",
            "## Synthetic seal",
            "",
            f"- Cases: `{coverage['case_count']}`",
            f"- ISR captures/overflows: `{coverage['isr_captures']}` / `{coverage['isr_overflows']}`",
            f"- Pressure accepted/terminal/retained: `{coverage['pressure_accepted']}` / `{coverage['pressure_terminal']}` / `{coverage['pressure_retained']}`",
            "",
            "## C6 witness",
            "",
            f"- Fixed control reserve: `{c6['fixed_reserve_bytes']}` bytes",
            f"- Required internal free: `{c6['required_internal_free_bytes']}` bytes",
            f"- Required largest block: `{c6['required_largest_block_bytes']}` bytes",
            f"- Remaining free/largest margins: `{c6['remaining_internal_free_bytes']}` / `{c6['remaining_largest_block_bytes']}` bytes",
            "",
            "## Claim boundary",
            "",
            "This is host-executed synthetic evidence. No production peripheral, protocol,",
            "target interrupt, firmware flash, or new physical hardware result is claimed.",
            "The retained HP0 S3/C6 observations are sizing inputs only.",
            "",
        ]
    )


def qualify(out_dir: Path) -> dict[str, Any]:
    model = _load_model()
    output = out_dir.expanduser().resolve()
    if output.exists() and any(output.iterdir()):
        raise QualificationError("HP1 output directory must be absent or empty")
    output.mkdir(parents=True, exist_ok=True)
    compiler = shutil.which("cc")
    if compiler is None:
        raise QualificationError("host C compiler is unavailable")

    model_copy = output / "resource-authority-model.json"
    shutil.copyfile(MODEL, model_copy)
    executable = output / "hp1-control-kernel-smoke"
    compile_log = output / "compile.log"
    run_log = output / "run.log"
    build = _run(_compile_command(compiler, executable), compile_log)
    if build.returncode != 0 or not executable.is_file():
        raise QualificationError("HP1 control-kernel smoke compilation failed")
    run = _run([str(executable)], run_log)
    if run.returncode != 0:
        raise QualificationError("HP1 control-kernel smoke execution failed")
    try:
        smoke = json.loads(run.stdout)
    except json.JSONDecodeError as exc:
        raise QualificationError("HP1 smoke emitted invalid JSON") from exc
    _validate_smoke(smoke)
    smoke_path = output / "synthetic-control-kernel.json"
    _write_json(smoke_path, smoke)

    report = {
        "aggregate": "HOST_RESOURCE_AUTHORITY_PROVEN",
        "c6_admission_witness": smoke["c6_admission"],
        "claim_boundary": {
            "hardware_execution_this_pass": "NOT_RUN",
            "runtime_classification": "HOST_EXECUTED_SYNTHETIC_ONLY",
            "retained_hp0_evidence_use": "SIZING_INPUT_ONLY",
        },
        "coverage": {
            "admission_denials": smoke["c6_admission"]["denial_count"],
            "case_count": smoke["case_count"],
            "isr_captures": smoke["isr"]["captures"],
            "isr_overflows": smoke["isr"]["overflows"],
            "pressure_accepted": smoke["pressure"]["accepted"],
            "pressure_retained": smoke["pressure"]["retained"],
            "pressure_rounds": smoke["pressure"]["rounds"],
            "pressure_terminal": smoke["pressure"]["terminal"],
        },
        "evidence": {
            "compile_log": _artifact(compile_log, output),
            "executable": _artifact(executable, output),
            "model": _artifact(model_copy, output),
            "run_log": _artifact(run_log, output),
            "smoke": _artifact(smoke_path, output),
        },
        "pass": "HP1",
        "phase": PHASE,
        "priorities": smoke["priorities"],
        "schema": "pulse.esp32.hp1-host-kernel-report.v1",
        "source_boundary": model["authority"],
        "status": "PASS",
    }
    _write_json(output / "qualification-report.json", report)
    (output / "qualification-report.md").write_text(
        _render_markdown(report), encoding="utf-8"
    )
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = qualify(args.out_dir)
    except (OSError, ValueError, QualificationError) as exc:
        print(f"HP1 qualification failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
