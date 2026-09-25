#!/usr/bin/env python3
"""Evaluate retained serial evidence from the AITRIP HX4.5 S3 harness."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


EXPECTED_BOARD = "AITRIP ESP32-S3-DevKitC-1 N8R2"
EXPECTED_MODULE_MARKING = "ESP32-S3-WROOM-1-N8R2"
EXPECTED_NATIVE_ELF_SHA256 = (
    "7c7c5465de5dc408b4fc79e8bdd9956234099817596d987c7950126ca2921daf"
)
EXPECTED_COMMON_WASM_SHA256 = (
    "ef8b21a4b7a423923c09f5e38fc626ff7d1cda856c4935db7f191695a333e5c4"
)
EXPECTED_FIRMWARE_SOURCE = {
    "sha256": "c7b4341e00911b3b26b4d9b8abcd831af4abdf7754503a79298e86aa2b9d2c31",
    "file_count": 141,
}
EXPECTED_NATIVE_SDK_SOURCE = {
    "sha256": "a7ceb397ab009950a1ebbdea60280f7944020a6523252b7de0d781e3e798bdd4",
    "file_count": 1,
}
EXPECTED_DEPENDENCY_LOCK_SHA256 = (
    "5c672b327f9f4fc8742ca78c5cdca76170cb78a18857e98b497ac0f0bbee0e4c"
)
EXPECTED_IDF_VERSION = "v5.4.4"
EXPECTED_IDF_COMMIT = "296b6eab9445fd720e71aecab961e2d3fbca9944"
EXPECTED_CANONICAL_IDF_PLATFORM = "linux/amd64"
EXPECTED_HIL_BUILD_HOST_PLATFORMS = {
    "linux/amd64",
    "darwin/amd64",
    "darwin/arm64",
}
APPLICATION_PARTITION_BYTES = 2 * 1024 * 1024
MINIMUM_LINK_DIRAM_REMAIN_BYTES = 1024
MINIMUM_LINK_IRAM_REMAIN_BYTES = 1
EXPECTED_FLASH_BYTES = 8 * 1024 * 1024
EXPECTED_PSRAM_BYTES = 2 * 1024 * 1024
EXPECTED_MEASURED_CYCLES = 5
EXPECTED_WARMUP_CYCLES = 1
MINIMUM_STACK_HEADROOM_BYTES = 512
MINIMUM_MAIN_STACK_HEADROOM_BYTES = 1024
MINIMUM_INTERNAL_FREE_BYTES = 8192
MINIMUM_INTERNAL_LARGEST_BYTES = 4096
MINIMUM_PSRAM_FREE_BYTES = 512 * 1024
MINIMUM_PSRAM_LARGEST_BYTES = 256 * 1024
MAXIMUM_QUEUE_HIGH_WATER = 4
HX5B_QUEUE_ROUNDS = 8
HX5B_ACCEPTED_EVENTS = 128
HX5B_QUEUE_CAPACITY = 16
HX5B_EFFECT_TIMEOUT_MS = 1000
MAXIMUM_LIFECYCLE_TIMING_MS = 2000
REPORT_SCHEMA = "pulse.esp32.hx45-s3-aitrip-hardware-report.v1"
ANSI_ESCAPE = re.compile(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
MARKER = re.compile(r"PULSE_HX45_([A-Z_]+)\s+(\{.*\})")
FATAL_PATTERNS = (
    "Guru Meditation Error",
    "Task watchdog got triggered",
    "Interrupt wdt timeout",
    "Brownout detector was triggered",
    "assert failed:",
    "abort() was called",
    "CORRUPT HEAP",
    "Stack canary watchpoint triggered",
    "stack overflow",
    "heap corruption detected",
)


class EvidenceError(RuntimeError):
    """Raised when the supplied evidence cannot be evaluated."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_markers(text: str) -> dict[str, list[dict[str, Any]]]:
    markers: dict[str, list[dict[str, Any]]] = {}
    clean = ANSI_ESCAPE.sub("", text.replace("\r", ""))
    for line_number, line in enumerate(clean.splitlines(), start=1):
        match = MARKER.search(line)
        if match is None:
            continue
        try:
            value = json.loads(match.group(2))
        except json.JSONDecodeError as exc:
            raise EvidenceError(
                f"invalid JSON marker on serial line {line_number}: {exc}"
            ) from exc
        if not isinstance(value, dict):
            raise EvidenceError(
                f"marker JSON on serial line {line_number} is not an object"
            )
        value["_serial_line"] = line_number
        markers.setdefault(match.group(1), []).append(value)
    return markers


def latest(markers: dict[str, list[dict[str, Any]]], name: str) -> dict[str, Any]:
    values = markers.get(name, [])
    if not values:
        raise EvidenceError(f"serial transcript omitted PULSE_HX45_{name}")
    return values[-1]


def require_marker_count(
    markers: dict[str, list[dict[str, Any]]],
    name: str,
    expected: int,
    failures: list[str],
) -> None:
    observed = len(markers.get(name, []))
    if observed != expected:
        failures.append(
            f"PULSE_HX45_{name} count is {observed}, expected {expected}"
        )


def validate_file_evidence(
    *,
    evidence: Any,
    root: Path,
    label: str,
    failures: list[str],
) -> None:
    if not isinstance(evidence, dict):
        failures.append(f"{label} evidence is not an object")
        return
    raw_path = evidence.get("path")
    expected_digest = evidence.get("sha256")
    expected_size = evidence.get("size")
    if not isinstance(raw_path, str) or not raw_path:
        failures.append(f"{label} evidence has no path")
        return
    artifact = Path(raw_path)
    if not artifact.is_absolute():
        artifact = root / artifact
    try:
        artifact = artifact.resolve()
        artifact.relative_to(root.resolve())
    except ValueError:
        failures.append(f"{label} evidence path escapes the run directory")
        return
    if not artifact.is_file():
        failures.append(f"{label} evidence file is missing")
        return
    observed_digest = sha256(artifact)
    observed_size = artifact.stat().st_size
    if observed_digest != expected_digest:
        failures.append(f"{label} evidence digest does not match the build report")
    if observed_size != expected_size:
        failures.append(f"{label} evidence size does not match the build report")


def evaluate(
    *,
    serial_log: Path,
    build_report_path: Path,
    module_marking: str,
    require_hx5b_pressure: bool = False,
) -> dict[str, Any]:
    serial_log = serial_log.resolve()
    build_report_path = build_report_path.resolve()
    if not serial_log.is_file() or not build_report_path.is_file():
        raise EvidenceError("serial log and build report must both exist")
    serial_text = serial_log.read_text(encoding="utf-8", errors="replace")
    build = json.loads(build_report_path.read_text(encoding="utf-8"))
    if not isinstance(build, dict):
        raise EvidenceError("build report root is not an object")
    markers = parse_markers(serial_text)
    failures: list[str] = []

    if require_hx5b_pressure:
        pressure_contract = build.get("pressure_contract", {})
        if (
            build.get("campaign") != "HX5b"
            or not isinstance(pressure_contract, dict)
            or pressure_contract.get("status") != "BUILD_CONFIGURED"
            or pressure_contract.get("queue_rounds") != HX5B_QUEUE_ROUNDS
            or pressure_contract.get("accepted_events") != HX5B_ACCEPTED_EVENTS
            or pressure_contract.get("queue_capacity") != HX5B_QUEUE_CAPACITY
            or pressure_contract.get("effect_timeout_ms") != HX5B_EFFECT_TIMEOUT_MS
            or pressure_contract.get("runtime") != "HARDWARE_NOT_RUN"
        ):
            failures.append("build report did not configure the exact HX5b pressure campaign")

    if build.get("schema") != "pulse.esp32.hx45-s3-aitrip-build.v1":
        failures.append("build report schema is unsupported")
    if build.get("status") != "PASS":
        failures.append("firmware build report is not PASS")
    claim = build.get("claim_boundary", {})
    if not isinstance(claim, dict):
        claim = {}
    if (
        claim.get("build") != "BUILD_PROVEN"
        or claim.get("runtime") != "HARDWARE_NOT_RUN"
        or claim.get("canonical_16mb_reference_unchanged") is not True
    ):
        failures.append("build report has an invalid pre-hardware claim boundary")
    build_board = build.get("board", {})
    if not isinstance(build_board, dict):
        build_board = {}
    if (
        build_board.get("manufacturer") != "AITRIP"
        or build_board.get("model") != "ESP32-S3-DevKitC-1 N8R2"
        or build_board.get("module") != EXPECTED_MODULE_MARKING
        or build_board.get("target") != "esp32s3"
        or build_board.get("flash_bytes") != EXPECTED_FLASH_BYTES
        or build_board.get("psram_bytes") != EXPECTED_PSRAM_BYTES
        or build_board.get("psram_mode") != "quad"
    ):
        failures.append("build report does not describe the exact AITRIP N8R2 lane")
    firmware = build.get("firmware", {})
    if not isinstance(firmware, dict):
        firmware = {}
    if firmware.get("status") != "PASS" or firmware.get("result") != "BUILD_PROVEN":
        failures.append("firmware artifact set is not BUILD_PROVEN")
    headroom_gate = firmware.get("headroom_gate", {})
    if not isinstance(headroom_gate, dict):
        headroom_gate = {}
    if (
        headroom_gate.get("status") != "PASS"
        or headroom_gate.get("minimum_diram_remain_bytes")
        != MINIMUM_LINK_DIRAM_REMAIN_BYTES
        or not isinstance(headroom_gate.get("observed_diram_remain_bytes"), int)
        or headroom_gate.get("observed_diram_remain_bytes", 0)
        < MINIMUM_LINK_DIRAM_REMAIN_BYTES
        or headroom_gate.get("minimum_iram_remain_bytes")
        != MINIMUM_LINK_IRAM_REMAIN_BYTES
        or not isinstance(headroom_gate.get("observed_iram_remain_bytes"), int)
        or headroom_gate.get("observed_iram_remain_bytes", 0)
        < MINIMUM_LINK_IRAM_REMAIN_BYTES
        or headroom_gate.get("application_partition_bytes")
        != APPLICATION_PARTITION_BYTES
        or not isinstance(headroom_gate.get("application_binary_bytes"), int)
        or headroom_gate.get("application_binary_bytes", APPLICATION_PARTITION_BYTES + 1)
        > APPLICATION_PARTITION_BYTES
    ):
        failures.append("firmware build headroom or app-partition gate did not pass")
    normalized_marking = re.sub(r"[^A-Z0-9]", "", module_marking.upper())
    normalized_expected = re.sub(r"[^A-Z0-9]", "", EXPECTED_MODULE_MARKING)
    if normalized_marking != normalized_expected:
        failures.append(
            f"module marking is {module_marking!r}, expected {EXPECTED_MODULE_MARKING!r}"
        )
    native_container = build.get("native_extension", {})
    if not isinstance(native_container, dict):
        native_container = {}
    native = native_container.get("elf", {})
    if not isinstance(native, dict):
        native = {}
    common = build.get("common_wasm", {})
    if not isinstance(common, dict):
        common = {}
    if native.get("sha256") != EXPECTED_NATIVE_ELF_SHA256:
        failures.append("native extension does not match the HX4.5 S3 seal")
    if common.get("sha256") != EXPECTED_COMMON_WASM_SHA256:
        failures.append("common Wasm does not match the HX4.5 seal")
    sealed_sources = build.get("sealed_sources", {})
    if not isinstance(sealed_sources, dict):
        sealed_sources = {}
    if sealed_sources.get("firmware") != EXPECTED_FIRMWARE_SOURCE:
        failures.append("firmware source does not match the current source seal")
    if sealed_sources.get("native_sdk") != EXPECTED_NATIVE_SDK_SOURCE:
        failures.append("native SDK source does not match the HX4.5 seal")
    environment = firmware.get("environment", {})
    if not isinstance(environment, dict):
        environment = {}
    if (
        environment.get("status") != "PASS"
        or environment.get("version") != EXPECTED_IDF_VERSION
        or environment.get("source_commit") != EXPECTED_IDF_COMMIT
        or environment.get("platform") not in EXPECTED_HIL_BUILD_HOST_PLATFORMS
        or environment.get("canonical_platform")
        != EXPECTED_CANONICAL_IDF_PLATFORM
        or environment.get("platform_scope") != "NAMED_BOARD_HIL_BUILD"
    ):
        failures.append(
            "firmware was not built from the exact IDF source in a supported named-board HIL host lane"
        )
    dependency_lock = firmware.get("dependency_lock", {})
    if (
        not isinstance(dependency_lock, dict)
        or dependency_lock.get("sha256") != EXPECTED_DEPENDENCY_LOCK_SHA256
    ):
        failures.append("dependency lock does not match the HX4.5 S3 seal")

    run_root = build_report_path.parent
    evidence_to_check: list[tuple[str, dict[str, Any]]] = [
        ("native extension", native),
        ("common Wasm", common),
        ("sdkconfig", firmware.get("sdkconfig", {})),
        ("dependency lock", dependency_lock),
        ("build log", firmware.get("build_log", {})),
    ]
    artifacts = firmware.get("artifacts", {})
    if not isinstance(artifacts, dict):
        artifacts = {}
    size_report = firmware.get("size", {})
    if (
        not isinstance(size_report, dict)
        or size_report.get("diram_remain")
        != headroom_gate.get("observed_diram_remain_bytes")
        or size_report.get("iram_remain")
        != headroom_gate.get("observed_iram_remain_bytes")
    ):
        failures.append("firmware size report does not match the build headroom gate")
    application_binary_evidence = artifacts.get("application_binary", {})
    if (
        not isinstance(application_binary_evidence, dict)
        or application_binary_evidence.get("size")
        != headroom_gate.get("application_binary_bytes")
    ):
        failures.append("application binary size does not match the partition gate")
    for artifact_name in (
        "application_elf",
        "application_binary",
        "application_map",
        "bootloader_binary",
        "partition_table_binary",
        "flasher_args",
        "flash_args",
    ):
        evidence_to_check.append(
            (artifact_name.replace("_", " "), artifacts.get(artifact_name, {}))
        )
    harness_sources = build.get("harness_sources", {})
    if not isinstance(harness_sources, dict):
        harness_sources = {}
    for source_name in (
        "CMakeLists.txt",
        "main/CMakeLists.txt",
        "main/hx45_s3_aitrip_main.c",
        "partitions.csv",
        "sdkconfig.defaults",
    ):
        evidence_to_check.append(
            (f"harness source {source_name}", harness_sources.get(source_name, {}))
        )
    generated_sources = build.get("generated_sources", {})
    if not isinstance(generated_sources, dict):
        generated_sources = {}
    evidence_to_check.append(
        ("generated extension blob", generated_sources.get("extension_blob", {}))
    )
    for label, evidence in evidence_to_check:
        validate_file_evidence(
            evidence=evidence,
            root=run_root,
            label=label,
            failures=failures,
        )

    serial_lower = serial_text.lower()
    fatal_hits = [
        pattern for pattern in FATAL_PATTERNS if pattern.lower() in serial_lower
    ]
    if fatal_hits:
        failures.append("fatal serial signatures observed: " + ", ".join(fatal_hits))

    for marker_name, expected_count in (
        ("BEGIN", 1),
        ("BOARD", 2),
        ("TRAP", 1),
        ("RESET_ARMED", 1),
        ("RESET_OBSERVED", 1),
        ("FINAL", 1),
    ):
        require_marker_count(markers, marker_name, expected_count, failures)

    boards = markers.get("BOARD", [])
    for board in boards:
        if board.get("board") != EXPECTED_BOARD or board.get("target") != "esp32s3":
            failures.append("serial board identity does not match the AITRIP S3 lane")
        if board.get("flash_bytes") != EXPECTED_FLASH_BYTES:
            failures.append("observed flash size is not 8 MB")
        if board.get("psram_bytes") != EXPECTED_PSRAM_BYTES:
            failures.append("observed PSRAM size is not 2 MB")
        if board.get("elf_sha256") != EXPECTED_NATIVE_ELF_SHA256:
            failures.append("running image reports an unexpected native ELF")
        if board.get("common_wasm_sha256") != EXPECTED_COMMON_WASM_SHA256:
            failures.append("running image reports an unexpected common Wasm")

    begin = latest(markers, "BEGIN")
    if (
        begin.get("status") != "RUNNING"
        or begin.get("warmup_cycles") != EXPECTED_WARMUP_CYCLES
        or begin.get("measured_cycles") != EXPECTED_MEASURED_CYCLES
    ):
        failures.append("begin marker does not declare the exact hardware campaign")

    cycles = markers.get("CYCLE", [])
    if len(cycles) != EXPECTED_WARMUP_CYCLES + EXPECTED_MEASURED_CYCLES:
        failures.append("cycle marker count is not exactly warmup plus five measured")
    if [item.get("cycle") for item in cycles] != list(
        range(EXPECTED_WARMUP_CYCLES + EXPECTED_MEASURED_CYCLES)
    ):
        failures.append("warmup and measured cycle markers are out of order")
    warmup = [item for item in cycles if item.get("measured") is False]
    if (
        len(warmup) != EXPECTED_WARMUP_CYCLES
        or warmup[0].get("cycle") != 0
        or warmup[0].get("status") != "PASS"
    ):
        failures.append("the single unmeasured warmup cycle is missing or failed")
    measured = [item for item in cycles if item.get("measured") is True]
    if [item.get("cycle") for item in measured] != list(
        range(1, EXPECTED_MEASURED_CYCLES + 1)
    ):
        failures.append("measured clean cycles are missing, duplicated, or out of order")
    for cycle in measured:
        if cycle.get("status") != "PASS":
            failures.append(f"measured cycle {cycle.get('cycle')} did not pass")
        if cycle.get("internal_before") != cycle.get("internal_after"):
            failures.append(f"measured cycle {cycle.get('cycle')} leaked internal heap")
        if cycle.get("psram_before") != cycle.get("psram_after"):
            failures.append(f"measured cycle {cycle.get('cycle')} leaked PSRAM heap")
        stack = cycle.get("stack_headroom_bytes")
        main_stack = cycle.get("main_stack_headroom_bytes")
        queue = cycle.get("queue_high_water")
        if not isinstance(stack, int) or stack < MINIMUM_STACK_HEADROOM_BYTES:
            failures.append(f"measured cycle {cycle.get('cycle')} has inadequate stack headroom")
        if (
            not isinstance(main_stack, int)
            or main_stack < MINIMUM_MAIN_STACK_HEADROOM_BYTES
        ):
            failures.append(
                f"measured cycle {cycle.get('cycle')} has inadequate main-task stack headroom"
            )
        if not isinstance(queue, int) or queue < 1 or queue > MAXIMUM_QUEUE_HIGH_WATER:
            failures.append(f"measured cycle {cycle.get('cycle')} has invalid queue high-water")
        if require_hx5b_pressure:
            for field in ("load_ms", "start_ms", "quiesce_ms", "deinit_ms"):
                value = cycle.get(field)
                if (
                    not isinstance(value, int)
                    or value < 0
                    or value > MAXIMUM_LIFECYCLE_TIMING_MS
                ):
                    failures.append(
                        f"measured cycle {cycle.get('cycle')} has invalid {field}"
                    )

    failed_cases = [
        item for item in markers.get("CASE", []) if item.get("status") != "PASS"
    ]
    if failed_cases:
        failures.append(
            "one or more harness cases failed: "
            + ", ".join(str(item.get("name")) for item in failed_cases)
        )
    required_cases = {
        "event-effect-roundtrip": (6, 0),
        "extension-stack-measured": (6, 1),
        "extension-queue-measured": (6, 1),
        "main-stack-headroom": (6, 1),
        "internal-free-headroom": (8, 1),
        "internal-largest-headroom": (8, 1),
        "psram-free-headroom": (8, 1),
        "psram-largest-headroom": (8, 1),
        "internal-heap-recovered": (5, 1),
        "psram-heap-recovered": (5, 1),
        "unknown-event-rejected-on-target": (1, -6),
        "extension-unload": (6, 0),
        "real-wasm-event-trap": (1, -15),
        "trap-main-stack-headroom": (1, 1),
        "expired-quiesce-requires-timeout": (1, -16),
        "expired-quiesce-latches-reset": (1, 1),
        "reset-main-stack-headroom": (1, 1),
        "reset-breadcrumb-recorded": (1, 1),
    }
    cases = markers.get("CASE", [])
    for name, (expected_count, expected_value) in required_cases.items():
        observed_cases = [item for item in cases if item.get("name") == name]
        if (
            len(observed_cases) != expected_count
            or any(
                item.get("status") != "PASS"
                or item.get("observed") != expected_value
                or item.get("expected") != expected_value
                for item in observed_cases
            )
        ):
            failures.append(
                f"required case {name!r} is missing, duplicated, or unexpected"
            )

    pressure_markers = markers.get("PRESSURE", [])
    pressure: dict[str, Any] = pressure_markers[-1] if pressure_markers else {}
    if require_hx5b_pressure:
        if len(pressure_markers) != 1:
            failures.append(
                f"PULSE_HX45_PRESSURE count is {len(pressure_markers)}, expected 1"
            )
        ordered_latency = [
            pressure.get("latency_minimum_ms"),
            pressure.get("latency_p50_ms"),
            pressure.get("latency_p95_ms"),
            pressure.get("latency_maximum_ms"),
        ]
        if (
            pressure.get("status") != "PASS"
            or pressure.get("campaign") != "HX5b"
            or pressure.get("queue_rounds") != HX5B_QUEUE_ROUNDS
            or pressure.get("accepted_events") != HX5B_ACCEPTED_EVENTS
            or pressure.get("rejected_events") != HX5B_QUEUE_ROUNDS
            or pressure.get("recovered_rounds") != HX5B_QUEUE_ROUNDS
            or pressure.get("queue_high_water") != HX5B_QUEUE_CAPACITY
            or pressure.get("end_pending") != 0
            or pressure.get("latency_sample_count") != HX5B_ACCEPTED_EVENTS
            or any(not isinstance(value, int) or value < 0 for value in ordered_latency)
            or ordered_latency != sorted(ordered_latency)
            or pressure.get("latency_maximum_ms", HX5B_EFFECT_TIMEOUT_MS + 1)
            > HX5B_EFFECT_TIMEOUT_MS
        ):
            failures.append("target queue-pressure or latency distribution evidence failed")
        for name in (
            "hx5b-queue-saturation",
            "hx5b-queue-drain-recovery",
            "hx5b-pressure-roundtrip",
        ):
            observed = [item for item in cases if item.get("name") == name]
            if (
                len(observed) != 1
                or observed[0].get("status") != "PASS"
                or observed[0].get("observed") != 1
                or observed[0].get("expected") != 1
            ):
                failures.append(f"required HX5b pressure case {name!r} did not pass once")
        if (
            len(cycles) < 2
            or not isinstance(pressure.get("_serial_line"), int)
            or not (
                cycles[0].get("_serial_line", 0)
                < pressure.get("_serial_line", 0)
                < cycles[1].get("_serial_line", 0)
            )
        ):
            failures.append("HX5b pressure marker is not inside the first measured cycle")

    trap = latest(markers, "TRAP")
    if (
        trap.get("status") != "PASS"
        or trap.get("observed") != -15
        or trap.get("runtime_outcome") != 7
    ):
        failures.append("real target-WAMR trap evidence did not pass")
    armed = latest(markers, "RESET_ARMED")
    if (
        armed.get("status") != "PASS"
        or armed.get("phase") != 1
        or armed.get("fault_code") != 0x48583304
        or armed.get("fault_status") != -5
        or armed.get("reset_required") != 1
    ):
        failures.append("reset-required path was not armed as expected")
    observed_reset = latest(markers, "RESET_OBSERVED")
    if (
        observed_reset.get("status") != "PASS"
        or not observed_reset.get("software_reset")
        or not observed_reset.get("breadcrumb_valid")
        or observed_reset.get("reset_required") != 1
        or observed_reset.get("fault_code") != 0x48583304
        or observed_reset.get("fault_status") != -5
    ):
        failures.append("software reset or retained breadcrumb evidence did not pass")
    final = latest(markers, "FINAL")
    if (
        final.get("status") != "PASS"
        or final.get("board") != EXPECTED_BOARD
        or final.get("target_runtime") != "NAMED_BOARD_OBSERVED"
    ):
        failures.append("final device verdict is not PASS")
    if final.get("measured_cycles") != EXPECTED_MEASURED_CYCLES:
        failures.append("final device verdict reports the wrong cycle count")
    final_stack = final.get("minimum_stack_headroom")
    final_main_stack = final.get("minimum_main_stack_headroom")
    final_queue = final.get("maximum_queue_high_water")
    if not isinstance(final_stack, int) or final_stack < MINIMUM_STACK_HEADROOM_BYTES:
        failures.append("final stack headroom is below the qualification floor")
    if (
        not isinstance(final_main_stack, int)
        or final_main_stack < MINIMUM_MAIN_STACK_HEADROOM_BYTES
    ):
        failures.append("final main-task stack headroom is below the qualification floor")
    if (
        not isinstance(final_queue, int)
        or final_queue < 1
        or final_queue > MAXIMUM_QUEUE_HIGH_WATER
    ):
        failures.append("final queue high-water is outside the declared bound")

    if cycles and isinstance(final_stack, int):
        observed_stacks = [
            item.get("stack_headroom_bytes")
            for item in cycles
            if isinstance(item.get("stack_headroom_bytes"), int)
        ]
        if len(observed_stacks) != len(cycles) or final_stack != min(observed_stacks):
            failures.append("final stack minimum does not match the cycle evidence")
    if cycles and isinstance(final_queue, int):
        observed_queues = [
            item.get("queue_high_water")
            for item in cycles
            if isinstance(item.get("queue_high_water"), int)
        ]
        if len(observed_queues) != len(cycles) or final_queue != max(observed_queues):
            failures.append("final queue maximum does not match the cycle evidence")

    main_stack_markers = markers.get("MAIN_STACK", [])
    if len(main_stack_markers) != 8:
        failures.append(
            f"main-task stack marker count is {len(main_stack_markers)}, expected 8"
        )
    main_stack_samples = [
        item.get("headroom_bytes")
        for item in main_stack_markers
        if isinstance(item.get("headroom_bytes"), int)
    ]
    if (
        len(main_stack_samples) != len(main_stack_markers)
        or not main_stack_samples
        or min(main_stack_samples) < MINIMUM_MAIN_STACK_HEADROOM_BYTES
        or final_main_stack != min(main_stack_samples)
    ):
        failures.append("main-task stack evidence is incomplete or below its floor")
    expected_main_stack_stages = [
        (cycle, "after-roundtrip")
        for cycle in range(EXPECTED_WARMUP_CYCLES + EXPECTED_MEASURED_CYCLES)
    ] + [(900, "after-real-wasm-trap"), (1000, "reset-required")]
    if [
        (item.get("cycle"), item.get("stage")) for item in main_stack_markers
    ] != expected_main_stack_stages:
        failures.append("main-task stack samples are missing or out of order")

    heap_markers = markers.get("HEAP", [])
    expected_heap_markers = (
        (EXPECTED_WARMUP_CYCLES + EXPECTED_MEASURED_CYCLES) * 5 + 3 + 1
    )
    if len(heap_markers) != expected_heap_markers:
        failures.append(
            f"heap marker count is {len(heap_markers)}, expected {expected_heap_markers}"
        )
    internal_samples = [
        item.get("internal_free")
        for item in heap_markers
        if isinstance(item.get("internal_free"), int)
    ]
    psram_samples = [
        item.get("psram_free")
        for item in heap_markers
        if isinstance(item.get("psram_free"), int)
    ]
    internal_largest_samples = [
        item.get("internal_largest")
        for item in heap_markers
        if isinstance(item.get("internal_largest"), int)
    ]
    psram_largest_samples = [
        item.get("psram_largest")
        for item in heap_markers
        if isinstance(item.get("psram_largest"), int)
    ]
    if (
        len(internal_samples) != len(heap_markers)
        or not internal_samples
        or min(internal_samples) < MINIMUM_INTERNAL_FREE_BYTES
        or final.get("minimum_internal_free") != min(internal_samples)
    ):
        failures.append("final internal-heap minimum does not match the heap evidence")
    if (
        len(psram_samples) != len(heap_markers)
        or not psram_samples
        or min(psram_samples) < MINIMUM_PSRAM_FREE_BYTES
        or final.get("minimum_psram_free") != min(psram_samples)
    ):
        failures.append("final PSRAM minimum does not match the heap evidence")
    if (
        len(internal_largest_samples) != len(heap_markers)
        or not internal_largest_samples
        or min(internal_largest_samples) < MINIMUM_INTERNAL_LARGEST_BYTES
        or final.get("minimum_internal_largest") != min(internal_largest_samples)
    ):
        failures.append("internal largest-block evidence is incomplete or below its floor")
    if (
        len(psram_largest_samples) != len(heap_markers)
        or not psram_largest_samples
        or min(psram_largest_samples) < MINIMUM_PSRAM_LARGEST_BYTES
        or final.get("minimum_psram_largest") != min(psram_largest_samples)
    ):
        failures.append("PSRAM largest-block evidence is incomplete or below its floor")
    expected_heap_stages: list[tuple[int, str]] = []
    for cycle in range(EXPECTED_WARMUP_CYCLES + EXPECTED_MEASURED_CYCLES):
        expected_heap_stages.extend(
            (cycle, stage)
            for stage in (
                "before",
                "after-extension-start",
                "after-wamr-load",
                "after-roundtrip",
                "after-clean-unload",
            )
        )
    expected_heap_stages.extend(
        (
            (900, "before-real-wasm-trap"),
            (900, "during-real-wasm-trap"),
            (900, "after-real-wasm-trap"),
            (1000, "reset-required"),
        )
    )
    if [
        (item.get("cycle"), item.get("stage")) for item in heap_markers
    ] != expected_heap_stages:
        failures.append("heap samples are missing or out of order")
    heap_by_key = {
        (item.get("cycle"), item.get("stage")): item for item in heap_markers
    }
    for cycle in measured:
        cycle_id = cycle.get("cycle")
        before = heap_by_key.get((cycle_id, "before"), {})
        after = heap_by_key.get((cycle_id, "after-clean-unload"), {})
        if (
            cycle.get("internal_before") != before.get("internal_free")
            or cycle.get("internal_after") != after.get("internal_free")
            or cycle.get("psram_before") != before.get("psram_free")
            or cycle.get("psram_after") != after.get("psram_free")
        ):
            failures.append(
                f"measured cycle {cycle_id} does not match its heap stage evidence"
            )

    if len(boards) == 2:
        ordered_lines = [
            boards[0].get("_serial_line"),
            begin.get("_serial_line"),
            cycles[0].get("_serial_line") if cycles else None,
            cycles[-1].get("_serial_line") if cycles else None,
            trap.get("_serial_line"),
            armed.get("_serial_line"),
            boards[1].get("_serial_line"),
            observed_reset.get("_serial_line"),
            final.get("_serial_line"),
        ]
        if not all(isinstance(line, int) for line in ordered_lines) or ordered_lines != sorted(ordered_lines):
            failures.append("required hardware markers are out of order")

    report: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "status": "PASS" if not failures else "FAIL",
        "runtime_result": "NAMED_BOARD_OBSERVED" if not failures else "FAILED",
        "board": {
            "manufacturer": "AITRIP",
            "model": "ESP32-S3-DevKitC-1 N8R2",
            "module_marking": module_marking,
            "identity_basis": "OPERATOR_ATTESTED_VENDOR_AND_MODULE_MARKING_PLUS_MEASURED_CHIP_MEMORY",
            "target": "esp32s3",
            "flash_bytes": boards[-1].get("flash_bytes") if boards else None,
            "psram_bytes": boards[-1].get("psram_bytes") if boards else None,
            "chip_revision": boards[-1].get("chip_revision") if boards else None,
        },
        "artifacts": {
            "serial_log": {
                "path": str(serial_log),
                "sha256": sha256(serial_log),
                "size": serial_log.stat().st_size,
            },
            "build_report": {
                "path": str(build_report_path),
                "sha256": sha256(build_report_path),
                "size": build_report_path.stat().st_size,
            },
            "native_extension_sha256": native.get("sha256"),
            "common_wasm_sha256": common.get("sha256"),
        },
        "observations": {
            "measured_clean_cycles": measured,
            "heap_samples": heap_markers,
            "firmware_size": size_report,
            "main_task_stack": main_stack_markers,
            "real_wasm_trap": trap,
            "reset_armed": armed,
            "reset_observed": observed_reset,
            "final": final,
            "fatal_serial_signatures": fatal_hits,
        },
        "pressure_seal": {
            "required": require_hx5b_pressure,
            "status": (
                "PASS"
                if require_hx5b_pressure and not failures
                else ("FAIL" if require_hx5b_pressure else "NOT_REQUESTED")
            ),
            "campaign": "HX5b" if require_hx5b_pressure else "HX4.5",
            "marker": pressure if require_hx5b_pressure else None,
        },
        "failures": failures,
        "claim_boundary": {
            "proves": [
                "ESP32-S3 target ELF inspection, relocation, and descriptor execution",
                "extension-owned FreeRTOS task and bounded queue lifecycle",
                "real WAMR common-Wasm event/effect round trip",
                "five measured clean unload cycles and heap recovery",
                "internal/PSRAM free and largest-block floors plus extension/main-task stack headroom",
                "target WAMR trap handling",
                "quiescence timeout, reset-required latch, software reset, and retained harness breadcrumb",
            ],
            "does_not_prove": [
                "electronic authentication of the AITRIP PCB vendor",
                "the canonical 16 MB partition realization",
                "GPIO, networking, BLE, LoRa, OTA, or power-loss behavior",
                "production security provisioning",
                "ESP32-C6 runtime behavior",
            ],
        },
    }
    return report


def render_markdown(report: dict[str, Any]) -> str:
    board = report["board"]
    final = report["observations"]["final"]
    title = (
        "# HX5b AITRIP ESP32-S3 N8R2 pressure qualification"
        if report["pressure_seal"]["required"]
        else "# HX4.5 AITRIP ESP32-S3 N8R2 hardware qualification"
    )
    lines = [
        title,
        "",
        f"- Status: `{report['status']}`",
        f"- Runtime result: `{report['runtime_result']}`",
        f"- Board: `{board['model']}`",
        f"- Module marking: `{board['module_marking']}`",
        f"- Flash / PSRAM: `{board['flash_bytes']}` / `{board['psram_bytes']}` bytes",
        f"- Measured clean cycles: `{final.get('measured_cycles', 0)}`",
        f"- Minimum internal heap: `{final.get('minimum_internal_free', 0)}` bytes",
        f"- Minimum internal largest block: `{final.get('minimum_internal_largest', 0)}` bytes",
        f"- Minimum PSRAM heap: `{final.get('minimum_psram_free', 0)}` bytes",
        f"- Minimum PSRAM largest block: `{final.get('minimum_psram_largest', 0)}` bytes",
        f"- Minimum extension stack headroom: `{final.get('minimum_stack_headroom', 0)}` bytes",
        f"- Minimum main-task stack headroom: `{final.get('minimum_main_stack_headroom', 0)}` bytes",
        f"- Maximum extension queue high-water: `{final.get('maximum_queue_high_water', 0)}`",
        "",
        "## Claim boundary",
        "",
        "This is named-board runtime evidence for the isolated 8 MB / 2 MB HIL lane. "
        "It does not qualify the canonical 16 MB partition realization or any physical peripheral.",
        "",
    ]
    if report["failures"]:
        lines.extend(["## Failures", ""])
        lines.extend(f"- {failure}" for failure in report["failures"])
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial-log", type=Path, required=True)
    parser.add_argument("--build-report", type=Path, required=True)
    parser.add_argument("--module-marking", required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--require-hx5b-pressure", action="store_true")
    args = parser.parse_args(argv)
    try:
        output = args.out_dir.expanduser().resolve()
        if output.exists():
            if not output.is_dir() or any(output.iterdir()):
                raise EvidenceError("output directory must be absent or empty")
        else:
            output.mkdir(parents=True)
        report = evaluate(
            serial_log=args.serial_log,
            build_report_path=args.build_report,
            module_marking=args.module_marking,
            require_hx5b_pressure=args.require_hx5b_pressure,
        )
        (output / "qualification-report.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        (output / "qualification-report.md").write_text(
            render_markdown(report), encoding="utf-8"
        )
    except (OSError, ValueError, json.JSONDecodeError, EvidenceError) as exc:
        print(f"AITRIP HX4.5 evaluation failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"status": report["status"], "out_dir": str(output)}))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
