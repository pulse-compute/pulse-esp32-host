#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class WasmParseError(ValueError):
    pass


@dataclass
class Reader:
    data: bytes
    pos: int = 0

    def require(self, n: int) -> bytes:
        if self.pos + n > len(self.data):
            raise WasmParseError("unexpected end of file")
        out = self.data[self.pos:self.pos + n]
        self.pos += n
        return out

    def u8(self) -> int:
        return self.require(1)[0]

    def u32_leb(self) -> int:
        result = 0
        shift = 0
        for _ in range(5):
            b = self.u8()
            result |= (b & 0x7f) << shift
            if (b & 0x80) == 0:
                return result
            shift += 7
        raise WasmParseError("invalid u32 LEB128")

    def name(self) -> str:
        n = self.u32_leb()
        raw = self.require(n)
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise WasmParseError("invalid UTF-8 name") from exc

    def skip_limits(self) -> None:
        flags = self.u32_leb()
        self.u32_leb()
        if flags & 0x01:
            self.u32_leb()

    def skip_valtype(self) -> None:
        self.u8()

    def skip_import_desc(self, kind: int) -> int | None:
        if kind == 0:  # func
            return self.u32_leb()
        if kind == 1:  # table
            self.u8()
            self.skip_limits()
            return None
        if kind == 2:  # memory
            self.skip_limits()
            return None
        if kind == 3:  # global
            self.skip_valtype()
            self.u8()
            return None
        if kind == 4:  # tag, used by exception-handling proposal
            self.u8()
            self.u32_leb()
            return None
        raise WasmParseError(f"unsupported import kind {kind}")


def inspect_wasm(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    r = Reader(data)
    if r.require(4) != b"\x00asm":
        raise WasmParseError("missing wasm magic")
    version = int.from_bytes(r.require(4), "little")
    imports: list[dict[str, Any]] = []
    exports: list[dict[str, Any]] = []
    sections: list[dict[str, Any]] = []

    while r.pos < len(data):
        section_id = r.u8()
        size = r.u32_leb()
        payload = r.require(size)
        sections.append({"id": section_id, "size": size})
        sr = Reader(payload)
        if section_id == 2:
            count = sr.u32_leb()
            for _ in range(count):
                module = sr.name()
                name = sr.name()
                kind = sr.u8()
                type_index = sr.skip_import_desc(kind)
                imports.append({"module": module, "name": name, "kind": kind, "type_index": type_index})
        elif section_id == 7:
            count = sr.u32_leb()
            for _ in range(count):
                name = sr.name()
                kind = sr.u8()
                index = sr.u32_leb()
                exports.append({"name": name, "kind": kind, "index": index})

    return {
        "schema": "wdc.wasm_inspect.v1",
        "path": str(path),
        "size_bytes": len(data),
        "version": version,
        "sections": sections,
        "imports": imports,
        "exports": exports,
    }


def parse_import_spec(spec: str) -> tuple[str, str]:
    if ":" not in spec:
        raise argparse.ArgumentTypeError("import requirement must be MODULE:NAME")
    module, name = spec.split(":", 1)
    if not module or not name:
        raise argparse.ArgumentTypeError("import requirement must be MODULE:NAME")
    return module, name


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect a WebAssembly binary imports/exports without external tools.")
    parser.add_argument("wasm", type=Path)
    parser.add_argument("--json", action="store_true", help="Compatibility flag; JSON is the default output.")
    parser.add_argument("--human", action="store_true", help="Print a human-readable summary instead of JSON.")
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--require-import", action="append", default=[], type=parse_import_spec)
    parser.add_argument("--require-export", action="append", default=[])
    args = parser.parse_args()

    errors: list[str] = []
    try:
        report = inspect_wasm(args.wasm)
    except Exception as exc:  # noqa: BLE001 - CLI should report parse failures simply.
        payload = {
            "schema": "wdc.wasm_inspect.v1",
            "path": str(args.wasm),
            "status": "FAIL",
            "valid_wasm": False,
            "errors": [str(exc)],
            "imports": [],
            "exports": [],
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 1

    imports = {(item["module"], item["name"]) for item in report["imports"]}
    exports = {item["name"] for item in report["exports"]}
    for module, name in args.require_import:
        if (module, name) not in imports:
            errors.append(f"MISSING: import {module}:{name}")
    for name in args.require_export:
        if name not in exports:
            errors.append(f"MISSING: export {name}")

    report["valid_wasm"] = True
    report["status"] = "PASS" if not errors else "FAIL"
    report["errors"] = errors

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if args.human:
        print(f"WASM: {args.wasm}")
        print(f"status: {report['status']}")
        print(f"size: {report['size_bytes']} bytes, version: {report['version']}")
        print("imports:")
        for item in report["imports"]:
            print(f"  - {item['module']}:{item['name']} kind={item['kind']}")
        print("exports:")
        for item in report["exports"]:
            print(f"  - {item['name']} kind={item['kind']}")
        for error in errors:
            print(error)
    else:
        print(json.dumps(report, indent=2, sort_keys=True))

    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
