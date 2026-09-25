#!/usr/bin/env python3
"""Qualify the HP4.2 exclusive inactive-slot update transaction."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Optional

try:
    from tools import hp5_5_source_authority
except ModuleNotFoundError:
    import hp5_5_source_authority  # type: ignore[no-redef]


ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "specs/PULSE-ESP32-011-exclusive-update-transaction.json"
HP43_MODEL = ROOT / "specs/PULSE-ESP32-012-host-only-recovery.json"
HP44_MODEL = ROOT / "specs/PULSE-ESP32-013-administration-adversarial-seal.json"
HP5_MODEL = ROOT / "specs/PULSE-ESP32-014-host-network-mediator.json"
FIRMWARE = ROOT / "firmware"
NATIVE_SDK = ROOT / "native-sdk"
SMOKE = ROOT / "tests/contract/hp4_2_admin_update_smoke.c"
BUNDLE = ROOT / "examples/bundles/relay-controller/dist/relay-controller-r8.wdcb"
ADMIN_HEADER = FIRMWARE / "components/wdc_admin/include/wdc_admin.h"
UPDATE_HEADER = FIRMWARE / "components/wdc_admin/include/wdc_admin_update.h"
ADMIN_SOURCE = FIRMWARE / "components/wdc_admin/wdc_admin.c"
UPDATE_SOURCE = FIRMWARE / "components/wdc_admin/wdc_admin_update.c"
CONTROL_HEADER = FIRMWARE / "components/wdc_control/include/wdc_control.h"
CONTROL_SOURCE = FIRMWARE / "components/wdc_control/wdc_control.c"

EXPECTED_AUTHORITY = {
    ROOT / "specs/PULSE-ESP32-006-host-kernel-resource-authority.json":
        "cc3afbfc4ff7d4a7b5b5aca6ae0b5953a34065501bbfea36d4580a2d193fd84d",
    ROOT / "specs/PULSE-ESP32-007-host-build-coherence.json":
        "f9dc94e2ea4bf45af14787671c9fd2ddfb71c888874c6ea8e722cdf0ec5da3f0",
    ROOT / "specs/PULSE-ESP32-008-application-slots.json":
        "79a5c85d8f75ac89ef9903bd8ee54f9400d8754a8c4deb806ab6644dc5e43f38",
    ROOT / "specs/PULSE-ESP32-008a-application-slot-adversarial-seal.json":
        "c52993ff889a3dffe2f87f54bd226e652592018410a24ad36b70592c35219a29",
    ROOT / "evidence/hardware/hp3_5-index.json":
        "3c7d209298ea0f4444991ec296f9b644bbb42428f1d63d7b475468ce2d71a6e9",
    ROOT / "specs/PULSE-ESP32-009-protected-administration.json":
        "c20f13c6c5817435a686837a70f5a9bd5b6802b020dad0a47ea2f29713f1f684",
    ROOT / "specs/PULSE-ESP32-010-protected-administration-core.json":
        "c908deb69c830418c971c9de355e0d319f1e1dd2e2e71c728bdc535434c9a31a",
}
EXPECTED_FIRMWARE = {
    "file_count": 148,
    "sha256": "77f4d2044776c6828e443486ee21199f95b4e1f34ae704c7323e901d51602eca",
}
EXPECTED_HP43_FIRMWARE = {
    "file_count": 150,
    "sha256": "d36978214d8e1d892961e7239facafa49eb1ed4150843dd1eeb23dec5d8ceb5f",
}
EXPECTED_HP44_FIRMWARE = {
    "file_count": 150,
    "sha256": "ff9f571860eda289cc276c6418f887b0af42552380c50f4038b5163ea929a386",
}
EXPECTED_HP5_FIRMWARE = {
    "file_count": 159,
    "sha256": "2e94b65a03a0612d4e770dc0f9b624dab874a75bf334bbd5173023427b7076a5",
}
EXPECTED_NATIVE_SDK = {
    "file_count": 1,
    "sha256": "a7ceb397ab009950a1ebbdea60280f7944020a6523252b7de0d781e3e798bdd4",
}
EXPECTED_CLAIM = {
    "application_code_executed": False,
    "classification": "HOST_NATIVE_UPDATE_TRANSACTION_ONLY",
    "firmware_component_linked": True,
    "host_firmware_ota_implemented": False,
    "host_update_transaction_implemented": True,
    "network_transport_implemented": False,
    "partition_layout_changed": False,
    "physical_execution": False,
    "production_authenticator_implemented": False,
    "production_cryptography": False,
    "recovery_transaction_implemented": False,
    "serial_driver_implemented": False,
    "target_build_executed": False,
}
EXPECTED_COMMANDS = [
    "STATUS",
    "BEGIN_UPDATE",
    "WRITE_CHUNK",
    "FINISH_UPDATE",
    "ABORT",
    "ACTIVATE_TRIAL",
]


class QualificationError(RuntimeError):
    """Raised when the HP4.2 implementation or evidence is incomplete."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_evidence(root: Path, ignored: Optional[set[str]] = None) -> dict[str, Any]:
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
    return {"file_count": count, "sha256": digest.hexdigest()}


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise QualificationError("%s keys drifted" % label)


def load_model() -> dict[str, Any]:
    try:
        value = json.loads(MODEL.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise QualificationError("cannot load HP4.2 model: %s" % exc) from exc
    if not isinstance(value, dict):
        raise QualificationError("HP4.2 model must be an object")
    return value


def _validate_model(model: dict[str, Any]) -> None:
    _exact_keys(
        model,
        {
            "aggregate",
            "authority_bindings",
            "claim",
            "command_authority",
            "component",
            "deferred",
            "failure_authority",
            "pass",
            "resource_admission",
            "schema",
            "source_history",
            "state_machine",
            "status",
            "streaming",
            "verification",
        },
        "HP4.2 model",
    )
    if (
        model.get("schema") !=
            "pulse.esp32.hp4_2-exclusive-update-transaction.v1"
        or model.get("pass") != "HP4.2"
        or model.get("status") != "IMPLEMENTED"
        or model.get("aggregate") !=
            "HOST_EXCLUSIVE_UPDATE_TRANSACTION_IMPLEMENTED"
    ):
        raise QualificationError("HP4.2 identity drifted")
    if model.get("claim") != EXPECTED_CLAIM:
        raise QualificationError("HP4.2 claim boundary drifted")
    command = model["command_authority"]
    if (
        command.get("enabled_commands") != EXPECTED_COMMANDS
        or command.get("enabled_mask") != 95
        or command.get("hp4_3_commands_still_unsupported") !=
            ["ENTER_RECOVERY", "REBOOT"]
    ):
        raise QualificationError("HP4.2 command boundary drifted")
    expected_resource = {
        "exclusive_required_internal_free_bytes": 163840,
        "exclusive_update_working_bytes": 65536,
        "fixed_control_reserve_bytes": 98304,
        "largest_block_floor_bytes": 32768,
        "required_largest_block_bytes": 98304,
        "update_largest_allocation_bytes": 65536,
        "user_controlled_sizes_or_priorities": False,
    }
    if model["resource_admission"] != expected_resource:
        raise QualificationError("HP1 exclusive admission binding drifted")
    stream = model["streaming"]
    if stream != {
        "expected_total_must_match": True,
        "maximum_chunk_bytes": 1024,
        "rate_bytes_per_window": 65536,
        "rate_chunks_per_window": 64,
        "rate_window_ms": 1000,
        "sequential_only": True,
        "stream_idle_deadline_ms": 30000,
        "transaction_deadline_ms": 900000,
        "working_buffer_bytes": 65536,
    }:
        raise QualificationError("HP4.2 streaming bounds drifted")
    state = model["state_machine"]
    if (
        state.get("engine_initial_mode") != "NORMAL"
        or state.get("normal_to_update_direct") is not False
        or state.get("recovery_origin_supported_this_pass") is not False
        or len(state.get("legal_transitions", [])) != 5
    ):
        raise QualificationError("HP4.2/HP4.3 state boundary drifted")
    failure = model["failure_authority"]
    if (
        failure.get("inactive_slot_only") is not True
        or failure.get("factory_host_partition_writable") is not False
        or failure.get("application_code_launched") is not False
        or failure.get("failure_mode") != "NORMAL"
    ):
        raise QualificationError("HP4.2 failure authority drifted")
    verification = model["verification"]
    if (
        verification.get("native_case_count") != 15
        or verification.get("metadata_commits_on_success") != 3
        or verification.get("durable_trial_readback_required") is not True
        or verification.get("activation_rechecks_authorization") is not True
        or verification.get("activation_rechecks_replaceable_verifier") is not True
        or verification.get("production_cryptography_claim") is not False
    ):
        raise QualificationError("HP4.2 verification boundary drifted")
    if not any("HP4.3 host-only recovery" in item for item in model["deferred"]):
        raise QualificationError("HP4.3 recovery is not explicitly deferred")


def _validate_authority(model: dict[str, Any]) -> dict[str, str]:
    for path, expected in EXPECTED_AUTHORITY.items():
        if not path.is_file() or sha256(path) != expected:
            raise QualificationError("authority hash drifted: %s" % path.name)
    expected_bindings = {
        "hp1_model_sha256": EXPECTED_AUTHORITY[
            ROOT / "specs/PULSE-ESP32-006-host-kernel-resource-authority.json"
        ],
        "hp2_model_sha256": EXPECTED_AUTHORITY[
            ROOT / "specs/PULSE-ESP32-007-host-build-coherence.json"
        ],
        "hp3_model_sha256": EXPECTED_AUTHORITY[
            ROOT / "specs/PULSE-ESP32-008-application-slots.json"
        ],
        "hp3_5_model_sha256": EXPECTED_AUTHORITY[
            ROOT / "specs/PULSE-ESP32-008a-application-slot-adversarial-seal.json"
        ],
        "hp3_5_evidence_index_sha256": EXPECTED_AUTHORITY[
            ROOT / "evidence/hardware/hp3_5-index.json"
        ],
        "hp4_0_model_sha256": EXPECTED_AUTHORITY[
            ROOT / "specs/PULSE-ESP32-009-protected-administration.json"
        ],
        "hp4_1_model_sha256": EXPECTED_AUTHORITY[
            ROOT / "specs/PULSE-ESP32-010-protected-administration-core.json"
        ],
    }
    if model["authority_bindings"] != expected_bindings:
        raise QualificationError("HP4.2 authority bindings drifted")
    return expected_bindings


def _validate_source_history(model: dict[str, Any]) -> dict[str, Any]:
    current_firmware = tree_evidence(
        FIRMWARE,
        {"build", "managed_components", "dependencies.lock", "sdkconfig", "__pycache__"},
    )
    native_sdk = tree_evidence(NATIVE_SDK, {"__pycache__"})
    successor = None
    if current_firmware != EXPECTED_FIRMWARE:
        if (
            current_firmware not in (
                EXPECTED_HP43_FIRMWARE,
                EXPECTED_HP44_FIRMWARE,
                EXPECTED_HP5_FIRMWARE,
                hp5_5_source_authority.EXPECTED_FIRMWARE,
            )
            or not HP43_MODEL.is_file()
        ):
            raise QualificationError("firmware changed outside the sealed HP4.3/HP4.4/HP5 successors")
        try:
            hp43 = json.loads(HP43_MODEL.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise QualificationError("cannot validate the HP4.3 successor") from exc
        history = hp43.get("source_history", {})
        if (
            hp43.get("schema") != "pulse.esp32.hp4_3-host-only-recovery.v1"
            or hp43.get("pass") != "HP4.3"
            or hp43.get("status") != "IMPLEMENTED"
            or history.get("hp4_2_firmware_sha256") != EXPECTED_FIRMWARE["sha256"]
            or history.get("hp4_2_firmware_file_count") != EXPECTED_FIRMWARE["file_count"]
            or history.get("current_firmware_sha256") != EXPECTED_HP43_FIRMWARE["sha256"]
            or history.get("current_firmware_file_count") != EXPECTED_HP43_FIRMWARE["file_count"]
        ):
            raise QualificationError("HP4.3 does not preserve the HP4.2 source history")
        if current_firmware == EXPECTED_HP43_FIRMWARE:
            successor = "HP4.3"
        else:
            if not HP44_MODEL.is_file():
                raise QualificationError("the sealed HP4.4 successor is missing")
            try:
                hp44 = json.loads(HP44_MODEL.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise QualificationError("cannot validate the HP4.4 successor") from exc
            hp44_history = hp44.get("source_history", {})
            if (
                hp44.get("schema")
                != "pulse.esp32.hp4_4-administration-adversarial-seal.v1"
                or hp44.get("pass") != "HP4.4"
                or hp44.get("status") != "SEALED"
                or hp44_history.get("hp4_3_firmware_sha256")
                != EXPECTED_HP43_FIRMWARE["sha256"]
                or hp44_history.get("hp4_3_firmware_file_count")
                != EXPECTED_HP43_FIRMWARE["file_count"]
                or hp44_history.get("current_firmware_sha256")
                != EXPECTED_HP44_FIRMWARE["sha256"]
                or hp44_history.get("current_firmware_file_count")
                != EXPECTED_HP44_FIRMWARE["file_count"]
            ):
                raise QualificationError("HP4.4 does not preserve the HP4.3 source history")
            if current_firmware == EXPECTED_HP44_FIRMWARE:
                successor = "HP4.4"
            elif HP5_MODEL.is_file():
                try:
                    hp5 = json.loads(HP5_MODEL.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    raise QualificationError("cannot validate the HP5 successor") from exc
                hp5_history = hp5.get("source_history", {})
                if (
                    hp5.get("schema") != "pulse.esp32.hp5-host-network-mediator.v1"
                    or hp5.get("pass") != "HP5"
                    or hp5.get("status") != "QUALIFIED"
                    or hp5_history.get("hp4_4_firmware_sha256")
                    != EXPECTED_HP44_FIRMWARE["sha256"]
                    or hp5_history.get("hp4_4_firmware_file_count")
                    != EXPECTED_HP44_FIRMWARE["file_count"]
                    or hp5_history.get("current_firmware_sha256")
                    != EXPECTED_HP5_FIRMWARE["sha256"]
                    or hp5_history.get("current_firmware_file_count")
                    != EXPECTED_HP5_FIRMWARE["file_count"]
                ):
                    raise QualificationError("HP5 does not preserve the HP4.4 source history")
                if current_firmware == EXPECTED_HP5_FIRMWARE:
                    successor = "HP5"
                else:
                    hp5_5_source_authority.validate(
                        current_firmware,
                        EXPECTED_HP5_FIRMWARE,
                        QualificationError,
                    )
                    successor = "HP5.5"
            else:
                raise QualificationError("the qualified HP5 successor is missing")
    if native_sdk != EXPECTED_NATIVE_SDK:
        raise QualificationError("native SDK changed during HP4.2")
    expected_history = {
        "current_firmware_file_count": EXPECTED_FIRMWARE["file_count"],
        "current_firmware_sha256": EXPECTED_FIRMWARE["sha256"],
        "current_native_sdk_file_count": EXPECTED_NATIVE_SDK["file_count"],
        "current_native_sdk_sha256": EXPECTED_NATIVE_SDK["sha256"],
        "hp4_1_archive_manifest_file_count": 455,
        "hp4_1_archive_manifest_payload_bytes": 3291858,
        "hp4_1_archive_sha256":
            "7d36f89fab2ed62b30cdb14841dcb96ee736d7720ce2bcf692315f865afa82d5",
        "hp4_1_firmware_file_count": 146,
        "hp4_1_firmware_sha256":
            "4f7b56a99adfedfa57c1d5179ad5ca03e6f57dd258a73fa3a6f71f747973253c",
        "hp4_1_native_sdk_file_count": 1,
        "hp4_1_native_sdk_sha256":
            "a7ceb397ab009950a1ebbdea60280f7944020a6523252b7de0d781e3e798bdd4",
    }
    if model["source_history"] != expected_history:
        raise QualificationError("HP4.2 source history drifted")
    return {
        "firmware": EXPECTED_FIRMWARE,
        "native_sdk": native_sdk,
        "current_firmware": current_firmware,
        "current_successor": successor,
    }


def _validate_component_surface() -> None:
    for path in [
        ADMIN_HEADER,
        UPDATE_HEADER,
        ADMIN_SOURCE,
        UPDATE_SOURCE,
        CONTROL_HEADER,
        CONTROL_SOURCE,
        FIRMWARE / "components/wdc_admin/CMakeLists.txt",
        FIRMWARE / "components/wdc_admin/README.md",
    ]:
        if not path.is_file():
            raise QualificationError("missing HP4.2 component file: %s" % path)
    admin_header = _text(ADMIN_HEADER)
    update_header = _text(UPDATE_HEADER)
    update_source = _text(UPDATE_SOURCE)
    control_header = _text(CONTROL_HEADER)
    control_source = _text(CONTROL_SOURCE)
    cmake = _text(FIRMWARE / "components/wdc_admin/CMakeLists.txt")
    app_main = _text(FIRMWARE / "main/app_main.c")
    for token in [
        "WDC_ADMIN_HP42_COMMAND_MASK",
        "WDC_ADMIN_COMMAND_ACTIVATE_TRIAL",
    ]:
        if token not in admin_header:
            raise QualificationError("admin command boundary missing: %s" % token)
    for token in [
        "WDC_ADMIN_UPDATE_WORKING_BYTES 65536u",
        "WDC_ADMIN_UPDATE_MAX_CHUNK_BYTES 1024u",
        "WDC_ADMIN_UPDATE_STREAM_IDLE_DEADLINE_MS 30000u",
        "WDC_ADMIN_UPDATE_TRANSACTION_DEADLINE_MS 900000u",
        "WdcAdminUpdateQuiesceEvidence",
        "wdc_admin_update_execute",
    ]:
        if token not in update_header:
            raise QualificationError("update contract missing: %s" % token)
    for token in [
        "wdc_control_admit_exclusive_update",
        "wdc_app_slots_stage_begin",
        "wdc_app_slots_stage_write",
        "wdc_app_slots_stage_finish",
        "wdc_app_slots_stage_abort",
        "wdc_app_slots_mark_trial",
        "wdc_ota_read_metadata",
        "wdc_admin_verify_artifact",
        "WDC_ADMIN_MODE_REBOOT_HANDOFF",
    ]:
        if token not in update_source:
            raise QualificationError("update implementation missing: %s" % token)
    for token in ["malloc(", "calloc(", "realloc(", "free("]:
        if token in update_source:
            raise QualificationError("dynamic allocation entered HP4.2")
    if (
        "wdc_control_admit_exclusive_update" not in control_header
        or "fixed_control_reserve_bytes" not in control_source
        or "exclusive_update_working_bytes" not in control_source
        or "update_largest_allocation_bytes" not in control_source
        or "largest_block_floor_bytes" not in control_source
    ):
        raise QualificationError("HP1 exclusive admission is incomplete")
    for dependency in [
        "wdc_activation",
        "wdc_app_slots",
        "wdc_bundle",
        "wdc_control",
        "wdc_host_identity",
        "wdc_ota",
    ]:
        if dependency not in cmake:
            raise QualificationError("HP4.2 component dependency missing: %s" % dependency)
    if (
        "wdc_admin_update.c" not in cmake
        or "wdc_admin_update_link_anchor" not in app_main
        or app_main.index("wdc_admin_update_link_anchor") >
            app_main.index("pthread_create")
    ):
        raise QualificationError("HP4.2 is not linked before the application")
    for component in ["wdc_app", "wdc_events", "wdc_extension", "wdc_net"]:
        component_cmake = _text(FIRMWARE / "components" / component / "CMakeLists.txt")
        if "wdc_admin" in component_cmake:
            raise QualificationError("application surface depends on wdc_admin: %s" % component)
    for path in [
        FIRMWARE / "components/wdc_abi/include/wdc_abi.h",
        ROOT / "guest-sdk/c/include/wdc_guest.h",
        ROOT / "guest-sdk/rust/wdc_guest/src/abi.rs",
        ROOT / "native-sdk/c/include/pulse_extension.h",
    ]:
        text = _text(path)
        if "WDC_ADMIN" in text or "wdc_admin" in text or "pulse_admin" in text:
            raise QualificationError("administration leaked into ABI: %s" % path)


def _compile_command(compiler: str, executable: Path) -> list[str]:
    include_components = [
        "wdc_abi",
        "wdc_caps",
        "wdc_profile",
        "wdc_bundle",
        "wdc_control",
        "wdc_host_identity",
        "wdc_ota",
        "wdc_activation",
        "wdc_app_slots",
        "wdc_admin",
    ]
    sources = [
        SMOKE,
        ADMIN_SOURCE,
        UPDATE_SOURCE,
        FIRMWARE / "components/wdc_abi/wdc_errors.c",
        FIRMWARE / "components/wdc_abi/wdc_cbor.c",
        FIRMWARE / "components/wdc_abi/wdc_pointer.c",
        FIRMWARE / "components/wdc_abi/wdc_host_call.c",
        FIRMWARE / "components/wdc_caps/wdc_caps.c",
        FIRMWARE / "components/wdc_bundle/wdc_bundle.c",
        CONTROL_SOURCE,
        FIRMWARE / "components/wdc_host_identity/wdc_host_identity.c",
        FIRMWARE / "components/wdc_host_identity/wdc_host_fingerprint_generated.c",
        FIRMWARE / "components/wdc_ota/wdc_ota.c",
        FIRMWARE / "components/wdc_activation/wdc_activation.c",
        FIRMWARE / "components/wdc_app_slots/wdc_app_slots.c",
        FIRMWARE / "components/wdc_profile/wdc_profile_static.c",
    ]
    command = [
        compiler,
        "-std=c11",
        "-Wall",
        "-Wextra",
        "-Werror",
        "-pedantic",
        "-O2",
        "-DWDC_HOST_TEST_TARGET_C6=1",
    ]
    command.extend(
        "-I" + str(FIRMWARE / "components" / component / "include")
        for component in include_components
    )
    command.extend(str(path) for path in sources)
    command.extend(["-o", str(executable)])
    return command


def _run_native_smoke() -> dict[str, Any]:
    compiler = os.environ.get("CC", "gcc")
    with tempfile.TemporaryDirectory(prefix="pulse-hp4_2-") as temp:
        executable = Path(temp) / "hp4_2_admin_update_smoke"
        build = subprocess.run(
            _compile_command(compiler, executable),
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if build.returncode != 0:
            raise QualificationError("native smoke build failed:\n%s" % build.stderr)
        run = subprocess.run(
            [str(executable), str(BUNDLE)],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if run.returncode != 0:
            raise QualificationError(
                "native smoke failed:\n%s\n%s" % (run.stdout, run.stderr)
            )
    lines = [line for line in run.stdout.splitlines() if line.strip()]
    if len(lines) != 1:
        raise QualificationError("native smoke emitted unexpected output")
    try:
        result = json.loads(lines[0])
    except json.JSONDecodeError as exc:
        raise QualificationError("native smoke did not emit JSON") from exc
    if (
        result.get("schema") != "pulse.esp32.hp4_2-admin-update-smoke.v1"
        or result.get("status") != "PASS"
        or result.get("failures") != 0
        or result.get("case_count") != 15
        or result.get("engine_static_bytes") != 3096
        or result.get("working_bytes") != 65536
        or result.get("chunk_bytes") != 1024
    ):
        raise QualificationError("native smoke result drifted")
    cases = result.get("cases")
    if not isinstance(cases, list) or len(cases) != 15 or any(
        case.get("status") != "PASS" for case in cases
    ):
        raise QualificationError("native smoke case set is incomplete")
    result["compiler"] = compiler
    return result


def validate(model: dict[str, Any]) -> dict[str, Any]:
    _validate_model(model)
    authority = _validate_authority(model)
    source = _validate_source_history(model)
    _validate_component_surface()
    native = _run_native_smoke()
    return {"authority": authority, "source": source, "native": native}


def _prepare(path: Path) -> Path:
    output = path.expanduser().resolve()
    if output.exists():
        if not output.is_dir() or any(output.iterdir()):
            raise QualificationError("output directory must be absent or empty")
    else:
        output.mkdir(parents=True)
    return output


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def qualify(out_dir: Path) -> dict[str, Any]:
    output = _prepare(out_dir)
    model = load_model()
    validation = validate(model)
    model_copy = output / "exclusive-update-transaction-model.json"
    shutil.copy2(MODEL, model_copy)
    native_path = output / "native-update-transaction-smoke.json"
    _write_json(native_path, validation["native"])
    artifacts = []
    for path in [model_copy, native_path]:
        artifacts.append(
            {
                "path": path.name,
                "sha256": sha256(path),
                "size": path.stat().st_size,
            }
        )
    manifest = {
        "schema": "pulse.esp32.hp4_2-admin-update-evidence.v1",
        "artifacts": artifacts,
        "status": "PASS",
    }
    manifest_path = output / "evidence-manifest.json"
    _write_json(manifest_path, manifest)
    report = {
        "schema": "pulse.esp32.hp4_2-admin-update-qualification.v1",
        "phase": "EXCLUSIVE_UPDATE_TRANSACTION",
        "pass": "HP4.2",
        "aggregate": "HOST_EXCLUSIVE_UPDATE_TRANSACTION_IMPLEMENTED",
        "status": "PASS",
        "classification": "HOST_NATIVE_UPDATE_TRANSACTION_ONLY",
        "claim": model["claim"],
        "source": validation["source"],
        "authority": validation["authority"],
        "native_case_count": validation["native"]["case_count"],
        "engine_static_bytes": validation["native"]["engine_static_bytes"],
        "exclusive_update_working_bytes":
            validation["native"]["working_bytes"],
        "maximum_stream_chunk_bytes": validation["native"]["chunk_bytes"],
        "application_code_executed": False,
        "target_build_executed": False,
        "physical_result_created": False,
        "production_cryptography": False,
        "recovery_transaction_implemented": False,
        "evidence_manifest": {
            "path": manifest_path.name,
            "sha256": sha256(manifest_path),
            "size": manifest_path.stat().st_size,
        },
    }
    _write_json(output / "qualification-report.json", report)
    return report


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        report = qualify(args.out_dir)
    except QualificationError as exc:
        print("HP4.2 qualification failed: %s" % exc, file=sys.stderr)
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
