#!/usr/bin/env python3
"""Build the sealed HP3.5 application-slot campaign for one named board."""
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
    from tools import verify_idf_environment
except ModuleNotFoundError:  # Direct execution from tools/.
    import verify_idf_environment  # type: ignore[no-redef]


ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN = ROOT / "tests/hardware-in-loop/hp3_5-slot-power-loss/campaign.json"
TEMPLATE = ROOT / "tests/hardware-in-loop/hp3_5-slot-power-loss/firmware"
BUNDLE = ROOT / "examples/bundles/relay-controller/dist/relay-controller-r8.wdcb"
MATRIX = ROOT / "firmware/idf-family-matrix.json"
PROJECT_NAME = "pulse_hp3_5_slot_hardware"
REPORT_SCHEMA = "pulse.esp32.hp3_5-slot-hardware-build.v1"
EXPECTED_CAMPAIGN_SHA256 = (
    "b482f49a4d50312ba9efcf78d2d0a10495a67cd9e621f8662abed84fc3e2e3d3"
)
EXPECTED_BUNDLE_SHA256 = (
    "f7e9a32838448b7bc7b5ba11e619b903f1ce9c1822376efd6adbaecba3c9813e"
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
NORMALIZED_BUILD_INPUT_MTIME = 315532800
HIL_BUILD_HOST_PLATFORMS = (
    "linux/amd64",
    "darwin/amd64",
    "darwin/arm64",
)

BOARD_CONFIGS: dict[str, dict[str, Any]] = {
    "aitrip-esp32s3-devkitc-1-n8r2": {
        "target": "esp32s3",
        "flash_bytes": 8 * 1024 * 1024,
        "psram_bytes": 2 * 1024 * 1024,
        "sdkconfig": "sdkconfig.s3.defaults",
        "board": "firmware/boards/aitrip-esp32s3-devkitc-1-n8r2/board.json",
        "partitions": "firmware/boards/aitrip-esp32s3-devkitc-1-n8r2/partitions.csv",
        "lock": "firmware/locks/host-extension/idf-5.4.4/esp32s3/dependencies.lock",
        "lock_sha256": "5c672b327f9f4fc8742ca78c5cdca76170cb78a18857e98b497ac0f0bbee0e4c",
        "minimum_diram_remain_bytes": 1024,
    },
    "seeed-xiao-esp32c6-4m": {
        "target": "esp32c6",
        "flash_bytes": 4 * 1024 * 1024,
        "psram_bytes": 0,
        "sdkconfig": "sdkconfig.c6.defaults",
        "board": "firmware/boards/seeed-xiao-esp32c6-4m/board.json",
        "partitions": "firmware/boards/seeed-xiao-esp32c6-4m/partitions.csv",
        "lock": "firmware/locks/host-extension/idf-5.4.4/esp32c6/dependencies.lock",
        "lock_sha256": "edfeaa76d16c1eb9e8f60e46e0a342af41bf238b1b1226a7c0c0b541f35e228a",
        "minimum_diram_remain_bytes": 64 * 1024,
    },
}

STATIC_HARNESS_PATHS = (
    "CMakeLists.txt",
    "main/CMakeLists.txt",
    "main/hp3_5_slot_hardware_main.c",
    "sdkconfig.s3.defaults",
    "sdkconfig.c6.defaults",
)


class HardwareBuildError(RuntimeError):
    """Raised when an HP3.5 named-board image cannot be prepared exactly."""


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


def tree_evidence(root: Path, ignored: set[str] | None = None) -> dict[str, Any]:
    digest = hashlib.sha256()
    count = 0
    ignored = ignored or set()
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


def normalize_tree_mtime(root: Path) -> None:
    for path in sorted(root.rglob("*"), reverse=True):
        os.utime(path, (NORMALIZED_BUILD_INPUT_MTIME,) * 2)
    os.utime(root, (NORMALIZED_BUILD_INPUT_MTIME,) * 2)


def load_campaign() -> tuple[dict[str, Any], str]:
    observed = sha256(CAMPAIGN)
    if observed != EXPECTED_CAMPAIGN_SHA256:
        raise HardwareBuildError(
            f"HP3.5 campaign hash is {observed}, expected {EXPECTED_CAMPAIGN_SHA256}"
        )
    campaign = json.loads(CAMPAIGN.read_text(encoding="utf-8"))
    if (
        campaign.get("schema")
        != "pulse.esp32.hp3_5-slot-hardware-campaign.v1"
        or campaign.get("campaign_id") != "hp3_5-safe-inactive-slot-v1"
        or campaign.get("status") != "FROZEN"
        or campaign.get("execution_status") != "NOT_RUN"
    ):
        raise HardwareBuildError("HP3.5 campaign identity or frozen status drifted")
    checkpoints = campaign.get("checkpoints")
    if not isinstance(checkpoints, list) or len(checkpoints) != 13:
        raise HardwareBuildError("HP3.5 campaign must retain exactly 13 checkpoints")
    return campaign, observed


def validate_inputs(
    board_id: str,
) -> tuple[dict[str, Any], dict[str, Any], str, dict[str, Any]]:
    campaign, campaign_sha = load_campaign()
    config = BOARD_CONFIGS[board_id]
    lanes = {
        lane.get("board_id"): lane
        for lane in campaign.get("board_lanes", [])
        if isinstance(lane, dict)
    }
    lane = lanes.get(board_id)
    if lane is None:
        raise HardwareBuildError(f"campaign omits named board lane: {board_id}")
    board_path = ROOT / config["board"]
    partitions_path = ROOT / config["partitions"]
    lock_path = ROOT / config["lock"]
    if (
        sha256(board_path) != lane.get("board_sha256")
        or sha256(partitions_path) != lane.get("partitions_sha256")
    ):
        raise HardwareBuildError("canonical board identity or partition table drifted")
    if sha256(lock_path) != config["lock_sha256"]:
        raise HardwareBuildError("IDF dependency lock drifted")
    if sha256(BUNDLE) != EXPECTED_BUNDLE_SHA256:
        raise HardwareBuildError("embedded HP3 application bundle drifted")
    firmware = tree_evidence(
        ROOT / "firmware",
        {"build", "managed_components", "dependencies.lock", "sdkconfig", "__pycache__"},
    )
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
                "firmware source is neither the HP3.5 seal nor an exact HP4 successor"
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
            raise HardwareBuildError("HP4.1 does not preserve the HP3.5 firmware history")
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
                                raise HardwareBuildError(
                                    "cannot validate the HP5.5 source successor"
                                ) from exc
                            hp55_history = hp55.get("source_history", {})
                            if (
                                hp55.get("schema") !=
                                    "pulse.esp32.hp5_5-network-administration-physical-seal.v1"
                                or hp55.get("pass") != "HP5.5"
                                or hp55.get("status") != "READY_FOR_PHYSICAL_EXECUTION"
                                or hp55.get("aggregate") != "HARDWARE_PENDING"
                                or hp55_history.get("hp5_firmware_sha256") !=
                                    EXPECTED_HP5_FIRMWARE_SOURCE["sha256"]
                                or hp55_history.get("hp5_firmware_file_count") !=
                                    EXPECTED_HP5_FIRMWARE_SOURCE["file_count"]
                                or hp55_history.get("current_firmware_sha256") !=
                                    EXPECTED_HP55_FIRMWARE_SOURCE["sha256"]
                                or hp55_history.get("current_firmware_file_count") !=
                                    EXPECTED_HP55_FIRMWARE_SOURCE["file_count"]
                            ):
                                raise HardwareBuildError(
                                    "HP5.5 does not preserve the HP5 source history"
                                )
                            successor = "HP5.5"
                        else:
                            raise HardwareBuildError(
                                "the exact HP5.5 source successor is missing"
                            )
                    else:
                        raise HardwareBuildError("the exact HP5 source successor is missing")
    native_sdk = tree_evidence(ROOT / "native-sdk", {"__pycache__"})
    if native_sdk != EXPECTED_NATIVE_SDK_SOURCE:
        raise HardwareBuildError("native SDK source no longer matches the HP3.5 source seal")
    for field in ("target", "flash_bytes", "psram_bytes"):
        if lane.get(field) != config[field]:
            raise HardwareBuildError(f"campaign board lane drifted: {field}")
    return campaign, lane, campaign_sha, {
        "firmware": firmware,
        "native_sdk": native_sdk,
        "historical_campaign_firmware": EXPECTED_FIRMWARE_SOURCE,
        "current_successor": successor,
    }


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
                "output directory must be absent or empty; use a fresh run directory"
            )
    else:
        output.mkdir(parents=True)
    return output


def render_bundle_source(data: bytes) -> str:
    if hashlib.sha256(data).hexdigest() != EXPECTED_BUNDLE_SHA256:
        raise HardwareBuildError("bundle bytes do not match the HP3.5 seal")
    rows = []
    for offset in range(0, len(data), 12):
        rows.append(
            "    " + ", ".join(f"0x{value:02x}" for value in data[offset : offset + 12]) + ","
        )
    return (
        "#include <stdint.h>\n\n"
        "const uint8_t pulse_hp35_bundle[] __attribute__((aligned(4))) = {\n"
        + "\n".join(rows)
        + "\n};\n"
        + f"const uint32_t pulse_hp35_bundle_len = {len(data)}u;\n"
    )


def render_campaign_header(
    campaign: dict[str, Any], lane: dict[str, Any], campaign_sha: str
) -> str:
    return (
        "#pragma once\n\n"
        f'#define HP35_CAMPAIGN_ID "{campaign["campaign_id"]}"\n'
        f'#define HP35_CAMPAIGN_SHA256 "{campaign_sha}"\n'
        f'#define HP35_BOARD_ID "{lane["board_id"]}"\n'
        f'#define HP35_TARGET "{lane["target"]}"\n'
        f"#define HP35_FLASH_BYTES {lane['flash_bytes']}u\n"
        f"#define HP35_PSRAM_BYTES {lane['psram_bytes']}u\n"
        f'#define HP35_PARTITION_SHA256 "{lane["partitions_sha256"]}"\n'
        f'#define HP35_BUNDLE_SHA256 "{EXPECTED_BUNDLE_SHA256}"\n'
    )


def stage_project(
    output: Path,
    board_id: str,
    campaign: dict[str, Any],
    lane: dict[str, Any],
    campaign_sha: str,
) -> tuple[Path, Path]:
    config = BOARD_CONFIGS[board_id]
    project = output / "project"
    shutil.copytree(TEMPLATE, project)
    shutil.copy2(ROOT / config["partitions"], project / "partitions.csv")
    shutil.copy2(ROOT / config["lock"], project / "dependencies.lock")
    shutil.copy2(project / config["sdkconfig"], project / "sdkconfig.defaults")
    (project / "main/hp3_5_bundle_blob.c").write_text(
        render_bundle_source(BUNDLE.read_bytes()), encoding="utf-8"
    )
    (project / "main/hp3_5_campaign_config.h").write_text(
        render_campaign_header(campaign, lane, campaign_sha), encoding="utf-8"
    )
    inputs = output / "inputs"
    inputs.mkdir()
    shutil.copy2(CAMPAIGN, inputs / "campaign.json")
    shutil.copy2(ROOT / config["board"], inputs / "board.json")
    shutil.copy2(ROOT / config["partitions"], inputs / "partitions.csv")
    shutil.copy2(BUNDLE, inputs / BUNDLE.name)
    staged_repository = output / "source"
    shutil.copytree(
        ROOT / "firmware/components",
        staged_repository / "firmware/components",
    )
    # ESP-IDF discovers every component beneath EXTRA_COMPONENT_DIRS while it
    # constructs the component graph. wdc_extension therefore validates its
    # public native-SDK include directory even though this campaign does not
    # link the native extension runtime.
    shutil.copytree(ROOT / "native-sdk", staged_repository / "native-sdk")
    normalize_tree_mtime(project)
    normalize_tree_mtime(staged_repository)
    return project, staged_repository


def harness_source_evidence(project: Path, output: Path) -> dict[str, Any]:
    files: dict[str, dict[str, Any]] = {}
    for relative in STATIC_HARNESS_PATHS:
        staged = project / relative
        template = TEMPLATE / relative
        if sha256(staged) != sha256(template):
            raise HardwareBuildError(f"staged harness source changed: {relative}")
        files[relative] = file_evidence(staged, str(staged.relative_to(output)))
    return {
        "tree": tree_evidence(TEMPLATE),
        "files": files,
    }


def validate_sdkconfig(path: Path, board_id: str) -> None:
    config = BOARD_CONFIGS[board_id]
    settings: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("CONFIG_") and "=" in line:
            key, value = line.split("=", 1)
            settings[key] = value
    target = config["target"]
    target_key = "CONFIG_IDF_TARGET_ESP32S3" if target == "esp32s3" else "CONFIG_IDF_TARGET_ESP32C6"
    flash_key = "CONFIG_ESPTOOLPY_FLASHSIZE_8MB" if target == "esp32s3" else "CONFIG_ESPTOOLPY_FLASHSIZE_4MB"
    required = {
        "CONFIG_IDF_TARGET": f'"{target}"',
        target_key: "y",
        "CONFIG_PARTITION_TABLE_CUSTOM": "y",
        "CONFIG_PARTITION_TABLE_CUSTOM_FILENAME": '"partitions.csv"',
        flash_key: "y",
        "CONFIG_ESP_TASK_WDT_EN": "y",
        "CONFIG_ESP_TASK_WDT_INIT": "y",
        "CONFIG_ESP_TASK_WDT_PANIC": "y",
        "CONFIG_ESP_TASK_WDT_TIMEOUT_S": "3",
        "CONFIG_ESP_MAIN_TASK_STACK_SIZE": "16384",
    }
    if target == "esp32s3":
        required.update(
            {
                "CONFIG_SPIRAM": "y",
                "CONFIG_SPIRAM_MODE_QUAD": "y",
                "CONFIG_SPIRAM_USE_MALLOC": "y",
            }
        )
    else:
        required["CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG"] = "y"
    mismatches = [
        f"{key}={settings.get(key)!r}, expected {value!r}"
        for key, value in required.items()
        if settings.get(key) != value
    ]
    if target == "esp32c6" and settings.get("CONFIG_SPIRAM") == "y":
        mismatches.append("CONFIG_SPIRAM must remain disabled on the C6 lane")
    if mismatches:
        raise HardwareBuildError("invalid generated HP3.5 sdkconfig: " + "; ".join(mismatches))


def run_command(
    command: list[str], *, cwd: Path, environment: dict[str, str], timeout: int
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
    board_id: str,
    *,
    idf_path: Path | None,
    idf_py: Path | None,
    timeout: int,
) -> tuple[dict[str, Any], str]:
    config = BOARD_CONFIGS[board_id]
    environment_evidence = verify_idf_environment.verify_idf_environment(
        MATRIX,
        idf_path=idf_path,
        idf_py=idf_py,
        allowed_platforms=HIL_BUILD_HOST_PLATFORMS,
    )
    environment_evidence["platform_scope"] = "NAMED_BOARD_HP3_5_HIL_BUILD"
    resolved_idf_py = Path(environment_evidence["idf_py"])
    build = output / "build"
    sdkconfig = output / "sdkconfig"
    definitions = [
        "-B",
        str(build),
        f"-DIDF_TARGET={config['target']}",
        f"-DSDKCONFIG={sdkconfig}",
        f"-DSDKCONFIG_DEFAULTS={project / 'sdkconfig.defaults'}",
        f"-DPULSE_REPO_ROOT={staged_repository}",
    ]
    commands = [
        [str(resolved_idf_py), *definitions, "reconfigure"],
        [str(resolved_idf_py), *definitions, "build"],
        [str(resolved_idf_py), "-B", str(build), "size", "--format", "json"],
    ]
    process_environment = os.environ.copy()
    process_environment.update(
        {
            "IDF_PATH": environment_evidence["idf_path"],
            "IDF_TARGET": config["target"],
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
        if sha256(project / "dependencies.lock") != config["lock_sha256"]:
            raise HardwareBuildError(f"{label} mutated the pinned dependency lock")
    validate_sdkconfig(sdkconfig, board_id)
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
        raise HardwareBuildError("firmware build omitted required artifacts: " + ", ".join(missing))
    size = last_json_object(outputs[-1])
    diram_remain = size.get("diram_remain")
    app_size = artifacts["application_binary"].stat().st_size
    if not isinstance(diram_remain, int) or diram_remain < config["minimum_diram_remain_bytes"]:
        raise HardwareBuildError("firmware link has inadequate remaining internal RAM")
    if app_size > 2 * 1024 * 1024:
        raise HardwareBuildError("firmware binary exceeds the canonical 2 MiB host partition")
    return (
        {
            "status": "PASS",
            "result": "BUILD_PROVEN",
            "environment": environment_evidence,
            "commands": commands,
            "sdkconfig": file_evidence(sdkconfig, "sdkconfig"),
            "dependency_lock": file_evidence(project / "dependencies.lock", "project/dependencies.lock"),
            "size": size,
            "headroom_gate": {
                "status": "PASS",
                "minimum_diram_remain_bytes": config["minimum_diram_remain_bytes"],
                "observed_diram_remain_bytes": diram_remain,
                "application_partition_bytes": 2 * 1024 * 1024,
                "application_binary_bytes": app_size,
            },
            "artifacts": {
                name: file_evidence(path, str(path.relative_to(output)))
                for name, path in artifacts.items()
            },
        },
        "\n".join(logs),
    )


def qualify_build(
    *,
    board_id: str,
    out_dir: Path,
    prepare_only: bool,
    idf_path: Path | None,
    idf_py: Path | None,
    timeout: int,
) -> dict[str, Any]:
    output = prepare_output(out_dir)
    campaign, lane, campaign_sha, sealed_sources = validate_inputs(board_id)
    project, staged_repository = stage_project(
        output, board_id, campaign, lane, campaign_sha
    )
    config = BOARD_CONFIGS[board_id]
    report: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "status": "PREPARED" if prepare_only else "FAIL",
        "evidence_origin": "SEALED_BUILD",
        "campaign_id": campaign["campaign_id"],
        "campaign_sha256": campaign_sha,
        "board_id": board_id,
        "target": lane["target"],
        "flash_bytes": lane["flash_bytes"],
        "psram_bytes": lane["psram_bytes"],
        "board_identity": file_evidence(output / "inputs/board.json", "inputs/board.json"),
        "partition_table": file_evidence(output / "inputs/partitions.csv", "inputs/partitions.csv"),
        "bundle": file_evidence(output / "inputs" / BUNDLE.name, f"inputs/{BUNDLE.name}"),
        "sealed_sources": sealed_sources,
        "harness_sources": harness_source_evidence(project, output),
        "generated_sources": {
            "campaign_config": file_evidence(
                project / "main/hp3_5_campaign_config.h",
                "project/main/hp3_5_campaign_config.h",
            ),
            "bundle_blob": file_evidence(
                project / "main/hp3_5_bundle_blob.c",
                "project/main/hp3_5_bundle_blob.c",
            ),
        },
        "staged_project": str(project),
        "staged_repository": str(staged_repository),
        "operator_contract": {
            "full_flash_backup_required": True,
            "fresh_full_flash_erase_required": True,
            "operator_attended": True,
            "restore_path_required": True,
            "serial_log_required": True,
        },
        "commands": {
            "erase": f"cd {project} && idf.py -B {output / 'build'} -p <PORT> erase-flash",
            "flash_monitor": f"cd {project} && idf.py -B {output / 'build'} -p <PORT> flash monitor 2>&1 | tee {output / 'serial.log'}",
            "evaluate": f"python3 tools/evaluate_hp3_5_slot_board.py --run-dir {output} --module-or-board-marking <MARKING>",
        },
        "claim_boundary": {
            "build": "NOT_RUN" if prepare_only else "BUILD_PROVEN",
            "runtime": "HARDWARE_NOT_RUN",
            "host_firmware_ota": "NOT_IMPLEMENTED",
            "external_provider": "NOT_IMPLEMENTED",
        },
    }
    if not prepare_only:
        firmware, log = build_firmware(
            output,
            project,
            staged_repository,
            board_id,
            idf_path=idf_path,
            idf_py=idf_py,
            timeout=timeout,
        )
        log_path = output / "build.log"
        log_path.write_text(log, encoding="utf-8")
        firmware["build_log"] = file_evidence(log_path, "build.log")
        report["firmware"] = firmware
        report["status"] = "PASS"
    report_path = output / "build-report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--board-id", choices=tuple(BOARD_CONFIGS), required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--idf-path", type=Path)
    parser.add_argument("--idf-py", type=Path)
    parser.add_argument("--timeout", type=int, default=1800)
    args = parser.parse_args(argv)
    try:
        report = qualify_build(
            board_id=args.board_id,
            out_dir=args.out_dir,
            prepare_only=args.prepare_only,
            idf_path=args.idf_path,
            idf_py=args.idf_py,
            timeout=args.timeout,
        )
    except (
        OSError,
        ValueError,
        json.JSONDecodeError,
        subprocess.TimeoutExpired,
        HardwareBuildError,
        verify_idf_environment.IDFEnvironmentError,
    ) as exc:
        print(f"HP3.5 named-board build failed: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "status": report["status"],
                "board_id": report["board_id"],
                "out_dir": str(args.out_dir.expanduser().resolve()),
                "runtime": "HARDWARE_NOT_RUN",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
