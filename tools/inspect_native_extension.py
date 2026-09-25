#!/usr/bin/env python3
"""Bounded, dependency-free ELF32 inventory for the HX extension proof."""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from collections import Counter
from pathlib import Path
from typing import Any

SCHEMA = "pulse.esp32.native-elf-inspection.v1"
METADATA_MAGIC = b"PULSEXT1"
METADATA_SIZE = 192
DESCRIPTOR_MAGIC = 0x31545845
DESCRIPTOR_SIZE = 160
ENTRY_EXPORT = "pulse_extension_entry_v1"

ELF_TYPES = {0: "ET_NONE", 1: "ET_REL", 2: "ET_EXEC", 3: "ET_DYN", 4: "ET_CORE"}
MACHINES = {94: "EM_XTENSA", 243: "EM_RISCV"}
TARGET_MACHINES = {"esp32s3": 94, "esp32c6": 243}
TARGET_IDENTITIES = {"esp32s3": (1, 1), "esp32c6": (2, 2)}
SECTION_TYPES = {
    0: "SHT_NULL",
    1: "SHT_PROGBITS",
    2: "SHT_SYMTAB",
    3: "SHT_STRTAB",
    4: "SHT_RELA",
    5: "SHT_HASH",
    6: "SHT_DYNAMIC",
    7: "SHT_NOTE",
    8: "SHT_NOBITS",
    9: "SHT_REL",
    11: "SHT_DYNSYM",
}
PROGRAM_TYPES = {
    0: "PT_NULL",
    1: "PT_LOAD",
    2: "PT_DYNAMIC",
    3: "PT_INTERP",
    6: "PT_PHDR",
    7: "PT_TLS",
}
SYMBOL_BINDINGS = {0: "LOCAL", 1: "GLOBAL", 2: "WEAK"}
SYMBOL_TYPES = {0: "NOTYPE", 1: "OBJECT", 2: "FUNC", 3: "SECTION", 4: "FILE", 5: "COMMON", 6: "TLS"}

RELOCATIONS = {
    94: {
        0: "R_XTENSA_NONE",
        1: "R_XTENSA_32",
        2: "R_XTENSA_RTLD",
        3: "R_XTENSA_GLOB_DAT",
        4: "R_XTENSA_JMP_SLOT",
        5: "R_XTENSA_RELATIVE",
        6: "R_XTENSA_PLT",
        8: "R_XTENSA_OP0",
        9: "R_XTENSA_OP1",
        10: "R_XTENSA_OP2",
    },
    243: {
        0: "R_RISCV_NONE",
        1: "R_RISCV_32",
        2: "R_RISCV_64",
        3: "R_RISCV_RELATIVE",
        4: "R_RISCV_COPY",
        5: "R_RISCV_JUMP_SLOT",
        16: "R_RISCV_BRANCH",
        17: "R_RISCV_JAL",
        18: "R_RISCV_CALL",
        19: "R_RISCV_CALL_PLT",
        20: "R_RISCV_GOT_HI20",
        23: "R_RISCV_PCREL_HI20",
        24: "R_RISCV_PCREL_LO12_I",
        25: "R_RISCV_PCREL_LO12_S",
        26: "R_RISCV_HI20",
        27: "R_RISCV_LO12_I",
        28: "R_RISCV_LO12_S",
        43: "R_RISCV_ALIGN",
        51: "R_RISCV_RELAX",
    },
}

# Exact cases implemented by elf_loader 1.3.2 arch relocation switches.
LOADER_SUPPORTED = {
    94: (2, 3, 4, 5),
    243: (0, 1, 3, 5),
}

CONSTRUCTOR_SECTIONS = {".init_array", ".fini_array", ".ctors", ".dtors"}
DYNAMIC_TAGS = {1: "DT_NEEDED", 12: "DT_INIT", 13: "DT_FINI"}
S3_LOADER_PACK_ORDER = (".data", ".rodata", ".data.rel.ro", ".bss")
S3_LOADER_MAX_WRITABLE_ALIGNMENT = 4096


class ElfInspectionError(ValueError):
    """Raised for a structurally unsafe or unsupported ELF input."""


def _all_zero(value: bytes) -> bool:
    return not any(value)


def _catalog_errors(values: list[int], count: int, label: str) -> list[str]:
    errors: list[str] = []
    if count < 1 or count > 4:
        errors.append(f"{label} count must be between 1 and 4")
        return errors
    active = values[:count]
    if any(item == 0 for item in active):
        errors.append(f"active {label} identities must be nonzero")
    if len(set(active)) != len(active):
        errors.append(f"duplicate {label} identity")
    if any(values[count:]):
        errors.append(f"unused {label} identities must be zero")
    return errors


def _parse_metadata(record: bytes, *, data: bytes, file_offset: int, expected_target: str | None) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    if len(record) != METADATA_SIZE:
        return {}, [f".pulse_ext_meta size is {len(record)}, expected {METADATA_SIZE}"]
    values = struct.unpack("<8sHHIHHIHHHH16sIIHHI4I4I8I32s32s", record)
    (
        magic,
        format_major,
        format_minor,
        record_size,
        architecture_id,
        soc_id,
        flags,
        required_host_abi_major,
        required_host_abi_min_minor,
        extension_abi_major,
        extension_abi_minor,
        extension_id,
        descriptor_size,
        descriptor_alignment,
        event_count,
        operation_count,
        reserved0,
        *tail,
    ) = values
    event_ids = list(tail[:4])
    operation_ids = list(tail[4:8])
    budgets = list(tail[8:16])
    artifact_sha256 = tail[16]
    reserved1 = tail[17]
    (
        task_count,
        task_stack_bytes,
        static_memory_bytes,
        queue_depth,
        queue_item_bytes,
        max_event_payload_bytes,
        max_effect_request_bytes,
        max_effect_completion_bytes,
    ) = budgets

    if magic != METADATA_MAGIC:
        errors.append("metadata magic is invalid")
    if (format_major, format_minor) != (1, 0):
        errors.append("metadata format version is unsupported")
    if record_size != METADATA_SIZE:
        errors.append("metadata record_size is invalid")
    if expected_target and (architecture_id, soc_id) != TARGET_IDENTITIES[expected_target]:
        errors.append(f"metadata target identity does not match {expected_target}")
    if flags != 0:
        errors.append("metadata flags must be zero")
    if required_host_abi_major != 1:
        errors.append("required host ABI major is incompatible")
    if required_host_abi_min_minor > 0:
        errors.append("required host ABI minor is unsupported")
    if (extension_abi_major, extension_abi_minor) != (1, 0):
        errors.append("extension ABI version is unsupported")
    if _all_zero(extension_id):
        errors.append("extension identity must be nonzero")
    if descriptor_size != DESCRIPTOR_SIZE:
        errors.append("metadata descriptor size is invalid")
    if descriptor_alignment != 4:
        errors.append("metadata descriptor alignment is invalid")
    errors.extend(_catalog_errors(event_ids, event_count, "event"))
    errors.extend(_catalog_errors(operation_ids, operation_count, "operation"))
    if reserved0 != 0 or not _all_zero(reserved1):
        errors.append("metadata reserved fields must be zero")
    if task_count != 1:
        errors.append("metadata task count must be exactly one")
    if task_stack_bytes < 2048 or task_stack_bytes > 8192 or task_stack_bytes % 16:
        errors.append("metadata task stack exceeds the host profile")
    if static_memory_bytes > 16384:
        errors.append("metadata static memory exceeds the host profile")
    if queue_depth < 1 or queue_depth > 16:
        errors.append("metadata queue depth exceeds the host profile")
    if queue_item_bytes < 32 or queue_item_bytes > 512 or queue_item_bytes % 4:
        errors.append("metadata queue item size exceeds the host profile")
    if queue_depth * queue_item_bytes > 4096:
        errors.append("metadata queue storage exceeds the host profile")
    if max_event_payload_bytes > 128:
        errors.append("metadata event payload exceeds the host profile")
    if max_effect_request_bytes > 256:
        errors.append("metadata effect request exceeds the host profile")
    if max_effect_completion_bytes > 256:
        errors.append("metadata effect completion exceeds the host profile")

    normalized_elf = bytearray(data)
    normalized_elf[file_offset + 128 : file_offset + 160] = bytes(32)
    normalized_artifact_sha256 = hashlib.sha256(normalized_elf).digest()
    normalized_metadata = bytearray(record)
    normalized_metadata[128:160] = bytes(32)
    normalized_metadata_sha256 = hashlib.sha256(normalized_metadata).digest()
    if artifact_sha256 != normalized_artifact_sha256:
        errors.append("metadata artifact hash mismatch")

    parsed = {
        "magic": magic.decode("ascii", errors="replace"),
        "format_major": format_major,
        "format_minor": format_minor,
        "record_size": record_size,
        "architecture_id": architecture_id,
        "soc_id": soc_id,
        "flags": flags,
        "required_host_abi_major": required_host_abi_major,
        "required_host_abi_min_minor": required_host_abi_min_minor,
        "extension_abi_major": extension_abi_major,
        "extension_abi_minor": extension_abi_minor,
        "extension_id": extension_id.hex(),
        "descriptor_size": descriptor_size,
        "descriptor_alignment": descriptor_alignment,
        "event_count": event_count,
        "operation_count": operation_count,
        "event_ids": event_ids,
        "operation_ids": operation_ids,
        "task_count": task_count,
        "task_stack_bytes": task_stack_bytes,
        "static_memory_bytes": static_memory_bytes,
        "queue_depth": queue_depth,
        "queue_item_bytes": queue_item_bytes,
        "max_event_payload_bytes": max_event_payload_bytes,
        "max_effect_request_bytes": max_effect_request_bytes,
        "max_effect_completion_bytes": max_effect_completion_bytes,
        "artifact_sha256": artifact_sha256.hex(),
        "normalized_artifact_sha256": normalized_artifact_sha256.hex(),
        "normalized_metadata_sha256": normalized_metadata_sha256.hex(),
        "reserved_zero": reserved0 == 0 and _all_zero(reserved1),
        "file_offset": file_offset,
    }
    return parsed, errors


def _range(data: bytes, offset: int, size: int, label: str) -> memoryview:
    if offset < 0 or size < 0 or offset > len(data) or size > len(data) - offset:
        raise ElfInspectionError(f"{label} range exceeds file bounds")
    return memoryview(data)[offset : offset + size]


def _unpack(fmt: str, data: bytes, offset: int, label: str) -> tuple[Any, ...]:
    size = struct.calcsize(fmt)
    return struct.unpack(fmt, _range(data, offset, size, label))


def _string(table: memoryview, offset: int, label: str) -> str:
    if offset < 0 or offset >= len(table):
        raise ElfInspectionError(f"{label} offset exceeds string table")
    raw = table[offset:].tobytes()
    end = raw.find(b"\0")
    if end < 0:
        raise ElfInspectionError(f"{label} is not NUL terminated")
    return raw[:end].decode("utf-8", errors="replace")


def _section_flags(flags: int) -> list[str]:
    names = []
    for mask, name in ((1, "WRITE"), (2, "ALLOC"), (4, "EXECINSTR"), (0x10, "MERGE"), (0x20, "STRINGS"), (0x400, "TLS")):
        if flags & mask:
            names.append(name)
    return names


def _program_flags(flags: int) -> list[str]:
    return [name for mask, name in ((4, "READ"), (2, "WRITE"), (1, "EXEC")) if flags & mask]


def _relocation_name(machine: int, relocation_type: int) -> str:
    return RELOCATIONS.get(machine, {}).get(relocation_type, f"UNKNOWN_{relocation_type}")


def _s3_loader_writable_layout(
    sections: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[str]]:
    """Model elf_loader 1.3.2's unpadded S3 writable-section packing."""
    errors: list[str] = []
    selected: dict[str, dict[str, Any]] = {}
    for section in sections:
        name = section["name"]
        matches = False
        if name == ".data":
            matches = (
                section["type"] == 1
                and "ALLOC" in section["flag_names"]
                and "WRITE" in section["flag_names"]
            )
        elif name in {".rodata", ".data.rel.ro"}:
            matches = section["type"] == 1 and "ALLOC" in section["flag_names"]
        elif name == ".bss":
            matches = (
                section["type"] == 8
                and "ALLOC" in section["flag_names"]
                and "WRITE" in section["flag_names"]
            )
        if not matches:
            continue
        if name in selected:
            errors.append(f"duplicate loader-packed section: {name}")
            continue
        selected[name] = section

    packed_offset = 0
    maximum_alignment = 1
    packed_sections: list[dict[str, Any]] = []
    for name in S3_LOADER_PACK_ORDER:
        section = selected.get(name)
        if section is None:
            continue
        alignment = section["alignment"] or 1
        if (
            alignment & (alignment - 1)
            or alignment > S3_LOADER_MAX_WRITABLE_ALIGNMENT
        ):
            errors.append(f"loader-packed section has unsupported alignment: {name}")
            continue
        packed_sections.append(
            {
                "name": name,
                "size": section["size"],
                "alignment": alignment,
                "packed_offset": packed_offset,
            }
        )
        packed_offset += section["size"]
        maximum_alignment = max(maximum_alignment, alignment)

    residues = [
        residue
        for residue in range(maximum_alignment)
        if all(
            (residue + item["packed_offset"]) % item["alignment"] == 0
            for item in packed_sections
        )
    ]
    if packed_sections and not residues:
        errors.append("loader-packed writable sections have incompatible alignments")
    return (
        {
            "pack_order": list(S3_LOADER_PACK_ORDER),
            "sections": packed_sections,
            "packed_size": packed_offset,
            "allocation_alignment": maximum_alignment,
            "runtime_base_residue": residues[0] if residues else None,
        },
        errors,
    )


def inspect_elf(
    path: Path,
    expected_target: str | None = None,
    *,
    require_extension: bool = False,
    allowed_imports: tuple[str, ...] = (),
) -> dict[str, Any]:
    data = path.read_bytes()
    errors: list[str] = []
    if len(data) < 52:
        raise ElfInspectionError("ELF header is truncated")
    if data[:4] != b"\x7fELF":
        raise ElfInspectionError("ELF magic is invalid")
    if data[4] != 1:
        raise ElfInspectionError("ELFCLASS32 is required")
    if data[5] != 1:
        raise ElfInspectionError("little-endian ELF data is required")
    if data[6] != 1:
        raise ElfInspectionError("current ELF identification version is required")

    header = _unpack("<16sHHIIIIIHHHHHH", data, 0, "ELF header")
    (
        _ident,
        elf_type,
        machine,
        version,
        entry,
        phoff,
        shoff,
        flags,
        ehsize,
        phentsize,
        phnum,
        shentsize,
        shnum,
        shstrndx,
    ) = header
    if version != 1:
        errors.append("ELF header version is not current")
    if ehsize != 52:
        errors.append(f"ELF header size is {ehsize}, expected 52")
    if phnum and phentsize < 32:
        errors.append("program-header entry size is smaller than ELF32")
    if shnum == 0:
        errors.append("extended or empty section counts are not accepted")
    if shnum and shentsize < 40:
        errors.append("section-header entry size is smaller than ELF32")
    if expected_target and machine != TARGET_MACHINES[expected_target]:
        errors.append(
            f"machine {MACHINES.get(machine, machine)!r} does not match {expected_target}"
        )
    if expected_target and elf_type != 3:
        errors.append(f"native loader probe must be ET_DYN, observed {ELF_TYPES.get(elf_type, elf_type)}")

    segments: list[dict[str, Any]] = []
    if phnum:
        _range(data, phoff, phentsize * phnum, "program-header table")
        for index in range(phnum):
            values = _unpack("<IIIIIIII", data, phoff + index * phentsize, f"program header {index}")
            p_type, p_offset, vaddr, paddr, filesz, memsz, p_flags, align = values
            if filesz:
                _range(data, p_offset, filesz, f"program segment {index}")
            if p_type == 1 and memsz < filesz:
                errors.append(f"program segment {index} has memsz smaller than filesz")
            segments.append(
                {
                    "index": index,
                    "type": p_type,
                    "type_name": PROGRAM_TYPES.get(p_type, f"PT_{p_type}"),
                    "offset": p_offset,
                    "virtual_address": vaddr,
                    "physical_address": paddr,
                    "file_size": filesz,
                    "memory_size": memsz,
                    "flags": p_flags,
                    "flag_names": _program_flags(p_flags),
                    "alignment": align,
                }
            )

    raw_sections: list[tuple[int, ...]] = []
    if shnum:
        _range(data, shoff, shentsize * shnum, "section-header table")
        for index in range(shnum):
            raw_sections.append(
                _unpack("<IIIIIIIIII", data, shoff + index * shentsize, f"section header {index}")
            )
    if shstrndx >= len(raw_sections):
        raise ElfInspectionError("section-name string-table index is invalid")
    shstr = raw_sections[shstrndx]
    section_names = _range(data, shstr[4], shstr[5], "section-name string table")

    sections: list[dict[str, Any]] = []
    names: list[str] = []
    constructor_surfaces: list[str] = []
    metadata_sections: list[dict[str, Any]] = []
    for index, values in enumerate(raw_sections):
        name_offset, sec_type, sec_flags, address, offset, size, link, info, align, entsize = values
        name = _string(section_names, name_offset, f"section {index} name")
        names.append(name)
        if sec_type != 8 and size:
            _range(data, offset, size, f"section {name or index}")
        if name in CONSTRUCTOR_SECTIONS:
            constructor_surfaces.append(name)
        if sec_flags & 0x400:
            constructor_surfaces.append(f"TLS section {name or index}")
        section = {
                "index": index,
                "name": name,
                "type": sec_type,
                "type_name": SECTION_TYPES.get(sec_type, f"SHT_{sec_type}"),
                "flags": sec_flags,
                "flag_names": _section_flags(sec_flags),
                "address": address,
                "offset": offset,
                "size": size,
                "link": link,
                "info": info,
                "alignment": align,
                "entry_size": entsize,
            }
        sections.append(section)
        if name == ".pulse_ext_meta":
            metadata_sections.append(section)

    for segment in segments:
        if segment["type"] == 3:
            constructor_surfaces.append("PT_INTERP")
        if segment["type"] == 7:
            constructor_surfaces.append("PT_TLS")
    load_segments = [segment for segment in segments if segment["type"] == 1]
    if expected_target and not load_segments:
        errors.append("at least one PT_LOAD segment is required")
    if expected_target == "esp32c6" and load_segments and load_segments[0]["virtual_address"] != 0:
        errors.append("elf_loader 1.3.2 C6 unified loading requires the first PT_LOAD virtual address to be zero")
    if expected_target == "esp32s3" and not any(
        section["name"] == ".text"
        and "ALLOC" in section["flag_names"]
        and "EXECINSTR" in section["flag_names"]
        for section in sections
    ):
        errors.append("elf_loader 1.3.2 S3 section loading requires an allocated executable .text section")
    s3_loader_writable_layout = None
    if expected_target == "esp32s3":
        s3_loader_writable_layout, layout_errors = _s3_loader_writable_layout(
            sections
        )
        errors.extend(layout_errors)

    symbol_tables: dict[int, list[dict[str, Any]]] = {}
    imports: dict[tuple[str, str, str], dict[str, Any]] = {}
    exports: dict[tuple[str, str, str, int], dict[str, Any]] = {}
    for sec_index, values in enumerate(raw_sections):
        _name, sec_type, _flags, _address, offset, size, link, _info, _align, entsize = values
        if sec_type not in (2, 11):
            continue
        if link >= len(raw_sections):
            errors.append(f"symbol table {names[sec_index]} has an invalid string-table link")
            continue
        string_header = raw_sections[link]
        strings = _range(data, string_header[4], string_header[5], f"symbols for {names[sec_index]}")
        stride = entsize or 16
        if stride < 16 or size % stride:
            errors.append(f"symbol table {names[sec_index]} has an invalid entry size")
            continue
        table: list[dict[str, Any]] = []
        for symbol_index in range(size // stride):
            name_off, value, symbol_size, info, other, shndx = _unpack(
                "<IIIBBH", data, offset + symbol_index * stride, f"symbol {symbol_index}"
            )
            symbol_name = _string(strings, name_off, f"symbol {symbol_index} name")
            binding = SYMBOL_BINDINGS.get(info >> 4, str(info >> 4))
            kind = SYMBOL_TYPES.get(info & 0xF, str(info & 0xF))
            item = {
                "index": symbol_index,
                "name": symbol_name,
                "value": value,
                "size": symbol_size,
                "binding": binding,
                "type": kind,
                "visibility": other & 0x3,
                "section_index": shndx,
            }
            table.append(item)
            if not symbol_name or binding not in {"GLOBAL", "WEAK"}:
                continue
            if shndx == 0:
                imports[(symbol_name, binding, kind)] = item
            else:
                exports[(symbol_name, binding, kind, value)] = item
        symbol_tables[sec_index] = table

    metadata: dict[str, Any] | None = None
    if require_extension and len(metadata_sections) != 1:
        errors.append("exactly one .pulse_ext_meta section is required")
    if len(metadata_sections) > 1:
        errors.append("duplicate .pulse_ext_meta sections are prohibited")
    if len(metadata_sections) == 1:
        metadata_section = metadata_sections[0]
        if metadata_section["type"] != 1:
            errors.append(".pulse_ext_meta must be SHT_PROGBITS")
        if "EXECINSTR" in metadata_section["flag_names"]:
            errors.append(".pulse_ext_meta must not be executable")
        if metadata_section["alignment"] != 4:
            errors.append(".pulse_ext_meta alignment must be 4")
        if metadata_section["size"] != METADATA_SIZE:
            errors.append(
                f".pulse_ext_meta size is {metadata_section['size']}, expected {METADATA_SIZE}"
            )
        else:
            record = _range(
                data,
                metadata_section["offset"],
                metadata_section["size"],
                ".pulse_ext_meta",
            ).tobytes()
            metadata, metadata_errors = _parse_metadata(
                record,
                data=data,
                file_offset=metadata_section["offset"],
                expected_target=expected_target,
            )
            errors.extend(metadata_errors)

    entry_exports = [
        item
        for item in exports.values()
        if item["name"] == ENTRY_EXPORT and item["type"] == "FUNC"
    ]
    if require_extension and len(entry_exports) != 1:
        errors.append(f"exactly one {ENTRY_EXPORT} function export is required")
    imported_names = {item["name"] for item in imports.values()}
    if require_extension:
        unexpected_imports = sorted(imported_names - set(allowed_imports))
        missing_imports = sorted(set(allowed_imports) - imported_names)
        if unexpected_imports:
            errors.append("unexpected or unresolved import: " + ", ".join(unexpected_imports))
        if missing_imports:
            errors.append("unresolved required import: " + ", ".join(missing_imports))
        if any(item["binding"] == "WEAK" for item in imports.values()):
            errors.append("unresolved weak imports are prohibited")

    relocations: list[dict[str, Any]] = []
    counts: Counter[tuple[int, str]] = Counter()
    for sec_index, values in enumerate(raw_sections):
        _name, sec_type, _flags, _address, offset, size, link, info, _align, entsize = values
        if sec_type not in (4, 9):
            continue
        stride = entsize or (12 if sec_type == 4 else 8)
        minimum = 12 if sec_type == 4 else 8
        if stride < minimum or size % stride:
            errors.append(f"relocation section {names[sec_index]} has an invalid entry size")
            continue
        symbols = symbol_tables.get(link, [])
        for relocation_index in range(size // stride):
            if sec_type == 4:
                rel_offset, rel_info, addend = _unpack(
                    "<IIi", data, offset + relocation_index * stride, f"relocation {relocation_index}"
                )
            else:
                rel_offset, rel_info = _unpack(
                    "<II", data, offset + relocation_index * stride, f"relocation {relocation_index}"
                )
                addend = None
            symbol_index = rel_info >> 8
            relocation_type = rel_info & 0xFF
            symbol_name = symbols[symbol_index]["name"] if symbol_index < len(symbols) else None
            if symbol_index >= len(symbols) and symbol_index != 0:
                errors.append(f"relocation {names[sec_index]}[{relocation_index}] has an invalid symbol index")
            type_name = _relocation_name(machine, relocation_type)
            counts[(relocation_type, type_name)] += 1
            relocations.append(
                {
                    "section": names[sec_index],
                    "target_section": names[info] if info < len(names) else None,
                    "offset": rel_offset,
                    "type": relocation_type,
                    "type_name": type_name,
                    "symbol_index": symbol_index,
                    "symbol": symbol_name,
                    "addend": addend,
                }
            )

    for sec_index, values in enumerate(raw_sections):
        if values[1] != 6:
            continue
        stride = values[9] or 8
        if stride < 8 or values[5] % stride:
            errors.append(f"dynamic section {names[sec_index]} has an invalid entry size")
            continue
        for index in range(values[5] // stride):
            tag, _value = _unpack("<iI", data, values[4] + index * stride, f"dynamic entry {index}")
            if tag in DYNAMIC_TAGS:
                constructor_surfaces.append(DYNAMIC_TAGS[tag])

    supported = LOADER_SUPPORTED.get(machine, ())
    observed_types = sorted({item["type"] for item in relocations})
    unsupported = sorted(set(observed_types) - set(supported))
    if unsupported:
        rendered = ", ".join(_relocation_name(machine, item) for item in unsupported)
        errors.append(f"relocations unsupported by elf_loader 1.3.2: {rendered}")
    if constructor_surfaces:
        errors.append("constructor or automatic-entry surfaces are present")

    writable_alloc_sections = [
        {"name": section["name"], "size": section["size"]}
        for section in sections
        if "ALLOC" in section["flag_names"]
        and "WRITE" in section["flag_names"]
        and section["size"] > 0
    ]
    writable_alloc_bytes = sum(item["size"] for item in writable_alloc_sections)
    declared_backing_bytes = None
    if metadata is not None:
        declared_backing_bytes = (
            metadata["static_memory_bytes"]
            + metadata["task_stack_bytes"]
            + metadata["queue_depth"] * metadata["queue_item_bytes"]
        )
        if require_extension and writable_alloc_bytes > declared_backing_bytes:
            errors.append(
                "allocated writable ELF sections exceed declared static/task/queue backing"
            )

    return {
        "schema": SCHEMA,
        "status": "PASS" if not errors else "FAIL",
        "file": {
            "path": str(path),
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        },
        "expected_target": expected_target,
        "header": {
            "class": "ELFCLASS32",
            "data": "ELFDATA2LSB",
            "type": elf_type,
            "type_name": ELF_TYPES.get(elf_type, f"ET_{elf_type}"),
            "machine": machine,
            "machine_name": MACHINES.get(machine, f"EM_{machine}"),
            "version": version,
            "entry": entry,
            "flags": flags,
            "program_header_count": phnum,
            "section_header_count": shnum,
        },
        "segments": segments,
        "sections": sections,
        "metadata": metadata,
        "entry_export": entry_exports[0] if len(entry_exports) == 1 else None,
        "allowed_imports": list(allowed_imports),
        "loader_supported_relocations": [
            {"type": item, "type_name": _relocation_name(machine, item)} for item in supported
        ],
        "observed_relocation_types": [
            {"type": item[0], "type_name": item[1], "count": count}
            for item, count in sorted(counts.items())
        ],
        "relocations": relocations,
        "imports": sorted(imports.values(), key=lambda item: (item["name"], item["binding"], item["type"])),
        "exports": sorted(exports.values(), key=lambda item: (item["name"], item["value"])),
        "constructor_surfaces": sorted(set(constructor_surfaces)),
        "resource_footprint": {
            "allocated_writable_sections": writable_alloc_sections,
            "allocated_writable_bytes": writable_alloc_bytes,
            "declared_backing_bytes": declared_backing_bytes,
            "s3_loader_writable_layout": s3_loader_writable_layout,
        },
        "validation_errors": errors,
    }


def _address_in_ranges(address: int, ranges: tuple[tuple[int, int], ...]) -> bool:
    for start, size in ranges:
        if size > 0 and address >= start and address - start < size:
            return True
    return False


def validate_descriptor_bytes(
    descriptor: bytes,
    metadata: dict[str, Any],
    *,
    executable_ranges: tuple[tuple[int, int], ...],
    readable_ranges: tuple[tuple[int, int], ...],
    descriptor_address: int,
) -> list[str]:
    """Validate a relocated descriptor image without invoking lifecycle code."""
    errors: list[str] = []
    if len(descriptor) != DESCRIPTOR_SIZE:
        return [f"descriptor size is {len(descriptor)}, expected {DESCRIPTOR_SIZE}"]
    values = struct.unpack("<IIHHI16s32sHHI4I4I6I32s", descriptor)
    (
        magic,
        struct_size,
        abi_major,
        abi_minor,
        flags,
        extension_id,
        metadata_sha256,
        event_count,
        operation_count,
        reserved0,
        *tail,
    ) = values
    event_ids = list(tail[:4])
    operation_ids = list(tail[4:8])
    function_addresses = list(tail[8:14])
    reserved1 = tail[14]
    if magic != DESCRIPTOR_MAGIC:
        errors.append("descriptor magic is invalid")
    if struct_size != DESCRIPTOR_SIZE:
        errors.append("descriptor struct_size is invalid")
    if (abi_major, abi_minor) != (1, 0):
        errors.append("descriptor ABI version is unsupported")
    if flags != 0:
        errors.append("descriptor flags must be zero")
    if extension_id.hex() != metadata.get("extension_id"):
        errors.append("metadata/descriptor identity disagreement")
    if metadata_sha256.hex() != metadata.get("normalized_metadata_sha256"):
        errors.append("metadata/descriptor hash disagreement")
    if event_count != metadata.get("event_count") or event_ids != metadata.get("event_ids"):
        errors.append("metadata/descriptor event catalog disagreement")
    if operation_count != metadata.get("operation_count") or operation_ids != metadata.get("operation_ids"):
        errors.append("metadata/descriptor operation catalog disagreement")
    if reserved0 != 0 or not _all_zero(reserved1):
        errors.append("descriptor reserved fields must be zero")
    if descriptor_address % 4 or not _address_in_ranges(descriptor_address, readable_ranges):
        errors.append("descriptor address is outside admitted readable memory")
    function_names = ("init", "start", "invoke", "health", "quiesce", "deinit")
    # Keep this compatible with the repository's /usr/bin/python3 default on
    # macOS, where Python 3.9 does not yet support zip(strict=...).  The ELF
    # descriptor format above always yields exactly six function addresses.
    for name, address in zip(function_names, function_addresses):
        if address == 0:
            errors.append(f"missing lifecycle function: {name}")
        elif not _address_in_ranges(address, executable_ranges):
            errors.append(f"lifecycle function is outside admitted executable memory: {name}")
    return errors


def validate_registry_catalog(descriptors: list[bytes]) -> list[str]:
    """Validate fixed identities across already-admitted descriptor records."""
    errors: list[str] = []
    extension_ids: set[bytes] = set()
    event_ids: set[int] = set()
    operation_ids: set[int] = set()
    for descriptor in descriptors:
        if len(descriptor) != DESCRIPTOR_SIZE:
            errors.append("registry descriptor size is invalid")
            continue
        values = struct.unpack("<IIHHI16s32sHHI4I4I6I32s", descriptor)
        extension_id = values[5]
        event_count = values[7]
        operation_count = values[8]
        tail = values[10:]
        events = tail[:4]
        operations = tail[4:8]
        if extension_id in extension_ids:
            errors.append("duplicate extension identity")
        extension_ids.add(extension_id)
        for item in events[:event_count]:
            if item in event_ids:
                errors.append("duplicate event identity")
            event_ids.add(item)
        for item in operations[:operation_count]:
            if item in operation_ids:
                errors.append("duplicate operation identity")
            operation_ids.add(item)
    return errors


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--elf", type=Path, required=True)
    parser.add_argument("--expected-target", choices=tuple(TARGET_MACHINES))
    parser.add_argument("--require-extension", action="store_true")
    parser.add_argument("--allow-import", action="append", default=[])
    parser.add_argument("--json-out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = inspect_elf(
            args.elf,
            args.expected_target,
            require_extension=args.require_extension,
            allowed_imports=tuple(args.allow_import),
        )
    except (OSError, ElfInspectionError) as exc:
        report = {
            "schema": SCHEMA,
            "status": "FAIL",
            "file": {"path": str(args.elf)},
            "expected_target": args.expected_target,
            "validation_errors": [str(exc)],
        }
    _write_json(args.json_out, report)
    print(json.dumps({"status": report["status"], "report": str(args.json_out)}))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
