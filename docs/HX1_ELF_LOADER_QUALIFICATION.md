# HX1 exact ELF-loader qualification

## Scope and result boundary

HX1 pins and compiles one narrow loader adapter for the two proof ISAs. The
sandbox can establish `BUILD_PROVEN`; it has no attached ESP32-S3 or ESP32-C6
board and therefore cannot establish loader runtime, unload, leak, executable
permission, or repeated-cycle behavior. Those fields remain
`HARDWARE_NOT_RUN` or `NOT_RUN` in generated evidence.

This pass does not add the HX2 native ABI, synthetic extension, descriptor,
metadata record, lifecycle host, or runtime registry.

The accepted run and report hashes are recorded in the durable
[native-extension host evidence index](../evidence/host-extension/INDEX.md#native-extension-host-evidence-index).

## Exact dependency

- Component: `espressif/elf_loader`
- Version: `1.3.2` (exact; no range in the Pulse manifest)
- Upstream repository: `https://github.com/espressif/esp-iot-solution.git`
- Upstream commit: `1608d9c922c992986c285fd753ef15ecbbad3cde`
- Component Git tree: `d2863c4d7360a3c735a8c801829ad0d10fd002e0`
- License: Apache-2.0
- Registry component hash: `9f7f6efa06e0847adeba6c9910c4308f33aae7d35ba0cc36c0850105c45e9874`
- Resolved transitive dependency: `espressif/cmake_utilities` 0.5.3,
  component hash
  `351350613ceafba240b761b4ea991e0f231ac7a9f59a9ee901f751bddc0bb18f`
- IDF constraint declared upstream: `>=4.4.3`; observed lane: exact ESP-IDF
  5.4.4 at `296b6eab9445fd720e71aecab961e2d3fbca9944`

The 1.3.0 history introduced shared-object support, 1.3.1 introduced the
overridable symbol resolver needed for a closed host policy, and 1.3.2 changed
ESP32-S31 handling only. Direct comparison of the 1.3.2 registry archive to
the pinned Git tree found identical code. The registry rewrites only
`idf_component.yml` to add immutable repository provenance and omit examples
and SBOM publishing metadata.

The independent locks are [S3](../firmware/locks/host-extension/idf-5.4.4/esp32s3/dependencies.lock)
and [C6](../firmware/locks/host-extension/idf-5.4.4/esp32c6/dependencies.lock).
They do not replace or relabel IF7 locks.

## Loader and ELF behavior found in source

The accepted HX1 probe shape is ELF32 little-endian `ET_DYN`. S3 uses
`EM_XTENSA` (94); C6 uses `EM_RISCV` (243). The exact machine, flags,
sections, imports, exports, and observed relocation counts are emitted by
`tools/inspect_native_extension.py` for each fresh qualification.

The 1.3.2 architecture switches implement these relocation cases:

| Target | Implemented loader cases | Observed HX1 probe cases |
|---|---|---|
| ESP32-S3 | `R_XTENSA_RTLD`, `R_XTENSA_GLOB_DAT`, `R_XTENSA_JMP_SLOT`, `R_XTENSA_RELATIVE` | `R_XTENSA_RTLD`, `R_XTENSA_JMP_SLOT`, `R_XTENSA_RELATIVE` |
| ESP32-C6 | `R_RISCV_NONE`, `R_RISCV_32`, `R_RISCV_RELATIVE`, `R_RISCV_JUMP_SLOT` | `R_RISCV_JUMP_SLOT` |

The probe has the sole qualification import `pulse_hx1_probe_import` and the
visible export `pulse_hx1_probe_entry`. These are evidence fixtures, not Pulse
ABI. HX1 disables the loader's libc, ESP-IDF, customer, and dynamic-object
symbol tables. HX1 installed a reject-all resolver. HX2 subsequently added a
bounded inspector-derived exact name/address table while preserving reject-all
behavior for the empty-import synthetic artifact.

`esp_elf_relocate` allocates, copies, and applies relocations. It does not call
the ELF entry; `esp_elf_request` is the separate execution API and the adapter
does not expose it. The independent inspector rejects `.init_array`,
`.fini_array`, `.ctors`, `.dtors`, TLS, `PT_INTERP`, `DT_NEEDED`, `DT_INIT`,
and `DT_FINI` before relocation.

There is one important source finding: `esp_elf_relocate` does not propagate
the return from `esp_elf_arch_relocate`. An unsupported case can therefore be
logged without failing the upstream relocation call. Pulse must never rely on
that return path. The independent inspector rejects every relocation type not
in the exact per-target set before `wdc_elf_load_inspected` is reachable. HX2
must make that inspection-to-adapter handoff structural rather than relying on
the function name alone; until then this is a runtime-seal blocker.

## Executable memory and ownership

For S3, `CONFIG_ELF_LOADER_BUS_ADDRESS_MIRROR=y`. The HX1 overlay disables
PSRAM loading, so source requests `MALLOC_CAP_EXEC` for text and
`MALLOC_CAP_8BIT` for the combined data/rodata/BSS allocation. For C6 the
loader allocates one cache-aligned PT_LOAD span and treats it as a unified
code/data segment, then writes back the internal-memory cache. Physical XIAO
execution showed that loader 1.3.2 drops its executable allocation flag in
this branch: the relocated entry landed in ordinary RW/NX heap and raised an
instruction-access fault on its first call.

Pulse now wraps the C6 loader allocation so executable requests retain
`MALLOC_CAP_EXEC`, and its C6 extension profiles explicitly disable the default
fixed PMP IRAM/DRAM split. A dynamic unified segment must be writable while it
is copied and relocated and executable afterward; the fixed RX/RW boundary
cannot express that lifecycle. The wrapper fails closed at allocation if the
configured memory policy cannot supply executable internal RAM.

The C6 unified loader source initializes the segment base to zero and never
takes its nominal first-segment branch. HX1 therefore admits only a C6
`ET_DYN` whose first `PT_LOAD` virtual address is zero, as produced by the
pinned compiler and verified by the independent inspector.

`wdc_elf_load_inspected` owns the loader state and unwinds with
`esp_elf_deinit` on a relocation error. `wdc_elf_unload` is null-safe and
idempotent, resets the global resolver, frees loader allocations through the
upstream deinitializer, and releases the opaque adapter handle. Actual return
codes, retained bytes, and bounded repeated cycles remain `NOT_RUN` without
boards.

## Build and evidence commands

The proof matrix is
[firmware/extension-proof-matrix.json](../firmware/extension-proof-matrix.json).
It contains exactly the S3 proof based on `esp32s3-reference` and the C6 proof
based on `esp32c6-compile`, while preserving C3 as `INCOMPATIBLE`.

```bash
make idf-family-seal-check
make check-hx0
make check-hx1
HX_OUT_DIR=reports/host-extension/hx1-<fresh-id> \
  make host-extension-loader-qualify
```

The qualification command derives and rebuilds an IF7 comparison baseline,
then performs two clean extension-enabled host builds and two clean native
probe builds per target. It records raw logs, exact environment/tool hashes,
component locks, size data and deltas, ELF inventories, and byte-level
reproducibility. A local one-line component-manager PID fallback used to make
the sandbox's PID namespace visible is hashed in the environment evidence; it
does not alter ESP-IDF, loader, firmware, compiler, or target source.
