#!/usr/bin/env python3
"""Qualify HX5a fault-model coverage without making a new hardware claim."""
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
    from tools import (
        qualify_extension_admission,
        qualify_extension_adversarial,
        qualify_extension_roundtrip,
        qualify_extension_runtime,
    )
except ModuleNotFoundError:  # Direct execution from tools/.
    import qualify_extension_admission  # type: ignore[no-redef]
    import qualify_extension_adversarial  # type: ignore[no-redef]
    import qualify_extension_roundtrip  # type: ignore[no-redef]
    import qualify_extension_runtime  # type: ignore[no-redef]


ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "specs/PULSE-ESP32-005a-extension-fault-model.json"
SCHEMA = "pulse.esp32.host-extension-report.v1"
FAULT_EVIDENCE_SCHEMA = "pulse.esp32.hx5a-fault-injection-evidence.v1"
PHASE = "FAULT_MODEL_HARDENED"
EXPECTED_CATEGORIES = {
    "admission-rejection",
    "reversible-pre-start-lifecycle",
    "cooperative-running-lifecycle",
    "uncertain-native-ownership",
    "runtime-trap-or-extension-fault",
    "bounded-pressure-or-contract-rejection",
}
EXPECTED_INHERITED = {
    "HX2-admission": 21,
    "HX3-lifecycle": 12,
    "HX4-event-effect-happy-path": 1,
    "HX4.5-adversarial": 11,
}
EXPECTED_TRANSITIONS = {
    "services-bind-return": "bind-failure-is-retryable",
    "init-return": "init-failure-reverse-unwind",
    "start-return": "start-failure-reverse-unwind",
    "health-return": "health-probation-failure-requires-reset",
    "invoke-return": "invoke-fault-requires-reset",
    "quiesce-return": "quiesce-fault-requires-reset",
    "quiesce-health-return": "quiesce-health-fault-requires-reset",
    "deinit-return": "deinit-fault-requires-reset",
    "unload-return": "partial-unload-fault-requires-reset",
}
EXPECTED_FAULT_CASES = set(EXPECTED_TRANSITIONS.values()) | {
    "invalid-state-is-not-budget",
    "capacity-failure-is-budget",
}


class QualificationError(RuntimeError):
    """Raised when HX5a evidence is incomplete, stale, or inconsistent."""


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


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _load_and_validate_model() -> dict[str, Any]:
    value = json.loads(MODEL.read_text(encoding="utf-8"))
    if (
        not isinstance(value, dict)
        or value.get("schema") != "pulse.esp32.hx5a-extension-fault-model.v1"
        or value.get("pass") != "HX5a"
        or value.get("phase") != PHASE
    ):
        raise QualificationError("HX5a fault model identity is invalid")
    categories = value.get("categories")
    if not isinstance(categories, list) or {item.get("id") for item in categories} != EXPECTED_CATEGORIES:
        raise QualificationError("HX5a fault category inventory drifted")
    if any(not item.get("evidence") or not item.get("required_outcome") for item in categories):
        raise QualificationError("HX5a fault category lacks evidence or outcome policy")
    inherited = value.get("inherited_corpora")
    if not isinstance(inherited, list) or {
        item.get("id"): item.get("case_count") for item in inherited
    } != EXPECTED_INHERITED:
        raise QualificationError("HX5a inherited corpus inventory drifted")
    transitions = value.get("transitions")
    if not isinstance(transitions, list) or {
        item.get("id"): item.get("case") for item in transitions
    } != EXPECTED_TRANSITIONS:
        raise QualificationError("HX5a transition inventory drifted")
    if len(value.get("hardware_baselines", [])) != 2 or not value.get("deferred_to_hx5b"):
        raise QualificationError("HX5a claim boundary is incomplete")
    return value


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


def _fault_compile_command(compiler: str, executable: Path) -> list[str]:
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
        "tests/contract/hx5a_fault_injection_smoke.c",
        "firmware/components/wdc_extension/wdc_extension_lifecycle.c",
        "-o",
        str(executable),
    ]


def _run_fault_injection_smoke(out: Path) -> dict[str, Any]:
    compiler = shutil.which("cc")
    if compiler is None:
        raise QualificationError("host C compiler is unavailable")
    evidence = out / "host-fault-injection-smoke"
    evidence.mkdir(parents=True)
    executable = evidence / "hx5a-fault-injection-smoke"
    compile_log = evidence / "compile.log"
    run_log = evidence / "run.log"
    build = _run(_fault_compile_command(compiler, executable), compile_log)
    if build.returncode != 0 or not executable.is_file():
        raise QualificationError("HX5a fault-injection smoke compilation failed")
    run = _run([str(executable)], run_log)
    if run.returncode != 0:
        raise QualificationError("HX5a fault-injection smoke execution failed")
    try:
        result = json.loads(run.stdout)
    except json.JSONDecodeError as exc:
        raise QualificationError("HX5a fault-injection smoke emitted invalid JSON") from exc
    cases = {item.get("name"): item.get("status") for item in result.get("cases", [])}
    transitions = {
        item.get("name"): item.get("status") for item in result.get("transitions", [])
    }
    if (
        result.get("schema") != "pulse.esp32.hx5a-fault-injection-smoke.v1"
        or result.get("status") != "PASS"
        or result.get("failures") != 0
        or result.get("case_count") != len(EXPECTED_FAULT_CASES)
        or cases != {name: "PASS" for name in EXPECTED_FAULT_CASES}
        or result.get("transition_count") != len(EXPECTED_TRANSITIONS)
        or transitions != {name: "PASS" for name in EXPECTED_TRANSITIONS}
    ):
        raise QualificationError("HX5a fault-injection coverage is incomplete")
    return {
        "schema": FAULT_EVIDENCE_SCHEMA,
        "status": "PASS",
        "classification": "HOST_EXECUTED_DETERMINISTIC_FAULTS",
        "smoke": result,
        "artifacts": {
            "executable": _artifact(executable, out),
            "compile_log": _artifact(compile_log, out),
            "run_log": _artifact(run_log, out),
        },
        "claim_boundary": (
            "The seam overrides successful host-test returns after the boundary call, so "
            "partial side effects and unwind policy execute deterministically. The seam is "
            "excluded from production builds and is not target or hardware fault injection."
        ),
    }


def _write_markdown(report: dict[str, Any], out: Path) -> None:
    lines = [
        "# HX5a extension fault-model hardening qualification",
        "",
        f"- Status: `{report['status']}`",
        f"- Phase: `{report['phase']}`",
        f"- Aggregate: `{report['aggregate']}`",
        f"- Executed host cases: `{report['coverage']['executed_case_count']}`",
        f"- Deterministic transition points: `{report['coverage']['transition_count']}/9 PASS`",
        "- Hardware execution this pass: `NOT_RUN`",
        "",
        "## Fault categories",
        "",
        "| Category | Reset policy | Status |",
        "|---|---|---|",
    ]
    for item in report["fault_model"]["categories"]:
        lines.append(
            f"| `{item['id']}` | `{item['reset_policy']}` | `PASS` |"
        )
    lines.extend(
        [
            "",
            "## Deterministic lifecycle transitions",
            "",
            "| Transition | Injected case | Recovery | Status |",
            "|---|---|---|---|",
        ]
    )
    for item in report["fault_model"]["transitions"]:
        lines.append(
            f"| `{item['id']}` | `{item['case']}` | {item['recovery']} | `PASS` |"
        )
    lines.extend(
        [
            "",
            "## Tightened behavior",
            "",
            "- Initialization now distinguishes invalid candidate state (`ERR_STATE`) from "
            "insufficient host capacity (`ERR_BUDGET`).",
            "- Failed or uncertain ELF unload now preserves fault provenance and latches "
            "`RESET_REQUIRED`, including partial reverse unload.",
            "- The bind-return seam proves a failed bind is unbound and retryable.",
            "",
            "## Claim boundary",
            "",
            report["claim_boundary"],
            "",
            "HX5b retains sustained saturation, late-completion storms, repeated faults under "
            "memory pressure, and targeted S3/C6 hardware reruns.",
            "",
        ]
    )
    (out / "qualification-report.md").write_text("\n".join(lines), encoding="utf-8")


def qualify(output: Path) -> dict[str, Any]:
    out = qualify_extension_runtime._prepare_output(output)  # noqa: SLF001
    model = _load_and_validate_model()

    admission = qualify_extension_admission._validate_vectors()  # noqa: SLF001
    admission_path = out / "hx2-admission-corpus.json"
    _write_json(admission_path, admission)
    lifecycle = qualify_extension_runtime._run_lifecycle_smoke(out)  # noqa: SLF001
    roundtrip = qualify_extension_roundtrip._run_roundtrip_smokes(out)  # noqa: SLF001
    roundtrip_path = out / "hx4-event-effect-corpus.json"
    _write_json(roundtrip_path, roundtrip)
    adversarial = qualify_extension_adversarial._run_adversarial_smokes(out)  # noqa: SLF001
    adversarial_path = out / "hx45-adversarial-corpus.json"
    _write_json(adversarial_path, adversarial)
    fault_injection = _run_fault_injection_smoke(out)
    fault_path = out / "hx5a-fault-injection-corpus.json"
    _write_json(fault_path, fault_injection)

    if (
        admission.get("status") != "PASS"
        or len(admission.get("rejected", [])) != EXPECTED_INHERITED["HX2-admission"]
        or admission.get("pre_execution_lifecycle_calls") != 0
        or lifecycle.get("status") != "PASS"
        or lifecycle.get("smoke", {}).get("case_count") != EXPECTED_INHERITED["HX3-lifecycle"]
        or roundtrip.get("status") != "PASS"
        or adversarial.get("status") != "PASS"
        or adversarial.get("native_adversarial", {}).get("case_count")
        != EXPECTED_INHERITED["HX4.5-adversarial"]
        or fault_injection.get("status") != "PASS"
    ):
        raise QualificationError("an inherited fault corpus did not pass exactly")

    source_hash, source_files = qualify_extension_runtime._tree_digest(  # noqa: SLF001
        ROOT, {"reports", "__pycache__"}
    )
    environment = {
        "schema": "pulse.esp32.hx5a-environment.v1",
        "python": sys.version,
        "platform": platform.platform(),
        "cwd": str(ROOT),
        "LANG": os.environ.get("LANG"),
        "LC_ALL": os.environ.get("LC_ALL"),
    }
    environment_path = out / "environment.json"
    _write_json(environment_path, environment)
    source = {
        "schema": "pulse.esp32.hx5a-source-identity.v1",
        "source_tree": {"sha256": source_hash, "file_count": source_files},
        "fault_model": {
            "path": str(MODEL.relative_to(ROOT)),
            "sha256": _sha256(MODEL),
        },
    }
    source_path = out / "source.json"
    _write_json(source_path, source)
    executed_case_count = (
        EXPECTED_INHERITED["HX2-admission"]
        + EXPECTED_INHERITED["HX3-lifecycle"]
        + EXPECTED_INHERITED["HX4-event-effect-happy-path"]
        + EXPECTED_INHERITED["HX4.5-adversarial"]
        + len(EXPECTED_FAULT_CASES)
    )
    report = {
        "schema": SCHEMA,
        "pass": "HX5a",
        "status": "PASS",
        "phase": PHASE,
        "aggregate": "HOST_HARDENING_PROVEN",
        "scope": "FAULT_MODEL_INJECTION_AND_CLEANUP_HARDENING",
        "source_tree": {"sha256": source_hash, "file_count": source_files},
        "evidence": {
            "environment": _artifact(environment_path, out),
            "source": _artifact(source_path, out),
        },
        "fault_model": {
            "schema": model["schema"],
            "path": str(MODEL.relative_to(ROOT)),
            "sha256": _sha256(MODEL),
            "categories": model["categories"],
            "transitions": model["transitions"],
        },
        "coverage": {
            "status": "PASS",
            "category_count": len(EXPECTED_CATEGORIES),
            "transition_count": len(EXPECTED_TRANSITIONS),
            "executed_case_count": executed_case_count,
            "all_categories_covered": True,
            "all_transitions_injected": True,
        },
        "corpora": {
            "admission": {
                "status": admission["status"],
                "case_count": len(admission["rejected"]),
                "lifecycle_calls": admission["pre_execution_lifecycle_calls"],
                "artifact": _artifact(admission_path, out),
            },
            "lifecycle": {
                "status": lifecycle["status"],
                "case_count": lifecycle["smoke"]["case_count"],
                "artifact": _artifact(out / "lifecycle-state-machine.json", out),
            },
            "event_effect_happy_path": {
                "status": roundtrip["status"],
                "case_count": 1,
                "artifact": _artifact(roundtrip_path, out),
            },
            "adversarial": {
                "status": adversarial["status"],
                "case_count": adversarial["native_adversarial"]["case_count"],
                "artifact": _artifact(adversarial_path, out),
            },
            "fault_injection": {
                "status": fault_injection["status"],
                "case_count": fault_injection["smoke"]["case_count"],
                "transition_count": fault_injection["smoke"]["transition_count"],
                "artifact": _artifact(fault_path, out),
            },
        },
        "hardware": {
            "execution_this_pass": "NOT_RUN",
            "baselines": model["hardware_baselines"],
        },
        "deferred": model["deferred_to_hx5b"],
        "claim_boundary": (
            "HX5a re-executes host admission, lifecycle, happy-path, adversarial, and "
            "deterministic transition-fault contracts. It does not run ESP-IDF, inject "
            "target faults, or ingest the earlier named-board evidence; those prior "
            "classifications are context only and are not upgraded by this report."
        ),
    }
    report_path = out / "qualification-report.json"
    _write_json(report_path, report)
    _write_markdown(report, out)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = qualify(args.out_dir)
    except (
        OSError,
        ValueError,
        json.JSONDecodeError,
        QualificationError,
        qualify_extension_admission.QualificationError,
        qualify_extension_adversarial.QualificationError,
        qualify_extension_roundtrip.QualificationError,
        qualify_extension_runtime.QualificationError,
    ) as exc:
        print(f"HX5a qualification failed: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "status": report["status"],
                "phase": report["phase"],
                "aggregate": report["aggregate"],
                "out_dir": str(args.out_dir),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
