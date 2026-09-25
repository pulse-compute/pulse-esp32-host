#!/usr/bin/env python3
"""Build deterministic HX target-native artifacts with exact ESP-IDF toolchains."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
from pathlib import Path
from typing import Any

try:
    from tools import inspect_native_extension
except ModuleNotFoundError:  # Direct execution from tools/.
    import inspect_native_extension  # type: ignore[no-redef]

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "native-extensions" / "loader-probe" / "probe.c"
SYNTHETIC_SOURCE = ROOT / "native-extensions" / "synthetic-loopback" / "extension.c"
NATIVE_SDK_INCLUDE = ROOT / "native-sdk" / "c" / "include"
SCHEMA = "pulse.esp32.native-extension-build.v1"
COMPILERS = {
    "esp32s3": "xtensa-esp32s3-elf-gcc",
    "esp32c6": "riscv32-esp-elf-gcc",
}
TARGET_IDENTITIES = {"esp32s3": (1, 1), "esp32c6": (2, 2)}
SYNTHETIC_EXTENSION_ID = b"PULSE-HX3-LOOP01"
SYNTHETIC_EVENT_ID = 0x5449434B
SYNTHETIC_OPERATION_ID = 0x4543484F
SYNTHETIC_ALLOWED_IMPORTS = (
    "pulse_host_complete_effect_v1",
    "pulse_host_emit_event_v1",
    "pulse_host_monotonic_ms_v1",
    "pulse_host_report_health_v1",
    "uxTaskGetStackHighWaterMark",
    "vQueueDelete",
    "vTaskDelay",
    "vTaskDelete",
    "vTaskSetThreadLocalStoragePointerAndDelCallback",
    "xQueueGenericCreateStatic",
    "xQueueGenericSend",
    "xQueueReceive",
    "xTaskCreateStatic",
)


class NativeBuildError(RuntimeError):
    """Raised when a native artifact cannot be built deterministically."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run(command: list[str], *, env: dict[str, str] | None = None) -> str:
    process = subprocess.run(
        command,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if process.returncode != 0:
        raise NativeBuildError(
            f"command exited with status {process.returncode}: {' '.join(command)}\n{process.stdout}"
        )
    return process.stdout.strip()


def _prepare_out(path: Path) -> Path:
    resolved = path.resolve()
    if resolved.exists():
        if not resolved.is_dir() or any(resolved.iterdir()):
            raise NativeBuildError("output directory must be absent or empty")
    else:
        resolved.mkdir(parents=True)
    return resolved


def _resolve_compiler(target: str, requested: Path | None) -> Path:
    if requested is not None:
        compiler = requested.resolve()
        if not compiler.is_file() or not os.access(compiler, os.X_OK):
            raise NativeBuildError("requested compiler is missing or not executable")
        return compiler
    discovered = shutil.which(COMPILERS[target])
    if discovered is None:
        raise NativeBuildError(
            f"{COMPILERS[target]} is not on PATH; pass --compiler with the exact toolchain binary"
        )
    return Path(discovered).resolve()


def build_probe(
    *, target: str, source: Path, out_dir: Path, compiler: Path | None = None
) -> dict[str, Any]:
    source = source.resolve()
    if not source.is_file():
        raise NativeBuildError(f"source file is missing: {source}")
    output = _prepare_out(out_dir)
    compiler_path = _resolve_compiler(target, compiler)
    elf = output / f"loader-probe-{target}.elf"
    inspection_path = output / "inspection.json"
    report_path = output / "build-report.json"
    log_path = output / "build.log"
    source_hash = _sha256(source)
    compiler_hash = _sha256(compiler_path)
    compiler_version = _run([str(compiler_path), "--version"]).splitlines()[0]
    compiler_machine = _run([str(compiler_path), "-dumpmachine"])

    command = [
        str(compiler_path),
        "-std=c11",
        "-Os",
        "-fPIC",
        "-ffunction-sections",
        "-fdata-sections",
        "-fvisibility=hidden",
        f"-frandom-seed={source_hash}",
        "-nostdlib",
        "-nostartfiles",
        "-shared",
        "-Wl,--gc-sections",
        "-Wl,--build-id=none",
        "-Wl,--allow-shlib-undefined",
        "-Wl,-e,pulse_hx1_probe_entry",
        str(source),
        "-o",
        str(elf),
    ]
    environment = os.environ.copy()
    environment.update({"LC_ALL": "C", "LANG": "C", "SOURCE_DATE_EPOCH": "0"})
    process = subprocess.run(
        command,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    log_path.write_text(
        "$ " + " ".join(command) + "\n" + (process.stdout or ""), encoding="utf-8"
    )
    if process.returncode != 0:
        raise NativeBuildError(f"compiler exited with status {process.returncode}; see {log_path}")
    if not elf.is_file() or elf.stat().st_size == 0:
        raise NativeBuildError("compiler completed without a non-empty ELF")

    inspection = inspect_native_extension.inspect_elf(elf, target)
    inspection_path.write_text(
        json.dumps(inspection, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    report = {
        "schema": SCHEMA,
        "status": "PASS" if inspection["status"] == "PASS" else "FAIL",
        "target": target,
        "source": {"path": str(source), "sha256": source_hash, "size": source.stat().st_size},
        "compiler": {
            "path": str(compiler_path),
            "sha256": compiler_hash,
            "version": compiler_version,
            "machine": compiler_machine,
        },
        "environment": {"LANG": "C", "LC_ALL": "C", "SOURCE_DATE_EPOCH": "0"},
        "command": command,
        "artifacts": {
            "elf": {"path": elf.name, "sha256": _sha256(elf), "size": elf.stat().st_size},
            "inspection": {
                "path": inspection_path.name,
                "sha256": _sha256(inspection_path),
                "size": inspection_path.stat().st_size,
            },
            "build_log": {
                "path": log_path.name,
                "sha256": _sha256(log_path),
                "size": log_path.stat().st_size,
            },
        },
        "validation_errors": inspection["validation_errors"],
    }
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def _synthetic_metadata(target: str) -> bytes:
    architecture_id, soc_id = TARGET_IDENTITIES[target]
    return struct.pack(
        "<8sHHIHHIHHHH16sIIHHI4I4I8I32s32s",
        b"PULSEXT1",
        1,
        0,
        192,
        architecture_id,
        soc_id,
        0,
        1,
        0,
        1,
        0,
        SYNTHETIC_EXTENSION_ID,
        160,
        4,
        1,
        1,
        0,
        SYNTHETIC_EVENT_ID,
        0,
        0,
        0,
        SYNTHETIC_OPERATION_ID,
        0,
        0,
        0,
        1,
        4096,
        3072,
        4,
        64,
        64,
        32,
        32,
        bytes(32),
        bytes(32),
    )


def build_synthetic_extension(
    *, target: str, source: Path, out_dir: Path, compiler: Path | None = None
) -> dict[str, Any]:
    source = source.resolve()
    if not source.is_file():
        raise NativeBuildError(f"source file is missing: {source}")
    if not (NATIVE_SDK_INCLUDE / "pulse_extension.h").is_file():
        raise NativeBuildError("native extension ABI header is missing")
    output = _prepare_out(out_dir)
    compiler_path = _resolve_compiler(target, compiler)
    elf = output / f"synthetic-loopback-{target}.elf"
    inspection_path = output / "inspection.json"
    report_path = output / "build-report.json"
    log_path = output / "build.log"
    generated_header = output / "pulse_extension_generated.h"
    source_hash = _sha256(source)
    compiler_hash = _sha256(compiler_path)
    compiler_version = _run([str(compiler_path), "--version"]).splitlines()[0]
    compiler_machine = _run([str(compiler_path), "-dumpmachine"])
    metadata = _synthetic_metadata(target)
    metadata_digest = hashlib.sha256(metadata).digest()
    digest_bytes = ", ".join(f"0x{item:02x}" for item in metadata_digest)
    architecture_id, soc_id = TARGET_IDENTITIES[target]
    generated_header.write_text(
        "#pragma once\n"
        f"#define PULSE_EXTENSION_TARGET_ARCHITECTURE_ID {architecture_id}u\n"
        f"#define PULSE_EXTENSION_TARGET_SOC_ID {soc_id}u\n"
        f"#define PULSE_EXTENSION_METADATA_SHA256_BYTES {digest_bytes}\n",
        encoding="utf-8",
    )

    command = [
        str(compiler_path),
        "-std=c11",
        "-Os",
        "-fPIC",
        "-fno-common",
        "-fno-builtin",
        "-ffunction-sections",
        "-fdata-sections",
        "-fvisibility=hidden",
        f"-frandom-seed={source_hash}",
        "-nostdlib",
        "-nostartfiles",
        "-shared",
        f"-I{NATIVE_SDK_INCLUDE}",
        "-include",
        str(generated_header),
        "-Wl,--gc-sections",
        "-Wl,--build-id=none",
        "-Wl,--allow-shlib-undefined",
        "-Wl,-e,pulse_extension_entry_v1",
        str(source),
        "-o",
        str(elf),
    ]
    environment = os.environ.copy()
    environment.update({"LC_ALL": "C", "LANG": "C", "SOURCE_DATE_EPOCH": "0"})
    process = subprocess.run(
        command,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    log_path.write_text(
        "$ " + " ".join(command) + "\n" + (process.stdout or ""), encoding="utf-8"
    )
    if process.returncode != 0:
        raise NativeBuildError(f"compiler exited with status {process.returncode}; see {log_path}")
    if not elf.is_file() or elf.stat().st_size == 0:
        raise NativeBuildError("compiler completed without a non-empty ELF")

    preliminary = inspect_native_extension.inspect_elf(elf, target)
    observed_metadata = preliminary.get("metadata")
    if not isinstance(observed_metadata, dict):
        raise NativeBuildError("linked ELF does not contain readable extension metadata")
    metadata_offset = observed_metadata.get("file_offset")
    if not isinstance(metadata_offset, int):
        raise NativeBuildError("linked ELF metadata offset is unavailable")
    image = bytearray(elf.read_bytes())
    image[metadata_offset + 128 : metadata_offset + 160] = bytes(32)
    artifact_digest = hashlib.sha256(image).digest()
    image[metadata_offset + 128 : metadata_offset + 160] = artifact_digest
    elf.write_bytes(image)

    inspection = inspect_native_extension.inspect_elf(
        elf,
        target,
        require_extension=True,
        allowed_imports=SYNTHETIC_ALLOWED_IMPORTS,
    )
    observed_digest = inspection.get("metadata", {}).get("normalized_metadata_sha256")
    if observed_digest != metadata_digest.hex():
        raise NativeBuildError(
            "generated metadata digest does not match the admitted ELF metadata"
        )
    inspection_path.write_text(
        json.dumps(inspection, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    report = {
        "schema": SCHEMA,
        "kind": "synthetic-loopback",
        "status": "PASS" if inspection["status"] == "PASS" else "FAIL",
        "target": target,
        "source": {"path": str(source), "sha256": source_hash, "size": source.stat().st_size},
        "native_sdk": {
            "header": str(NATIVE_SDK_INCLUDE / "pulse_extension.h"),
            "sha256": _sha256(NATIVE_SDK_INCLUDE / "pulse_extension.h"),
        },
        "compiler": {
            "path": str(compiler_path),
            "sha256": compiler_hash,
            "version": compiler_version,
            "machine": compiler_machine,
        },
        "environment": {"LANG": "C", "LC_ALL": "C", "SOURCE_DATE_EPOCH": "0"},
        "command": command,
        "artifacts": {
            "elf": {"path": elf.name, "sha256": _sha256(elf), "size": elf.stat().st_size},
            "inspection": {
                "path": inspection_path.name,
                "sha256": _sha256(inspection_path),
                "size": inspection_path.stat().st_size,
            },
            "generated_header": {
                "path": generated_header.name,
                "sha256": _sha256(generated_header),
                "size": generated_header.stat().st_size,
            },
            "build_log": {
                "path": log_path.name,
                "sha256": _sha256(log_path),
                "size": log_path.stat().st_size,
            },
        },
        "normalized_metadata_sha256": metadata_digest.hex(),
        "normalized_artifact_sha256": artifact_digest.hex(),
        "target_refinement_imports": list(SYNTHETIC_ALLOWED_IMPORTS),
        "lifecycle_execution": "NOT_RUN_NO_TARGET_RUNTIME",
        "validation_errors": inspection["validation_errors"],
    }
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True, choices=tuple(COMPILERS))
    parser.add_argument("--kind", choices=("loader-probe", "synthetic-loopback"), default="loader-probe")
    parser.add_argument("--source", type=Path)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--compiler", type=Path)
    args = parser.parse_args(argv)
    try:
        source = args.source or (SYNTHETIC_SOURCE if args.kind == "synthetic-loopback" else DEFAULT_SOURCE)
        builder = build_synthetic_extension if args.kind == "synthetic-loopback" else build_probe
        report = builder(target=args.target, source=source, out_dir=args.out_dir, compiler=args.compiler)
    except (OSError, NativeBuildError, inspect_native_extension.ElfInspectionError) as exc:
        print(f"native extension build failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"status": report["status"], "out_dir": str(args.out_dir)}))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
