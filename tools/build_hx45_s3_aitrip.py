#!/usr/bin/env python3
"""Build the isolated HX4.5 image for the named AITRIP S3 N8R2 board."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

try:
    from tools import (
        build_native_extension,
        inspect_native_extension,
        verify_idf_environment,
    )
except ModuleNotFoundError:  # Direct execution from tools/.
    import build_native_extension  # type: ignore[no-redef]
    import inspect_native_extension  # type: ignore[no-redef]
    import verify_idf_environment  # type: ignore[no-redef]


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "tests/hardware-in-loop/hx45-s3-aitrip-n8r2"
DEFAULT_SEALED_NATIVE_ELF = (
    TEMPLATE / "fixtures/synthetic-loopback-esp32s3.elf"
)
MATRIX = ROOT / "firmware/idf-family-matrix.json"
LOCK = ROOT / "firmware/locks/host-extension/idf-5.4.4/esp32s3/dependencies.lock"
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
EXPECTED_HP41_FIRMWARE_SOURCE = {
    "sha256": "4f7b56a99adfedfa57c1d5179ad5ca03e6f57dd258a73fa3a6f71f747973253c",
    "file_count": 146,
}
EXPECTED_HP42_FIRMWARE_SOURCE = {
    "sha256": "77f4d2044776c6828e443486ee21199f95b4e1f34ae704c7323e901d51602eca",
    "file_count": 148,
}
EXPECTED_HP43_FIRMWARE_SOURCE = {
    "sha256": "d36978214d8e1d892961e7239facafa49eb1ed4150843dd1eeb23dec5d8ceb5f",
    "file_count": 150,
}
EXPECTED_HP44_FIRMWARE_SOURCE = {
    "sha256": "ff9f571860eda289cc276c6418f887b0af42552380c50f4038b5163ea929a386",
    "file_count": 150,
}
EXPECTED_HP5_FIRMWARE_SOURCE = {
    "sha256": "2e94b65a03a0612d4e770dc0f9b624dab874a75bf334bbd5173023427b7076a5",
    "file_count": 159,
}
EXPECTED_HP55_FIRMWARE_SOURCE = {
    "sha256": "d60e2669cd3b2dd5869e2305c92e39913b270ba9d54844d3a34d614681c5a98a",
    "file_count": 168,
}
HP41_MODEL = ROOT / "specs/PULSE-ESP32-010-protected-administration-core.json"
HP42_MODEL = ROOT / "specs/PULSE-ESP32-011-exclusive-update-transaction.json"
HP43_MODEL = ROOT / "specs/PULSE-ESP32-012-host-only-recovery.json"
HP44_MODEL = ROOT / "specs/PULSE-ESP32-013-administration-adversarial-seal.json"
HP5_MODEL = ROOT / "specs/PULSE-ESP32-014-host-network-mediator.json"
HP55_MODEL = ROOT / "specs/PULSE-ESP32-015-network-administration-physical-seal.json"
EXPECTED_NATIVE_SDK_SOURCE = {
    "sha256": "a7ceb397ab009950a1ebbdea60280f7944020a6523252b7de0d781e3e798bdd4",
    "file_count": 1,
}
EXPECTED_DEPENDENCY_LOCK_SHA256 = (
    "5c672b327f9f4fc8742ca78c5cdca76170cb78a18857e98b497ac0f0bbee0e4c"
)
COMMON_WASM = (
    ROOT
    / "firmware/components/wdc_runtime/test_vectors/wdc_hx4_event_effect_wasm.wasm"
)
PROJECT_NAME = "pulse_hx45_s3_aitrip_n8r2"
REPORT_SCHEMA = "pulse.esp32.hx45-s3-aitrip-build.v1"
APPLICATION_PARTITION_BYTES = 2 * 1024 * 1024
MINIMUM_LINK_DIRAM_REMAIN_BYTES = 1024
MINIMUM_LINK_IRAM_REMAIN_BYTES = 1
HIL_BUILD_HOST_PLATFORMS = (
    "linux/amd64",
    "darwin/amd64",
    "darwin/arm64",
)
# ZIP timestamps carry no timezone.  A snapshot produced in UTC and extracted
# west of UTC can otherwise make source files appear newer than CMake's freshly
# generated Ninja manifest.  Stage all build inputs with a fixed past mtime.
NORMALIZED_BUILD_INPUT_MTIME = 315532800  # 1980-01-01T00:00:00Z
HARNESS_SOURCE_PATHS = (
    "CMakeLists.txt",
    "main/CMakeLists.txt",
    "main/hx45_s3_aitrip_main.c",
    "partitions.csv",
    "sdkconfig.defaults",
)


class HardwareBuildError(RuntimeError):
    """Raised when a named-board image cannot be prepared exactly."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_evidence(path: Path, logical_path: str | None = None) -> dict[str, Any]:
    return {
        "path": logical_path or str(path),
        "sha256": sha256(path),
        "size": path.stat().st_size,
    }


def tree_evidence(root: Path, ignored: set[str]) -> dict[str, Any]:
    digest = hashlib.sha256()
    count = 0
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root)
        if any(part in ignored for part in relative.parts):
            continue
        digest.update(relative.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha256(path).encode("ascii"))
        digest.update(b"\n")
        count += 1
    return {"sha256": digest.hexdigest(), "file_count": count}


def validate_sealed_sources() -> dict[str, Any]:
    firmware = tree_evidence(
        ROOT / "firmware",
        {"build", "managed_components", "dependencies.lock", "sdkconfig", "__pycache__"},
    )
    native_sdk = tree_evidence(ROOT / "native-sdk", {"__pycache__"})
    successor: str | None = None
    if firmware != EXPECTED_FIRMWARE_SOURCE:
        if firmware not in (
            EXPECTED_HP41_FIRMWARE_SOURCE,
            EXPECTED_HP42_FIRMWARE_SOURCE,
            EXPECTED_HP43_FIRMWARE_SOURCE,
            EXPECTED_HP44_FIRMWARE_SOURCE,
            EXPECTED_HP5_FIRMWARE_SOURCE,
            EXPECTED_HP55_FIRMWARE_SOURCE,
        ) or not HP41_MODEL.is_file():
            raise HardwareBuildError(
                "firmware source is neither the HX4.5 campaign seal nor an exact HP4 successor"
            )
        try:
            hp41 = json.loads(HP41_MODEL.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise HardwareBuildError("cannot validate the HP4.1 source successor") from exc
        history = hp41.get("source_history", {})
        if (
            hp41.get("schema")
            != "pulse.esp32.hp4_1-protected-administration-core.v1"
            or hp41.get("pass") != "HP4.1"
            or hp41.get("status") != "IMPLEMENTED"
            or history.get("hp4_0_firmware_sha256")
            != EXPECTED_FIRMWARE_SOURCE["sha256"]
            or history.get("hp4_0_firmware_file_count")
            != EXPECTED_FIRMWARE_SOURCE["file_count"]
            or history.get("current_firmware_sha256")
            != EXPECTED_HP41_FIRMWARE_SOURCE["sha256"]
            or history.get("current_firmware_file_count")
            != EXPECTED_HP41_FIRMWARE_SOURCE["file_count"]
        ):
            raise HardwareBuildError("HP4.1 does not preserve the HX4.5 firmware history")
        if firmware == EXPECTED_HP41_FIRMWARE_SOURCE:
            successor = "HP4.1"
        else:
            if not HP42_MODEL.is_file():
                raise HardwareBuildError("the exact HP4.2 source successor is missing")
            try:
                hp42 = json.loads(HP42_MODEL.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise HardwareBuildError("cannot validate the HP4.2 source successor") from exc
            hp42_history = hp42.get("source_history", {})
            if (
                hp42.get("schema")
                != "pulse.esp32.hp4_2-exclusive-update-transaction.v1"
                or hp42.get("pass") != "HP4.2"
                or hp42.get("status") != "IMPLEMENTED"
                or hp42_history.get("hp4_1_firmware_sha256")
                != EXPECTED_HP41_FIRMWARE_SOURCE["sha256"]
                or hp42_history.get("hp4_1_firmware_file_count")
                != EXPECTED_HP41_FIRMWARE_SOURCE["file_count"]
                or hp42_history.get("current_firmware_sha256")
                != EXPECTED_HP42_FIRMWARE_SOURCE["sha256"]
                or hp42_history.get("current_firmware_file_count")
                != EXPECTED_HP42_FIRMWARE_SOURCE["file_count"]
            ):
                raise HardwareBuildError("HP4.2 does not preserve the HP4.1 source history")
            if firmware == EXPECTED_HP42_FIRMWARE_SOURCE:
                successor = "HP4.2"
            else:
                if not HP43_MODEL.is_file():
                    raise HardwareBuildError("the exact HP4.3 source successor is missing")
                try:
                    hp43 = json.loads(HP43_MODEL.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    raise HardwareBuildError("cannot validate the HP4.3 source successor") from exc
                hp43_history = hp43.get("source_history", {})
                if (
                    hp43.get("schema") !=
                        "pulse.esp32.hp4_3-host-only-recovery.v1"
                    or hp43.get("pass") != "HP4.3"
                    or hp43.get("status") != "IMPLEMENTED"
                    or hp43_history.get("hp4_2_firmware_sha256") !=
                        EXPECTED_HP42_FIRMWARE_SOURCE["sha256"]
                    or hp43_history.get("hp4_2_firmware_file_count") !=
                        EXPECTED_HP42_FIRMWARE_SOURCE["file_count"]
                    or hp43_history.get("current_firmware_sha256") !=
                        EXPECTED_HP43_FIRMWARE_SOURCE["sha256"]
                    or hp43_history.get("current_firmware_file_count") !=
                        EXPECTED_HP43_FIRMWARE_SOURCE["file_count"]
                ):
                    raise HardwareBuildError("HP4.3 does not preserve the HP4.2 source history")
                if firmware == EXPECTED_HP43_FIRMWARE_SOURCE:
                    successor = "HP4.3"
                else:
                    if not HP44_MODEL.is_file():
                        raise HardwareBuildError("the exact HP4.4 source successor is missing")
                    try:
                        hp44 = json.loads(HP44_MODEL.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError) as exc:
                        raise HardwareBuildError("cannot validate the HP4.4 source successor") from exc
                    hp44_history = hp44.get("source_history", {})
                    if (
                        hp44.get("schema")
                        != "pulse.esp32.hp4_4-administration-adversarial-seal.v1"
                        or hp44.get("pass") != "HP4.4"
                        or hp44.get("status") != "SEALED"
                        or hp44_history.get("hp4_3_firmware_sha256")
                        != EXPECTED_HP43_FIRMWARE_SOURCE["sha256"]
                        or hp44_history.get("hp4_3_firmware_file_count")
                        != EXPECTED_HP43_FIRMWARE_SOURCE["file_count"]
                        or hp44_history.get("current_firmware_sha256")
                        != EXPECTED_HP44_FIRMWARE_SOURCE["sha256"]
                        or hp44_history.get("current_firmware_file_count")
                        != EXPECTED_HP44_FIRMWARE_SOURCE["file_count"]
                    ):
                        raise HardwareBuildError("HP4.4 does not preserve the HP4.3 source history")
                    if firmware == EXPECTED_HP44_FIRMWARE_SOURCE:
                        successor = "HP4.4"
                    elif HP5_MODEL.is_file():
                        try:
                            hp5 = json.loads(HP5_MODEL.read_text(encoding="utf-8"))
                        except (OSError, json.JSONDecodeError) as exc:
                            raise HardwareBuildError("cannot validate the HP5 source successor") from exc
                        hp5_history = hp5.get("source_history", {})
                        if (
                            hp5.get("schema") != "pulse.esp32.hp5-host-network-mediator.v1"
                            or hp5.get("pass") != "HP5"
                            or hp5.get("status") != "QUALIFIED"
                            or hp5_history.get("hp4_4_firmware_sha256")
                            != EXPECTED_HP44_FIRMWARE_SOURCE["sha256"]
                            or hp5_history.get("hp4_4_firmware_file_count")
                            != EXPECTED_HP44_FIRMWARE_SOURCE["file_count"]
                            or hp5_history.get("current_firmware_sha256")
                            != EXPECTED_HP5_FIRMWARE_SOURCE["sha256"]
                            or hp5_history.get("current_firmware_file_count")
                            != EXPECTED_HP5_FIRMWARE_SOURCE["file_count"]
                        ):
                            raise HardwareBuildError("HP5 does not preserve the HP4.4 source history")
                        if firmware == EXPECTED_HP5_FIRMWARE_SOURCE:
                            successor = "HP5"
                        elif HP55_MODEL.is_file():
                            try:
                                hp55 = json.loads(HP55_MODEL.read_text(encoding="utf-8"))
                            except (OSError, json.JSONDecodeError) as exc:
                                raise HardwareBuildError("cannot validate the HP5.5 source successor") from exc
                            hp55_history = hp55.get("source_history", {})
                            if (
                                hp55.get("schema") != "pulse.esp32.hp5_5-network-administration-physical-seal.v1"
                                or hp55.get("pass") != "HP5.5"
                                or hp55.get("status") != "READY_FOR_PHYSICAL_EXECUTION"
                                or hp55.get("aggregate") != "HARDWARE_PENDING"
                                or hp55_history.get("hp5_firmware_sha256") != EXPECTED_HP5_FIRMWARE_SOURCE["sha256"]
                                or hp55_history.get("hp5_firmware_file_count") != EXPECTED_HP5_FIRMWARE_SOURCE["file_count"]
                                or hp55_history.get("current_firmware_sha256") != EXPECTED_HP55_FIRMWARE_SOURCE["sha256"]
                                or hp55_history.get("current_firmware_file_count") != EXPECTED_HP55_FIRMWARE_SOURCE["file_count"]
                            ):
                                raise HardwareBuildError("HP5.5 does not preserve the HP5 source history")
                            successor = "HP5.5"
                        else:
                            raise HardwareBuildError("the exact HP5.5 source successor is missing")
                    else:
                        raise HardwareBuildError("the exact HP5 source successor is missing")
    if native_sdk != EXPECTED_NATIVE_SDK_SOURCE:
        raise HardwareBuildError("native SDK source no longer matches the HX4.5 seal")
    if sha256(LOCK) != EXPECTED_DEPENDENCY_LOCK_SHA256:
        raise HardwareBuildError("S3 dependency lock no longer matches the HX4.5 seal")
    return {
        "firmware": firmware,
        "native_sdk": native_sdk,
        "historical_campaign_firmware": EXPECTED_FIRMWARE_SOURCE,
        "current_successor": successor,
    }


def validate_sdkconfig(path: Path) -> None:
    settings: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("CONFIG_") and "=" in line:
            key, value = line.split("=", 1)
            settings[key] = value
    required = {
        "CONFIG_IDF_TARGET": '"esp32s3"',
        "CONFIG_IDF_TARGET_ESP32S3": "y",
        "CONFIG_PARTITION_TABLE_CUSTOM": "y",
        "CONFIG_PARTITION_TABLE_CUSTOM_FILENAME": '"partitions.csv"',
        "CONFIG_ESPTOOLPY_FLASHSIZE_8MB": "y",
        "CONFIG_SPIRAM": "y",
        "CONFIG_SPIRAM_MODE_QUAD": "y",
        "CONFIG_SPIRAM_SPEED_40M": "y",
        "CONFIG_SPIRAM_USE_MALLOC": "y",
        "CONFIG_SPIRAM_MALLOC_ALWAYSINTERNAL": "4096",
        "CONFIG_SPIRAM_MALLOC_RESERVE_INTERNAL": "32768",
        "CONFIG_ELF_LOADER": "y",
        "CONFIG_ELF_LOADER_LOAD_PSRAM": "y",
        "CONFIG_ELF_LOADER_CACHE_OFFSET": "y",
        "CONFIG_FREERTOS_SUPPORT_STATIC_ALLOCATION": "y",
        "CONFIG_FREERTOS_TLSP_DELETION_CALLBACKS": "y",
        "CONFIG_FREERTOS_THREAD_LOCAL_STORAGE_POINTERS": "1",
        "CONFIG_FREERTOS_CHECK_STACKOVERFLOW_CANARY": "y",
        "CONFIG_ESP_MAIN_TASK_STACK_SIZE": "16384",
    }
    mismatches = [
        f"{key}={settings.get(key)!r}, expected {value!r}"
        for key, value in required.items()
        if settings.get(key) != value
    ]
    forbidden = (
        "CONFIG_ESPTOOLPY_FLASHSIZE_16MB",
        "CONFIG_SPIRAM_MODE_OCT",
        "CONFIG_ELF_DYNAMIC_LOAD_SHARED_OBJECT",
        "CONFIG_ELF_LOADER_LIBC_SYMBOLS",
        "CONFIG_ELF_LOADER_ESPIDF_SYMBOLS",
        "CONFIG_ELF_LOADER_CUSTOMER_SYMBOLS",
    )
    mismatches.extend(
        f"{key} must remain disabled" for key in forbidden if settings.get(key) == "y"
    )
    if mismatches:
        raise HardwareBuildError("invalid generated AITRIP sdkconfig: " + "; ".join(mismatches))


def prepare_output(path: Path) -> Path:
    output = path.expanduser().resolve()
    try:
        output.relative_to(TEMPLATE.resolve())
    except ValueError:
        pass
    else:
        raise HardwareBuildError("output directory may not be inside the HIL template")
    if output.exists():
        if not output.is_dir() or any(output.iterdir()):
            raise HardwareBuildError(
                "output directory must be absent or empty; choose a fresh "
                "RUN_DIR suffix and do not create it before running make"
            )
    else:
        output.mkdir(parents=True)
    return output


def render_blob_source(data: bytes, digest: str) -> str:
    if hashlib.sha256(data).hexdigest() != digest:
        raise HardwareBuildError("extension bytes do not match the supplied digest")
    token = int.from_bytes(bytes.fromhex(digest)[:4], "little")
    rows = []
    for offset in range(0, len(data), 12):
        chunk = data[offset : offset + 12]
        rows.append("    " + ", ".join(f"0x{value:02x}" for value in chunk) + ",")
    return (
        "#include <stdint.h>\n\n"
        "const uint8_t pulse_hx45_extension_elf[] "
        "__attribute__((aligned(4))) = {\n"
        + "\n".join(rows)
        + "\n};\n"
        + f"const uint32_t pulse_hx45_extension_elf_len = {len(data)}u;\n"
        + f"const uint32_t pulse_hx45_extension_build_token = 0x{token:08x}u;\n"
        + f'const char pulse_hx45_extension_sha256[] = "{digest}";\n'
        + f'const char pulse_hx45_common_wasm_sha256[] = "{EXPECTED_COMMON_WASM_SHA256}";\n'
    )


def validate_sealed_native_elf(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise HardwareBuildError(f"sealed native ELF is missing: {path}")
    observed = sha256(path)
    if observed != EXPECTED_NATIVE_ELF_SHA256:
        raise HardwareBuildError(
            f"native ELF digest is {observed}, expected {EXPECTED_NATIVE_ELF_SHA256}"
        )
    inspection = inspect_native_extension.inspect_elf(
        path,
        "esp32s3",
        require_extension=True,
        allowed_imports=build_native_extension.SYNTHETIC_ALLOWED_IMPORTS,
    )
    if inspection["status"] != "PASS":
        raise HardwareBuildError(
            "sealed native ELF failed inspection: "
            + "; ".join(inspection["validation_errors"])
        )
    return inspection


def prepare_native_elf(
    output: Path, sealed_native_elf: Path | None
) -> tuple[Path, dict[str, Any]]:
    native_dir = output / "native-extension"
    if sealed_native_elf is None:
        report = build_native_extension.build_synthetic_extension(
            target="esp32s3",
            source=build_native_extension.SYNTHETIC_SOURCE,
            out_dir=native_dir,
        )
        elf = native_dir / "synthetic-loopback-esp32s3.elf"
        if report["status"] != "PASS":
            raise HardwareBuildError("native extension build did not pass")
        if sha256(elf) != EXPECTED_NATIVE_ELF_SHA256:
            raise HardwareBuildError(
                "fresh native extension does not reproduce the HX4.5-sealed ELF"
            )
        return elf, report

    native_dir.mkdir()
    elf = native_dir / "synthetic-loopback-esp32s3.elf"
    shutil.copy2(sealed_native_elf.resolve(), elf)
    inspection = validate_sealed_native_elf(elf)
    inspection_path = native_dir / "inspection.json"
    inspection_path.write_text(
        json.dumps(inspection, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    report = {
        "schema": "pulse.esp32.native-extension-build.v1",
        "kind": "synthetic-loopback",
        "status": "PASS",
        "target": "esp32s3",
        "source": "HX4.5_SEALED_ARTIFACT",
        "artifacts": {
            "elf": file_evidence(elf, elf.name),
            "inspection": file_evidence(inspection_path, inspection_path.name),
        },
        "validation_errors": [],
    }
    report_path = native_dir / "build-report.json"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return elf, report


def normalize_tree_mtime(root: Path) -> None:
    for path in sorted(root.rglob("*"), reverse=True):
        os.utime(path, (NORMALIZED_BUILD_INPUT_MTIME,) * 2)
    os.utime(root, (NORMALIZED_BUILD_INPUT_MTIME,) * 2)


def stage_project(output: Path, elf: Path) -> tuple[Path, Path]:
    project = output / "project"
    shutil.copytree(TEMPLATE, project)
    shutil.copy2(LOCK, project / "dependencies.lock")
    digest = sha256(elf)
    blob = render_blob_source(elf.read_bytes(), digest)
    (project / "main/hx45_extension_blob.c").write_text(blob, encoding="utf-8")
    inputs = output / "inputs"
    inputs.mkdir()
    shutil.copy2(COMMON_WASM, inputs / COMMON_WASM.name)

    # Build from sealed copies rather than the extracted repository tree.  In
    # addition to making the retained run self-contained, this prevents a
    # timezone-shifted archive mtime from forcing Ninja to re-run CMake forever.
    staged_repository = output / "source"
    shutil.copytree(
        ROOT / "firmware/components",
        staged_repository / "firmware/components",
    )
    shutil.copytree(ROOT / "native-sdk", staged_repository / "native-sdk")
    normalize_tree_mtime(project)
    normalize_tree_mtime(staged_repository)
    return project, staged_repository


def harness_source_evidence(project: Path, output: Path) -> dict[str, dict[str, Any]]:
    evidence: dict[str, dict[str, Any]] = {}
    for relative in HARNESS_SOURCE_PATHS:
        staged = project / relative
        template = TEMPLATE / relative
        if sha256(staged) != sha256(template):
            raise HardwareBuildError(f"staged harness source changed: {relative}")
        evidence[relative] = file_evidence(
            staged, str(staged.relative_to(output))
        )
    return evidence


def run_command(
    command: list[str],
    *,
    cwd: Path,
    environment: dict[str, str],
    timeout: int,
) -> str:
    process = subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )
    if process.returncode != 0:
        raise HardwareBuildError(
            f"command exited with status {process.returncode}: {' '.join(command)}\n"
            + process.stdout
        )
    return process.stdout


def last_json_object(output: str) -> dict[str, Any]:
    """Return the last complete JSON object emitted by an IDF command."""
    decoder = json.JSONDecoder()
    candidates: list[tuple[int, int, dict[str, Any]]] = []
    for index, character in enumerate(output):
        if character != "{":
            continue
        try:
            value, end = decoder.raw_decode(output[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            candidates.append((index + end, -index, value))
    if not candidates:
        raise HardwareBuildError("IDF size output did not contain a JSON object")
    return max(candidates)[2]


def build_firmware(
    output: Path,
    project: Path,
    staged_repository: Path,
    *,
    idf_path: Path | None,
    idf_py: Path | None,
    timeout: int,
    hx5b_pressure: bool = False,
) -> tuple[dict[str, Any], str]:
    environment_evidence = verify_idf_environment.verify_idf_environment(
        MATRIX,
        idf_path=idf_path,
        idf_py=idf_py,
        allowed_platforms=HIL_BUILD_HOST_PLATFORMS,
    )
    environment_evidence["platform_scope"] = "NAMED_BOARD_HIL_BUILD"
    resolved_idf_py = Path(environment_evidence["idf_py"])
    build = output / "build"
    sdkconfig = output / "sdkconfig"
    defaults = project / "sdkconfig.defaults"
    definitions = [
        "-B",
        str(build),
        "-DIDF_TARGET=esp32s3",
        f"-DSDKCONFIG={sdkconfig}",
        f"-DSDKCONFIG_DEFAULTS={defaults}",
        f"-DPULSE_REPO_ROOT={staged_repository}",
    ]
    if hx5b_pressure:
        definitions.append("-DPULSE_HX5B_PRESSURE=ON")
    commands = [
        [str(resolved_idf_py), *definitions, "reconfigure"],
        [str(resolved_idf_py), *definitions, "build"],
        [str(resolved_idf_py), "-B", str(build), "size", "--format", "json"],
    ]
    process_environment = os.environ.copy()
    process_environment.update(
        {
            "IDF_PATH": environment_evidence["idf_path"],
            "IDF_TARGET": "esp32s3",
            "IDF_CCACHE_ENABLE": "0",
            "LANG": "C",
            "LC_ALL": "C",
            "SOURCE_DATE_EPOCH": "0",
        }
    )
    logs: list[str] = []
    outputs: list[str] = []
    for label, command in zip(("reconfigure", "build", "size"), commands):
        result = run_command(
            command,
            cwd=project,
            environment=process_environment,
            timeout=timeout,
        )
        outputs.append(result)
        logs.append(f"=== {label} ===\n$ {' '.join(command)}\n{result.rstrip()}\n")
        if sha256(project / "dependencies.lock") != sha256(LOCK):
            raise HardwareBuildError(f"{label} mutated the pinned dependency lock")
    validate_sdkconfig(sdkconfig)
    harness_source_evidence(project, output)

    artifacts = {
        "application_elf": build / f"{PROJECT_NAME}.elf",
        "application_binary": build / f"{PROJECT_NAME}.bin",
        "application_map": build / f"{PROJECT_NAME}.map",
        "bootloader_binary": build / "bootloader/bootloader.bin",
        "partition_table_binary": build / "partition_table/partition-table.bin",
        "flasher_args": build / "flasher_args.json",
        "flash_args": build / "flash_args",
    }
    missing = [name for name, path in artifacts.items() if not path.is_file()]
    if missing:
        raise HardwareBuildError(
            "firmware build omitted required artifacts: " + ", ".join(missing)
        )
    size = last_json_object(outputs[-1])
    diram_remain = size.get("diram_remain")
    iram_remain = size.get("iram_remain")
    application_size = artifacts["application_binary"].stat().st_size
    if (
        not isinstance(diram_remain, int)
        or diram_remain < MINIMUM_LINK_DIRAM_REMAIN_BYTES
    ):
        raise HardwareBuildError("firmware link has inadequate remaining internal RAM")
    if (
        not isinstance(iram_remain, int)
        or iram_remain < MINIMUM_LINK_IRAM_REMAIN_BYTES
    ):
        raise HardwareBuildError("firmware link has no remaining dedicated IRAM")
    if application_size > APPLICATION_PARTITION_BYTES:
        raise HardwareBuildError("firmware binary exceeds the isolated 2 MB app partition")
    firmware = {
        "status": "PASS",
        "result": "BUILD_PROVEN",
        "environment": environment_evidence,
        "commands": commands,
        "sdkconfig": file_evidence(sdkconfig, "sdkconfig"),
        "dependency_lock": file_evidence(
            project / "dependencies.lock", "project/dependencies.lock"
        ),
        "size": size,
        "headroom_gate": {
            "status": "PASS",
            "minimum_diram_remain_bytes": MINIMUM_LINK_DIRAM_REMAIN_BYTES,
            "observed_diram_remain_bytes": diram_remain,
            "minimum_iram_remain_bytes": MINIMUM_LINK_IRAM_REMAIN_BYTES,
            "observed_iram_remain_bytes": iram_remain,
            "application_partition_bytes": APPLICATION_PARTITION_BYTES,
            "application_binary_bytes": application_size,
        },
        "artifacts": {
            name: file_evidence(path, str(path.relative_to(output)))
            for name, path in artifacts.items()
        },
    }
    return firmware, "\n".join(logs)


def qualify_build(
    *,
    out_dir: Path,
    sealed_native_elf: Path | None,
    prepare_only: bool,
    idf_path: Path | None,
    idf_py: Path | None,
    timeout: int,
    hx5b_pressure: bool = False,
) -> dict[str, Any]:
    output = prepare_output(out_dir)
    if not TEMPLATE.is_dir() or not LOCK.is_file() or not COMMON_WASM.is_file():
        raise HardwareBuildError("AITRIP template, component lock, or common Wasm is missing")
    if sha256(COMMON_WASM) != EXPECTED_COMMON_WASM_SHA256:
        raise HardwareBuildError("common HX4 Wasm no longer matches the HX4.5 seal")
    sealed_sources = validate_sealed_sources()
    native_elf, native_report = prepare_native_elf(output, sealed_native_elf)
    project, staged_repository = stage_project(output, native_elf)
    report: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "status": "PREPARED" if prepare_only else "FAIL",
        "campaign": "HX5b" if hx5b_pressure else "HX4.5",
        "board": {
            "manufacturer": "AITRIP",
            "model": "ESP32-S3-DevKitC-1 N8R2",
            "module": "ESP32-S3-WROOM-1-N8R2",
            "target": "esp32s3",
            "flash_bytes": 8 * 1024 * 1024,
            "psram_bytes": 2 * 1024 * 1024,
            "psram_mode": "quad",
        },
        "claim_boundary": {
            "build": "NOT_RUN" if prepare_only else "BUILD_PROVEN",
            "runtime": "HARDWARE_NOT_RUN",
            "canonical_16mb_reference_unchanged": True,
        },
        "pressure_contract": (
            {
                "status": "BUILD_CONFIGURED",
                "queue_rounds": 8,
                "accepted_events": 128,
                "queue_capacity": 16,
                "effect_timeout_ms": 1000,
                "runtime": "HARDWARE_NOT_RUN",
            }
            if hx5b_pressure
            else {"status": "NOT_REQUESTED"}
        ),
        "sealed_sources": sealed_sources,
        "native_extension": {
            "elf": file_evidence(native_elf, "native-extension/synthetic-loopback-esp32s3.elf"),
            "report_status": native_report["status"],
        },
        "common_wasm": file_evidence(
            output / "inputs" / COMMON_WASM.name,
            f"inputs/{COMMON_WASM.name}",
        ),
        "harness_sources": harness_source_evidence(project, output),
        "generated_sources": {
            "extension_blob": file_evidence(
                project / "main/hx45_extension_blob.c",
                "project/main/hx45_extension_blob.c",
            )
        },
        "staged_project": str(project),
        "staged_repository": str(staged_repository),
        "flash_command": (
            f"cd {project} && idf.py -B {output / 'build'} -p <PORT> flash monitor"
        ),
    }
    if not prepare_only:
        firmware, log = build_firmware(
            output,
            project,
            staged_repository,
            idf_path=idf_path,
            idf_py=idf_py,
            timeout=timeout,
            hx5b_pressure=hx5b_pressure,
        )
        log_path = output / "build.log"
        log_path.write_text(log, encoding="utf-8")
        firmware["build_log"] = file_evidence(log_path, "build.log")
        report["firmware"] = firmware
        report["status"] = "PASS"
    report_path = output / "build-report.json"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, required=True)
    native_source = parser.add_mutually_exclusive_group()
    native_source.add_argument(
        "--sealed-native-elf",
        type=Path,
        default=DEFAULT_SEALED_NATIVE_ELF,
        help="Use only the exact HX4.5-sealed S3 ELF instead of rebuilding it",
    )
    native_source.add_argument(
        "--rebuild-native-elf",
        action="store_true",
        help="Explicitly rebuild and reproduce the sealed ELF instead of using the fixture",
    )
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--idf-path", type=Path)
    parser.add_argument("--idf-py", type=Path)
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument(
        "--hx5b-pressure",
        action="store_true",
        help="Enable the opt-in HX5b 128-roundtrip target pressure campaign",
    )
    args = parser.parse_args(argv)
    try:
        report = qualify_build(
            out_dir=args.out_dir,
            sealed_native_elf=(
                None if args.rebuild_native_elf else args.sealed_native_elf
            ),
            prepare_only=args.prepare_only,
            idf_path=args.idf_path,
            idf_py=args.idf_py,
            timeout=args.timeout,
            hx5b_pressure=args.hx5b_pressure,
        )
    except (
        OSError,
        ValueError,
        json.JSONDecodeError,
        subprocess.TimeoutExpired,
        HardwareBuildError,
        build_native_extension.NativeBuildError,
        inspect_native_extension.ElfInspectionError,
        verify_idf_environment.IDFEnvironmentError,
    ) as exc:
        print(f"AITRIP HX4.5 build failed: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "status": report["status"],
                "out_dir": str(args.out_dir.resolve()),
                "runtime": "HARDWARE_NOT_RUN",
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
