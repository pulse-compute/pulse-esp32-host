#!/usr/bin/env python3
"""Build a WDC R9 bundle container.

Container v1 layout:
  magic[8] = b"WDCBNDL\0"
  u16 container_version
  u16 header_len (=120)
  u32 manifest_len
  u32 payload_len
  manifest_sha256[32]
  payload_sha256[32]
  u16 signature_alg
  u16 signature_len
  reserved[32]
  manifest bytes
  payload bytes
  signature bytes

R9 supports deterministic development HMAC-SHA256 bundles. Production-profile test vectors are emitted by tools/wdc_bundle_tool.py because firmware production mode requires a verifier callback.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import hmac
import json
import struct
import sys
from pathlib import Path
from typing import Any

MAGIC = b"WDCBNDL\0"
CONTAINER_VERSION = 1
HEADER_LEN = 120
SIG_NONE = 0
SIG_HMAC_SHA256_DEV = 1
SIG_ED25519 = 2
DEV_KEY = b"wdc-dev-bundle-signing-key-r6"
DEV_SIG_ALG_TEXT = "hmac-sha256-dev"
DEV_SIGNATURE_VALUE = "external-bundle-signature"


def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("manifest top-level JSON must be an object")
    return data


def canonical_json_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def update_manifest(template: dict[str, Any], payload: bytes, key_id: str, sig_alg_text: str) -> dict[str, Any]:
    manifest = copy.deepcopy(template)
    manifest.setdefault("payload", {})
    manifest["payload"]["sha256"] = hashlib.sha256(payload).hexdigest()
    manifest["payload"]["size_bytes"] = len(payload)
    manifest.setdefault("signature", {})
    manifest["signature"]["alg"] = sig_alg_text
    manifest["signature"]["key_id"] = key_id
    manifest["signature"]["value"] = DEV_SIGNATURE_VALUE
    return manifest


def build_header(manifest: bytes, payload: bytes, signature_alg: int, signature_len: int) -> bytes:
    header = struct.pack(
        "<8sHHII32s32sHH32s",
        MAGIC,
        CONTAINER_VERSION,
        HEADER_LEN,
        len(manifest),
        len(payload),
        hashlib.sha256(manifest).digest(),
        hashlib.sha256(payload).digest(),
        signature_alg,
        signature_len,
        bytes(32),
    )
    if len(header) != HEADER_LEN:
        raise AssertionError(f"internal header length mismatch: {len(header)}")
    return header


def build_bundle(manifest: dict[str, Any], payload: bytes, signature_alg: int) -> tuple[bytes, bytes, bytes, bytes]:
    manifest_bytes = canonical_json_bytes(manifest)
    if signature_alg == SIG_NONE:
        signature = b""
    elif signature_alg == SIG_HMAC_SHA256_DEV:
        provisional_header = build_header(manifest_bytes, payload, signature_alg, 32)
        signature = hmac.new(DEV_KEY, provisional_header + manifest_bytes + payload, hashlib.sha256).digest()
    else:
        raise ValueError("R9 package tool can only emit none or hmac-sha256-dev signatures")
    header = build_header(manifest_bytes, payload, signature_alg, len(signature))
    return header + manifest_bytes + payload + signature, header, manifest_bytes, signature


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a WDC R9 bundle container")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--payload", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--manifest-out", type=Path)
    parser.add_argument("--key-id", default="dev-r6")
    parser.add_argument("--signature", choices=["hmac-sha256-dev", "none"], default="hmac-sha256-dev")
    parser.add_argument("--metadata-out", type=Path)
    args = parser.parse_args(argv)

    try:
        template = load_json(args.manifest)
        payload = args.payload.read_bytes()
        signature_alg = SIG_HMAC_SHA256_DEV if args.signature == "hmac-sha256-dev" else SIG_NONE
        sig_alg_text = DEV_SIG_ALG_TEXT if signature_alg == SIG_HMAC_SHA256_DEV else "none-dev"
        manifest = update_manifest(template, payload, args.key_id, sig_alg_text)
        bundle, header, manifest_bytes, signature = build_bundle(manifest, payload, signature_alg)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_bytes(bundle)
        if args.manifest_out:
            args.manifest_out.parent.mkdir(parents=True, exist_ok=True)
            args.manifest_out.write_bytes(manifest_bytes)
        metadata = {
            "schema": "wdc.r6.bundle_metadata.v1",
            "bundle_path": str(args.out),
            "bundle_size_bytes": len(bundle),
            "container_version": CONTAINER_VERSION,
            "header_len": HEADER_LEN,
            "manifest_size_bytes": len(manifest_bytes),
            "payload_size_bytes": len(payload),
            "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
            "payload_sha256": hashlib.sha256(payload).hexdigest(),
            "signature_alg": sig_alg_text,
            "signature_alg_id": signature_alg,
            "signature_key_id": args.key_id,
            "signature_len": len(signature),
            "signature_hex": signature.hex(),
            "header_sha256": hashlib.sha256(header).hexdigest(),
        }
        if args.metadata_out:
            args.metadata_out.parent.mkdir(parents=True, exist_ok=True)
            args.metadata_out.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        else:
            print(json.dumps(metadata, indent=2, sort_keys=True))
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"wdc_package_bundle: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
