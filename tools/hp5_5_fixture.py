#!/usr/bin/env python3
"""Deterministic HP5.5 Wasm and application-artifact fixture construction."""
from __future__ import annotations

import binascii
import hashlib
import json
import struct
from pathlib import Path
from typing import Any

try:
    from tools import wdc_bundle_tool
except ModuleNotFoundError:  # Direct execution from tools/.
    import wdc_bundle_tool  # type: ignore[no-redef]


ROOT = Path(__file__).resolve().parents[1]
BASE_MANIFEST = ROOT / "examples/bundles/relay-controller/manifest.json"
WDC_APP_ARTIFACT_MAGIC = 0x50534150
WDC_APP_ARTIFACT_VERSION = 1
WDC_APP_ARTIFACT_HEADER_BYTES = 192
WDC_HOST_CAP_ALL_V1 = 0x0F
WDC_HOST_TARGET_MASK_ALL = 0x03
WDC_HOST_PLACEMENT_PORTABLE = 1

I32 = 0x7F


def _u32(value: int) -> bytes:
    result = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            result.append(byte | 0x80)
        else:
            result.append(byte)
            return bytes(result)


def _vec(items: list[bytes]) -> bytes:
    return _u32(len(items)) + b"".join(items)


def _name(value: str) -> bytes:
    encoded = value.encode("utf-8")
    return _u32(len(encoded)) + encoded


def _section(identifier: int, payload: bytes) -> bytes:
    return bytes([identifier]) + _u32(len(payload)) + payload


def _function_type(parameters: list[int], results: list[int]) -> bytes:
    return (
        b"\x60"
        + bytes([len(parameters)])
        + bytes(parameters)
        + bytes([len(results)])
        + bytes(results)
    )


def _code_body(instructions: bytes) -> bytes:
    body = b"\x00" + instructions + b"\x0b"
    return _u32(len(body)) + body


def make_http_responder_wasm() -> bytes:
    """Return a real common Wasm handler for the first HP5.5 request.

    The first service request has request id 1. The module issues the exact
    paired HTTP response effect with a fixed `hp55` body. Later cases exercise
    no-response and rejection behavior through the same host service.
    """

    types = _section(
        1,
        _vec(
            [
                _function_type([I32, I32, I32, I32, I32], [I32]),
                _function_type([], [I32]),
                _function_type([I32, I32], [I32]),
                _function_type([I32], [I32]),
            ]
        ),
    )
    imports = _section(
        2,
        _vec([_name("wdc") + _name("wdc_host_call") + b"\x00" + _u32(0)]),
    )
    functions = _section(3, _vec([_u32(1), _u32(2), _u32(1), _u32(3)]))
    memory = _section(5, _vec([b"\x00" + _u32(1)]))
    exports = _section(
        7,
        _vec(
            [
                _name("memory") + b"\x02" + _u32(0),
                _name("wdc_module_init") + b"\x00" + _u32(1),
                _name("wdc_module_on_event") + b"\x00" + _u32(2),
                _name("wdc_module_health") + b"\x00" + _u32(3),
                _name("wdc_module_shutdown") + b"\x00" + _u32(4),
            ]
        ),
    )
    # CBOR: {3:22, 28:1, 31:200, 9:h'hp55'}.
    response_request = b"\xa4\x03\x16\x18\x1c\x01\x18\x1f\x18\xc8\x09\x44hp55"
    request_offset = 1024
    response_offset = 2048
    on_event = (
        b"\x41" + _u32(0x0505)
        + b"\x41" + _u32(request_offset)
        + b"\x41" + _u32(len(response_request))
        + b"\x41" + _u32(response_offset)
        + b"\x41" + _u32(64)
        + b"\x10" + _u32(0)
    )
    code = _section(
        10,
        _vec(
            [
                _code_body(b"\x41\x00"),
                _code_body(on_event),
                _code_body(b"\x41\x00"),
                _code_body(b"\x41\x00"),
            ]
        ),
    )
    data_entry = (
        b"\x00"
        + b"\x41"
        + _u32(request_offset)
        + b"\x0b"
        + _u32(len(response_request))
        + response_request
    )
    data = _section(11, _vec([data_entry]))
    metadata = _section(
        0,
        _name("pulse.hp5_5")
        + b"common-wasm-http-response;request-id=1;body=hp55",
    )
    return b"\x00asm\x01\x00\x00\x00" + types + imports + functions + memory + exports + code + data + metadata


def make_bundle(version: int) -> bytes:
    if version < 1 or version > 0xFFFFFFFF:
        raise ValueError("bundle version is outside uint32")
    manifest = json.loads(BASE_MANIFEST.read_text(encoding="utf-8"))
    manifest["bundle_id"] = "com.pulse.hp5_5.network-audit"
    manifest["bundle_version"] = version
    manifest["bundle_semver"] = f"0.{version}.0"
    manifest["security_counter"] = version
    manifest["target"]["soc"] = ["esp32-c6", "esp32-s3"]
    payload = make_http_responder_wasm()
    patched = wdc_bundle_tool.patch_manifest(
        manifest, payload, "hmac-sha256-dev", "dev-r6"
    )
    manifest_bytes = wdc_bundle_tool.canonical_json_bytes(patched)
    header = wdc_bundle_tool.header_pack(
        manifest_bytes, payload, wdc_bundle_tool.SIG_HMAC_SHA256_DEV, 32
    )
    signature = wdc_bundle_tool.sign(
        header,
        manifest_bytes,
        payload,
        wdc_bundle_tool.SIG_HMAC_SHA256_DEV,
        wdc_bundle_tool.DEFAULT_DEV_KEY,
        "dev-r6",
    )
    bundle = header + manifest_bytes + payload + signature
    verification = wdc_bundle_tool.verify_bytes(bundle)
    if verification.get("status") != "PASS":
        raise ValueError("constructed HP5.5 bundle does not verify")
    return bundle


def make_artifact(version: int) -> bytes:
    bundle = make_bundle(version)
    application_id = b"com.pulse.hp5_5.network-audit"
    requirements = (
        WDC_HOST_TARGET_MASK_ALL,
        1,
        0,
        0,
        WDC_HOST_CAP_ALL_V1,
        WDC_HOST_PLACEMENT_PORTABLE,
        49152,
        16384,
        8192,
        4096,
        0,
        8192,
        49152,
        0,
        4,
        0,
    )
    header = bytearray(WDC_APP_ARTIFACT_HEADER_BYTES)
    struct.pack_into(
        "<IHHIIIIQ16I",
        header,
        0,
        WDC_APP_ARTIFACT_MAGIC,
        WDC_APP_ARTIFACT_VERSION,
        WDC_APP_ARTIFACT_HEADER_BYTES,
        WDC_APP_ARTIFACT_HEADER_BYTES + len(bundle),
        len(bundle),
        version,
        0,
        version,
        *requirements,
    )
    header[96:128] = hashlib.sha256(bundle).digest()
    header[128:160] = hashlib.sha256(application_id).digest()
    struct.pack_into("<I", header, 188, 0)
    struct.pack_into("<I", header, 188, binascii.crc32(header) & 0xFFFFFFFF)
    artifact = bytes(header) + bundle
    if len(artifact) != struct.unpack_from("<I", header, 8)[0]:
        raise ValueError("constructed HP5.5 artifact length is incoherent")
    return artifact


def c_array(symbol: str, data: bytes) -> str:
    rows = []
    for offset in range(0, len(data), 12):
        rows.append(
            "    "
            + ", ".join(f"0x{byte:02x}u" for byte in data[offset : offset + 12])
            + ","
        )
    return (
        f"const uint8_t {symbol}[] __attribute__((aligned(4))) = {{\n"
        + "\n".join(rows)
        + f"\n}};\nconst uint32_t {symbol}_len = {len(data)}u;\n"
    )


def artifact_inventory() -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for role, version in (("baseline", 8), ("positive", 9), ("fallback", 10)):
        artifact = make_artifact(version)
        result[role] = {
            "version": version,
            "bytes": len(artifact),
            "sha256": hashlib.sha256(artifact).hexdigest(),
            "bundle_sha256": hashlib.sha256(make_bundle(version)).hexdigest(),
        }
    return result


if __name__ == "__main__":
    print(json.dumps(artifact_inventory(), indent=2, sort_keys=True))
