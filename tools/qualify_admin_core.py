#!/usr/bin/env python3
"""Qualify the HP4.1 fixed-storage protected-administration core."""
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
MODEL = ROOT / "specs/PULSE-ESP32-010-protected-administration-core.json"
HP4_MODEL = ROOT / "specs/PULSE-ESP32-009-protected-administration.json"
HP42_MODEL = ROOT / "specs/PULSE-ESP32-011-exclusive-update-transaction.json"
HP43_MODEL = ROOT / "specs/PULSE-ESP32-012-host-only-recovery.json"
HP44_MODEL = ROOT / "specs/PULSE-ESP32-013-administration-adversarial-seal.json"
HP5_MODEL = ROOT / "specs/PULSE-ESP32-014-host-network-mediator.json"
FIRMWARE = ROOT / "firmware"
NATIVE_SDK = ROOT / "native-sdk"
SMOKE = ROOT / "tests/contract/hp4_1_admin_core_smoke.c"
ADMIN_HEADER = FIRMWARE / "components/wdc_admin/include/wdc_admin.h"
ADMIN_SOURCE = FIRMWARE / "components/wdc_admin/wdc_admin.c"
SERIAL_SOURCE = FIRMWARE / "components/wdc_admin/wdc_admin_serial.c"
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
    HP4_MODEL:
        "c20f13c6c5817435a686837a70f5a9bd5b6802b020dad0a47ea2f29713f1f684",
}
EXPECTED_FIRMWARE = {
    "sha256": "4f7b56a99adfedfa57c1d5179ad5ca03e6f57dd258a73fa3a6f71f747973253c",
    "file_count": 146,
}
EXPECTED_HP42_FIRMWARE = {
    "sha256": "77f4d2044776c6828e443486ee21199f95b4e1f34ae704c7323e901d51602eca",
    "file_count": 148,
}
EXPECTED_HP43_FIRMWARE = {
    "sha256": "d36978214d8e1d892961e7239facafa49eb1ed4150843dd1eeb23dec5d8ceb5f",
    "file_count": 150,
}
EXPECTED_HP44_FIRMWARE = {
    "sha256": "ff9f571860eda289cc276c6418f887b0af42552380c50f4038b5163ea929a386",
    "file_count": 150,
}
EXPECTED_HP5_FIRMWARE = {
    "sha256": "2e94b65a03a0612d4e770dc0f9b624dab874a75bf334bbd5173023427b7076a5",
    "file_count": 159,
}
EXPECTED_NATIVE_SDK = {
    "sha256": "a7ceb397ab009950a1ebbdea60280f7944020a6523252b7de0d781e3e798bdd4",
    "file_count": 1,
}
EXPECTED_CLAIM = {
    "application_code_executed": False,
    "artifact_verifier_interface_implemented": True,
    "classification": "HOST_NATIVE_CORE_ONLY",
    "firmware_component_linked": True,
    "host_update_transaction_implemented": False,
    "network_transport_implemented": False,
    "physical_execution": False,
    "production_authenticator_implemented": False,
    "production_cryptography": False,
    "recovery_transaction_implemented": False,
    "serial_driver_implemented": False,
    "serial_normalizer_implemented": True,
}
EXPECTED_REJECTIONS = [
    "BAD_FRAME",
    "BOUNDS",
    "UNAUTHORIZED",
    "EXPIRED",
    "STALE_REPLAY",
    "OUT_OF_ORDER",
    "RATE_LIMITED",
    "BUSY",
    "UNSUPPORTED",
    "WRONG_STATE",
]


class QualificationError(RuntimeError):
    """Raised when the HP4.1 implementation or evidence is incomplete."""


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
    return {"sha256": digest.hexdigest(), "file_count": count}


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise QualificationError("%s keys drifted" % label)


def load_model() -> dict[str, Any]:
    try:
        value = json.loads(MODEL.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise QualificationError("cannot load HP4.1 model: %s" % exc) from exc
    if not isinstance(value, dict):
        raise QualificationError("HP4.1 model must be an object")
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
            "fixed_storage",
            "interfaces",
            "negative_surface",
            "pass",
            "rate_and_replay",
            "record_layouts",
            "schema",
            "serial_normalizer",
            "source_history",
            "status",
            "terminal_and_audit",
            "verification",
        },
        "HP4.1 model",
    )
    if (
        model.get("schema") !=
            "pulse.esp32.hp4_1-protected-administration-core.v1"
        or model.get("pass") != "HP4.1"
        or model.get("status") != "IMPLEMENTED"
        or model.get("aggregate") !=
            "HOST_PROTECTED_ADMINISTRATION_CORE_IMPLEMENTED"
    ):
        raise QualificationError("HP4.1 identity drifted")
    if model.get("claim") != EXPECTED_CLAIM:
        raise QualificationError("HP4.1 claim boundary drifted")
    if model["record_layouts"] != {
        "audit_bytes": 160,
        "authenticated_entry_bytes": 128,
        "request_bytes": 112,
        "terminal_bytes": 64,
    }:
        raise QualificationError("HP4.0 record binding drifted")
    storage = model["fixed_storage"]
    if (
        storage.get("core_budget_bytes") != 8192
        or storage.get("serial_budget_bytes") != 2304
        or storage.get("hp1_administration_reserve_bytes") != 12288
        or storage.get("native_host_observed_combined_bytes") != 9784
        or storage.get("audit_records") != 32
        or storage.get("audit_bytes") != 5120
        or storage.get("maximum_payload_bytes") != 1024
        or storage.get("maximum_status_response_bytes") != 1024
    ):
        raise QualificationError("fixed storage plan drifted")
    command = model["command_authority"]
    if (
        command.get("default_hp4_1_enabled_commands") != ["STATUS"]
        or command.get("maximum_inflight") != 1
        or command.get("preaccept_rejections") != EXPECTED_REJECTIONS
        or len(command.get("frozen_command_vocabulary", [])) != 8
    ):
        raise QualificationError("command authority drifted")
    replay = model["rate_and_replay"]
    expected_replay = {
        "authorization_backoff_ms": 30000,
        "authorization_failure_limit": 8,
        "authorization_window_ms": 60000,
        "capacity_and_replay_commit_together": True,
        "first_sequence": 1,
        "rejected_commands_advance_sequence": False,
        "session_capacity": 1,
        "session_idle_ms": 30000,
        "session_lifetime_ms": 900000,
        "strictly_consecutive": True,
        "volatile_authorization_epoch_high_water": True,
    }
    if replay != expected_replay:
        raise QualificationError("rate or replay contract drifted")
    serial = model["serial_normalizer"]
    if (
        serial.get("transport") != "SERIAL_PHYSICAL_V1"
        or serial.get("byte_order") != "LITTLE_ENDIAN"
        or serial.get("length_prefix_bytes") != 4
        or serial.get("frame_maximum_bytes_including_prefix") != 2048
        or serial.get("partial_feed_supported") is not True
    ):
        raise QualificationError("serial normalizer contract drifted")
    if model["interfaces"]["authorizer"].get("transport_cannot_emit_entry") is not True:
        raise QualificationError("transport acquired authorization authority")
    if model["interfaces"]["artifact_verifier"].get("production_cryptography_claim") is not False:
        raise QualificationError("artifact interface widened the crypto claim")


def _validate_authority(model: dict[str, Any]) -> dict[str, str]:
    for path, expected in EXPECTED_AUTHORITY.items():
        if not path.is_file() or sha256(path) != expected:
            raise QualificationError("authority hash drifted: %s" % path.name)
    bindings = model["authority_bindings"]
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
        "hp4_0_model_sha256": EXPECTED_AUTHORITY[HP4_MODEL],
    }
    if bindings != expected_bindings:
        raise QualificationError("model authority bindings drifted")
    return expected_bindings


def _validate_source_history(model: dict[str, Any]) -> dict[str, Any]:
    firmware = tree_evidence(
        FIRMWARE,
        {"build", "managed_components", "dependencies.lock", "sdkconfig", "__pycache__"},
    )
    native_sdk = tree_evidence(NATIVE_SDK, {"__pycache__"})
    successor = None
    if firmware != EXPECTED_FIRMWARE:
        if firmware not in (
            EXPECTED_HP42_FIRMWARE,
            EXPECTED_HP43_FIRMWARE,
            EXPECTED_HP44_FIRMWARE,
            EXPECTED_HP5_FIRMWARE,
            hp5_5_source_authority.EXPECTED_FIRMWARE,
        ) or not HP42_MODEL.is_file():
            raise QualificationError("firmware changed outside the sealed HP4.2/HP4.3/HP4.4/HP5 successors")
        try:
            hp42 = json.loads(HP42_MODEL.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise QualificationError("cannot validate the HP4.2 successor") from exc
        hp42_history = hp42.get("source_history", {})
        if (
            hp42.get("schema") !=
                "pulse.esp32.hp4_2-exclusive-update-transaction.v1"
            or hp42.get("pass") != "HP4.2"
            or hp42.get("status") != "IMPLEMENTED"
            or hp42_history.get("hp4_1_firmware_sha256") !=
                EXPECTED_FIRMWARE["sha256"]
            or hp42_history.get("hp4_1_firmware_file_count") !=
                EXPECTED_FIRMWARE["file_count"]
            or hp42_history.get("current_firmware_sha256") !=
                EXPECTED_HP42_FIRMWARE["sha256"]
            or hp42_history.get("current_firmware_file_count") !=
                EXPECTED_HP42_FIRMWARE["file_count"]
        ):
            raise QualificationError("HP4.2 does not preserve the HP4.1 firmware history")
        if firmware == EXPECTED_HP42_FIRMWARE:
            successor = "HP4.2"
        else:
            if not HP43_MODEL.is_file():
                raise QualificationError("the sealed HP4.3 successor is missing")
            try:
                hp43 = json.loads(HP43_MODEL.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise QualificationError("cannot validate the HP4.3 successor") from exc
            hp43_history = hp43.get("source_history", {})
            if (
                hp43.get("schema") !=
                    "pulse.esp32.hp4_3-host-only-recovery.v1"
                or hp43.get("pass") != "HP4.3"
                or hp43.get("status") != "IMPLEMENTED"
                or hp43_history.get("hp4_2_firmware_sha256") !=
                    EXPECTED_HP42_FIRMWARE["sha256"]
                or hp43_history.get("hp4_2_firmware_file_count") !=
                    EXPECTED_HP42_FIRMWARE["file_count"]
                or hp43_history.get("current_firmware_sha256") !=
                    EXPECTED_HP43_FIRMWARE["sha256"]
                or hp43_history.get("current_firmware_file_count") !=
                    EXPECTED_HP43_FIRMWARE["file_count"]
            ):
                raise QualificationError("HP4.3 does not preserve the HP4.2 firmware history")
            if firmware == EXPECTED_HP43_FIRMWARE:
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
                    raise QualificationError("HP4.4 does not preserve the HP4.3 firmware history")
                if firmware == EXPECTED_HP44_FIRMWARE:
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
                        raise QualificationError("HP5 does not preserve the HP4.4 firmware history")
                    if firmware == EXPECTED_HP5_FIRMWARE:
                        successor = "HP5"
                    else:
                        hp5_5_source_authority.validate(
                            firmware, EXPECTED_HP5_FIRMWARE, QualificationError
                        )
                        successor = "HP5.5"
                else:
                    raise QualificationError("the qualified HP5 successor is missing")
    if native_sdk != EXPECTED_NATIVE_SDK:
        raise QualificationError("native SDK changed during HP4.1")
    history = model["source_history"]
    expected = {
        "current_firmware_file_count": EXPECTED_FIRMWARE["file_count"],
        "current_firmware_sha256": EXPECTED_FIRMWARE["sha256"],
        "current_native_sdk_file_count": EXPECTED_NATIVE_SDK["file_count"],
        "current_native_sdk_sha256": EXPECTED_NATIVE_SDK["sha256"],
        "hp4_0_archive_manifest_file_count": 445,
        "hp4_0_archive_manifest_payload_bytes": 3122110,
        "hp4_0_archive_sha256":
            "e2387f4974b2425267b29bf8285c387ca5e7d9d4fbfc6f3e75796001d6058722",
        "hp4_0_firmware_file_count": 141,
        "hp4_0_firmware_sha256":
            "c7b4341e00911b3b26b4d9b8abcd831af4abdf7754503a79298e86aa2b9d2c31",
        "hp4_0_native_sdk_file_count": 1,
        "hp4_0_native_sdk_sha256":
            "a7ceb397ab009950a1ebbdea60280f7944020a6523252b7de0d781e3e798bdd4",
    }
    if history != expected:
        raise QualificationError("source history drifted")
    return {
        "firmware": EXPECTED_FIRMWARE,
        "native_sdk": native_sdk,
        "current_firmware": firmware,
        "current_successor": successor,
    }


def _validate_component_surface(model: dict[str, Any]) -> None:
    for path in [
        ADMIN_HEADER,
        ADMIN_SOURCE,
        SERIAL_SOURCE,
        FIRMWARE / "components/wdc_admin/CMakeLists.txt",
        FIRMWARE / "components/wdc_admin/README.md",
    ]:
        if not path.is_file():
            raise QualificationError("missing component file: %s" % path)
    header = _text(ADMIN_HEADER)
    source = _text(ADMIN_SOURCE)
    serial = _text(SERIAL_SOURCE)
    cmake = _text(FIRMWARE / "components/wdc_admin/CMakeLists.txt")
    main_cmake = _text(FIRMWARE / "main/CMakeLists.txt")
    app_main = _text(FIRMWARE / "main/app_main.c")
    for token in [
        "WDC_ADMIN_AUTHENTICATED_ENTRY_BYTES 128u",
        "WDC_ADMIN_REQUEST_BYTES 112u",
        "WDC_ADMIN_TERMINAL_BYTES 64u",
        "WDC_ADMIN_AUDIT_RECORD_BYTES 160u",
        "WDC_ADMIN_AUDIT_RING_RECORDS 32u",
        "WDC_ADMIN_FIXED_STORAGE_BUDGET_BYTES 12288u",
        "WdcAdminAuthorizeFn",
        "WdcAdminArtifactVerifyFn",
        "WDC_ADMIN_HP41_COMMAND_MASK",
    ]:
        if token not in header:
            raise QualificationError("header contract missing: %s" % token)
    for token in [
        "_Static_assert(sizeof(WdcAdminCore)",
        "wdc_control_submit",
        "core->next_command_sequence += 1u",
        "WDC_ADMIN_LIFECYCLE_TERMINAL",
        "WDC_ADMIN_AUDIT_RING_RECORDS",
    ]:
        if token not in source:
            raise QualificationError("core implementation missing: %s" % token)
    for token in model["negative_surface"]["no_dynamic_allocation_tokens"]:
        if token in source or token in serial:
            raise QualificationError("dynamic allocation entered admin core")
    if (
        "wdc_admin_authorization_begin(" in serial
        or "wdc_admin_authorization_finish(" in serial
        or "WdcAdminAuthenticatedEntry" in serial
    ):
        raise QualificationError("serial normalizer can establish authority")
    for token in ["wdc_abi", "wdc_control"]:
        if token not in cmake:
            raise QualificationError("component dependency missing: %s" % token)
    if "wdc_admin" not in main_cmake or "wdc_admin_link_anchor" not in app_main:
        raise QualificationError("firmware does not link the HP4.1 core")
    if app_main.index("wdc_admin_link_anchor") > app_main.index("pthread_create"):
        raise QualificationError("admin anchor is application-thread dependent")
    for component in model["negative_surface"][
        "application_components_with_no_wdc_admin_dependency"
    ]:
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


def _run_native_smoke() -> dict[str, Any]:
    compiler = os.environ.get("CC", "gcc")
    with tempfile.TemporaryDirectory(prefix="pulse-hp4_1-") as temp:
        binary = Path(temp) / "hp4_1_admin_core_smoke"
        command = [
            compiler,
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-pedantic",
            "-O2",
            "-I" + str(FIRMWARE / "components/wdc_admin/include"),
            "-I" + str(FIRMWARE / "components/wdc_control/include"),
            "-I" + str(FIRMWARE / "components/wdc_abi/include"),
            str(SMOKE),
            str(ADMIN_SOURCE),
            str(SERIAL_SOURCE),
            str(CONTROL_SOURCE),
            "-o",
            str(binary),
        ]
        build = subprocess.run(
            command,
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if build.returncode != 0:
            raise QualificationError("native smoke build failed:\n%s" % build.stderr)
        run = subprocess.run(
            [str(binary)],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if run.returncode != 0:
            raise QualificationError("native smoke failed:\n%s\n%s" % (run.stdout, run.stderr))
    lines = [line for line in run.stdout.splitlines() if line.strip()]
    if len(lines) != 1:
        raise QualificationError("native smoke emitted unexpected output")
    try:
        result = json.loads(lines[0])
    except json.JSONDecodeError as exc:
        raise QualificationError("native smoke did not emit JSON") from exc
    if (
        result.get("schema") != "pulse.esp32.hp4_1-admin-core-smoke.v1"
        or result.get("status") != "PASS"
        or result.get("failures") != 0
        or result.get("case_count") != 14
        or result.get("fixed_storage_bytes") != 9784
        or result.get("core_static_bytes", 8193) > 8192
        or result.get("serial_static_bytes", 2305) > 2304
    ):
        raise QualificationError("native smoke result drifted")
    cases = result.get("cases")
    if not isinstance(cases, list) or len(cases) != 14 or any(
        case.get("status") != "PASS" for case in cases
    ):
        raise QualificationError("native smoke case set is incomplete")
    result["compiler"] = compiler
    return result


def validate(model: dict[str, Any]) -> dict[str, Any]:
    _validate_model(model)
    authority = _validate_authority(model)
    source = _validate_source_history(model)
    _validate_component_surface(model)
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
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def qualify(out_dir: Path) -> dict[str, Any]:
    output = _prepare(out_dir)
    model = load_model()
    validation = validate(model)
    model_copy = output / "protected-administration-core-model.json"
    shutil.copy2(MODEL, model_copy)
    native_path = output / "native-core-smoke.json"
    _write_json(native_path, validation["native"])
    artifacts = []
    for path in (model_copy, native_path):
        artifacts.append({
            "path": path.name,
            "sha256": sha256(path),
            "size": path.stat().st_size,
        })
    manifest = {
        "schema": "pulse.esp32.hp4_1-admin-core-evidence.v1",
        "artifacts": artifacts,
        "status": "PASS",
    }
    manifest_path = output / "evidence-manifest.json"
    _write_json(manifest_path, manifest)
    report = {
        "schema": "pulse.esp32.hp4_1-admin-core-qualification.v1",
        "phase": "PROTECTED_ADMINISTRATION_CORE",
        "pass": "HP4.1",
        "aggregate": "HOST_PROTECTED_ADMINISTRATION_CORE_IMPLEMENTED",
        "status": "PASS",
        "classification": "HOST_NATIVE_CORE_ONLY",
        "claim": model["claim"],
        "source": validation["source"],
        "authority": validation["authority"],
        "native_case_count": validation["native"]["case_count"],
        "preaccept_rejection_count": validation["native"]["rejections"],
        "core_static_bytes": validation["native"]["core_static_bytes"],
        "serial_static_bytes": validation["native"]["serial_static_bytes"],
        "combined_fixed_storage_bytes": validation["native"]["fixed_storage_bytes"],
        "application_code_executed": False,
        "target_build_executed": False,
        "physical_result_created": False,
        "production_cryptography": False,
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
        print("HP4.1 qualification failed: %s" % exc, file=sys.stderr)
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
