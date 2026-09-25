#!/usr/bin/env python3
"""Prepare or build the frozen HP5.5 dual-board physical audit fixture."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

try:
    from tools import (
        build_hp3_5_slot_hardware,
        host_build_contract,
        hp5_5_fixture,
        resolve_hp5_5_target_contracts,
        verify_idf_environment,
    )
except ModuleNotFoundError:
    import build_hp3_5_slot_hardware  # type: ignore[no-redef]
    import host_build_contract  # type: ignore[no-redef]
    import hp5_5_fixture  # type: ignore[no-redef]
    import resolve_hp5_5_target_contracts  # type: ignore[no-redef]
    import verify_idf_environment  # type: ignore[no-redef]


ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN = ROOT / "tests/hardware-in-loop/hp5_5-network-admin/campaign.json"
MODEL = ROOT / "specs/PULSE-ESP32-015-network-administration-physical-seal.json"
TEMPLATE = ROOT / "tests/hardware-in-loop/hp5_5-network-admin/firmware"
CATALOG = ROOT / "firmware/host-build/hp5_5/catalog.json"
MATRIX = ROOT / "firmware/idf-family-matrix.json"
PROJECT_NAME = "pulse_hp5_5_network_admin"
REPORT_SCHEMA = "pulse.esp32.hp5_5-network-admin-build.v1"
EXPECTED_CAMPAIGN_SHA256 = (
    "7a19148314f4bb5f2d5a03e5918324254afc4ece9eeff800b45c8ed0931f545e"
)
EXPECTED_MODEL_SHA256 = (
    "b95d1daae6f93db1d577f03cb27d7658cff8f7948a9997236642b294cff701a4"
)
EXPECTED_PREDECESSOR = {
    "name": "pulse-esp32-host-hp5-source-v1.zip",
    "sha256": "e7df20f0909afbf2b3b8e4bea9b2b5a4ac40682471ea31c60b3ce344405ed347",
    "size": 1181638,
    "root": "pulse-esp32-host-main",
    "file_count": 489,
    "payload_bytes": 3880933,
}
EXPECTED_FIRMWARE = {
    "sha256": "d60e2669cd3b2dd5869e2305c92e39913b270ba9d54844d3a34d614681c5a98a",
    "file_count": 168,
}
NORMALIZED_MTIME = 315532800
HIL_PLATFORMS = ("linux/amd64", "darwin/amd64", "darwin/arm64")

BOARD_CONFIGS: dict[str, dict[str, Any]] = {
    "aitrip-esp32s3-devkitc-1-n8r2": {
        "target": "esp32s3",
        "flash_bytes": 8 * 1024 * 1024,
        "psram_bytes": 2 * 1024 * 1024,
        "sdkconfig": "sdkconfig.s3.defaults",
        "board": "firmware/boards/aitrip-esp32s3-devkitc-1-n8r2/board.json",
        "partitions": "firmware/boards/aitrip-esp32s3-devkitc-1-n8r2/partitions.csv",
        "dependency_lock": "firmware/locks/host-extension/idf-5.4.4/esp32s3/dependencies.lock",
        "dependency_lock_sha256": "5c672b327f9f4fc8742ca78c5cdca76170cb78a18857e98b497ac0f0bbee0e4c",
        "minimum_diram_remain_bytes": 1024,
    },
    "seeed-xiao-esp32c6-4m": {
        "target": "esp32c6",
        "flash_bytes": 4 * 1024 * 1024,
        "psram_bytes": 0,
        "sdkconfig": "sdkconfig.c6.defaults",
        "board": "firmware/boards/seeed-xiao-esp32c6-4m/board.json",
        "partitions": "firmware/boards/seeed-xiao-esp32c6-4m/partitions.csv",
        "dependency_lock": "firmware/locks/host-extension/idf-5.4.4/esp32c6/dependencies.lock",
        "dependency_lock_sha256": "edfeaa76d16c1eb9e8f60e46e0a342af41bf238b1b1226a7c0c0b541f35e228a",
        "minimum_diram_remain_bytes": 65536,
    },
}


class HardwareBuildError(RuntimeError):
    """Raised when the HP5.5 physical build is not exactly reproducible."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_evidence(path: Path, logical: str | None = None) -> dict[str, Any]:
    return {
        "path": logical or str(path),
        "sha256": sha256(path),
        "size": path.stat().st_size,
    }


def normalize_tree(root: Path) -> None:
    for path in sorted(root.rglob("*"), reverse=True):
        os.utime(path, (NORMALIZED_MTIME, NORMALIZED_MTIME))
    os.utime(root, (NORMALIZED_MTIME, NORMALIZED_MTIME))


def _safe_member(name: str, root: str) -> str:
    parts = PurePosixPath(name).parts
    if not parts or parts[0] != root or any(part in ("", ".", "..") for part in parts):
        raise HardwareBuildError("predecessor archive contains an unsafe member")
    return "/".join(parts[1:])


def verify_predecessor_archive(path: Path) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    if (
        not resolved.is_file()
        or resolved.name != EXPECTED_PREDECESSOR["name"]
        or resolved.stat().st_size != EXPECTED_PREDECESSOR["size"]
        or sha256(resolved) != EXPECTED_PREDECESSOR["sha256"]
    ):
        raise HardwareBuildError("sealed HP5 predecessor archive identity drifted")
    with zipfile.ZipFile(resolved) as archive:
        infos = archive.infolist()
        if any(info.date_time != (1980, 1, 1, 0, 0, 0) for info in infos):
            raise HardwareBuildError("predecessor archive timestamp normalization drifted")
        root = EXPECTED_PREDECESSOR["root"]
        manifest_name = f"{root}/PACKAGE-MANIFEST.json"
        names = [info.filename for info in infos]
        if names.count(manifest_name) != 1 or len(names) != EXPECTED_PREDECESSOR["file_count"] + 1:
            raise HardwareBuildError("predecessor archive member count drifted")
        manifest = json.loads(archive.read(manifest_name))
        if (
            manifest.get("schema") != "pulse.esp32.release-package-manifest.v1"
            or manifest.get("kind") != "SOURCE"
            or manifest.get("archive_root") != root
            or manifest.get("file_count") != EXPECTED_PREDECESSOR["file_count"]
            or manifest.get("payload_bytes") != EXPECTED_PREDECESSOR["payload_bytes"]
            or manifest.get("fixed_zip_timestamp") != "1980-01-01T00:00:00"
        ):
            raise HardwareBuildError("predecessor archive manifest drifted")
        members = {info.filename: info for info in infos}
        expected_names = {manifest_name}
        for item in manifest.get("files", []):
            relative = item.get("path")
            if not isinstance(relative, str) or not relative:
                raise HardwareBuildError("predecessor manifest path is invalid")
            member_name = f"{root}/{relative}"
            _safe_member(member_name, root)
            expected_names.add(member_name)
            info = members.get(member_name)
            if info is None or info.file_size != item.get("size"):
                raise HardwareBuildError("predecessor archive payload inventory drifted")
            if hashlib.sha256(archive.read(info)).hexdigest() != item.get("sha256"):
                raise HardwareBuildError("predecessor archive payload hash drifted")
        if set(names) != expected_names:
            raise HardwareBuildError("predecessor archive has unmanifested payload")
    return {
        "name": resolved.name,
        "sha256": EXPECTED_PREDECESSOR["sha256"],
        "size": EXPECTED_PREDECESSOR["size"],
        "archive_root": EXPECTED_PREDECESSOR["root"],
        "manifested_files": EXPECTED_PREDECESSOR["file_count"],
        "manifested_payload_bytes": EXPECTED_PREDECESSOR["payload_bytes"],
    }


def load_provision(path: Path) -> tuple[dict[str, Any], dict[str, bytes]]:
    provision = path.expanduser().resolve()
    try:
        provision.relative_to(ROOT)
    except ValueError:
        pass
    else:
        raise HardwareBuildError("test provision must remain outside the source tree")
    manifest_path = provision / "provision-manifest.json"
    if not manifest_path.is_file():
        raise HardwareBuildError("test provision manifest is missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        manifest.get("schema") != "pulse.esp32.hp5_5-test-provision.v1"
        or manifest.get("status") != "LOCAL_SECRET_MATERIAL"
        or manifest.get("publishable") is not False
    ):
        raise HardwareBuildError("test provision boundary drifted")
    names = {
        "ssid": "wifi-ssid.bin",
        "password": "wifi-password.bin",
        "certificate": "server-cert.pem",
        "private_key": "server-key.pem",
        "admin_proof": "admin-proof.bin",
        "channel_binding": "channel-binding.bin",
    }
    blobs: dict[str, bytes] = {}
    for role, name in names.items():
        candidate = provision / name
        if not candidate.is_file() or candidate.is_symlink():
            raise HardwareBuildError(f"test provision file is missing: {name}")
        blobs[role] = candidate.read_bytes()
    if (
        not 8 <= len(blobs["ssid"]) < 32
        or not 8 <= len(blobs["password"]) < 64
        or len(blobs["channel_binding"]) != 32
        or hashlib.sha256(blobs["certificate"]).hexdigest()
            != manifest.get("certificate_sha256")
        or hashlib.sha256(blobs["admin_proof"]).hexdigest()
            != manifest.get("admin_proof_sha256")
        or blobs["channel_binding"].hex() != manifest.get("channel_binding_sha256")
    ):
        raise HardwareBuildError("test provision content does not match its manifest")
    return manifest, blobs


def validate_source(board_id: str) -> tuple[dict[str, Any], dict[str, Any], str]:
    if sha256(CAMPAIGN) != EXPECTED_CAMPAIGN_SHA256 or sha256(MODEL) != EXPECTED_MODEL_SHA256:
        raise HardwareBuildError("HP5.5 campaign or model identity drifted")
    campaign = json.loads(CAMPAIGN.read_text(encoding="utf-8"))
    model = json.loads(MODEL.read_text(encoding="utf-8"))
    execution = campaign.get("execution_source_authority", {})
    firmware = build_hp3_5_slot_hardware.tree_evidence(
        ROOT / "firmware",
        {"build", "managed_components", "dependencies.lock", "sdkconfig", "__pycache__"},
    )
    if firmware != EXPECTED_FIRMWARE:
        raise HardwareBuildError("HP5.5 firmware source authority drifted")
    if execution.get("harness") != {
        "path": "tests/hardware-in-loop/hp5_5-network-admin/firmware",
        **build_hp3_5_slot_hardware.tree_evidence(TEMPLATE),
    }:
        raise HardwareBuildError("HP5.5 physical harness authority drifted")
    if execution.get("fixture_artifacts") != hp5_5_fixture.artifact_inventory():
        raise HardwareBuildError("HP5.5 deterministic fixture authority drifted")
    if (
        model.get("schema") != "pulse.esp32.hp5_5-network-administration-physical-seal.v1"
        or model.get("status") != "READY_FOR_PHYSICAL_EXECUTION"
        or model.get("aggregate") != "HARDWARE_PENDING"
        or model.get("source_history", {}).get("current_firmware_sha256")
            != firmware["sha256"]
    ):
        raise HardwareBuildError("HP5.5 model does not bind the execution source")
    resolution = resolve_hp5_5_target_contracts.verify()
    lanes = {lane["board_id"]: lane for lane in campaign.get("board_lanes", [])}
    lane = lanes.get(board_id)
    resolved_lane = {
        item["board_id"]: item for item in resolution["lanes"]
    }.get(board_id)
    config = BOARD_CONFIGS[board_id]
    if lane is None or resolved_lane is None:
        raise HardwareBuildError("HP5.5 named-board lane is missing")
    for field in ("target", "flash_bytes", "psram_bytes"):
        if lane.get(field) != config[field]:
            raise HardwareBuildError(f"HP5.5 board lane drifted: {field}")
    for field in ("plan_sha256", "lock_sha256", "fingerprint_sha256"):
        if lane.get(field) != resolved_lane.get(field):
            raise HardwareBuildError(f"HP5.5 target contract drifted: {field}")
    if sha256(ROOT / config["board"]) != lane.get("board_sha256") or sha256(
        ROOT / config["partitions"]
    ) != lane.get("partitions_sha256"):
        raise HardwareBuildError("HP5.5 board or partition identity drifted")
    if sha256(ROOT / config["dependency_lock"]) != config["dependency_lock_sha256"]:
        raise HardwareBuildError("pinned ESP-IDF dependency lock drifted")
    return campaign, lane, EXPECTED_CAMPAIGN_SHA256


def prepare_output(path: Path) -> Path:
    output = path.expanduser().resolve()
    try:
        output.relative_to(ROOT)
    except ValueError:
        pass
    else:
        raise HardwareBuildError("HP5.5 run directory must remain outside source")
    if output.exists():
        if not output.is_dir() or any(output.iterdir()):
            raise HardwareBuildError("run directory must be absent or empty")
    else:
        output.mkdir(parents=True)
    return output


def c_array(symbol: str, data: bytes, *, string: bool = False) -> str:
    payload = data + (b"\0" if string else b"")
    rows = []
    for offset in range(0, len(payload), 12):
        values = payload[offset : offset + 12]
        rows.append(
            "    "
            + ", ".join(
                f"(char)0x{byte:02x}" if string else f"0x{byte:02x}u"
                for byte in values
            )
            + ","
        )
    ctype = "char" if string else "uint8_t"
    values = "\n".join(rows)
    return (
        f"const {ctype} {symbol}[] = {{\n{values}\n}};\n"
        f"const uint32_t {symbol}_len = {len(data)}u;\n"
    )


def render_provision(blobs: dict[str, bytes]) -> tuple[str, str]:
    proof_sha = hashlib.sha256(blobs["admin_proof"]).digest()
    header = """#pragma once
#include <stdint.h>
extern const char pulse_hp55_wifi_ssid[];
extern const uint32_t pulse_hp55_wifi_ssid_len;
extern const char pulse_hp55_wifi_password[];
extern const uint32_t pulse_hp55_wifi_password_len;
extern const uint8_t pulse_hp55_server_certificate[];
extern const uint32_t pulse_hp55_server_certificate_len;
extern const uint8_t pulse_hp55_server_private_key[];
extern const uint32_t pulse_hp55_server_private_key_len;
extern const uint8_t pulse_hp55_admin_proof_sha256[32];
extern const uint8_t pulse_hp55_channel_binding_sha256[32];
"""
    source = "#include <stdint.h>\n\n"
    source += c_array("pulse_hp55_wifi_ssid", blobs["ssid"], string=True)
    source += c_array("pulse_hp55_wifi_password", blobs["password"], string=True)
    source += c_array("pulse_hp55_server_certificate", blobs["certificate"])
    source += c_array("pulse_hp55_server_private_key", blobs["private_key"])
    source += c_array("pulse_hp55_admin_proof_sha256", proof_sha).replace(
        "const uint32_t pulse_hp55_admin_proof_sha256_len = 32u;\n", ""
    )
    source += c_array("pulse_hp55_channel_binding_sha256", blobs["channel_binding"]).replace(
        "const uint32_t pulse_hp55_channel_binding_sha256_len = 32u;\n", ""
    )
    return header, source


def render_blobs() -> tuple[str, str, dict[str, dict[str, Any]], bytes, bytes]:
    wasm = hp5_5_fixture.make_http_responder_wasm()
    baseline = hp5_5_fixture.make_artifact(8)
    positive = hp5_5_fixture.make_artifact(9)
    fallback = hp5_5_fixture.make_artifact(10)
    header = """#pragma once
#include <stdint.h>
extern const uint8_t pulse_hp55_wasm[];
extern const uint32_t pulse_hp55_wasm_len;
extern const uint8_t pulse_hp55_baseline_artifact[];
extern const uint32_t pulse_hp55_baseline_artifact_len;
"""
    source = "#include <stdint.h>\n\n"
    source += hp5_5_fixture.c_array("pulse_hp55_wasm", wasm)
    source += hp5_5_fixture.c_array("pulse_hp55_baseline_artifact", baseline)
    inventory = hp5_5_fixture.artifact_inventory()
    if (
        hashlib.sha256(baseline).hexdigest() != inventory["baseline"]["sha256"]
        or hashlib.sha256(positive).hexdigest() != inventory["positive"]["sha256"]
        or hashlib.sha256(fallback).hexdigest() != inventory["fallback"]["sha256"]
    ):
        raise HardwareBuildError("deterministic HP5.5 artifact generation drifted")
    return header, source, inventory, positive, fallback


def render_config(campaign: dict[str, Any], lane: dict[str, Any], campaign_sha: str) -> str:
    return (
        "#pragma once\n\n"
        f'#define HP55_CAMPAIGN_ID "{campaign["campaign_id"]}"\n'
        f'#define HP55_CAMPAIGN_SHA256 "{campaign_sha}"\n'
        f'#define HP55_BOARD_ID "{lane["board_id"]}"\n'
        f'#define HP55_TARGET "{lane["target"]}"\n'
        f"#define HP55_FLASH_BYTES {lane['flash_bytes']}u\n"
        f"#define HP55_PSRAM_BYTES {lane['psram_bytes']}u\n"
        f'#define HP55_PLAN_SHA256 "{lane["plan_sha256"]}"\n'
        f'#define HP55_LOCK_SHA256 "{lane["lock_sha256"]}"\n'
        f'#define HP55_FINGERPRINT_SHA256 "{lane["fingerprint_sha256"]}"\n'
        f"#define HP55_MIN_INTERNAL_FREE_BYTES {lane['minimum_runtime_internal_free_bytes']}u\n"
        f"#define HP55_MIN_INTERNAL_LARGEST_BYTES {lane['minimum_runtime_largest_block_bytes']}u\n"
        f"#define HP55_MIN_PSRAM_FREE_BYTES {lane['minimum_runtime_psram_free_bytes']}u\n"
    )


def operator_commands(board_id: str) -> dict[str, str]:
    """Return path-neutral attended commands retained in the build report."""

    config = BOARD_CONFIGS[board_id]
    return {
        "backup": (
            "esptool.py --chip %s -p <PORT> read_flash 0 %d "
            "full-flash-backup.bin"
        ) % (config["target"], config["flash_bytes"]),
        "erase": "idf.py -B build -p <PORT> erase-flash",
        "flash_monitor": (
            "idf.py -B build -p <PORT> flash monitor 2>&1 | tee serial.log"
        ),
        "client": (
            "python3 tools/run_hp5_5_network_client.py --run-dir <RUN_DIR> "
            "--provision-dir <PROVISION_DIR> --device-host <DEVICE_IP>"
        ),
        "evaluate": (
            "python3 tools/evaluate_hp5_5_network_board.py --run-dir <RUN_DIR> "
            "--provision-dir <PROVISION_DIR> --module-or-board-marking "
            "<MARKING> --restore-command <RESTORE_COMMAND> "
            "--fresh-erase-attested --operator-attended"
        ),
    }


def stage_project(
    output: Path,
    board_id: str,
    campaign: dict[str, Any],
    lane: dict[str, Any],
    campaign_sha: str,
    blobs: dict[str, bytes],
) -> tuple[Path, Path, dict[str, Any]]:
    config = BOARD_CONFIGS[board_id]
    project = output / "project"
    shutil.copytree(TEMPLATE, project)
    shutil.copy2(ROOT / config["partitions"], project / "partitions.csv")
    shutil.copy2(ROOT / config["dependency_lock"], project / "dependencies.lock")
    shutil.copy2(project / config["sdkconfig"], project / "sdkconfig.defaults")
    provision_header, provision_source = render_provision(blobs)
    fixture_header, fixture_source, inventory, positive, fallback = render_blobs()
    generated = {
        "hp5_5_campaign_config.h": render_config(campaign, lane, campaign_sha),
        "hp5_5_provision.h": provision_header,
        "hp5_5_provision.c": provision_source,
        "hp5_5_fixture_blobs.h": fixture_header,
        "hp5_5_fixture_blobs.c": fixture_source,
    }
    for name, content in generated.items():
        (project / "main" / name).write_text(content, encoding="utf-8")
    client = output / "client-fixtures"
    client.mkdir()
    (client / "positive-v9.artifact").write_bytes(positive)
    (client / "fallback-v10.artifact").write_bytes(fallback)
    inputs = output / "inputs"
    inputs.mkdir()
    shutil.copy2(CAMPAIGN, inputs / "campaign.json")
    shutil.copy2(MODEL, inputs / "model.json")
    shutil.copy2(ROOT / config["board"], inputs / "board.json")
    shutil.copy2(ROOT / config["partitions"], inputs / "partitions.csv")
    for kind in ("plans", "locks", "fingerprints"):
        source = ROOT / "firmware/host-build/hp5_5" / kind / f"{board_id}.json"
        shutil.copy2(source, inputs / f"target-{kind[:-1]}.json")
    staged = output / "source"
    shutil.copytree(ROOT / "firmware/components", staged / "firmware/components")
    shutil.copytree(ROOT / "native-sdk", staged / "native-sdk")
    generated_fingerprint = host_build_contract.render_generated_c(
        host_build_contract.load_json(CATALOG), ROOT
    )
    (staged / "firmware/components/wdc_host_identity/wdc_host_fingerprint_generated.c").write_text(
        generated_fingerprint, encoding="utf-8"
    )
    normalize_tree(project)
    normalize_tree(staged)
    return project, staged, inventory


def staged_source_seals(output: Path, project: Path, staged: Path) -> dict[str, Any]:
    """Hash every source class used by the physical link without raw secrets."""

    return {
        "template": build_hp3_5_slot_hardware.tree_evidence(TEMPLATE),
        "project": build_hp3_5_slot_hardware.tree_evidence(
            project, {"managed_components", "build", "__pycache__"}
        ),
        "staged_repository": build_hp3_5_slot_hardware.tree_evidence(
            staged, {"build", "managed_components", "__pycache__"}
        ),
        "inputs": build_hp3_5_slot_hardware.tree_evidence(
            output / "inputs", {"__pycache__"}
        ),
    }


def validate_sdkconfig(path: Path, board_id: str) -> None:
    config = BOARD_CONFIGS[board_id]
    settings: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("CONFIG_") and "=" in line:
            key, value = line.split("=", 1)
            settings[key] = value
    required = {
        "CONFIG_IDF_TARGET": f'"{config["target"]}"',
        "CONFIG_PARTITION_TABLE_CUSTOM": "y",
        "CONFIG_PARTITION_TABLE_CUSTOM_FILENAME": '"partitions.csv"',
        "CONFIG_ESP_TASK_WDT_EN": "y",
        "CONFIG_ESP_TASK_WDT_INIT": "y",
        "CONFIG_ESP_TASK_WDT_PANIC": "y",
        "CONFIG_ESP_TASK_WDT_TIMEOUT_S": "8",
        "CONFIG_ESP_MAIN_TASK_STACK_SIZE": "16384",
    }
    required["CONFIG_IDF_TARGET_ESP32S3" if config["target"] == "esp32s3" else "CONFIG_IDF_TARGET_ESP32C6"] = "y"
    required["CONFIG_ESPTOOLPY_FLASHSIZE_8MB" if config["target"] == "esp32s3" else "CONFIG_ESPTOOLPY_FLASHSIZE_4MB"] = "y"
    if config["target"] == "esp32s3":
        required.update({"CONFIG_SPIRAM": "y", "CONFIG_SPIRAM_MODE_QUAD": "y"})
    elif settings.get("CONFIG_SPIRAM") == "y":
        raise HardwareBuildError("C6 HP5.5 lane unexpectedly enables PSRAM")
    bad = [f"{key}={settings.get(key)!r}" for key, value in required.items() if settings.get(key) != value]
    if bad:
        raise HardwareBuildError("invalid HP5.5 sdkconfig: " + "; ".join(bad))


def run_command(command: list[str], cwd: Path, environment: dict[str, str], timeout: int) -> str:
    process = subprocess.run(
        command, cwd=cwd, env=environment, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        timeout=timeout, check=False,
    )
    if process.returncode != 0:
        raise HardwareBuildError(
            f"command exited with {process.returncode}: {' '.join(command)}\n{process.stdout}"
        )
    return process.stdout


def last_json(output: str) -> dict[str, Any]:
    decoder = json.JSONDecoder()
    values: list[tuple[int, dict[str, Any]]] = []
    for index, character in enumerate(output):
        if character == "{":
            try:
                value, end = decoder.raw_decode(output[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                values.append((index + end, value))
    if not values:
        raise HardwareBuildError("IDF size output omitted JSON")
    return max(values, key=lambda item: item[0])[1]


def build_firmware(
    output: Path, project: Path, staged: Path, board_id: str,
    idf_path: Path | None, idf_py: Path | None, timeout: int,
) -> tuple[dict[str, Any], str]:
    config = BOARD_CONFIGS[board_id]
    environment = verify_idf_environment.verify_idf_environment(
        MATRIX, idf_path=idf_path, idf_py=idf_py, allowed_platforms=HIL_PLATFORMS
    )
    environment["platform_scope"] = "NAMED_BOARD_HP5_5_NETWORK_ADMIN_BUILD"
    resolved_idf_py = Path(environment["idf_py"])
    build = output / "build"
    sdkconfig = output / "sdkconfig"
    definitions = [
        "-B", str(build), f"-DIDF_TARGET={config['target']}",
        f"-DSDKCONFIG={sdkconfig}",
        f"-DSDKCONFIG_DEFAULTS={project / 'sdkconfig.defaults'}",
        f"-DPULSE_REPO_ROOT={staged}",
    ]
    commands = [
        [str(resolved_idf_py), *definitions, "reconfigure"],
        [str(resolved_idf_py), *definitions, "build"],
        [str(resolved_idf_py), "-B", str(build), "size", "--format", "json"],
    ]
    process_environment = os.environ.copy()
    process_environment.update({
        "IDF_PATH": environment["idf_path"], "IDF_TARGET": config["target"],
        "IDF_CCACHE_ENABLE": "0", "LANG": "C", "LC_ALL": "C",
        "SOURCE_DATE_EPOCH": "0",
    })
    logs: list[str] = []
    outputs: list[str] = []
    for label, command in zip(("reconfigure", "build", "size"), commands):
        observed = run_command(command, project, process_environment, timeout)
        outputs.append(observed)
        logs.append(f"=== {label} ===\n$ {' '.join(command)}\n{observed.rstrip()}\n")
        if sha256(project / "dependencies.lock") != config["dependency_lock_sha256"]:
            raise HardwareBuildError("ESP-IDF mutated the pinned dependency lock")
    validate_sdkconfig(sdkconfig, board_id)
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
        raise HardwareBuildError("HP5.5 build omitted: " + ", ".join(missing))
    size = last_json(outputs[-1])
    diram = size.get("diram_remain")
    app_bytes = artifacts["application_binary"].stat().st_size
    if not isinstance(diram, int) or diram < config["minimum_diram_remain_bytes"]:
        raise HardwareBuildError("HP5.5 link has inadequate remaining internal RAM")
    if app_bytes > 2 * 1024 * 1024:
        raise HardwareBuildError("HP5.5 firmware exceeds the fixed factory partition")
    return ({
        "status": "PASS", "result": "BUILD_PROVEN", "environment": environment,
        "commands": commands, "sdkconfig": file_evidence(sdkconfig, "sdkconfig"),
        "size": size,
        "headroom_gate": {
            "status": "PASS",
            "minimum_diram_remain_bytes": config["minimum_diram_remain_bytes"],
            "observed_diram_remain_bytes": diram,
            "application_partition_bytes": 2 * 1024 * 1024,
            "application_binary_bytes": app_bytes,
        },
        "artifacts": {
            name: file_evidence(path, str(path.relative_to(output)))
            for name, path in artifacts.items()
        },
    }, "\n".join(logs))


def qualify_build(
    *, board_id: str, out_dir: Path, source_archive: Path,
    provision_dir: Path, prepare_only: bool, idf_path: Path | None,
    idf_py: Path | None, timeout: int,
) -> dict[str, Any]:
    output = prepare_output(out_dir)
    predecessor = verify_predecessor_archive(source_archive)
    manifest, secret_blobs = load_provision(provision_dir)
    campaign, lane, campaign_sha = validate_source(board_id)
    project, staged, inventory = stage_project(
        output, board_id, campaign, lane, campaign_sha, secret_blobs
    )
    report: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "status": "PREPARED" if prepare_only else "FAIL",
        "evidence_origin": "SEALED_SOURCE_PHYSICAL_BUILD",
        "campaign_id": campaign["campaign_id"],
        "campaign_sha256": campaign_sha,
        "model_sha256": EXPECTED_MODEL_SHA256,
        "board_id": board_id,
        "target": lane["target"],
        "flash_bytes": lane["flash_bytes"],
        "psram_bytes": lane["psram_bytes"],
        "plan_sha256": lane["plan_sha256"],
        "lock_sha256": lane["lock_sha256"],
        "fingerprint_sha256": lane["fingerprint_sha256"],
        "predecessor_archive": predecessor,
        "execution_source": EXPECTED_FIRMWARE,
        "board_identity": file_evidence(output / "inputs/board.json", "inputs/board.json"),
        "partition_table": file_evidence(output / "inputs/partitions.csv", "inputs/partitions.csv"),
        "dependency_lock": file_evidence(
            project / "dependencies.lock", "project/dependencies.lock"
        ),
        "fixture_artifacts": inventory,
        "client_artifacts": {
            "positive": file_evidence(output / "client-fixtures/positive-v9.artifact", "client-fixtures/positive-v9.artifact"),
            "fallback": file_evidence(output / "client-fixtures/fallback-v10.artifact", "client-fixtures/fallback-v10.artifact"),
        },
        "source_seals": staged_source_seals(output, project, staged),
        "provision": {
            "publishable": False,
            "certificate_sha256": manifest["certificate_sha256"],
            "admin_proof_sha256": manifest["admin_proof_sha256"],
            "channel_binding_sha256": manifest["channel_binding_sha256"],
            "secret_scan_required": True,
            "secret_values_retained_in_report": False,
        },
        "staged_project": "project",
        "staged_repository": "source",
        "operator_contract": {
            "full_flash_backup_required": True,
            "fresh_full_flash_erase_required": True,
            "operator_attended": True,
            "restore_path_required": True,
            "serial_log_required": True,
            "network_transcript_required": True,
            "test_provision_nonpublishable": True,
        },
        "commands": operator_commands(board_id),
        "claim_boundary": {
            "build": "NOT_RUN" if prepare_only else "BUILD_PROVEN",
            "runtime": "HARDWARE_NOT_RUN",
            "aggregate": "HARDWARE_PENDING",
        },
    }
    if not prepare_only:
        firmware, log = build_firmware(
            output, project, staged, board_id, idf_path, idf_py, timeout
        )
        log_path = output / "build.log"
        log_path.write_text(log, encoding="utf-8")
        firmware["build_log"] = file_evidence(log_path, "build.log")
        report["firmware"] = firmware
        report["status"] = "PASS"
    (output / "build-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--board-id", choices=tuple(BOARD_CONFIGS), required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--source-archive", type=Path, required=True)
    parser.add_argument("--provision-dir", type=Path, required=True)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--idf-path", type=Path)
    parser.add_argument("--idf-py", type=Path)
    parser.add_argument("--timeout", type=int, default=1800)
    args = parser.parse_args(argv)
    try:
        report = qualify_build(
            board_id=args.board_id, out_dir=args.out_dir,
            source_archive=args.source_archive, provision_dir=args.provision_dir,
            prepare_only=args.prepare_only, idf_path=args.idf_path,
            idf_py=args.idf_py, timeout=args.timeout,
        )
    except (
        OSError, ValueError, json.JSONDecodeError, zipfile.BadZipFile,
        subprocess.TimeoutExpired, HardwareBuildError,
        host_build_contract.HostBuildContractError,
        verify_idf_environment.IDFEnvironmentError,
    ) as exc:
        print(f"HP5.5 named-board build failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({
        "status": report["status"], "board_id": report["board_id"],
        "out_dir": str(args.out_dir.expanduser().resolve()),
        "runtime": "HARDWARE_NOT_RUN",
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
