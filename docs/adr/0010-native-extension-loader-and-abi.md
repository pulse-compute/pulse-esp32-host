# ADR 0010 — Native Extension Loader and Experimental ABI

## Status

Accepted for the HX0-HX7 synthetic proof only.

This decision is experimental. It does not freeze a permanent public Pulse
native ABI or qualify an ELF loader, target runtime, or board.

## Context

PULSE-ESP32-003 redirects future device capabilities away from an expanding
firmware-owned semantic ABI and toward provider-selected target-native
refinements. The first implementation unit must determine whether that shape
remains coherent across the ESP32-S3 Xtensa and ESP32-C6 RISC-V
representatives while preserving the existing Pulse/Wasm event path.

Executing an extension function to learn whether the extension is compatible
would invert the admission boundary. Allowing a loader-specific API to leak
into lifecycle, provider, or guest code would also make the first dependency a
permanent architectural surface.

## Decision

### Two-stage admission

The host admits an extension in two stages:

1. An independent bounded ELF inspector validates structure, target machine,
   imports, relocations, constructor policy, and the fixed 192-byte
   `.pulse_ext_meta` record before loader execution.
2. After relocation behind `wdc_elf`, the host calls only
   `pulse_extension_entry_v1`, validates the fixed 160-byte descriptor and all
   lifecycle pointers, seals the catalog, and only then calls `init`.

A provider-generated sidecar may index or cache metadata but is not authority.
The normalized artifact digest is recomputed from the ELF. The runtime
descriptor carries a separate digest of the normalized metadata record, which
avoids a self-referential artifact hash while proving that the relocated
descriptor agrees with the inspected record. The same immutable raw buffer
that passed inspection is handed to the loader.

### Identity and catalog

Runtime identity is numeric and fixed-width: a 16-byte extension identity plus
32-bit event and operation identities. Human-readable names remain source-map
and evidence data. The provider resolves the complete catalog; the host rejects
duplicates and seals it before `init`. Runtime registration is absent.

### Lifecycle and task ownership

The lifecycle is `init`, `start`, `invoke`, `health`, `quiesce`, and `deinit`.
The host supplies the absolute quiescence deadline. The extension creates and
owns exactly one static task and one static bounded queue during `start`. The
host supervises but does not normally create or force-delete that task.

Reset remains the authoritative production hard teardown after task start.
Clean quiescence and unload cycles are still implemented and measured for
qualification. A missed deadline or uncertain task state requires reset and
prevents confirmation.

HX3 confirms normal task termination with an extension-installed FreeRTOS
thread-local deletion callback. The extension's `quiesce` does not release its
static TCB or queue backing until the kernel has invoked that callback. This is
target-refinement machinery, not a stable Pulse service.

### Host services and imports

The stable surface is six explicitly versioned imports:

```text
pulse_host_emit_event_v1
pulse_host_complete_effect_v1
pulse_host_monotonic_ms_v1
pulse_host_log_v1
pulse_host_report_health_v1
pulse_host_report_fault_v1
```

There is no allocation service in v1. Direct ESP-IDF and FreeRTOS imports are
target-refinement dependencies, must be enumerated per realization, and do not
become stable Pulse ABI. Unexpected and unresolved imports fail closed.

### Existing host boundaries

`wdc_elf` is a narrow loader adapter. Loader-specific types do not cross it.
`wdc_extension` owns admission, registry, and lifecycle. Extension events enter
the existing `wdc_events` queue and reach Wasm through `wdc_runtime`; extension
operations complete through host-owned correlations. No extension task or
callback calls Wasm directly.

The extension proof uses a separate matrix derived from
`esp32s3-reference` and `esp32c6-compile`. It does not alter IF7's historical
family-matrix results. WDC bundle v1 remains a single-Wasm container and is not
overloaded with native artifacts.

## Consequences

- Compatibility can be rejected before arbitrary extension code executes.
- A fixed in-ELF record avoids sidecar drift while keeping the loader behind a
  replaceable adapter.
- The runtime contract is small enough to implement as a C SDK with exact
  size/alignment assertions on both proof ISAs.
- Catalog sealing and host-owned correlation state prevent dynamic authority
  growth and ambiguous completion ownership.
- Direct platform imports remain visible target debt and evidence rather than
  silently becoming Pulse portability promises.
- Static task/queue ownership keeps the proof bounded and postpones allocation
  semantics until demonstrated pressure exists.
- Kernel-confirmed static-task deletion prevents a pre-delete flag from being
  mistaken for completed teardown.
- Clean unload is measurable, but this decision does not authorize hot
  extension replacement.
- The exact loader version, ELF type, relocations, target import allowlists,
  executable-memory placement, and repeated-cycle behavior remain HX1
  evidence decisions.

## Rejected alternatives

### Execute the descriptor to discover compatibility

Rejected because incompatible or malformed code would run before the host had
established target, ABI, catalog, or budget compatibility.

### Provider sidecar as sole authority

Rejected because the sidecar and ELF could drift or be substituted
independently. A sidecar remains useful as evidence, not as the final admission
source.

### Human-readable runtime identities

Rejected for v1 because C strings add length, termination, encoding,
allocation, and ownership ambiguity to the hot path. Evidence can retain
readable names without making them ABI.

### Host-created extension tasks

Rejected because it splits responsibility for driver topology and cleanup.
The extension owns its low-level task; the host owns declared budgets,
supervision, deadlines, and reset policy.

### Host allocation service in v1

Rejected because the synthetic proof can use static storage. Adding allocator
ownership before need would expand failure, lifetime, and teardown semantics.

### Extend WDC bundle v1 or introduce RAX now

Rejected because the loader/lifecycle proof should establish actual artifact
requirements before a composite deployment container is designed.

### Let networking or GPIO define the first ABI

Rejected because those capabilities introduce unrelated resource, driver,
timing, and recovery pressure. The first proof remains synthetic.

## References

- [PULSE-ESP32-004 host extension spine](../../specs/PULSE-ESP32-004-host-extension-spine.md)
- [PULSE-ESP32-003 native target refinement](../../specs/PULSE-ESP32-003-native-target-refinement-addendum.md)
- [ADR 0002 dispatcher-based ABI](0002-dispatcher-based-abi.md)
- [ADR 0004 reboot-based activation](0004-reboot-based-activation.md)
- [ADR 0009 IDF family build matrix](0009-idf-family-build-matrix.md)
