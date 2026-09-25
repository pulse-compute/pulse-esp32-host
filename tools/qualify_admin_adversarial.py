#!/usr/bin/env python3
"""Qualify the HP4.4 host-native administration adversarial seal."""
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

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import qualify_admin_core  # noqa: E402
import qualify_admin_recovery  # noqa: E402
import qualify_admin_update  # noqa: E402
import hp5_5_source_authority  # noqa: E402


MODEL = ROOT / "specs/PULSE-ESP32-013-administration-adversarial-seal.json"
HP5_MODEL = ROOT / "specs/PULSE-ESP32-014-host-network-mediator.json"
FIRMWARE = ROOT / "firmware"
NATIVE_SDK = ROOT / "native-sdk"
SMOKE = ROOT / "tests/contract/hp4_4_admin_adversarial_smoke.c"
BUNDLE = ROOT / "examples/bundles/relay-controller/dist/relay-controller-r8.wdcb"
ADMIN_SOURCE = FIRMWARE / "components/wdc_admin/wdc_admin.c"
UPDATE_SOURCE = FIRMWARE / "components/wdc_admin/wdc_admin_update.c"
RECOVERY_SOURCE = FIRMWARE / "components/wdc_admin/wdc_admin_recovery.c"
APP_SLOTS_SOURCE = FIRMWARE / "components/wdc_app_slots/wdc_app_slots.c"

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
    ROOT / "specs/PULSE-ESP32-011-exclusive-update-transaction.json":
        "38f3c9f80204c655d318de5348d083efc754b9114a2e3ee174546c8666d745ea",
    ROOT / "specs/PULSE-ESP32-012-host-only-recovery.json":
        "36ac4f1a0cba50c576de9ea0fc071920240c953a89ff09cfc3ef92839649a690",
}
EXPECTED_FIRMWARE = {
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
    "administration_adversarial_sealed": True,
    "application_code_executed": False,
    "classification": "HOST_NATIVE_ADMINISTRATION_ADVERSARIAL_ONLY",
    "factory_host_writable": False,
    "firmware_component_linked": True,
    "host_firmware_ota_implemented": False,
    "network_transport_implemented": False,
    "partition_layout_changed": False,
    "physical_execution": False,
    "production_authenticator_implemented": False,
    "production_cryptography": False,
    "serial_driver_implemented": False,
    "target_build_executed": False,
}
EXPECTED_CATEGORIES = [
    ("preaccept-and-mutation", 21),
    ("authorization-and-replay", 13),
    ("quiesce-and-unload", 12),
    ("resource-floor", 4),
    ("safe-stream-cut", 2362),
    ("stream-transaction", 14),
    ("verification-rejection", 9),
    ("journal-interruption", 1030),
    ("capacity-saturation", 10),
    ("terminal-and-audit", 8),
    ("recovery-interaction", 40),
]
EXPECTED_SOURCE_HISTORY = {
    "current_firmware_file_count": 150,
    "current_firmware_sha256": EXPECTED_FIRMWARE["sha256"],
    "current_native_sdk_file_count": 1,
    "current_native_sdk_sha256": EXPECTED_NATIVE_SDK["sha256"],
    "hp4_3_archive_manifest_file_count": 469,
    "hp4_3_archive_sha256":
        "78407faf0981ac1d8d39f449136c613ee9aa4ca92ca168715ea0aed1b5f38eee",
    "hp4_3_firmware_file_count": 150,
    "hp4_3_firmware_sha256":
        "d36978214d8e1d892961e7239facafa49eb1ed4150843dd1eeb23dec5d8ceb5f",
    "hp4_3_native_sdk_file_count": 1,
    "hp4_3_native_sdk_sha256": EXPECTED_NATIVE_SDK["sha256"],
}


class QualificationError(RuntimeError):
    """Raised when the HP4.4 implementation or evidence is incomplete."""


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


def load_model() -> dict[str, Any]:
    try:
        value = json.loads(MODEL.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise QualificationError("cannot load HP4.4 model: %s" % exc) from exc
    if not isinstance(value, dict):
        raise QualificationError("HP4.4 model must be an object")
    return value


def _validate_model(model: dict[str, Any]) -> None:
    if (
        model.get("schema")
        != "pulse.esp32.hp4_4-administration-adversarial-seal.v1"
        or model.get("pass") != "HP4.4"
        or model.get("phase") != "ADMINISTRATION_ADVERSARIAL_SEAL"
        or model.get("status") != "SEALED"
        or model.get("aggregate")
        != "HOST_ADMINISTRATION_ADVERSARIAL_SEALED"
    ):
        raise QualificationError("HP4.4 identity drifted")
    if model.get("claim") != EXPECTED_CLAIM:
        raise QualificationError("HP4.4 claim boundary drifted")
    matrix = model.get("matrix", {})
    categories = matrix.get("categories")
    if categories != [
        {"case_count": count, "name": name}
        for name, count in EXPECTED_CATEGORIES
    ]:
        raise QualificationError("HP4.4 adversarial category matrix drifted")
    if (
        matrix.get("new_native_case_count") != 3523
        or matrix.get("inherited_native_case_count") != 41
        or matrix.get("aggregate_native_case_count") != 3564
        or "= 1030" not in matrix.get("journal_formula", "")
        or "= 2362" not in matrix.get("safe_stream_formula", "")
    ):
        raise QualificationError("HP4.4 matrix totals drifted")
    finding = model.get("finding", {})
    if finding != {
        "disposition": "FIXED_AND_REGRESSION_LOCKED",
        "mutation_rule": (
            "no ticket allocation, replay high-water advance, mode change, "
            "control-lane admission, terminal, audit, or slot mutation"
        ),
        "name": "COMMAND_SEQUENCE_EXHAUSTION_REJECTED_PREACCEPT",
        "rejection": "WDC_ADMIN_REJECTION_RATE_LIMITED",
        "recovery": (
            "the exhausted session remains closable; a strictly newer "
            "authenticated epoch starts a fresh session at sequence one"
        ),
    }:
        raise QualificationError("HP4.4 sequence-exhaustion finding drifted")
    verification = model.get("verification", {})
    if (
        verification.get("native_smoke")
        != "tests/contract/hp4_4_admin_adversarial_smoke.c"
        or verification.get("inherited_native_cases")
        != {"HP4.1": 14, "HP4.2": 15, "HP4.3": 12}
        or verification.get("physical_result_created") is not False
    ):
        raise QualificationError("HP4.4 verification boundary drifted")
    if not any("HP5 network transport" in item for item in model.get("deferred", [])):
        raise QualificationError("HP5 transport is not explicitly deferred")
    if not any("HP5.5 combined physical" in item for item in model.get("deferred", [])):
        raise QualificationError("HP5.5 physical evidence is not explicitly deferred")


def _validate_authority(model: dict[str, Any]) -> dict[str, str]:
    observed: dict[str, str] = {}
    for path, expected in EXPECTED_AUTHORITY.items():
        actual = sha256(path)
        if actual != expected:
            raise QualificationError("authority changed: %s" % path)
        observed[path.relative_to(ROOT).as_posix()] = actual
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
        "hp4_2_model_sha256": EXPECTED_AUTHORITY[
            ROOT / "specs/PULSE-ESP32-011-exclusive-update-transaction.json"
        ],
        "hp4_3_model_sha256": EXPECTED_AUTHORITY[
            ROOT / "specs/PULSE-ESP32-012-host-only-recovery.json"
        ],
    }
    if model.get("authority_bindings") != expected_bindings:
        raise QualificationError("HP4.4 authority bindings drifted")
    return observed


def _validate_source_history(model: dict[str, Any]) -> dict[str, Any]:
    firmware = tree_evidence(
        FIRMWARE,
        {"build", "managed_components", "dependencies.lock", "sdkconfig", "__pycache__"},
    )
    native_sdk = tree_evidence(NATIVE_SDK, {"__pycache__"})
    successor = "HP4.4"
    if firmware in (
        EXPECTED_HP5_FIRMWARE,
        hp5_5_source_authority.EXPECTED_FIRMWARE,
    ):
        if not HP5_MODEL.is_file():
            raise QualificationError("the exact HP5 successor is missing")
        try:
            hp5 = json.loads(HP5_MODEL.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise QualificationError("cannot validate the HP5 successor") from exc
        history = hp5.get("source_history", {})
        if (
            hp5.get("schema") != "pulse.esp32.hp5-host-network-mediator.v1"
            or hp5.get("pass") != "HP5"
            or hp5.get("aggregate") != "HOST_NETWORK_MEDIATOR_IMPLEMENTED"
            or history.get("hp4_4_firmware_sha256") != EXPECTED_FIRMWARE["sha256"]
            or history.get("hp4_4_firmware_file_count") != EXPECTED_FIRMWARE["file_count"]
            or history.get("current_firmware_sha256") != EXPECTED_HP5_FIRMWARE["sha256"]
            or history.get("current_firmware_file_count") != EXPECTED_HP5_FIRMWARE["file_count"]
        ):
            raise QualificationError("HP5 does not preserve the HP4.4 source history")
        if firmware == EXPECTED_HP5_FIRMWARE:
            successor = "HP5"
        else:
            hp5_5_source_authority.validate(
                firmware, EXPECTED_HP5_FIRMWARE, QualificationError
            )
            successor = "HP5.5"
    elif firmware != EXPECTED_FIRMWARE:
        raise QualificationError("firmware changed outside the sealed HP4.4/HP5/HP5.5 successors")
    if native_sdk != EXPECTED_NATIVE_SDK:
        raise QualificationError("native SDK changed during HP4.4")
    if model.get("source_history") != EXPECTED_SOURCE_HISTORY:
        raise QualificationError("HP4.4 source history drifted")
    return {
        "firmware": firmware,
        "sealed_firmware": EXPECTED_FIRMWARE,
        "current_successor": successor,
        "native_sdk": native_sdk,
        "predecessor": {
            "archive_manifest_file_count": 469,
            "archive_sha256": EXPECTED_SOURCE_HISTORY["hp4_3_archive_sha256"],
            "firmware_file_count": 150,
            "firmware_sha256": EXPECTED_SOURCE_HISTORY["hp4_3_firmware_sha256"],
        },
    }


def _validate_component_surface() -> None:
    required = [
        SMOKE,
        ADMIN_SOURCE,
        UPDATE_SOURCE,
        RECOVERY_SOURCE,
        APP_SLOTS_SOURCE,
        FIRMWARE / "components/wdc_admin/include/wdc_admin.h",
        FIRMWARE / "components/wdc_admin/include/wdc_admin_update.h",
        FIRMWARE / "components/wdc_admin/include/wdc_admin_recovery.h",
    ]
    for path in required:
        if not path.is_file():
            raise QualificationError("missing HP4.4 source: %s" % path)
    admin = _text(ADMIN_SOURCE)
    guard = "if (core->next_command_sequence == UINT64_MAX)"
    stale = "if (request->command_sequence > core->next_command_sequence)"
    allocate = "core->next_command_sequence += 1u;"
    if guard not in admin or admin.index(guard) <= admin.index(stale) or admin.index(guard) >= admin.index(allocate):
        raise QualificationError("sequence-exhaustion guard is not preaccept")
    for token in [
        "WDC_ADMIN_REJECTION_RATE_LIMITED",
        "replay high-water cannot wrap",
        "fresh, higher authorization epoch",
    ]:
        if token not in admin:
            raise QualificationError("sequence-exhaustion hardening drifted: %s" % token)
    production = admin + _text(UPDATE_SOURCE) + _text(RECOVERY_SOURCE)
    for token in ["malloc(", "calloc(", "realloc(", "free("]:
        if token in production:
            raise QualificationError("dynamic allocation entered administration: %s" % token)
    smoke = _text(SMOKE)
    for token in [
        "HP44_TOTAL_CASES 3523u",
        "HP44_SAFE_STREAM_CASES 2362u",
        "HP44_JOURNAL_CASES 1030u",
        "UINT64_MAX",
        "hp44_run_safe_stream_cut_matrix",
        "hp44_run_journal_matrix",
        "hp44_run_recovery_matrix",
    ]:
        if token not in smoke:
            raise QualificationError("HP4.4 smoke matrix drifted: %s" % token)
    for path in [
        FIRMWARE / "components/wdc_abi/include/wdc_abi.h",
        ROOT / "guest-sdk/c/include/wdc_guest.h",
        ROOT / "guest-sdk/rust/wdc_guest/src/abi.rs",
        ROOT / "native-sdk/c/include/pulse_extension.h",
    ]:
        text = _text(path)
        if "WDC_ADMIN" in text or "wdc_admin" in text or "pulse_admin" in text:
            raise QualificationError("administration leaked into ABI: %s" % path)
    for component in ["wdc_app", "wdc_events", "wdc_extension", "wdc_net"]:
        cmake = _text(FIRMWARE / "components" / component / "CMakeLists.txt")
        if "wdc_admin" in cmake:
            raise QualificationError("application surface depends on wdc_admin: %s" % component)


def _compile_command(compiler: str, executable: Path) -> list[str]:
    include_components = [
        "wdc_abi", "wdc_caps", "wdc_profile", "wdc_bundle", "wdc_control",
        "wdc_host_identity", "wdc_ota", "wdc_activation", "wdc_app_slots",
        "wdc_admin",
    ]
    sources = [
        SMOKE,
        ADMIN_SOURCE,
        UPDATE_SOURCE,
        RECOVERY_SOURCE,
        FIRMWARE / "components/wdc_abi/wdc_errors.c",
        FIRMWARE / "components/wdc_abi/wdc_cbor.c",
        FIRMWARE / "components/wdc_abi/wdc_pointer.c",
        FIRMWARE / "components/wdc_abi/wdc_host_call.c",
        FIRMWARE / "components/wdc_caps/wdc_caps.c",
        FIRMWARE / "components/wdc_bundle/wdc_bundle.c",
        FIRMWARE / "components/wdc_control/wdc_control.c",
        FIRMWARE / "components/wdc_host_identity/wdc_host_identity.c",
        FIRMWARE / "components/wdc_host_identity/wdc_host_fingerprint_generated.c",
        FIRMWARE / "components/wdc_ota/wdc_ota.c",
        FIRMWARE / "components/wdc_activation/wdc_activation.c",
        APP_SLOTS_SOURCE,
        FIRMWARE / "components/wdc_profile/wdc_profile_static.c",
    ]
    command = [
        compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic",
        "-O2", "-DWDC_HOST_TEST_TARGET_C6=1",
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
    with tempfile.TemporaryDirectory(prefix="pulse-hp4_4-") as temp:
        executable = Path(temp) / "hp4_4_admin_adversarial_smoke"
        build = subprocess.run(
            _compile_command(compiler, executable), cwd=ROOT, check=False,
            capture_output=True, text=True, timeout=120,
        )
        if build.returncode != 0:
            raise QualificationError("native adversarial build failed:\n%s" % build.stderr)
        run = subprocess.run(
            [str(executable), str(BUNDLE)], cwd=ROOT, check=False,
            capture_output=True, text=True, timeout=120,
        )
        if run.returncode != 0:
            raise QualificationError(
                "native adversarial smoke failed:\n%s\n%s" % (run.stdout, run.stderr)
            )
    lines = [line for line in run.stdout.splitlines() if line.strip()]
    if len(lines) != 1:
        raise QualificationError("native adversarial smoke emitted unexpected output")
    try:
        result = json.loads(lines[0])
    except json.JSONDecodeError as exc:
        raise QualificationError("native adversarial smoke did not emit JSON") from exc
    expected_categories = [
        {"name": name, "expected": count, "observed": count, "passed": count}
        for name, count in EXPECTED_CATEGORIES
    ]
    if (
        result.get("schema") != "pulse.esp32.hp4_4-admin-adversarial-smoke.v1"
        or result.get("status") != "PASS"
        or result.get("case_count") != 3523
        or result.get("failures") != 0
        or result.get("inherited_native_case_count") != 41
        or result.get("aggregate_native_case_count") != 3564
        or result.get("safe_stream_cut_cases") != 2362
        or result.get("journal_interruption_cases") != 1030
        or result.get("sequence_wrap_prevented") is not True
        or result.get("last_confirmed_preserved") is not True
        or result.get("ambiguous_boot_authority") is not False
        or result.get("factory_host_written") is not False
        or result.get("application_code_launched") is not False
        or result.get("physical_execution") is not False
        or result.get("categories") != expected_categories
    ):
        raise QualificationError("native adversarial result drifted")
    result["compiler"] = compiler
    return result


def _run_inherited_native() -> dict[str, Any]:
    try:
        results = {
            "HP4.1": qualify_admin_core._run_native_smoke(),
            "HP4.2": qualify_admin_update._run_native_smoke(),
            "HP4.3": qualify_admin_recovery._run_native_smoke(),
        }
    except Exception as exc:
        raise QualificationError("inherited native suite failed: %s" % exc) from exc
    expected = {"HP4.1": 14, "HP4.2": 15, "HP4.3": 12}
    for phase, count in expected.items():
        if results[phase].get("status") != "PASS" or results[phase].get("case_count") != count:
            raise QualificationError("inherited %s native result drifted" % phase)
    return {
        "schema": "pulse.esp32.hp4_4-inherited-native-suite.v1",
        "status": "PASS",
        "case_count": sum(expected.values()),
        "phases": results,
    }


def validate(model: dict[str, Any]) -> dict[str, Any]:
    _validate_model(model)
    authority = _validate_authority(model)
    source = _validate_source_history(model)
    _validate_component_surface()
    native = _run_native_smoke()
    inherited = _run_inherited_native()
    return {
        "authority": authority,
        "source": source,
        "native": native,
        "inherited": inherited,
    }


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
    model_copy = output / "administration-adversarial-seal-model.json"
    shutil.copy2(MODEL, model_copy)
    native_path = output / "native-adversarial-smoke.json"
    inherited_path = output / "inherited-native-suite.json"
    _write_json(native_path, validation["native"])
    _write_json(inherited_path, validation["inherited"])
    artifacts = [
        {"path": path.name, "sha256": sha256(path), "size": path.stat().st_size}
        for path in [model_copy, native_path, inherited_path]
    ]
    manifest = {
        "schema": "pulse.esp32.hp4_4-administration-adversarial-evidence.v1",
        "artifacts": artifacts,
        "status": "PASS",
    }
    manifest_path = output / "evidence-manifest.json"
    _write_json(manifest_path, manifest)
    report = {
        "schema": "pulse.esp32.hp4_4-administration-adversarial-qualification.v1",
        "phase": "ADMINISTRATION_ADVERSARIAL_SEAL",
        "pass": "HP4.4",
        "aggregate": "HOST_ADMINISTRATION_ADVERSARIAL_SEALED",
        "status": "PASS",
        "classification": "HOST_NATIVE_ADMINISTRATION_ADVERSARIAL_ONLY",
        "claim": model["claim"],
        "source": validation["source"],
        "authority": validation["authority"],
        "new_native_case_count": validation["native"]["case_count"],
        "inherited_native_case_count": validation["inherited"]["case_count"],
        "aggregate_native_case_count": (
            validation["native"]["case_count"]
            + validation["inherited"]["case_count"]
        ),
        "safe_stream_cut_cases": validation["native"]["safe_stream_cut_cases"],
        "journal_interruption_cases": validation["native"]["journal_interruption_cases"],
        "finding": model["finding"],
        "application_code_executed": False,
        "target_build_executed": False,
        "physical_result_created": False,
        "production_cryptography": False,
        "network_transport_implemented": False,
        "host_firmware_ota_implemented": False,
        "hp4_closed": True,
        "next_pass": "HP5",
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
        print("HP4.4 qualification failed: %s" % exc, file=sys.stderr)
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
