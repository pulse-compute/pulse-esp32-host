#!/usr/bin/env python3
"""R0 contract validator for WDC device profiles and bundle manifests.

This intentionally uses only the Python standard library so R0 contract tests can
run on a clean host machine. The JSON Schema files are the human/tooling schema
source; this script implements the minimum semantic checks needed for R0.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable

ABI_MAJOR = 1
ABI_MINOR = 0
REQUIRED_ENTRYPOINTS = {
    "init": "wdc_module_init",
    "event": "wdc_module_on_event",
    "health": "wdc_module_health",
    "shutdown": "wdc_module_shutdown",
}
ALLOWED_CAPABILITY_KINDS = {
    "gpio",
    "sensor",
    "i2c",
    "network",
    "ble",
    "config",
    "storage",
    "diagnostics",
    "clock",
}
PROFILE_RESOURCE_SECTION = {
    "gpio": "gpio",
    "sensor": "sensors",
    "i2c": "i2c",
    "network": "network",
    "ble": "ble",
}
SHELL_VIRTUAL_KINDS = {"config", "storage", "diagnostics", "clock"}


class ValidationErrorSet(Exception):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("\n".join(errors))


def load_json(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as f:
        value = json.load(f)
    if not isinstance(value, dict):
        raise ValidationErrorSet([f"{path}: top-level JSON value must be an object"])
    return value


def _require(obj: dict[str, Any], key: str, errors: list[str], where: str) -> Any:
    if key not in obj:
        errors.append(f"{where}: missing required key '{key}'")
        return None
    return obj[key]


def _require_int(obj: dict[str, Any], key: str, errors: list[str], where: str, minimum: int | None = None) -> int | None:
    value = _require(obj, key, errors, where)
    if not isinstance(value, int) or isinstance(value, bool):
        errors.append(f"{where}.{key}: expected integer")
        return None
    if minimum is not None and value < minimum:
        errors.append(f"{where}.{key}: expected >= {minimum}")
    return value


def _require_str(obj: dict[str, Any], key: str, errors: list[str], where: str) -> str | None:
    value = _require(obj, key, errors, where)
    if not isinstance(value, str):
        errors.append(f"{where}.{key}: expected string")
        return None
    if not value:
        errors.append(f"{where}.{key}: must not be empty")
    return value


def _expect_only(obj: dict[str, Any], allowed: Iterable[str], errors: list[str], where: str) -> None:
    allowed_set = set(allowed)
    for key in obj.keys():
        if key not in allowed_set:
            errors.append(f"{where}: unsupported key '{key}'")


def validate_profile(profile: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    _expect_only(profile, {"profile_format", "device", "resources"}, errors, "profile")
    fmt = _require_int(profile, "profile_format", errors, "profile")
    if fmt is not None and fmt != 1:
        errors.append("profile.profile_format: expected 1")

    device = _require(profile, "device", errors, "profile")
    if isinstance(device, dict):
        _expect_only(device, {"device_class", "hardware", "board_rev", "device_id_template"}, errors, "profile.device")
        _require_str(device, "device_class", errors, "profile.device")
        hardware = _require_str(device, "hardware", errors, "profile.device")
        if hardware is not None and hardware != "esp32-s3":
            errors.append("profile.device.hardware: expected 'esp32-s3'")
        _require_str(device, "board_rev", errors, "profile.device")
    else:
        errors.append("profile.device: expected object")

    resources = _require(profile, "resources", errors, "profile")
    if isinstance(resources, dict):
        _expect_only(resources, {"gpio", "i2c", "sensors", "network", "ble"}, errors, "profile.resources")
        gpio = resources.get("gpio")
        if not isinstance(gpio, dict) or not gpio:
            errors.append("profile.resources.gpio: expected non-empty object")
        elif isinstance(gpio, dict):
            for name, cfg in gpio.items():
                if not isinstance(name, str) or not name:
                    errors.append("profile.resources.gpio: resource names must be non-empty strings")
                if not isinstance(cfg, dict):
                    errors.append(f"profile.resources.gpio.{name}: expected object")
                    continue
                pin = cfg.get("pin")
                if not isinstance(pin, int) or isinstance(pin, bool):
                    errors.append(f"profile.resources.gpio.{name}.pin: expected integer")
                mode = cfg.get("mode")
                if not isinstance(mode, str) or not mode:
                    errors.append(f"profile.resources.gpio.{name}.mode: expected string")
    else:
        errors.append("profile.resources: expected object")

    return errors


def validate_manifest(manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    allowed_top = {
        "manifest_format",
        "bundle_id",
        "bundle_version",
        "bundle_semver",
        "security_counter",
        "abi",
        "target",
        "runtime",
        "entrypoints",
        "limits",
        "capabilities",
        "payload",
        "signature",
    }
    _expect_only(manifest, allowed_top, errors, "manifest")
    fmt = _require_int(manifest, "manifest_format", errors, "manifest")
    if fmt is not None and fmt != 1:
        errors.append("manifest.manifest_format: expected 1")
    _require_str(manifest, "bundle_id", errors, "manifest")
    _require_int(manifest, "bundle_version", errors, "manifest", minimum=0)
    _require_str(manifest, "bundle_semver", errors, "manifest")
    _require_int(manifest, "security_counter", errors, "manifest", minimum=0)

    abi = _require(manifest, "abi", errors, "manifest")
    if isinstance(abi, dict):
        _expect_only(abi, {"major", "min_minor", "max_minor"}, errors, "manifest.abi")
        major = _require_int(abi, "major", errors, "manifest.abi")
        min_minor = _require_int(abi, "min_minor", errors, "manifest.abi", minimum=0)
        max_minor = _require_int(abi, "max_minor", errors, "manifest.abi", minimum=0)
        if major is not None and major != ABI_MAJOR:
            errors.append(f"manifest.abi.major: expected {ABI_MAJOR}")
        if min_minor is not None and max_minor is not None and min_minor > max_minor:
            errors.append("manifest.abi: min_minor must be <= max_minor")
        if min_minor is not None and max_minor is not None and not (min_minor <= ABI_MINOR <= max_minor):
            errors.append(f"manifest.abi: shell ABI minor {ABI_MINOR} not in supported range")
    else:
        errors.append("manifest.abi: expected object")

    target = _require(manifest, "target", errors, "manifest")
    if isinstance(target, dict):
        _expect_only(target, {"soc", "device_class", "board_rev_min"}, errors, "manifest.target")
        soc = target.get("soc")
        if not isinstance(soc, list) or "esp32-s3" not in soc:
            errors.append("manifest.target.soc: must include 'esp32-s3'")
        device_class = target.get("device_class")
        if not isinstance(device_class, list) or not device_class:
            errors.append("manifest.target.device_class: expected non-empty array")
        _require_str(target, "board_rev_min", errors, "manifest.target")
    else:
        errors.append("manifest.target: expected object")

    runtime = _require(manifest, "runtime", errors, "manifest")
    if isinstance(runtime, dict):
        _expect_only(runtime, {"engine", "payload_kind", "wasm_features"}, errors, "manifest.runtime")
        if runtime.get("engine") != "wamr":
            errors.append("manifest.runtime.engine: expected 'wamr'")
        if runtime.get("payload_kind") not in {"wasm", "wamr-aot"}:
            errors.append("manifest.runtime.payload_kind: expected 'wasm' or 'wamr-aot'")
        features = runtime.get("wasm_features")
        if isinstance(features, dict):
            _expect_only(features, {"threads", "shared_memory", "wasi"}, errors, "manifest.runtime.wasm_features")
            for feature in ("threads", "shared_memory", "wasi"):
                if features.get(feature) is not False:
                    errors.append(f"manifest.runtime.wasm_features.{feature}: R0/R1 requires false")
        else:
            errors.append("manifest.runtime.wasm_features: expected object")
    else:
        errors.append("manifest.runtime: expected object")

    entrypoints = _require(manifest, "entrypoints", errors, "manifest")
    if isinstance(entrypoints, dict):
        _expect_only(entrypoints, REQUIRED_ENTRYPOINTS.keys(), errors, "manifest.entrypoints")
        for key, expected in REQUIRED_ENTRYPOINTS.items():
            if entrypoints.get(key) != expected:
                errors.append(f"manifest.entrypoints.{key}: expected '{expected}'")
    else:
        errors.append("manifest.entrypoints: expected object")

    limits = _require(manifest, "limits", errors, "manifest")
    required_limits = [
        "linear_memory_max_bytes", "stack_bytes", "max_event_bytes", "max_request_bytes", "max_response_bytes",
        "init_timeout_ms", "event_timeout_ms", "health_timeout_ms", "host_call_timeout_ms", "max_outstanding_async_requests",
    ]
    if isinstance(limits, dict):
        _expect_only(limits, required_limits, errors, "manifest.limits")
        for key in required_limits:
            minimum = 0 if key == "max_outstanding_async_requests" else 1
            _require_int(limits, key, errors, "manifest.limits", minimum=minimum)
    else:
        errors.append("manifest.limits: expected object")

    caps = _require(manifest, "capabilities", errors, "manifest")
    if isinstance(caps, list):
        ids: set[int] = set()
        for idx, cap in enumerate(caps):
            where = f"manifest.capabilities[{idx}]"
            if not isinstance(cap, dict):
                errors.append(f"{where}: expected object")
                continue
            # This is a semantic contract check: manifests request logical resources, never physical pins.
            if "pin" in cap or "gpio_num" in cap:
                errors.append(f"{where}: manifest must not contain physical pin fields")
            cap_id = _require_int(cap, "id", errors, where, minimum=1)
            if cap_id is not None:
                if cap_id in ids:
                    errors.append(f"{where}.id: duplicate capability id {cap_id}")
                ids.add(cap_id)
            kind = _require_str(cap, "kind", errors, where)
            if kind is not None and kind not in ALLOWED_CAPABILITY_KINDS:
                errors.append(f"{where}.kind: unsupported kind '{kind}'")
            _require_str(cap, "resource", errors, where)
            ops = cap.get("ops")
            if not isinstance(ops, list) or not ops or not all(isinstance(op, str) and op for op in ops):
                errors.append(f"{where}.ops: expected non-empty string array")
    else:
        errors.append("manifest.capabilities: expected array")

    payload = _require(manifest, "payload", errors, "manifest")
    if isinstance(payload, dict):
        sha = _require_str(payload, "sha256", errors, "manifest.payload")
        if sha is not None and (len(sha) != 64 or any(c not in "0123456789abcdefABCDEF" for c in sha)):
            errors.append("manifest.payload.sha256: expected 64 hex chars")
        _require_int(payload, "size_bytes", errors, "manifest.payload", minimum=0)
    else:
        errors.append("manifest.payload: expected object")

    signature = _require(manifest, "signature", errors, "manifest")
    if isinstance(signature, dict):
        _require_str(signature, "alg", errors, "manifest.signature")
        _require_str(signature, "key_id", errors, "manifest.signature")
        _require_str(signature, "value", errors, "manifest.signature")
    else:
        errors.append("manifest.signature: expected object")

    return errors


def validate_manifest_against_profile(manifest: dict[str, Any], profile: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    target = manifest.get("target") if isinstance(manifest.get("target"), dict) else {}
    device = profile.get("device") if isinstance(profile.get("device"), dict) else {}
    resources = profile.get("resources") if isinstance(profile.get("resources"), dict) else {}

    device_class = device.get("device_class")
    if isinstance(target, dict) and isinstance(target.get("device_class"), list):
        if device_class not in target.get("device_class", []):
            errors.append(f"manifest.target.device_class: profile class '{device_class}' not permitted")

    if isinstance(target, dict) and isinstance(target.get("soc"), list):
        hardware = device.get("hardware")
        if hardware not in target.get("soc", []):
            errors.append(f"manifest.target.soc: profile hardware '{hardware}' not permitted")

    caps = manifest.get("capabilities")
    if isinstance(caps, list):
        for idx, cap in enumerate(caps):
            if not isinstance(cap, dict):
                continue
            kind = cap.get("kind")
            resource = cap.get("resource")
            where = f"manifest.capabilities[{idx}]"
            if not isinstance(kind, str) or not isinstance(resource, str):
                continue
            if kind in SHELL_VIRTUAL_KINDS:
                continue
            section_name = PROFILE_RESOURCE_SECTION.get(kind)
            section = resources.get(section_name) if isinstance(resources, dict) else None
            if not isinstance(section, dict):
                errors.append(f"{where}: profile has no resource section for kind '{kind}'")
                continue
            if resource not in section:
                errors.append(f"{where}: resource '{resource}' not found in profile.resources.{section_name}")
    return errors


def run_profile(profile_path: Path) -> int:
    profile = load_json(profile_path)
    errors = validate_profile(profile)
    if errors:
        for err in errors:
            print(err, file=sys.stderr)
        return 1
    print(f"OK profile {profile_path}")
    return 0


def run_manifest(manifest_path: Path, profile_path: Path | None) -> int:
    manifest = load_json(manifest_path)
    errors = validate_manifest(manifest)
    if profile_path is not None:
        profile = load_json(profile_path)
        errors.extend(validate_profile(profile))
        errors.extend(validate_manifest_against_profile(manifest, profile))
    if errors:
        for err in errors:
            print(err, file=sys.stderr)
        return 1
    print(f"OK manifest {manifest_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate WDC R0 contract artifacts")
    sub = parser.add_subparsers(dest="command", required=True)
    p_profile = sub.add_parser("profile", help="validate a device profile")
    p_profile.add_argument("--profile", required=True, type=Path)
    p_manifest = sub.add_parser("manifest", help="validate a bundle manifest")
    p_manifest.add_argument("--manifest", required=True, type=Path)
    p_manifest.add_argument("--profile", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "profile":
        return run_profile(args.profile)
    if args.command == "manifest":
        return run_manifest(args.manifest, args.profile)
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
