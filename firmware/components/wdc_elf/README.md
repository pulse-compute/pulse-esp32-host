# `wdc_elf`

`wdc_elf` is the narrow adapter around Espressif `elf_loader` 1.3.2.
Its public header owns only opaque Pulse host types and fixed-width values;
`esp_elf_t`, loader configuration, and loader symbol-resolution types remain
private to `wdc_elf.c`.

`wdc_elf_load_inspected` is intentionally named to prevent a false admission
claim. The upstream relocation API accepts only an unbounded byte pointer, so
the same immutable buffer must first pass the independent bounded inspector.
HX1 compiled and linked this path but produced no hardware/runtime evidence.
HX2 adds `wdc_elf_load_inspected_with_symbols`, which accepts at most sixteen
exact inspector-derived name/address bindings for the relocation call and
clears the resolver immediately afterward. The empty table remains reject-all.

The HX1 overlays disable the upstream ambient libc, ESP-IDF, customer, and
dynamic-object symbol tables. No ambient or wildcard symbol table is enabled.
The adapter is intentionally single-relocation-at-a-time because the upstream
resolver hook is global.

ESP32-C6 uses a unified PT_LOAD segment. The pinned loader requests that span
as executable but drops `MALLOC_CAP_EXEC` in its unified-bus allocator branch.
Pulse wraps that allocation to restore executable intent and disables the
default fixed PMP IRAM/DRAM split in C6 extension profiles; otherwise the
heap-backed relocated entry is RW/NX and faults on its first instruction.
The wrapper requests executable memory without combining `MALLOC_CAP_EXEC`
and `MALLOC_CAP_8BIT`, an explicitly unsupported ESP-IDF heap-capability pair.
