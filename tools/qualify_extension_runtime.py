#!/usr/bin/env python3
"""Qualify HX3 lifecycle contracts and dual-ISA build artifacts honestly."""
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
    from tools import build_native_extension
except ModuleNotFoundError:  # Direct execution from tools/.
    import build_native_extension  # type: ignore[no-redef]

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "pulse.esp32.host-extension-report.v1"
LIFECYCLE_SCHEMA = "pulse.esp32.hx3-lifecycle-evidence.v1"
IDF_VERSION = "5.4.4"
IDF_COMMIT = "296b6eab9445fd720e71aecab961e2d3fbca9944"


class QualificationError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tree_digest(root: Path, ignored: set[str]) -> tuple[str, int]:
    digest = hashlib.sha256()
    count = 0
    for path in sorted(root.rglob("*")):
        if not path.is_file() or any(part in ignored for part in path.relative_to(root).parts):
            continue
        relative = path.relative_to(root).as_posix().encode("utf-8")
        data = path.read_bytes()
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
        count += 1
    return digest.hexdigest(), count


def _prepare_output(path: Path) -> Path:
    resolved = path.resolve()
    if resolved.exists():
        if not resolved.is_dir() or any(resolved.iterdir()):
            raise QualificationError("output directory must be absent or empty")
    else:
        resolved.mkdir(parents=True)
    return resolved


def _run_lifecycle_smoke(out: Path) -> dict[str, Any]:
    compiler = shutil.which("cc")
    if compiler is None:
        raise QualificationError("host C compiler is unavailable")
    evidence = out / "host-lifecycle-smoke"
    evidence.mkdir(parents=True)
    executable = evidence / "hx3-lifecycle-smoke"
    compile_log = evidence / "compile.log"
    run_log = evidence / "run.log"
    command = [
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
        "tests/contract/hx3_lifecycle_smoke.c",
        "firmware/components/wdc_extension/wdc_extension_lifecycle.c",
        "-o",
        str(executable),
    ]
    build = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    compile_log.write_text(
        "$ " + " ".join(command) + "\n" + (build.stdout or ""), encoding="utf-8"
    )
    if build.returncode != 0 or not executable.is_file():
        raise QualificationError("HX3 lifecycle smoke compilation failed")
    run = subprocess.run(
        [str(executable)],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    run_log.write_text(run.stdout or "", encoding="utf-8")
    if run.returncode != 0:
        raise QualificationError("HX3 lifecycle smoke execution failed")
    try:
        result = json.loads(run.stdout)
    except json.JSONDecodeError as exc:
        raise QualificationError("HX3 lifecycle smoke emitted invalid JSON") from exc
    required = {
        "happy-lifecycle",
        "init-failure-reverse-unwind",
        "start-failure-before-task",
        "start-failure-after-partial-task",
        "unhealthy-probation",
        "duplicate-start",
        "invoke-before-start",
        "invoke-after-quiesce",
        "quiescence-timeout-reset",
        "duplicate-deinit",
        "expired-quiesce-deadline",
        "repeated-lifecycle-cycles",
    }
    observed = {
        item.get("name")
        for item in result.get("cases", [])
        if item.get("status") == "PASS"
    }
    if (
        result.get("status") != "PASS"
        or result.get("case_count") != len(required)
        or result.get("simulated_reset_count") != 3
        or observed != required
    ):
        raise QualificationError("HX3 lifecycle smoke omitted or failed a required case")
    report = {
        "schema": LIFECYCLE_SCHEMA,
        "status": "PASS",
        "classification": "HOST_SIMULATED_CONTRACT_ONLY",
        "smoke": result,
        "artifacts": {
            "executable": {
                "path": str(executable.relative_to(out)),
                "sha256": _sha256(executable),
                "size": executable.stat().st_size,
            },
            "compile_log": {
                "path": str(compile_log.relative_to(out)),
                "sha256": _sha256(compile_log),
            },
            "run_log": {
                "path": str(run_log.relative_to(out)),
                "sha256": _sha256(run_log),
            },
        },
        "claim_boundary": (
            "The native host smoke executes mock descriptors only. It proves ordering, "
            "rejection, reverse unwind, and reset-required policy; it is not ESP32 task, "
            "heap, loader, or hardware runtime evidence."
        ),
    }
    path = out / "lifecycle-state-machine.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def _target_result(target: str, target_dir: Path, compiler: Path | None) -> dict[str, Any]:
    runs = []
    for label in ("a", "b"):
        runs.append(
            build_native_extension.build_synthetic_extension(
                target=target,
                source=build_native_extension.SYNTHETIC_SOURCE,
                out_dir=target_dir / f"run-{label}",
                compiler=compiler,
            )
        )
    if any(run["status"] != "PASS" for run in runs):
        raise QualificationError(f"{target} synthetic lifecycle ELF build failed")
    first_elf = target_dir / "run-a" / runs[0]["artifacts"]["elf"]["path"]
    second_elf = target_dir / "run-b" / runs[1]["artifacts"]["elf"]["path"]
    if first_elf.read_bytes() != second_elf.read_bytes():
        raise QualificationError(f"{target} synthetic lifecycle ELF is not reproducible")
    inspection = json.loads(
        (target_dir / "run-a" / "inspection.json").read_text(encoding="utf-8")
    )
    imports = [item["name"] for item in inspection["imports"]]
    if sorted(imports) != sorted(build_native_extension.SYNTHETIC_ALLOWED_IMPORTS):
        raise QualificationError(f"{target} direct import inventory drifted")
    resource = inspection["resource_footprint"]
    if resource["allocated_writable_bytes"] > resource["declared_backing_bytes"]:
        raise QualificationError(f"{target} writable ELF footprint exceeds declared backing")
    metadata = inspection["metadata"]
    return {
        "classification": "BUILD_PROVEN",
        "runtime": "HARDWARE_NOT_RUN",
        "lifecycle_execution": "NOT_RUN_NO_TARGET_RUNTIME",
        "reproducible": True,
        "elf": {
            "path": str(first_elf.relative_to(target_dir.parents[1])),
            "sha256": _sha256(first_elf),
            "size": first_elf.stat().st_size,
            "machine": inspection["header"]["machine_name"],
            "flags": inspection["header"]["flags"],
            "artifact_sha256": metadata["artifact_sha256"],
            "metadata_sha256": metadata["normalized_metadata_sha256"],
        },
        "imports": imports,
        "relocations": inspection["observed_relocation_types"],
        "constructor_surfaces": inspection["constructor_surfaces"],
        "budgets": {
            "task_count": metadata["task_count"],
            "task_stack_bytes": metadata["task_stack_bytes"],
            "static_memory_bytes": metadata["static_memory_bytes"],
            "queue_depth": metadata["queue_depth"],
            "queue_item_bytes": metadata["queue_item_bytes"],
            "queue_storage_bytes": metadata["queue_depth"]
            * metadata["queue_item_bytes"],
            "allocated_writable_bytes": resource["allocated_writable_bytes"],
            "declared_backing_bytes": resource["declared_backing_bytes"],
            "allocated_writable_sections": resource["allocated_writable_sections"],
        },
        "runs": {
            "run-a": "targets/" + target + "/run-a/build-report.json",
            "run-b": "targets/" + target + "/run-b/build-report.json",
        },
    }


def _write_markdown(report: dict[str, Any], output: Path) -> None:
    lines = [
        "# HX3 extension lifecycle qualification",
        "",
        f"- Status: `{report['status']}`",
        f"- Aggregate: `{report['aggregate']}`",
        "- Target runtime: `HARDWARE_NOT_RUN`",
        "- Host lifecycle cases: `12/12 PASS`",
        f"- Repeated clean host-simulated cycles: `{report['repeated_cycles']['cycles']}`",
        "",
        "| Target | Classification | Machine | ELF SHA-256 | Reproducible |",
        "|---|---|---|---|---|",
    ]
    for target in ("esp32s3", "esp32c6"):
        item = report["targets"][target]
        lines.append(
            f"| `{target}` | `{item['classification']}` | `{item['elf']['machine']}` | "
            f"`{item['elf']['sha256']}` | `yes` |"
        )
    lines.extend(
        [
            "",
            "## Claim boundary",
            "",
            "The host smoke proves deterministic lifecycle policy against mock descriptors. "
            "The target ELFs and firmware are build evidence only. No board was attached, so "
            "FreeRTOS task execution, target heap deltas, loader/unload behavior, stack high-water "
            "marks, serial transcripts, reset reasons, and retained diagnostics remain unexecuted.",
            "",
        ]
    )
    if "firmware_qualification" in report:
        lines.extend(
            [
                "## Firmware integration",
                "",
                "The exact ESP-IDF v5.4.4 extension-enabled firmware is byte-reproducible "
                "across two isolated builds for both targets. This does not upgrade runtime.",
                "",
                "| Target | Firmware delta | Internal RAM delta | Remaining internal RAM |",
                "|---|---:|---:|---:|",
            ]
        )
        for target in ("esp32s3", "esp32c6"):
            item = report["firmware_qualification"]["targets"][target]
            lines.append(
                f"| `{target}` | `{item['firmware_bin_delta']:+d}` bytes | "
                f"`{item['internal_ram_delta']:+d}` bytes | "
                f"`{item['remaining_internal_ram']}` bytes |"
            )
        lines.append("")
    (output / "qualification-report.md").write_text(
        "\n".join(lines), encoding="utf-8"
    )


def qualify(output: Path, compilers: dict[str, Path | None]) -> dict[str, Any]:
    out = _prepare_output(output)
    lifecycle = _run_lifecycle_smoke(out)
    targets: dict[str, Any] = {}
    for target in ("esp32s3", "esp32c6"):
        targets[target] = _target_result(target, out / "targets" / target, compilers[target])

    smoke = lifecycle["smoke"]
    budget_report = {
        "schema": "pulse.esp32.hx3-task-queue-budget.v1",
        "status": "PASS",
        "idf": {"version": IDF_VERSION, "commit": IDF_COMMIT},
        "target_refinement_imports": {
            "stable_pulse": [
                "pulse_host_monotonic_ms_v1",
                "pulse_host_report_health_v1",
            ],
            "freertos": [
                item
                for item in build_native_extension.SYNTHETIC_ALLOWED_IMPORTS
                if not item.startswith("pulse_host_")
            ],
            "allocation_imports": [],
        },
        "targets": {target: item["budgets"] for target, item in targets.items()},
        "runtime_measurements": {
            "task_stack_high_water": "NOT_MEASURED_NO_HARDWARE",
            "queue_high_water": "NOT_MEASURED_NO_HARDWARE",
        },
    }
    budget_path = out / "task-queue-budget.json"
    budget_path.write_text(
        json.dumps(budget_report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    repeated_report = {
        "schema": "pulse.esp32.hx3-repeated-cycle-memory.v1",
        "status": "PASS",
        "classification": "HOST_STRUCT_STATE_ONLY",
        "cycles": smoke["repeated_cycles"],
        "retained_bytes": smoke["repeated_cycle_retained_bytes"],
        "target_heap_delta": "NOT_MEASURED_NO_HARDWARE",
        "loader_heap_delta": "NOT_MEASURED_NO_HARDWARE",
        "claim_boundary": (
            "Mock candidate and registry state returned to zero. No target ELF was loaded or "
            "unloaded and no ESP32 heap observation was made."
        ),
    }
    repeated_path = out / "repeated-cycle-memory.json"
    repeated_path.write_text(
        json.dumps(repeated_report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    source_hash, source_files = _tree_digest(ROOT, {"reports", "__pycache__"})
    environment = {
        "python": sys.version,
        "platform": platform.platform(),
        "cwd": str(ROOT),
        "LANG": os.environ.get("LANG"),
        "LC_ALL": os.environ.get("LC_ALL"),
        "SOURCE_DATE_EPOCH": os.environ.get("SOURCE_DATE_EPOCH"),
        "idf": {"version": IDF_VERSION, "commit": IDF_COMMIT},
        "source_tree": {"sha256": source_hash, "file_count": source_files},
    }
    environment_path = out / "environment.json"
    environment_path.write_text(
        json.dumps(environment, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    report = {
        "schema": SCHEMA,
        "pass": "HX3",
        "status": "PASS",
        "aggregate": "BUILD_ONLY_PROVEN",
        "scope": "LIFECYCLE_TASK_OWNERSHIP_HEALTH_TEARDOWN",
        "source_tree": environment["source_tree"],
        "targets": targets,
        "lifecycle": {
            "status": lifecycle["status"],
            "classification": lifecycle["classification"],
            "report": "lifecycle-state-machine.json",
            "sha256": _sha256(out / "lifecycle-state-machine.json"),
            "required_cases": smoke["case_count"],
            "reverse_unwind": smoke["reverse_unwind"],
            "simulated_reset_count": smoke["simulated_reset_count"],
        },
        "task_queue_budget": {
            "status": budget_report["status"],
            "report": "task-queue-budget.json",
            "sha256": _sha256(budget_path),
        },
        "repeated_cycles": {
            "status": repeated_report["status"],
            "classification": repeated_report["classification"],
            "cycles": repeated_report["cycles"],
            "retained_bytes": repeated_report["retained_bytes"],
            "report": "repeated-cycle-memory.json",
            "sha256": _sha256(repeated_path),
        },
        "runtime": {
            "status": "HARDWARE_NOT_RUN",
            "esp32s3_transcript": None,
            "esp32c6_transcript": None,
            "task_stack_high_water": "NOT_MEASURED_NO_HARDWARE",
            "heap_psram_stages": "NOT_MEASURED_NO_HARDWARE",
            "reset_reason": "NOT_OBSERVED_NO_HARDWARE",
            "retained_diagnostic": "NOT_OBSERVED_NO_HARDWARE",
        },
        "deferred": [
            "GPIO",
            "network",
            "BLE",
            "storage",
            "RAX",
            "firmware OTA",
            "event/effect round trip (HX4)",
        ],
    }
    report_path = out / "qualification-report.json"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    _write_markdown(report, out)
    return report


def finalize_with_firmware(output: Path, firmware_report_path: Path) -> dict[str, Any]:
    out = output.resolve()
    report_path = out / "qualification-report.json"
    if not report_path.is_file() or not firmware_report_path.is_file():
        raise QualificationError("HX3 and firmware qualification reports must both exist")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    firmware = json.loads(firmware_report_path.read_text(encoding="utf-8"))
    if (
        report.get("status") != "PASS"
        or firmware.get("status") != "PASS"
        or firmware.get("result") != "BUILD_PROVEN"
    ):
        raise QualificationError("cannot finalize HX3 from a non-passing build report")
    firmware_targets: dict[str, Any] = {}
    for item in firmware["targets"]:
        target = item["target"]
        first_host_report = firmware_report_path.parent / item["host_reports"][0]
        cell = json.loads(first_host_report.read_text(encoding="utf-8"))
        firmware_targets[target] = {
            "id": item["id"],
            "build_result": item["build_result"],
            "runtime_result": item["runtime_result"],
            "reproducibility": item["reproducibility"],
            "firmware_bin_delta": item["delta"]["firmware_bin_bytes"],
            "internal_ram_delta": item["delta"]["size_bytes"]["used_diram"],
            "remaining_internal_ram": cell["size"]["diram_remain"],
        }
    report["firmware_qualification"] = {
        "status": firmware["status"],
        "result": firmware["result"],
        "report": str(firmware_report_path.resolve().relative_to(out)),
        "sha256": _sha256(firmware_report_path),
        "firmware_source": firmware["firmware_source"],
        "native_sdk_source": firmware.get("native_sdk_source"),
        "targets": firmware_targets,
    }
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    _write_markdown(report, out)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--s3-compiler", type=Path)
    parser.add_argument("--c6-compiler", type=Path)
    parser.add_argument("--firmware-report", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.firmware_report is not None:
            report = finalize_with_firmware(args.out_dir, args.firmware_report.resolve())
        else:
            report = qualify(
                args.out_dir,
                {"esp32s3": args.s3_compiler, "esp32c6": args.c6_compiler},
            )
    except (OSError, ValueError, QualificationError,
            build_native_extension.NativeBuildError) as exc:
        print(f"HX3 qualification failed: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "status": report["status"],
                "aggregate": report["aggregate"],
                "out_dir": str(args.out_dir),
            }
        )
    )
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
