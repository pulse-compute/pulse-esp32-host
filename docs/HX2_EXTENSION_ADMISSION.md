# HX2 two-stage extension admission

## Result

HX2 is `PASS` with aggregate `BUILD_ONLY_PROVEN` evidence. The exact
ESP32-S3/Xtensa and ESP32-C6/RISC-V synthetic ELFs are byte-reproducible, and
the firmware containing the new host admission component is byte-reproducible
for both targets under ESP-IDF v5.4.4.

This is not runtime evidence. No board loaded an extension, called the pure
descriptor entry, or executed `init`, `start`, `invoke`, `health`, `quiesce`,
or `deinit`. Runtime remains `HARDWARE_NOT_RUN`.

The accepted run is recorded in the durable
[native-extension host evidence index](../evidence/host-extension/INDEX.md#native-extension-host-evidence-index),
and its JSON report has SHA-256
`0043f91f798f39fc62e9d0a3b8343eb5028fc0b8ac843fa5966ba7172f202b2b`.

## Implemented boundary

The sole public C ABI authority is
`native-sdk/c/include/pulse_extension.h`. It freezes the experimental 32-bit
little-endian HX contract, including:

- the 192-byte `.pulse_ext_meta` record;
- the 160-byte runtime descriptor;
- fixed extension, event, and operation identities;
- exact lifecycle and host-service signatures;
- exact size, alignment, and function-pointer offset assertions; and
- no allocation service, unbounded string, runtime registration callback, or
  platform capability surface.

`firmware/components/wdc_extension` owns the host boundary in two stages:

1. `wdc_extension_inspect` performs overflow-safe raw ELF, section, program,
   symbol, relocation, constructor, target, metadata, budget, import, and
   normalized SHA-256 validation. It has no loader or callable extension
   surface.
2. `wdc_extension_load_descriptor` first rechecks the immutable raw-byte hash,
   passes at most sixteen inspector-derived exact name/address bindings to
   `wdc_elf`, relocates, maps the one canonical entry export, calls only that
   pure descriptor entry, and validates descriptor readability, identity,
   catalog, digest, reserved fields, and all six executable function addresses.

The upstream ambient libc, IDF, customer, and dynamic symbol tables remain
disabled. An empty admitted import set installs a reject-all resolver; a
nonempty set is exact and is cleared immediately after relocation.

The fixed-capacity registry rejects duplicate extension, event, or operation
identities and seals the complete catalog. HX2 deliberately exposes no
lifecycle execution API. HX3 owns those transitions and task supervision.

## Synthetic artifact

`native-extensions/synthetic-loopback` declares one event (`test:tick` in
evidence), one operation (`test:echo` in evidence), one future task, and one
future bounded queue. It imports no Pulse service, ESP-IDF, FreeRTOS, GPIO,
network, BLE, storage, allocation, or RAX symbol.

Its descriptor and lifecycle functions exist so descriptor admission is
concrete. `start` returns `PULSE_EXT_ERR_UNSUPPORTED` until HX3 supplies the
static task and queue. This prevents an HX2 artifact from appearing runnable
before its lifecycle contract exists.

| Target | Machine | Synthetic ELF SHA-256 | Size |
|---|---|---|---:|
| ESP32-S3 | `EM_XTENSA` | `fe713e141b6f42124439f3a25cab4207452defeb76b4c35e94bd55a775df4113` | 3,496 bytes |
| ESP32-C6 | `EM_RISCV` | `55b0ebc5e1c830c8f4dd206a7d913163f1068b0ae696269fca3898134fc04407` | 3,044 bytes |

## Fail-closed vectors

The committed corpus under
`tests/contract/native_extension_vectors/` contains two valid ELFs, fifteen
pre-execution rejections, five descriptor rejections, and one registry
rejection. It covers the HX2 minimum corpus:

- wrong machine and target identity;
- unknown or truncated metadata and an out-of-bounds metadata section;
- duplicate extension, event, and operation identities;
- incompatible ABI major and unsupported required minor;
- wrong descriptor size and nonzero reserved fields;
- metadata/descriptor identity or hash disagreement;
- missing lifecycle functions;
- unexpected or unresolved imports;
- a declared budget above the host profile; and
- normalized artifact hash mismatch.

All 21 rejected cases record zero lifecycle calls. Pre-execution rejection does
not invoke the loader. Descriptor and registry rejection may conceptually
follow the pure descriptor entry but never dispatches a lifecycle function.

The bounded firmware SHA-256 implementation is independently exercised against
standard empty, `abc`, and multi-block-known message vectors. It avoids pulling
the much larger platform cryptography component into the already constrained
S3 host merely to bind an experimental ELF record.

## Firmware cost and residual risk

The values below compare the complete loader + admission host against the
fresh IF7-derived baseline used by the qualification tool.

| Target | Firmware binary delta | Internal RAM delta | Remaining internal RAM |
|---|---:|---:|---:|
| ESP32-S3 | +7,632 bytes | +184 bytes | 2,653 bytes |
| ESP32-C6 | +7,824 bytes | +184 bytes | 114,570 bytes |

The S3 still reports only one byte of dedicated IRAM headroom. HX2 adds no IRAM
text, but this pre-existing limit remains the dominant build risk. Its broader
internal RAM is now 99.22% occupied.

The other unresolved loader risks from HX1 remain:

- upstream `esp_elf_relocate` does not propagate architecture relocation
  errors, so the independent inspector must remain authoritative;
- the C6 unified-segment loader path requires the first `PT_LOAD` virtual
  address to be zero; and
- executable placement, descriptor entry, relocation behavior, unload, and
  leak behavior remain unexecuted on hardware.

## HX3 handoff

HX3 completed this handoff without changing HX2's pre-execution boundary. It
adds lifecycle execution only inside `wdc_extension`, replaces the synthetic
`start` failure with one statically provisioned FreeRTOS task and one bounded
static queue, implements deterministic health/quiescence/deinit, and preserves
reset as the authoritative hard teardown after task start. See
[HX3 extension lifecycle](HX3_EXTENSION_LIFECYCLE.md).

Neither target is promoted to `RUNTIME_PROVEN` without named ESP32-S3 and
ESP32-C6 boards.
