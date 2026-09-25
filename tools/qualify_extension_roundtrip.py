#!/usr/bin/env python3
"""Qualify the provisional HX4 event/effect happy path without runtime overclaim."""
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
    from tools import build_native_extension, qualify_extension_runtime
except ModuleNotFoundError:  # Direct execution from tools/.
    import build_native_extension  # type: ignore[no-redef]
    import qualify_extension_runtime  # type: ignore[no-redef]


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "pulse.esp32.host-extension-report.v1"
ROUNDTRIP_SCHEMA = "pulse.esp32.hx4-event-effect-evidence.v1"
IDF_VERSION = "5.4.4"
IDF_COMMIT = "296b6eab9445fd720e71aecab961e2d3fbca9944"
COMMON_WASM = (
    ROOT
    / "firmware/components/wdc_runtime/test_vectors/wdc_hx4_event_effect_wasm.wasm"
)


class QualificationError(RuntimeError):
    """Raised when HX4 evidence cannot be generated honestly."""


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
        "$ " + " ".join(command) + "\n" + (process.stdout or ""), encoding="utf-8"
    )
    return process


def _run_roundtrip_smokes(out: Path) -> dict[str, Any]:
    compiler = shutil.which("cc")
    node = shutil.which("node")
    if compiler is None:
        raise QualificationError("host C compiler is unavailable")
    if node is None:
        raise QualificationError("Node.js is unavailable for the real Wasm smoke")

    evidence = out / "host-event-effect-smoke"
    evidence.mkdir(parents=True)
    executable = evidence / "hx4-roundtrip-smoke"
    compile_log = evidence / "compile.log"
    native_log = evidence / "native-run.log"
    wasm_log = evidence / "wasm-run.log"
    compile_command = [
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
        "-Ifirmware/components/wdc_runtime/include",
        "-Ifirmware/components/wdc_events/include",
        "-Ifirmware/components/wdc_abi/include",
        "-Ifirmware/components/wdc_diag/include",
        "tests/contract/hx4_roundtrip_smoke.c",
        "firmware/components/wdc_extension/wdc_extension_bridge.c",
        "firmware/components/wdc_extension/wdc_extension_host_services.c",
        "firmware/components/wdc_extension/wdc_extension_lifecycle.c",
        "firmware/components/wdc_runtime/wdc_runtime.c",
        "firmware/components/wdc_runtime/wdc_static_wasm.c",
        "firmware/components/wdc_events/wdc_event_queue.c",
        "firmware/components/wdc_events/wdc_event_encode.c",
        "firmware/components/wdc_abi/wdc_cbor.c",
        "firmware/components/wdc_abi/wdc_host_call.c",
        "-o",
        str(executable),
    ]
    build = _run(compile_command, compile_log)
    if build.returncode != 0 or not executable.is_file():
        raise QualificationError("HX4 native round-trip smoke compilation failed")
    native = _run([str(executable)], native_log)
    if native.returncode != 0:
        raise QualificationError("HX4 native round-trip smoke failed")
    wasm = _run([node, "tests/contract/hx4_wasm_smoke.mjs"], wasm_log)
    if wasm.returncode != 0:
        raise QualificationError("HX4 real Wasm smoke failed")
    try:
        native_result = json.loads(native.stdout)
        wasm_result = json.loads(wasm.stdout)
    except json.JSONDecodeError as exc:
        raise QualificationError("HX4 smoke emitted invalid JSON") from exc
    if (
        native_result.get("status") != "PASS"
        or native_result.get("handler_calls") != 1
        or native_result.get("invoke_calls") != 1
        or native_result.get("queue_before") != 1
        or native_result.get("queue_after") != 0
        or native_result.get("duplicate_completion_status") != -7
    ):
        raise QualificationError("HX4 native smoke omitted a required happy-path invariant")
    if (
        wasm_result.get("status") != "PASS"
        or wasm_result.get("target_neutral") is not True
        or len(wasm_result.get("calls", [])) != 1
        or wasm_result["calls"][0].get("opcode") != 0x0801
    ):
        raise QualificationError("HX4 Wasm smoke omitted the target-neutral effect call")

    return {
        "schema": ROUNDTRIP_SCHEMA,
        "status": "PASS",
        "classification": "HOST_EXECUTED_CONTRACT_ONLY",
        "phase": "PROVISIONAL_HAPPY_PATH",
        "native_roundtrip": native_result,
        "real_wasm_execution": wasm_result,
        "artifacts": {
            "executable": _artifact(executable, out),
            "compile_log": _artifact(compile_log, out),
            "native_run_log": _artifact(native_log, out),
            "wasm_run_log": _artifact(wasm_log, out),
        },
        "claim_boundary": (
            "The C smoke executes the complete ownership and queue contract with a mock "
            "started descriptor. Node executes the exact common Wasm bytes and observes its "
            "host call. Neither is ESP32 task, loader, WAMR-on-target, or hardware evidence."
        ),
    }


def _copy_common_wasm(out: Path, targets: dict[str, Any]) -> dict[str, Any]:
    if not COMMON_WASM.is_file():
        raise QualificationError("the canonical HX4 common Wasm artifact is missing")
    source_hash = _sha256(COMMON_WASM)
    realizations: dict[str, Any] = {}
    for target in ("esp32s3", "esp32c6"):
        destination = out / "targets" / target / "common-wasm" / COMMON_WASM.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(COMMON_WASM, destination)
        if destination.read_bytes() != COMMON_WASM.read_bytes():
            raise QualificationError(f"{target} common Wasm copy differs from canonical bytes")
        realizations[target] = _artifact(destination, out)
        targets[target]["common_wasm"] = realizations[target]
    hashes = {item["sha256"] for item in realizations.values()}
    if hashes != {source_hash}:
        raise QualificationError("S3 and C6 common Wasm hashes are not identical")
    return {
        "canonical": _artifact(COMMON_WASM, ROOT),
        "sha256": source_hash,
        "identical_across_targets": True,
        "target_selector": "NONE",
        "realizations": realizations,
    }


def _write_markdown(report: dict[str, Any], output: Path) -> None:
    roundtrip = report["event_effect"]
    native = roundtrip["native_roundtrip"]
    lines = [
        "# HX4 extension event/effect qualification",
        "",
        f"- Status: `{report['status']}`",
        f"- Phase: `{report['phase']}`",
        f"- Aggregate: `{report['aggregate']}`",
        "- Target runtime: `HARDWARE_NOT_RUN`",
        f"- Common Wasm SHA-256: `{report['common_wasm']['sha256']}`",
        "- Common Wasm target selector: `NONE`",
        "- Adversarial seal: `DEFERRED_TO_HX4_5`",
        "",
        "## Executed happy path",
        "",
        "```text",
        "extension service -> wdc_events -> wdc_runtime/Wasm",
        "  -> WDC_OP_EFFECT_INVOKE -> sealed extension registry",
        "  -> extension invoke -> exactly-one bounded completion",
        "```",
        "",
        f"Host-simulated queue depth changed `{native['queue_before']} -> {native['queue_after']}`. ",
        f"Event `{native['event_id']}` carried causation `{native['causation_id']}`; operation ",
        f"`0x{native['operation_id']:08x}` used correlation `{native['correlation_id']}` and ",
        f"deadline `{native['deadline_ms']}` ms. Request and completion payloads were ",
        f"`{native['effect_payload_len']}` bytes using CBOR.",
        "",
        "| Target | Native ELF | Common Wasm | Classification | Runtime |",
        "|---|---|---|---|---|",
    ]
    for target in ("esp32s3", "esp32c6"):
        item = report["targets"][target]
        lines.append(
            f"| `{target}` | `{item['elf']['sha256']}` | "
            f"`{item['common_wasm']['sha256']}` | `{item['classification']}` | "
            f"`{item['runtime']}` |"
        )
    lines.extend(
        [
            "",
            "## Claim boundary",
            "",
            "The happy path is executed on the host and the exact Wasm module is executed by a "
            "real WebAssembly engine. Target-native extension ELFs and firmware are build evidence "
            "only. No S3 or C6 board was attached, so target WAMR dispatch, FreeRTOS scheduling, "
            "loader execution, queue/stack high-water values, heap recovery, and serial traces "
            "remain unobserved.",
            "",
            "HX4 is deliberately provisional. Unknown identities, overflow, oversize, timeout, "
            "post-timeout/post-quiescence completion, trap, and extension-fault attacks are the "
            "HX4.5 adversarial seal and are not claimed here.",
            "",
        ]
    )
    if "firmware_qualification" in report:
        lines.extend(
            [
                "## Firmware integration",
                "",
                "The exact extension-enabled firmware is byte-reproducible across two isolated "
                "builds for both targets. This does not upgrade runtime classification.",
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
    (output / "qualification-report.md").write_text("\n".join(lines), encoding="utf-8")


def qualify(output: Path, compilers: dict[str, Path | None]) -> dict[str, Any]:
    out = qualify_extension_runtime._prepare_output(output)  # noqa: SLF001
    lifecycle = qualify_extension_runtime._run_lifecycle_smoke(out)  # noqa: SLF001
    roundtrip = _run_roundtrip_smokes(out)
    targets: dict[str, Any] = {}
    for target in ("esp32s3", "esp32c6"):
        targets[target] = qualify_extension_runtime._target_result(  # noqa: SLF001
            target, out / "targets" / target, compilers[target]
        )
    common_wasm = _copy_common_wasm(out, targets)

    transcript_path = out / "event-effect-transcript.json"
    transcript_path.write_text(
        json.dumps(roundtrip, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    source_hash, source_files = qualify_extension_runtime._tree_digest(  # noqa: SLF001
        ROOT, {"reports", "__pycache__"}
    )
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
    (out / "environment.json").write_text(
        json.dumps(environment, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    report = {
        "schema": SCHEMA,
        "pass": "HX4",
        "phase": "PROVISIONAL_HAPPY_PATH",
        "status": "PASS",
        "aggregate": "BUILD_ONLY_PROVEN",
        "scope": "EXTENSION_EVENT_WASM_EFFECT_ROUND_TRIP",
        "source_tree": environment["source_tree"],
        "targets": targets,
        "common_wasm": common_wasm,
        "event_effect": {
            **roundtrip,
            "report": "event-effect-transcript.json",
            "sha256": _sha256(transcript_path),
        },
        "inherited_hx3_lifecycle": {
            "status": lifecycle["status"],
            "classification": lifecycle["classification"],
            "report": "lifecycle-state-machine.json",
            "sha256": _sha256(out / "lifecycle-state-machine.json"),
            "required_cases": lifecycle["smoke"]["case_count"],
        },
        "negative_cases": {
            "duplicate_completion": "PASS_OWNERSHIP_SENTINEL",
            "remaining": "DEFERRED_TO_HX4_5",
            "deferred_cases": [
                "unknown event identity",
                "unknown operation identity",
                "event queue full",
                "oversized event frame",
                "oversized effect frame",
                "expired deadline",
                "completion after timeout",
                "completion after quiescence",
                "Wasm trap during event handling",
                "extension fault during operation",
            ],
        },
        "runtime": {
            "status": "HARDWARE_NOT_RUN",
            "esp32s3_transcript": None,
            "esp32c6_transcript": None,
            "target_queue_depth": "NOT_MEASURED_NO_HARDWARE",
            "target_completion_latency": "NOT_MEASURED_NO_HARDWARE",
            "task_stack_high_water": "NOT_MEASURED_NO_HARDWARE",
            "heap_psram_stages": "NOT_MEASURED_NO_HARDWARE",
        },
        "deferred": [
            "HX4.5 adversarial event/effect seal",
            "ESP32-S3 hardware execution after HX4.5",
            "ESP32-C6 hardware execution",
            "GPIO and all HX5+ peripheral work",
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
        raise QualificationError("HX4 and firmware qualification reports must both exist")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    firmware = json.loads(firmware_report_path.read_text(encoding="utf-8"))
    if (
        report.get("status") != "PASS"
        or report.get("phase") != "PROVISIONAL_HAPPY_PATH"
        or firmware.get("status") != "PASS"
        or firmware.get("result") != "BUILD_PROVEN"
    ):
        raise QualificationError("cannot finalize HX4 from a non-passing build report")
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
    try:
        relative_report = firmware_report_path.resolve().relative_to(out)
    except ValueError as exc:
        raise QualificationError("firmware report must be contained in the HX4 output") from exc
    report["firmware_qualification"] = {
        "status": firmware["status"],
        "result": firmware["result"],
        "report": str(relative_report),
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
    except (
        OSError,
        ValueError,
        QualificationError,
        qualify_extension_runtime.QualificationError,
        build_native_extension.NativeBuildError,
    ) as exc:
        print(f"HX4 qualification failed: {exc}", file=sys.stderr)
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
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
