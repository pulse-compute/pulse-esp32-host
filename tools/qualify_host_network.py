#!/usr/bin/env python3
"""Qualify the HP5 host-owned Wi-Fi/TLS and Pulse HTTP mediator."""
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

import qualify_admin_adversarial  # noqa: E402
import hp5_5_source_authority  # noqa: E402


MODEL = ROOT / "specs/PULSE-ESP32-014-host-network-mediator.json"
FIRMWARE = ROOT / "firmware"
GUEST_SDK = ROOT / "guest-sdk"
NATIVE_SDK = ROOT / "native-sdk"
SMOKE = ROOT / "tests/contract/hp5_http_service_smoke.c"

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
    ROOT / "specs/PULSE-ESP32-013-administration-adversarial-seal.json":
        "8c7258d502dfbfeedfa8ac1c07a5c47c622bed004eff4f96c6ef8b1a4e1cf99a",
}
EXPECTED_FIRMWARE = {
    "file_count": 159,
    "sha256": "2e94b65a03a0612d4e770dc0f9b624dab874a75bf334bbd5173023427b7076a5",
}
EXPECTED_GUEST_SDK = {
    "file_count": 13,
    "sha256": "bc5a537e98343c030ad03c85427c55b244d954a1b26e91c5796f40ba0185f0b3",
}
EXPECTED_NATIVE_SDK = {
    "file_count": 1,
    "sha256": "a7ceb397ab009950a1ebbdea60280f7944020a6523252b7de0d781e3e798bdd4",
}
EXPECTED_CLAIM = {
    "application_code_executed": False,
    "application_http_route_implemented": True,
    "authenticated_external_admin_adapter_implemented": True,
    "classification": "HOST_NATIVE_NETWORK_MEDIATOR_ONLY",
    "common_wasm_handler_host_stub_exercised": True,
    "factory_host_writable": False,
    "firmware_component_linked": True,
    "host_firmware_ota_implemented": False,
    "mqtt_transport_implemented": False,
    "network_transport_source_implemented": True,
    "partition_layout_changed": False,
    "physical_execution": False,
    "production_authenticator_implemented": False,
    "production_cryptography_validated": False,
    "serial_driver_implemented": False,
    "target_build_executed": False,
    "tls_listener_source_implemented": True,
    "wifi_station_adapter_source_implemented": True,
}
EXPECTED_BOUNDS = {
    "admin_request_deadline_ms": 30000,
    "app_body_bytes": 1024,
    "app_request_deadline_ms": 5000,
    "app_route_count": 4,
    "app_slots": 1,
    "listeners": 2,
    "open_sockets_per_listener": 3,
    "parser_bytes": 2304,
    "request_body_bytes": 2048,
    "response_body_bytes": 1280,
    "service_bytes": 8192,
}
EXPECTED_SOURCE_HISTORY = {
    "current_firmware_file_count": 159,
    "current_firmware_sha256": EXPECTED_FIRMWARE["sha256"],
    "current_guest_sdk_file_count": 13,
    "current_guest_sdk_sha256": EXPECTED_GUEST_SDK["sha256"],
    "current_native_sdk_file_count": 1,
    "current_native_sdk_sha256": EXPECTED_NATIVE_SDK["sha256"],
    "hp4_4_archive_manifest_file_count": 474,
    "hp4_4_archive_payload_bytes": 3697926,
    "hp4_4_archive_sha256":
        "df9c4e5e92b0bbd18f04f439cd1cacf3459973a11fbfb9a3a7305f6abb2a7410",
    "hp4_4_archive_size_bytes": 1132476,
    "hp4_4_firmware_file_count": 150,
    "hp4_4_firmware_sha256":
        "ff9f571860eda289cc276c6418f887b0af42552380c50f4038b5163ea929a386",
}


class QualificationError(RuntimeError):
    """Raised when HP5 source or evidence crosses the frozen boundary."""


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
        raise QualificationError("cannot load HP5 model: %s" % exc) from exc
    if not isinstance(value, dict):
        raise QualificationError("HP5 model must be an object")
    return value


def _validate_model(model: dict[str, Any]) -> None:
    if (
        model.get("schema") != "pulse.esp32.hp5-host-network-mediator.v1"
        or model.get("pass") != "HP5"
        or model.get("phase") != "HOST_NETWORK_MEDIATOR"
        or model.get("status") != "QUALIFIED"
        or model.get("aggregate") != "HOST_NETWORK_MEDIATOR_IMPLEMENTED"
    ):
        raise QualificationError("HP5 identity drifted")
    if model.get("claim") != EXPECTED_CLAIM:
        raise QualificationError("HP5 claim boundary drifted")
    if model.get("bounds") != EXPECTED_BOUNDS:
        raise QualificationError("HP5 fixed bounds drifted")
    if model.get("source_history") != EXPECTED_SOURCE_HISTORY:
        raise QualificationError("HP5 source history drifted")
    verification = model.get("verification", {})
    if (
        verification.get("native_case_count") != 35
        or verification.get("hp4_4_inherited_native_cases") != 3564
        or verification.get("native_smoke")
        != "tests/contract/hp5_http_service_smoke.c"
        or verification.get("physical_result_created") is not False
    ):
        raise QualificationError("HP5 verification boundary drifted")
    routes = model.get("routes", {})
    if routes.get("admin") != [
        "POST /pulse/v1/admin/session/begin",
        "POST /pulse/v1/admin/session/finish",
        "DELETE /pulse/v1/admin/session",
        "POST /pulse/v1/admin/command",
        "GET /pulse/v1/admin/terminal",
    ]:
        raise QualificationError("HP5 protected routes drifted")
    deferred = model.get("deferred", [])
    for token in ("HP5.5 dual-board", "HP6 thin external", "HP7 MQTT", "HP8 external"):
        if not any(token in item for item in deferred):
            raise QualificationError("missing deferred boundary: %s" % token)


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
        "hp4_4_model_sha256": EXPECTED_AUTHORITY[
            ROOT / "specs/PULSE-ESP32-013-administration-adversarial-seal.json"
        ],
    }
    if model.get("authority_bindings") != expected_bindings:
        raise QualificationError("HP5 authority bindings drifted")
    return observed


def _validate_source_history() -> dict[str, Any]:
    firmware = tree_evidence(
        FIRMWARE,
        {"build", "managed_components", "dependencies.lock", "sdkconfig", "__pycache__"},
    )
    guest_sdk = tree_evidence(GUEST_SDK, {"target", "__pycache__"})
    native_sdk = tree_evidence(NATIVE_SDK, {"__pycache__"})
    successor = "HP5"
    if firmware != EXPECTED_FIRMWARE:
        hp5_5_source_authority.validate(
            firmware, EXPECTED_FIRMWARE, QualificationError
        )
        successor = "HP5.5"
    if guest_sdk != EXPECTED_GUEST_SDK:
        raise QualificationError("HP5 guest SDK tree drifted")
    if native_sdk != EXPECTED_NATIVE_SDK:
        raise QualificationError("native extension SDK changed during HP5")
    return {
        "firmware": firmware,
        "sealed_firmware": EXPECTED_FIRMWARE,
        "current_successor": successor,
        "guest_sdk": guest_sdk,
        "native_sdk": native_sdk,
    }


def _validate_component_surface() -> None:
    required = [
        SMOKE,
        FIRMWARE / "components/wdc_http/include/wdc_http_service.h",
        FIRMWARE / "components/wdc_http/include/wdc_http_platform.h",
        FIRMWARE / "components/wdc_http/wdc_http_service.c",
        FIRMWARE / "components/wdc_http/wdc_http_runtime.c",
        FIRMWARE / "components/wdc_http/wdc_http_platform_espidf.c",
        FIRMWARE / "components/wdc_admin/wdc_admin.c",
    ]
    for path in required:
        if not path.is_file():
            raise QualificationError("missing HP5 source: %s" % path)
    header = _text(required[1])
    service = _text(required[3])
    runtime = _text(required[4])
    platform = _text(required[5])
    admin = _text(required[6])
    for token in [
        "WDC_HTTP_SERVICE_STATIC_BUDGET_BYTES 8192u",
        "WDC_HTTP_PARSER_STATIC_BUDGET_BYTES 2304u",
        "WDC_HTTP_APP_ROUTE_CAPACITY 4u",
        "WDC_HTTP_ADMIN_COMMAND_PATH",
        "WDC_HTTP_ADMIN_TERMINAL_PATH",
    ]:
        if token not in header:
            raise QualificationError("HP5 bound/route missing: %s" % token)
    for token in [
        "_Static_assert(sizeof(WdcHttpParser)",
        "_Static_assert(sizeof(WdcHttpService)",
        "wdc_admin_serial_feed",
        "wdc_admin_authorization_begin",
        "WDC_EVENT_HTTP_REQUEST",
        "first bounded response wins",
    ]:
        component_docs = (
            _text(FIRMWARE / "components/wdc_http/README.md")
            + _text(FIRMWARE / "components/wdc_net/README.md")
        )
        if token not in service and token not in component_docs:
            raise QualificationError("HP5 service integration missing: %s" % token)
    for token in ["wdc_runtime_call_event_cbor", "WdcRuntime"]:
        if token not in runtime:
            raise QualificationError("common Wasm handler adapter missing: %s" % token)
    for token in [
        "esp_wifi_init",
        "esp_wifi_connect",
        "HTTPD_SSL_CONFIG_DEFAULT",
        "httpd_ssl_start",
        "WDC_HTTP_APP_CTRL_PORT",
        "WDC_HTTP_ADMIN_CTRL_PORT",
        "WDC_HTTP_PLATFORM_MAX_OPEN_SOCKETS_PER_LANE",
        "s_platform.admin",
        "s_platform.app",
    ]:
        if token not in platform:
            raise QualificationError("ESP-IDF listener source missing: %s" % token)
    for token in [
        "WDC_ADMIN_TRANSPORT_AUTHENTICATED_EXTERNAL_V1",
        "external_entry",
        "WDC_ADMIN_AUTH_METHOD_REPLACEABLE_AUTHENTICATOR",
    ]:
        if token not in admin and token not in _text(FIRMWARE / "components/wdc_admin/include/wdc_admin.h"):
            raise QualificationError("HP4 external-entry binding missing: %s" % token)
    allocation_free = service + admin
    for token in ("malloc(", "calloc(", "realloc(", "free("):
        if token in allocation_free:
            raise QualificationError("request-controlled allocation entered HP5: %s" % token)
    guest = "".join(_text(path) for path in sorted(GUEST_SDK.rglob("*")) if path.is_file())
    native = "".join(_text(path) for path in sorted(NATIVE_SDK.rglob("*")) if path.is_file())
    for token in ("WDC_ADMIN_COMMAND", "wdc_admin", "wifi_password", "private_key"):
        if token in guest or token in native:
            raise QualificationError("private host authority leaked to portable SDK: %s" % token)
    for token in ("WDC_OP_HTTP_RESPOND", "WDC_EVENT_HTTP_REQUEST", "wdc_guest_http_respond"):
        if token not in guest:
            raise QualificationError("paired guest HTTP response surface missing: %s" % token)
    if "WDC_ADMIN_TRANSPORT_AUTHENTICATED_EXTERNAL_V1" not in _text(
        FIRMWARE / "components/wdc_admin/include/wdc_admin.h"
    ):
        raise QualificationError("authenticated external transport is not realized")


def _native_command(executable: Path) -> list[str]:
    include_components = [
        "wdc_abi", "wdc_admin", "wdc_activation", "wdc_bundle", "wdc_caps",
        "wdc_control", "wdc_diag", "wdc_events", "wdc_http", "wdc_net", "wdc_profile",
        "wdc_runtime",
    ]
    sources = [
        "firmware/components/wdc_abi/wdc_errors.c",
        "firmware/components/wdc_abi/wdc_cbor.c",
        "firmware/components/wdc_abi/wdc_pointer.c",
        "firmware/components/wdc_abi/wdc_host_call.c",
        "firmware/components/wdc_admin/wdc_admin.c",
        "firmware/components/wdc_admin/wdc_admin_serial.c",
        "firmware/components/wdc_caps/wdc_caps.c",
        "firmware/components/wdc_control/wdc_control.c",
        "firmware/components/wdc_diag/wdc_diag.c",
        "firmware/components/wdc_events/wdc_event_queue.c",
        "firmware/components/wdc_events/wdc_event_encode.c",
        "firmware/components/wdc_net/wdc_net.c",
        "firmware/components/wdc_http/wdc_http_service.c",
        "firmware/components/wdc_http/wdc_http_runtime.c",
        "firmware/components/wdc_http/wdc_http_platform_espidf.c",
        "firmware/components/wdc_profile/wdc_profile_static.c",
        "firmware/components/wdc_runtime/wdc_runtime.c",
        "firmware/components/wdc_runtime/wdc_static_wasm.c",
        "tests/contract/hp5_http_service_smoke.c",
    ]
    compiler = os.environ.get("CC") or shutil.which("gcc")
    if compiler is None:
        raise QualificationError("gcc is required for HP5 qualification")
    command = [
        compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic",
        "-O2",
    ]
    for component in include_components:
        command.extend(["-I", str(FIRMWARE / "components" / component / "include")])
    command.extend([str(ROOT / source) for source in sources])
    command.extend(["-o", str(executable)])
    return command


def _run_native_smoke() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="pulse-hp5-") as temp:
        executable = Path(temp) / "hp5_http_service_smoke"
        compile_run = subprocess.run(
            _native_command(executable), cwd=ROOT, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )
        if compile_run.returncode != 0:
            raise QualificationError("HP5 native compile failed: %s" % compile_run.stderr)
        execution = subprocess.run(
            [str(executable)], cwd=ROOT, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )
        if execution.returncode != 0:
            raise QualificationError("HP5 native smoke failed: %s" % execution.stderr)
    lines = [line for line in execution.stdout.splitlines() if line.strip()]
    if not lines:
        raise QualificationError("HP5 native smoke emitted no result")
    try:
        result = json.loads(lines[-1])
    except json.JSONDecodeError as exc:
        raise QualificationError("HP5 native smoke emitted invalid JSON") from exc
    if (
        result.get("schema") != "pulse.esp32.hp5-http-service-smoke.v1"
        or result.get("status") != "PASS"
        or result.get("case_count") != 35
        or result.get("failures") != 0
        or result.get("fixed_parser") is not True
        or result.get("separate_admin_lane") is not True
        or result.get("external_entry_reuses_hp4") is not True
        or result.get("first_response_wins") is not True
        or result.get("network_loss_does_not_rollback") is not True
    ):
        raise QualificationError("HP5 native result drifted")
    return result


def _run_inherited_hp4() -> dict[str, Any]:
    adversarial = qualify_admin_adversarial._run_native_smoke()
    inherited = qualify_admin_adversarial._run_inherited_native()
    aggregate = adversarial.get("case_count", 0) + inherited.get("case_count", 0)
    if aggregate != 3564 or adversarial.get("status") != "PASS" or inherited.get("status") != "PASS":
        raise QualificationError("inherited HP4.4 native closure failed")
    return {
        "schema": "pulse.esp32.hp5-inherited-hp4_4.v1",
        "status": "PASS",
        "hp4_4_adversarial_cases": adversarial["case_count"],
        "hp4_1_through_hp4_3_cases": inherited["case_count"],
        "aggregate_case_count": aggregate,
    }


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def qualify(out_dir: Path) -> dict[str, Any]:
    model = load_model()
    _validate_model(model)
    authority = _validate_authority(model)
    source = _validate_source_history()
    _validate_component_surface()
    native = _run_native_smoke()
    inherited = _run_inherited_hp4()
    out = out_dir.expanduser().resolve()
    if out.exists():
        raise QualificationError("output directory must not already exist")
    out.mkdir(parents=True)
    _write_json(out / "host-network-mediator-model.json", model)
    _write_json(out / "native-http-service-smoke.json", native)
    _write_json(out / "inherited-hp4_4-native.json", inherited)
    _write_json(out / "source-and-authority-seal.json", {
        "schema": "pulse.esp32.hp5-source-authority-seal.v1",
        "status": "PASS", "authority": authority, "source": source,
        "predecessor": EXPECTED_SOURCE_HISTORY,
    })
    artifacts = []
    for name in (
        "host-network-mediator-model.json", "native-http-service-smoke.json",
        "inherited-hp4_4-native.json", "source-and-authority-seal.json",
    ):
        path = out / name
        artifacts.append({"name": name, "sha256": sha256(path), "size": path.stat().st_size})
    manifest = {
        "schema": "pulse.esp32.hp5-host-network-evidence.v1",
        "status": "PASS", "artifacts": artifacts,
    }
    _write_json(out / "evidence-manifest.json", manifest)
    report = {
        "schema": "pulse.esp32.hp5-host-network-qualification.v1",
        "pass": "HP5",
        "aggregate": "HOST_NETWORK_MEDIATOR_IMPLEMENTED",
        "classification": "HOST_NATIVE_NETWORK_MEDIATOR_ONLY",
        "status": "PASS",
        "native_case_count": native["case_count"],
        "inherited_hp4_4_native_case_count": inherited["aggregate_case_count"],
        "network_transport_source_implemented": True,
        "common_wasm_handler_host_stub_exercised": True,
        "target_build_executed": False,
        "physical_result_created": False,
        "production_authenticator_implemented": False,
        "hp5_closed": True,
        "next_pass": "HP5.5",
        "evidence_manifest_sha256": sha256(out / "evidence-manifest.json"),
    }
    _write_json(out / "qualification-report.json", report)
    (out / "qualification-report.md").write_text(
        "# HP5 host network qualification\n\n"
        "Result: `HOST_NETWORK_MEDIATOR_IMPLEMENTED` (`PASS`).\n\n"
        "The fixed host-native HTTP parser/service, common Wasm handler adapter, "
        "paired response effect, protected external administration adapter, and "
        "ESP-IDF Wi-Fi/HTTPS source are implemented. The 35-case HP5 native "
        "smoke and all 3,564 inherited HP4.4 native cases passed.\n\n"
        "No ESP-IDF target build, Wi-Fi/TLS handshake, physical board result, "
        "production authenticator, provisioning, or cryptographic/key-lifecycle "
        "claim was created. Those observations remain HP5.5.\n",
        encoding="utf-8",
    )
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = qualify(args.out_dir)
    except (OSError, ValueError, QualificationError) as exc:
        print("HP5 qualification failed: %s" % exc, file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
