#!/usr/bin/env python3
"""Qualify the HX4.5 adversarial event/effect seal without hardware overclaim."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

try:
    from tools import (
        build_native_extension,
        qualify_extension_roundtrip,
        qualify_extension_runtime,
        qualify_extension_spine,
    )
except ModuleNotFoundError:  # Direct execution from tools/.
    import build_native_extension  # type: ignore[no-redef]
    import qualify_extension_roundtrip  # type: ignore[no-redef]
    import qualify_extension_runtime  # type: ignore[no-redef]
    import qualify_extension_spine  # type: ignore[no-redef]


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "pulse.esp32.host-extension-report.v1"
ADVERSARIAL_SCHEMA = "pulse.esp32.hx4.5-event-effect-adversarial-evidence.v1"
PHASE = "ADVERSARIAL_HOST_SEALED"
EXPECTED_CASES = {
    "unknown-event-identity": -6,
    "unknown-operation-identity": -6,
    "event-queue-full": -4,
    "oversized-event-frame": -6,
    "oversized-effect-frame": -4,
    "expired-deadline": -11,
    "completion-after-timeout": -8,
    "duplicate-completion": -7,
    "completion-after-quiescence": -8,
    "wasm-trap-during-event": -15,
    "extension-fault-during-operation": -16,
}


class QualificationError(RuntimeError):
    """Raised when HX4.5 evidence cannot be generated honestly."""


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


def _adversarial_compile_command(compiler: str, executable: Path) -> list[str]:
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
        "-Ifirmware/components/wdc_runtime/include",
        "-Ifirmware/components/wdc_events/include",
        "-Ifirmware/components/wdc_abi/include",
        "-Ifirmware/components/wdc_diag/include",
        "tests/contract/hx45_adversarial_smoke.c",
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


def _run_adversarial_smokes(out: Path) -> dict[str, Any]:
    compiler = shutil.which("cc")
    node = shutil.which("node")
    if compiler is None:
        raise QualificationError("host C compiler is unavailable")
    if node is None:
        raise QualificationError("Node.js is unavailable for the real Wasm smoke")
    evidence = out / "host-adversarial-smoke"
    evidence.mkdir(parents=True)
    executable = evidence / "hx45-adversarial-smoke"
    compile_log = evidence / "compile.log"
    native_log = evidence / "native-run.log"
    wasm_log = evidence / "wasm-run.log"
    build = _run(_adversarial_compile_command(compiler, executable), compile_log)
    if build.returncode != 0 or not executable.is_file():
        raise QualificationError("HX4.5 native adversarial smoke compilation failed")
    native = _run([str(executable)], native_log)
    if native.returncode != 0:
        raise QualificationError("HX4.5 native adversarial smoke failed")
    wasm = _run([node, "tests/contract/hx45_wasm_adversarial_smoke.mjs"], wasm_log)
    if wasm.returncode != 0:
        raise QualificationError("HX4.5 real-Wasm adversarial smoke failed")
    try:
        native_result = json.loads(native.stdout)
        wasm_result = json.loads(wasm.stdout)
    except json.JSONDecodeError as exc:
        raise QualificationError("HX4.5 smoke emitted invalid JSON") from exc
    observed = {item.get("name"): item for item in native_result.get("cases", [])}
    if (
        native_result.get("status") != "PASS"
        or native_result.get("failures") != 0
        or native_result.get("case_count") != len(EXPECTED_CASES)
        or set(observed) != set(EXPECTED_CASES)
    ):
        raise QualificationError("HX4.5 native smoke omitted a required negative case")
    for name, expected in EXPECTED_CASES.items():
        item = observed[name]
        if (
            item.get("status") != "PASS"
            or item.get("observed") != expected
            or item.get("expected") != expected
        ):
            raise QualificationError(f"HX4.5 negative case failed: {name}")
    propagations = wasm_result.get("status_propagations", [])
    if (
        wasm_result.get("status") != "PASS"
        or wasm_result.get("target_neutral") is not True
        or [item.get("host_status") for item in propagations]
        != [-6, -4, -11, -16, -9]
        or any(
            item.get("host_status") != item.get("guest_status")
            or item.get("calls") != 1
            for item in propagations
        )
        or wasm_result.get("event_trap", {}).get("observed") is not True
    ):
        raise QualificationError("HX4.5 real Wasm did not preserve rejection/trap behavior")
    return {
        "schema": ADVERSARIAL_SCHEMA,
        "status": "PASS",
        "classification": "HOST_EXECUTED_ADVERSARIAL_CONTRACT",
        "phase": PHASE,
        "native_adversarial": native_result,
        "real_wasm_adversarial": wasm_result,
        "artifacts": {
            "executable": _artifact(executable, out),
            "compile_log": _artifact(compile_log, out),
            "native_run_log": _artifact(native_log, out),
            "wasm_run_log": _artifact(wasm_log, out),
        },
        "claim_boundary": (
            "The native corpus executes host queue, runtime, ABI, registry, completion, "
            "quiescence, and reset-latch contracts with mock descriptors. Node executes "
            "the exact common HX4 Wasm and a real trapping Wasm fixture. This is not "
            "ESP32 task, loader, WAMR-on-target, or hardware evidence."
        ),
    }


def _negative_case_map(adversarial: dict[str, Any]) -> dict[str, Any]:
    return {
        item["name"]: {
            "status": item["status"],
            "observed": item["observed"],
            "expected": item["expected"],
        }
        for item in adversarial["native_adversarial"]["cases"]
    }


def _write_markdown(report: dict[str, Any], output: Path) -> None:
    adversarial = report["adversarial_event_effect"]
    lines = [
        "# HX4.5 extension event/effect adversarial qualification",
        "",
        f"- Status: `{report['status']}`",
        f"- Phase: `{report['phase']}`",
        f"- Aggregate: `{report['aggregate']}`",
        "- Host adversarial cases: `11/11 PASS`",
        "- Target runtime: `HARDWARE_NOT_RUN`",
        f"- Common Wasm SHA-256: `{report['common_wasm']['sha256']}`",
        "- Common Wasm target selector: `NONE`",
        "",
        "## Adversarial corpus",
        "",
        "| Case | Observed | Expected | Status |",
        "|---|---:|---:|---|",
    ]
    for item in adversarial["native_adversarial"]["cases"]:
        lines.append(
            f"| `{item['name']}` | `{item['observed']}` | "
            f"`{item['expected']}` | `{item['status']}` |"
        )
    lines.extend(
        [
            "",
            "The exact common HX4 Wasm propagated unknown-operation, oversize, timeout, "
            "extension-I/O, and canceled-state host statuses unchanged. A separate real "
            "WebAssembly fixture executed `unreachable` in its event handler and trapped.",
            "",
            "## Preserved happy path",
            "",
            "HX4's bounded event/effect happy path remains passing. The common Wasm bytes "
            "remain unchanged and identical in the S3 and C6 realization directories.",
            "",
            "| Target | Native ELF | Common Wasm | Classification | Runtime |",
            "|---|---|---|---|---|",
        ]
    )
    for target in ("esp32s3", "esp32c6"):
        item = report["targets"][target]
        lines.append(
            f"| `{target}` | `{item['elf']['sha256']}` | "
            f"`{item['common_wasm']['sha256']}` | `{item['classification']}` | "
            f"`{item['runtime']}` |"
        )
    if "firmware_qualification" in report:
        lines.extend(
            [
                "",
                "## Firmware integration",
                "",
                "Both extension-enabled target builds are byte-reproducible across two "
                "isolated runs. This does not upgrade runtime classification.",
                "",
                "| Target | Firmware delta | Internal RAM delta | Remaining internal RAM | Remaining IRAM |",
                "|---|---:|---:|---:|---:|",
            ]
        )
        for target in ("esp32s3", "esp32c6"):
            item = report["firmware_qualification"]["targets"][target]
            iram_remaining = (
                str(item["remaining_iram"])
                if item["dedicated_iram_total"] != 0
                else "n/a"
            )
            lines.append(
                f"| `{target}` | `{item['firmware_bin_delta']:+d}` bytes | "
                f"`{item['internal_ram_delta']:+d}` bytes | "
                f"`{item['remaining_internal_ram']}` bytes | "
                f"`{iram_remaining}` |"
            )
    lines.extend(
        [
            "",
            "## Claim boundary and hard stop",
            "",
            "HX4.5 seals the host-executed adversarial contract and dual-target build "
            "realizations. No S3 or C6 board was attached. Target WAMR dispatch, native "
            "extension task scheduling, queue/stack high-water values, heap recovery, and "
            "serial traces remain unobserved.",
            "",
            "The next action is the named ESP32-S3 hardware qualification. HX5 and all "
            "peripheral work remain blocked until that review is complete.",
            "",
        ]
    )
    (output / "qualification-report.md").write_text("\n".join(lines), encoding="utf-8")


def qualify(output: Path, compilers: dict[str, Path | None]) -> dict[str, Any]:
    report = qualify_extension_roundtrip.qualify(output, compilers)
    out = output.resolve()
    adversarial = _run_adversarial_smokes(out)
    transcript = out / "adversarial-event-effect-transcript.json"
    transcript.write_text(
        json.dumps(adversarial, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    report.update(
        {
            "schema": SCHEMA,
            "pass": "HX4.5",
            "phase": PHASE,
            "scope": "EXTENSION_EVENT_EFFECT_ADVERSARIAL_SEAL",
            "adversarial_event_effect": {
                **adversarial,
                "report": "adversarial-event-effect-transcript.json",
                "sha256": _sha256(transcript),
            },
            "negative_cases": {
                "status": "PASS",
                "count": len(EXPECTED_CASES),
                "cases": _negative_case_map(adversarial),
            },
            "deferred": [
                "ESP32-S3 named-board hardware qualification",
                "ESP32-C6 hardware execution",
                "GPIO and all HX5+ peripheral work",
            ],
        }
    )
    report_path = out / "qualification-report.json"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    _write_markdown(report, out)
    return report


def _validate_firmware_source(firmware: dict[str, Any]) -> None:
    firmware_hash, firmware_files = qualify_extension_spine._tree_digest(  # noqa: SLF001
        ROOT / "firmware",
        ignored={
            "build",
            "managed_components",
            "dependencies.lock",
            "sdkconfig",
            "__pycache__",
        },
    )
    current_firmware = {"sha256": firmware_hash, "file_count": firmware_files}
    if firmware.get("firmware_source") != current_firmware:
        raise QualificationError("firmware report source identity does not match HX4.5")
    native_hash, native_files = qualify_extension_spine._tree_digest(  # noqa: SLF001
        ROOT / "native-sdk", ignored={"__pycache__"}
    )
    current_native = {"sha256": native_hash, "file_count": native_files}
    if firmware.get("native_sdk_source") != current_native:
        raise QualificationError("firmware report native SDK identity does not match HX4.5")


def finalize_with_firmware(output: Path, firmware_report_path: Path) -> dict[str, Any]:
    out = output.resolve()
    report_path = out / "qualification-report.json"
    if not report_path.is_file() or not firmware_report_path.is_file():
        raise QualificationError("HX4.5 and firmware qualification reports must both exist")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    firmware = json.loads(firmware_report_path.read_text(encoding="utf-8"))
    if (
        report.get("status") != "PASS"
        or report.get("phase") != PHASE
        or report.get("adversarial_event_effect", {}).get("status") != "PASS"
        or firmware.get("status") != "PASS"
        or firmware.get("result") != "BUILD_PROVEN"
    ):
        raise QualificationError("cannot finalize HX4.5 from a non-passing report")
    source_hash, source_files = qualify_extension_runtime._tree_digest(  # noqa: SLF001
        ROOT, {"reports", "__pycache__"}
    )
    if report.get("source_tree") != {
        "sha256": source_hash,
        "file_count": source_files,
    }:
        raise QualificationError("HX4.5 source changed after adversarial execution")
    _validate_firmware_source(firmware)
    firmware_targets: dict[str, Any] = {}
    for item in firmware.get("targets", []):
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
            "dedicated_iram_total": cell["size"]["iram_total"],
            "remaining_iram": cell["size"]["iram_remain"],
        }
    if set(firmware_targets) != {"esp32s3", "esp32c6"}:
        raise QualificationError("firmware report omitted an HX4.5 target")
    try:
        relative_report = firmware_report_path.resolve().relative_to(out)
    except ValueError as exc:
        raise QualificationError("firmware report must be contained in HX4.5 output") from exc
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
        qualify_extension_roundtrip.QualificationError,
        qualify_extension_runtime.QualificationError,
        qualify_extension_spine.QualificationError,
        build_native_extension.NativeBuildError,
    ) as exc:
        print(f"HX4.5 qualification failed: {exc}", file=sys.stderr)
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
