#!/usr/bin/env python3
"""Generate deterministic HX2 valid and fail-closed admission vectors."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import struct
import sys
from pathlib import Path
from typing import Callable

try:
    from tools import inspect_native_extension
except ModuleNotFoundError:  # Direct execution from tools/.
    import inspect_native_extension  # type: ignore[no-redef]

SCHEMA = "pulse.esp32.hx2-admission-vectors.v1"


def _write(path: Path, data: bytes) -> None:
    path.write_bytes(data)


def _rehash(image: bytearray, metadata_offset: int) -> None:
    image[metadata_offset + 128 : metadata_offset + 160] = bytes(32)
    image[metadata_offset + 128 : metadata_offset + 160] = hashlib.sha256(image).digest()


def _metadata_mutation(
    valid: bytes,
    metadata_offset: int,
    mutate: Callable[[bytearray, int], None],
) -> bytes:
    image = bytearray(valid)
    mutate(image, metadata_offset)
    _rehash(image, metadata_offset)
    return bytes(image)


def _set_u16(image: bytearray, offset: int, value: int) -> None:
    struct.pack_into("<H", image, offset, value)


def _set_u32(image: bytearray, offset: int, value: int) -> None:
    struct.pack_into("<I", image, offset, value)


def _section_header_offset(image: bytes, section_index: int) -> int:
    section_table = struct.unpack_from("<I", image, 32)[0]
    section_stride = struct.unpack_from("<H", image, 46)[0]
    return section_table + section_index * section_stride


def _symbol_to_unresolved_import(image: bytes, report: dict[str, object], metadata_offset: int) -> bytes:
    result = bytearray(image)
    sections = report["sections"]
    assert isinstance(sections, list)
    by_index = {item["index"]: item for item in sections if isinstance(item, dict)}
    for section in sections:
        if not isinstance(section, dict) or section.get("type") not in (2, 11):
            continue
        strings = by_index[section["link"]]
        stride = section["entry_size"] or 16
        for index in range(section["size"] // stride):
            entry = section["offset"] + index * stride
            name_offset = struct.unpack_from("<I", result, entry)[0]
            start = strings["offset"] + name_offset
            end = result.find(0, start, strings["offset"] + strings["size"])
            if end < 0:
                continue
            name = bytes(result[start:end]).decode("ascii", errors="ignore")
            if name == "synthetic_init":
                result[entry + 12] = (1 << 4) | 2  # STB_GLOBAL | STT_FUNC
                struct.pack_into("<H", result, entry + 14, 0)  # SHN_UNDEF
                _rehash(result, metadata_offset)
                return bytes(result)
    raise RuntimeError("could not find synthetic_init symbol for unresolved-import vector")


def _descriptor(metadata: dict[str, object]) -> bytes:
    functions = (0x1000, 0x1004, 0x1008, 0x100C, 0x1010, 0x1014)
    return struct.pack(
        "<IIHHI16s32sHHI4I4I6I32s",
        inspect_native_extension.DESCRIPTOR_MAGIC,
        inspect_native_extension.DESCRIPTOR_SIZE,
        1,
        0,
        0,
        bytes.fromhex(str(metadata["extension_id"])),
        bytes.fromhex(str(metadata["normalized_metadata_sha256"])),
        int(metadata["event_count"]),
        int(metadata["operation_count"]),
        0,
        *[int(item) for item in metadata["event_ids"]],
        *[int(item) for item in metadata["operation_ids"]],
        *functions,
        bytes(32),
    )


def generate(s3: Path, c6: Path, output: Path) -> dict[str, object]:
    if output.exists():
        if not output.is_dir() or any(output.iterdir()):
            raise ValueError("output directory must be absent or empty")
    else:
        output.mkdir(parents=True)
    s3_report = inspect_native_extension.inspect_elf(s3, "esp32s3", require_extension=True)
    c6_report = inspect_native_extension.inspect_elf(c6, "esp32c6", require_extension=True)
    if s3_report["status"] != "PASS" or c6_report["status"] != "PASS":
        raise ValueError("valid source artifacts must pass strict extension inspection")
    valid_s3 = s3.read_bytes()
    valid_c6 = c6.read_bytes()
    s3_meta = s3_report["metadata"]
    c6_meta = c6_report["metadata"]
    assert isinstance(s3_meta, dict) and isinstance(c6_meta, dict)
    s3_offset = int(s3_meta["file_offset"])
    c6_offset = int(c6_meta["file_offset"])
    _write(output / "valid-esp32s3.elf", valid_s3)
    _write(output / "valid-esp32c6.elf", valid_c6)

    pre_execution: list[dict[str, str]] = []

    def add(name: str, data: bytes, target: str, token: str) -> None:
        filename = f"invalid-{name}.elf"
        _write(output / filename, data)
        pre_execution.append(
            {"name": name, "file": filename, "expected_target": target, "expected_error": token}
        )

    wrong_machine = bytearray(valid_s3)
    _set_u16(wrong_machine, 18, 243)
    _rehash(wrong_machine, s3_offset)
    add("wrong-machine", bytes(wrong_machine), "esp32s3", "does not match esp32s3")
    add(
        "wrong-target-id",
        _metadata_mutation(valid_s3, s3_offset, lambda image, base: _set_u16(image, base + 18, 9)),
        "esp32s3",
        "metadata target identity",
    )
    add(
        "unknown-metadata-version",
        _metadata_mutation(valid_s3, s3_offset, lambda image, base: _set_u16(image, base + 8, 2)),
        "esp32s3",
        "metadata format version",
    )
    truncated = bytearray(valid_s3)
    metadata_section = next(item for item in s3_report["sections"] if item["name"] == ".pulse_ext_meta")
    metadata_header = _section_header_offset(valid_s3, metadata_section["index"])
    _set_u32(truncated, metadata_header + 20, 191)
    add("truncated-metadata", bytes(truncated), "esp32s3", ".pulse_ext_meta size")
    outside = bytearray(valid_s3)
    _set_u32(outside, metadata_header + 16, len(outside) + 4)
    add("metadata-outside-bounds", bytes(outside), "esp32s3", "range exceeds file bounds")
    add(
        "duplicate-event-id",
        _metadata_mutation(
            valid_s3,
            s3_offset,
            lambda image, base: (_set_u16(image, base + 56, 2), image.__setitem__(slice(base + 68, base + 72), image[base + 64 : base + 68])),
        ),
        "esp32s3",
        "duplicate event identity",
    )
    add(
        "duplicate-operation-id",
        _metadata_mutation(
            valid_s3,
            s3_offset,
            lambda image, base: (_set_u16(image, base + 58, 2), image.__setitem__(slice(base + 84, base + 88), image[base + 80 : base + 84])),
        ),
        "esp32s3",
        "duplicate operation identity",
    )
    add(
        "incompatible-abi-major",
        _metadata_mutation(valid_s3, s3_offset, lambda image, base: _set_u16(image, base + 24, 2)),
        "esp32s3",
        "host ABI major",
    )
    add(
        "unsupported-required-abi-minor",
        _metadata_mutation(valid_s3, s3_offset, lambda image, base: _set_u16(image, base + 26, 1)),
        "esp32s3",
        "host ABI minor",
    )
    add(
        "wrong-descriptor-size-metadata",
        _metadata_mutation(valid_s3, s3_offset, lambda image, base: _set_u32(image, base + 48, 156)),
        "esp32s3",
        "metadata descriptor size",
    )
    add(
        "nonzero-metadata-reserved",
        _metadata_mutation(valid_s3, s3_offset, lambda image, base: _set_u32(image, base + 60, 1)),
        "esp32s3",
        "metadata reserved fields",
    )
    add(
        "budget-above-profile",
        _metadata_mutation(valid_s3, s3_offset, lambda image, base: _set_u32(image, base + 100, 16384)),
        "esp32s3",
        "task stack",
    )
    mismatch = bytearray(valid_s3)
    text_section = next(item for item in s3_report["sections"] if item["name"] == ".text")
    mismatch[text_section["offset"]] ^= 1
    add("artifact-hash-mismatch", bytes(mismatch), "esp32s3", "artifact hash mismatch")
    unresolved = _symbol_to_unresolved_import(valid_s3, s3_report, s3_offset)
    add("unexpected-import", unresolved, "esp32s3", "unexpected")
    add("unresolved-import", unresolved, "esp32s3", "unresolved")

    valid_descriptor = _descriptor(s3_meta)
    _write(output / "valid-descriptor.bin", valid_descriptor)
    descriptor_vectors: list[dict[str, str]] = []

    def add_descriptor(name: str, data: bytes, token: str) -> None:
        filename = f"invalid-descriptor-{name}.bin"
        _write(output / filename, data)
        descriptor_vectors.append({"name": name, "file": filename, "expected_error": token})

    add_descriptor("wrong-size", valid_descriptor[:-1], "descriptor size")
    identity = bytearray(valid_descriptor)
    identity[16] ^= 1
    add_descriptor("identity-disagreement", bytes(identity), "identity disagreement")
    digest = bytearray(valid_descriptor)
    digest[32] ^= 1
    add_descriptor("hash-mismatch", bytes(digest), "hash disagreement")
    reserved = bytearray(valid_descriptor)
    reserved[128] = 1
    add_descriptor("nonzero-reserved", bytes(reserved), "reserved fields")
    missing = bytearray(valid_descriptor)
    _set_u32(missing, 104, 0)
    add_descriptor("missing-lifecycle", bytes(missing), "missing lifecycle function")

    manifest: dict[str, object] = {
        "schema": SCHEMA,
        "valid": [
            {"file": "valid-esp32s3.elf", "expected_target": "esp32s3"},
            {"file": "valid-esp32c6.elf", "expected_target": "esp32c6"},
        ],
        "pre_execution_rejections": pre_execution,
        "descriptor_metadata_file": "valid-esp32s3.elf",
        "valid_descriptor": "valid-descriptor.bin",
        "descriptor_rejections": descriptor_vectors,
        "registry_rejections": [
            {"name": "duplicate-extension-identity", "files": ["valid-descriptor.bin", "valid-descriptor.bin"], "expected_error": "duplicate extension identity"}
        ],
        "proof": {
            "pre_execution_lifecycle_calls": 0,
            "descriptor_rejection_lifecycle_calls": 0,
        },
    }
    (output / "vectors.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--s3-elf", type=Path, required=True)
    parser.add_argument("--c6-elf", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        manifest = generate(args.s3_elf, args.c6_elf, args.out_dir)
    except (OSError, RuntimeError, ValueError, inspect_native_extension.ElfInspectionError) as exc:
        print(f"HX2 vector generation failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"status": "PASS", "vectors": len(manifest["pre_execution_rejections"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
