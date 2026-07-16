#!/usr/bin/env python3
"""Generate tiny R2 WASM fixtures and C arrays.

This intentionally avoids external tools such as wat2wasm so the R2 repo can be
validated on a plain host. The generated binary is a real WebAssembly MVP module.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "firmware/components/wdc_runtime"
INC = OUT / "include"
VECTORS = OUT / "test_vectors"


def u32(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def vec(items: list[bytes]) -> bytes:
    return u32(len(items)) + b"".join(items)


def name(s: str) -> bytes:
    b = s.encode("utf-8")
    return u32(len(b)) + b


def section(sec_id: int, payload: bytes) -> bytes:
    return bytes([sec_id]) + u32(len(payload)) + payload


def functype(params: list[int], results: list[int]) -> bytes:
    return bytes([0x60]) + bytes([len(params)]) + bytes(params) + bytes([len(results)]) + bytes(results)

I32 = 0x7F


def code_body(locals_decl: bytes, instr: bytes) -> bytes:
    body = locals_decl + instr + b"\x0b"
    return u32(len(body)) + body


def make_module(include_shutdown: bool = True, init_status: int = 0, health_status: int = 0, trap_init: bool = False, event_status: int = 0, trap_event: bool = False) -> bytes:
    # Type indices:
    # 0: (i32,i32,i32)->i32   imported wdc_log(level, ptr, len)
    # 1: ()->i32              init/health
    # 2: (i32,i32)->i32       on_event
    # 3: (i32)->i32           shutdown
    types = section(1, vec([
        functype([I32, I32, I32], [I32]),
        functype([], [I32]),
        functype([I32, I32], [I32]),
        functype([I32], [I32]),
    ]))

    imports = section(2, vec([
        name("wdc") + name("wdc_log") + b"\x00" + u32(0),
    ]))

    defined_type_indices = [1, 2, 1]
    if include_shutdown:
        defined_type_indices.append(3)
    funcs = section(3, vec([u32(i) for i in defined_type_indices]))

    memory = section(5, vec([b"\x00" + u32(1)]))  # one page min

    # Function indexes: imported wdc_log = 0, defined funcs = 1..N.
    exports_list = [
        name("memory") + b"\x02" + u32(0),
        name("wdc_module_init") + b"\x00" + u32(1),
        name("wdc_module_on_event") + b"\x00" + u32(2),
        name("wdc_module_health") + b"\x00" + u32(3),
    ]
    if include_shutdown:
        exports_list.append(name("wdc_module_shutdown") + b"\x00" + u32(4))
    exports = section(7, vec(exports_list))

    msg = b"r2 hello from static wasm"
    msg_offset = 1024

    if trap_init:
        init_instr = b"\x00"  # unreachable
    else:
        # call imported wdc_log(WDC_LOG_INFO=1, msg_offset, len); drop; i32.const init_status
        init_instr = (
            b"\x41" + u32(1) +
            b"\x41" + u32(msg_offset) +
            b"\x41" + u32(len(msg)) +
            b"\x10" + u32(0) +
            b"\x1a" +
            b"\x41" + u32(init_status & 0xFFFFFFFF)
        )

    on_event_instr = (b"\x00" if trap_event else (b"\x41" + u32(event_status & 0xFFFFFFFF)))
    health_instr = b"\x41" + u32(health_status & 0xFFFFFFFF)
    shutdown_instr = b"\x41" + u32(0)

    bodies = [
        code_body(b"\x00", init_instr),
        code_body(b"\x00", on_event_instr),
        code_body(b"\x00", health_instr),
    ]
    if include_shutdown:
        bodies.append(code_body(b"\x00", shutdown_instr))
    code = section(10, vec(bodies))

    data_entry = b"\x00" + b"\x41" + u32(msg_offset) + b"\x0b" + u32(len(msg)) + msg
    data = section(11, vec([data_entry]))

    # WAMR ignores this custom section. The host-test backend uses it to
    # emulate lifecycle results without embedding a WASM interpreter.
    host_meta_text = (
        f"init_status={init_status};health_status={health_status};"
        f"event_status={event_status};"
        f"trap_init={1 if trap_init else 0};"
        f"trap_event={1 if trap_event else 0};"
        f"include_shutdown={1 if include_shutdown else 0}"
    ).encode("ascii")
    host_meta = section(0, name("wdc.r2.host_meta") + host_meta_text)

    return b"\x00asm" + b"\x01\x00\x00\x00" + types + imports + funcs + memory + exports + code + data + host_meta


def c_array(name_: str, data: bytes) -> str:
    rows = []
    for i in range(0, len(data), 12):
        chunk = data[i:i+12]
        rows.append("    " + ", ".join(f"0x{b:02x}" for b in chunk) + ",")
    return f"const uint8_t {name_}[] = {{\n" + "\n".join(rows) + f"\n}};\nconst uint32_t {name_}_len = {len(data)}u;\n"


def main() -> int:
    INC.mkdir(parents=True, exist_ok=True)
    VECTORS.mkdir(parents=True, exist_ok=True)
    fixtures = {
        "wdc_static_hello_wasm": make_module(),
        "wdc_static_missing_shutdown_wasm": make_module(include_shutdown=False),
        "wdc_static_init_fail_wasm": make_module(init_status=15),
        "wdc_static_health_fail_wasm": make_module(health_status=15),
        "wdc_static_init_trap_wasm": make_module(trap_init=True),
        "wdc_static_event_trap_wasm": make_module(trap_event=True),
        "wdc_static_event_fail_wasm": make_module(event_status=15),
    }
    for n, data in fixtures.items():
        (VECTORS / f"{n}.wasm").write_bytes(data)

    header = """#pragma once\n\n#include <stdint.h>\n\n#ifdef __cplusplus\nextern \"C\" {\n#endif\n\nextern const uint8_t wdc_static_hello_wasm[];\nextern const uint32_t wdc_static_hello_wasm_len;\nextern const uint8_t wdc_static_missing_shutdown_wasm[];\nextern const uint32_t wdc_static_missing_shutdown_wasm_len;\nextern const uint8_t wdc_static_init_fail_wasm[];\nextern const uint32_t wdc_static_init_fail_wasm_len;\nextern const uint8_t wdc_static_health_fail_wasm[];\nextern const uint32_t wdc_static_health_fail_wasm_len;\nextern const uint8_t wdc_static_init_trap_wasm[];\nextern const uint32_t wdc_static_init_trap_wasm_len;\nextern const uint8_t wdc_static_event_trap_wasm[];\nextern const uint32_t wdc_static_event_trap_wasm_len;\nextern const uint8_t wdc_static_event_fail_wasm[];\nextern const uint32_t wdc_static_event_fail_wasm_len;\n\n#ifdef __cplusplus\n}\n#endif\n"""
    (INC / "wdc_static_wasm.h").write_text(header, encoding="utf-8")

    src = "#include \"wdc_static_wasm.h\"\n\n"
    for n, data in fixtures.items():
        src += c_array(n, data) + "\n"
    (OUT / "wdc_static_wasm.c").write_text(src, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
