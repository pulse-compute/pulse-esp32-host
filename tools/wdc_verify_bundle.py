#!/usr/bin/env python3
"""Verify a WDC R9 bundle container with only Python stdlib dependencies."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import struct
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.wdc_validate import ValidationErrorSet, load_json, validate_manifest, validate_manifest_against_profile  # noqa: E402

MAGIC = b"WDCBNDL\0"
HEADER_LEN = 120
CONTAINER_VERSION = 1
SIG_NONE = 0
SIG_HMAC_SHA256_DEV = 1
SIG_ED25519 = 2
ED25519_SIG_LEN = 64
PROD_TEST_CONTEXT = b"WDC-R9-ED25519-TEST-VECTOR"
DEV_KEY = b"wdc-dev-bundle-signing-key-r6"


def parse_bundle(data: bytes) -> dict[str, Any]:
    if len(data) < HEADER_LEN:
        raise ValueError("bundle shorter than WDC R9 header")
    magic, version, header_len, manifest_len, payload_len, manifest_sha, payload_sha, signature_alg, signature_len, _reserved = struct.unpack(
        "<8sHHII32s32sHH32s", data[:HEADER_LEN]
    )
    if magic != MAGIC:
        raise ValueError("bad bundle magic")
    if version != CONTAINER_VERSION or header_len != HEADER_LEN:
        raise ValueError("unsupported bundle container version/header length")
    manifest_offset = header_len
    payload_offset = manifest_offset + manifest_len
    signature_offset = payload_offset + payload_len
    total_len = signature_offset + signature_len
    if manifest_len == 0 or payload_len == 0:
        raise ValueError("manifest and payload must be non-empty")
    if total_len > len(data):
        raise ValueError("bundle sections extend past file length")
    return {
        "header": data[:HEADER_LEN],
        "manifest": data[manifest_offset:payload_offset],
        "payload": data[payload_offset:signature_offset],
        "signature": data[signature_offset:total_len],
        "manifest_sha256": manifest_sha,
        "payload_sha256": payload_sha,
        "signature_alg": signature_alg,
        "signature_len": signature_len,
        "total_len": total_len,
    }


def wasm_has_required_exports(payload: bytes) -> bool:
    return all(name in payload for name in [
        b"wdc_module_init",
        b"wdc_module_on_event",
        b"wdc_module_health",
        b"wdc_module_shutdown",
    ])


def verify_bundle(bundle_path: Path,
                  profile_path: Path | None,
                  min_security_counter: int,
                  production_mode: bool,
                  allow_unsigned_dev: bool) -> dict[str, Any]:
    data = bundle_path.read_bytes()
    result: dict[str, Any] = {
        "schema": "wdc.r6.bundle_verification.v1",
        "bundle_path": str(bundle_path),
        "status": "FAIL",
        "checks": {},
    }
    parsed = parse_bundle(data)
    manifest_bytes: bytes = parsed["manifest"]
    payload: bytes = parsed["payload"]
    signature: bytes = parsed["signature"]
    result["checks"]["structure"] = "PASS"

    if parsed["total_len"] != len(data):
        raise ValueError("bundle has trailing bytes")
    result["checks"]["no_trailing_bytes"] = "PASS"

    if hashlib.sha256(manifest_bytes).digest() != parsed["manifest_sha256"]:
        raise ValueError("manifest sha256 mismatch")
    result["checks"]["manifest_hash"] = "PASS"
    if hashlib.sha256(payload).digest() != parsed["payload_sha256"]:
        raise ValueError("payload sha256 mismatch")
    result["checks"]["payload_hash"] = "PASS"

    manifest = json.loads(manifest_bytes.decode("utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("manifest JSON must be an object")
    errors = validate_manifest(manifest)
    if errors:
        raise ValidationErrorSet(errors)
    result["checks"]["manifest_schema"] = "PASS"

    if manifest["payload"]["sha256"].lower() != hashlib.sha256(payload).hexdigest():
        raise ValueError("manifest payload sha256 does not match payload")
    if manifest["payload"]["size_bytes"] != len(payload):
        raise ValueError("manifest payload size does not match payload")
    result["checks"]["manifest_payload_binding"] = "PASS"

    if manifest["security_counter"] < min_security_counter:
        raise ValueError(f"security counter rollback: {manifest['security_counter']} < {min_security_counter}")
    result["checks"]["anti_rollback"] = "PASS"

    runtime = manifest.get("runtime", {})
    if runtime.get("engine") != "wamr" or runtime.get("payload_kind") != "wasm":
        raise ValueError("R9 verifier expects runtime.engine=wamr and payload_kind=wasm")
    features = runtime.get("wasm_features", {})
    if features.get("threads") or features.get("shared_memory") or features.get("wasi"):
        raise ValueError("unsupported wasm feature requested")
    if not wasm_has_required_exports(payload):
        raise ValueError("required WDC WASM exports missing from payload")
    result["checks"]["runtime_payload"] = "PASS"

    if profile_path is not None:
        profile = load_json(profile_path)
        errors = validate_manifest_against_profile(manifest, profile)
        if errors:
            raise ValidationErrorSet(errors)
        result["checks"]["profile_compatibility"] = "PASS"
    else:
        result["checks"]["profile_compatibility"] = "SKIPPED"

    signature_alg = parsed["signature_alg"]
    if signature_alg == SIG_NONE:
        if production_mode or not allow_unsigned_dev:
            raise ValueError("unsigned development bundles disabled by policy")
    elif signature_alg == SIG_HMAC_SHA256_DEV:
        if production_mode:
            raise ValueError("development HMAC signature disabled in production mode")
        expected = hmac.new(DEV_KEY, parsed["header"] + manifest_bytes + payload, hashlib.sha256).digest()
        if signature != expected:
            raise ValueError("development HMAC signature mismatch")
    elif signature_alg == SIG_ED25519:
        raise ValueError("production Ed25519 verifier callback is not available in standalone verifier; use wdc_bundle_tool.py --test-production-verifier for R9 test vectors")
    else:
        raise ValueError(f"unsupported signature algorithm id {signature_alg}")
    result["checks"]["signature"] = "PASS"

    result.update({
        "status": "PASS",
        "bundle_id": manifest["bundle_id"],
        "bundle_version": manifest["bundle_version"],
        "security_counter": manifest["security_counter"],
        "payload_size_bytes": len(payload),
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "payload_sha256": hashlib.sha256(payload).hexdigest(),
        "signature_alg_id": signature_alg,
        "signature_alg": manifest["signature"]["alg"],
        "signature_key_id": manifest["signature"]["key_id"],
    })
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify a WDC R9 bundle")
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--min-security-counter", type=int, default=0)
    parser.add_argument("--production-mode", action="store_true")
    parser.add_argument("--allow-unsigned-dev", action="store_true")
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args(argv)
    try:
        report = verify_bundle(
            args.bundle,
            args.profile,
            args.min_security_counter,
            args.production_mode,
            args.allow_unsigned_dev,
        )
        payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
        if args.json_out:
            args.json_out.parent.mkdir(parents=True, exist_ok=True)
            args.json_out.write_text(payload, encoding="utf-8")
        else:
            print(payload, end="")
        return 0
    except Exception as exc:  # noqa: BLE001
        report = {
            "schema": "wdc.r6.bundle_verification.v1",
            "bundle_path": str(args.bundle),
            "status": "FAIL",
            "error": str(exc),
        }
        payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
        if args.json_out:
            args.json_out.parent.mkdir(parents=True, exist_ok=True)
            args.json_out.write_text(payload, encoding="utf-8")
        print(payload, end="", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
