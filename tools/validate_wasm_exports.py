#!/usr/bin/env python3
"""Validate the minimal WDC WASM import/export contract without external tools."""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path

REQUIRED_EXPORTS = {
    "wdc_module_init",
    "wdc_module_on_event",
    "wdc_module_health",
    "wdc_module_shutdown",
}
REQUIRED_IMPORTS = {
    ("wdc", "wdc_log"),
    ("wdc", "wdc_millis"),
    ("wdc", "wdc_random"),
    ("wdc", "wdc_yield"),
    ("wdc", "wdc_host_call"),
}


class WasmError(ValueError):
    pass


@dataclass
class WasmSummary:
    path: str
    valid_wasm: bool
    imports: list[dict]
    exports: list[dict]
    required_imports_present: bool
    required_exports_present: bool
    missing_imports: list[str]
    missing_exports: list[str]
    memory_exported: bool


class Reader:
    def __init__(self, data: bytes):
        self.data = data
        self.off = 0

    def remaining(self) -> int:
        return len(self.data) - self.off

    def read(self, n: int) -> bytes:
        if n < 0 or self.off + n > len(self.data):
            raise WasmError("unexpected EOF")
        out = self.data[self.off:self.off + n]
        self.off += n
        return out

    def read_u8(self) -> int:
        return self.read(1)[0]

    def read_varuint(self, bits: int = 32) -> int:
        result = 0
        shift = 0
        while True:
            b = self.read_u8()
            result |= (b & 0x7f) << shift
            if (b & 0x80) == 0:
                break
            shift += 7
            if shift >= bits + 7:
                raise WasmError("LEB128 value too large")
        return result

    def read_name(self) -> str:
        n = self.read_varuint()
        raw = self.read(n)
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise WasmError(f"invalid UTF-8 name: {exc}") from exc

    def skip_limits(self) -> None:
        flags = self.read_u8()
        self.read_varuint()
        if flags & 0x01:
            self.read_varuint()

    def skip_blocktype(self) -> None:
        # MVP valtype or empty blocktype. This parser only needs to skip enough
        # for imports/exports; malformed rare cases will raise EOF/errors.
        self.read_u8()


def parse_imports(payload: bytes) -> list[dict]:
    r = Reader(payload)
    imports = []
    count = r.read_varuint()
    for _ in range(count):
        module = r.read_name()
        name = r.read_name()
        kind = r.read_u8()
        if kind == 0x00:  # func
            type_index = r.read_varuint()
            imports.append({"module": module, "name": name, "kind": "func", "type_index": type_index})
        elif kind == 0x01:  # table
            elem_type = r.read_u8()
            r.skip_limits()
            imports.append({"module": module, "name": name, "kind": "table", "element_type": elem_type})
        elif kind == 0x02:  # memory
            r.skip_limits()
            imports.append({"module": module, "name": name, "kind": "memory"})
        elif kind == 0x03:  # global
            valtype = r.read_u8()
            mutable = r.read_u8()
            imports.append({"module": module, "name": name, "kind": "global", "valtype": valtype, "mutable": mutable})
        else:
            raise WasmError(f"unknown import kind {kind}")
    return imports


def parse_exports(payload: bytes) -> list[dict]:
    r = Reader(payload)
    exports = []
    count = r.read_varuint()
    for _ in range(count):
        name = r.read_name()
        kind = r.read_u8()
        index = r.read_varuint()
        kind_name = {0x00: "func", 0x01: "table", 0x02: "memory", 0x03: "global"}.get(kind, f"unknown:{kind}")
        exports.append({"name": name, "kind": kind_name, "index": index})
    return exports


def summarize(path: Path, require_all_imports: bool = False) -> WasmSummary:
    data = path.read_bytes()
    if len(data) < 8 or data[:4] != b"\x00asm" or data[4:8] != b"\x01\x00\x00\x00":
        raise WasmError("not a WebAssembly MVP module")
    r = Reader(data[8:])
    imports: list[dict] = []
    exports: list[dict] = []
    last_section = 0
    while r.remaining() > 0:
        sec_id = r.read_u8()
        sec_len = r.read_varuint()
        payload = r.read(sec_len)
        if sec_id != 0 and sec_id < last_section:
            raise WasmError("sections out of order")
        if sec_id != 0:
            last_section = sec_id
        if sec_id == 2:
            imports.extend(parse_imports(payload))
        elif sec_id == 7:
            exports.extend(parse_exports(payload))
    import_pairs = {(i["module"], i["name"]) for i in imports if i.get("kind") == "func"}
    export_names = {e["name"] for e in exports if e.get("kind") == "func"}
    memory_exported = any(e["name"] == "memory" and e.get("kind") == "memory" for e in exports)
    if require_all_imports:
        required_imports_present = REQUIRED_IMPORTS.issubset(import_pairs)
        missing_imports = sorted(f"{m}.{n}" for (m, n) in REQUIRED_IMPORTS - import_pairs)
    else:
        # Some valid guest bundles only import the host functions they use. R3.5
        # requires the module namespace and all lifecycle exports; full import
        # coverage can be requested by --require-all-imports.
        required_imports_present = bool(import_pairs & REQUIRED_IMPORTS)
        missing_imports = [] if required_imports_present else sorted(f"{m}.{n}" for (m, n) in REQUIRED_IMPORTS)
    missing_exports = sorted(REQUIRED_EXPORTS - export_names)
    return WasmSummary(
        path=str(path),
        valid_wasm=True,
        imports=imports,
        exports=exports,
        required_imports_present=required_imports_present,
        required_exports_present=not missing_exports,
        missing_imports=missing_imports,
        missing_exports=missing_exports,
        memory_exported=memory_exported,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("wasm", type=Path)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--require-all-imports", action="store_true")
    args = parser.parse_args()
    try:
        summary = summarize(args.wasm, require_all_imports=args.require_all_imports)
    except WasmError as exc:
        result = {"path": str(args.wasm), "valid_wasm": False, "error": str(exc)}
        print(json.dumps(result, indent=2, sort_keys=True) if args.json else f"FAIL {args.wasm}: {exc}")
        return 1
    result = asdict(summary)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"WASM: {args.wasm}")
        print(f"  imports: {', '.join(i['module'] + '.' + i['name'] for i in summary.imports) or '(none)'}")
        print(f"  exports: {', '.join(e['name'] for e in summary.exports) or '(none)'}")
        print(f"  required lifecycle exports: {'OK' if summary.required_exports_present else 'MISSING ' + ', '.join(summary.missing_exports)}")
        print(f"  WDC imports: {'OK' if summary.required_imports_present else 'MISSING'}")
    return 0 if summary.valid_wasm and summary.required_exports_present and summary.required_imports_present else 1


if __name__ == "__main__":
    raise SystemExit(main())
