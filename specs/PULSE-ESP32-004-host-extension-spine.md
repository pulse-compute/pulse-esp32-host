# Pulse ESP32 Host Extension Spine Contract

**Document:** PULSE-ESP32-004  
**Version:** Experimental v0.1  
**Status:** HX0 contract; sufficient only for the synthetic dual-ISA proof  
**Prepared:** 2026-08-09  
**Baseline:** PULSE-ESP32-003 and the IF7 firmware source identity
`2e0935fbc0f8fc2013bb09c4f8a5453bc8718a91b3e0b5c3201b997e616c6a9e`  
**Required lane:** `idf-5.4.4`, ESP-IDF `v5.4.4`, source commit
`296b6eab9445fd720e71aecab961e2d3fbca9944`  
**Required proof targets:** `esp32s3-reference` and `esp32c6-compile`

## 1. Contract status and scope

This document freezes the smallest experimental native-extension contract
needed to test one host-extension spine on Xtensa and RISC-V. It is not a
permanent public ABI and it does not authorize a general capability catalog.

The proof boundary is:

```text
one common Pulse/Wasm artifact
  + one provider-selected native ELF for the exact target
  -> structural ELF and metadata inspection without executing extension code
  -> relocation through one pinned loader adapter
  -> runtime descriptor validation
  -> sealed event/operation registry
  -> init, start, invoke, health, quiesce, deinit
  -> one extension-owned task and bounded queue
  -> one synthetic event/effect round trip through the existing Wasm path
```

The native extension is trusted target refinement. It shares the firmware
address space and is not an adversarial sandbox. Admission, bounded resources,
lifecycle supervision, health, fault recording, probation, and recovery remain
fail-closed because trusted code can still be wrong.

HX0 introduces no loader, extension, firmware integration, runtime result, or
hardware result. Those claims require later passes and their exact evidence.

## 2. Authority and amendments

This document is authoritative for the HX0-HX7 extension proof. It explicitly
amends the illustrative native-extension shape in PULSE-ESP32-003 as follows:

1. Runtime identity uses a fixed 128-bit extension identity and fixed 32-bit
   event/operation identities. Unbounded C strings are not ABI identity.
2. A fixed `.pulse_ext_meta` ELF section is the pre-execution compatibility
   authority. A provider sidecar may cache or report the same facts but is not
   admission authority.
3. The runtime export is one versioned descriptor entry point with six
   lifecycle functions: `init`, `start`, `invoke`, `health`, `quiesce`, and
   `deinit`.
4. `quiesce` replaces the illustrative `stop` function and receives an
   explicit host-owned absolute deadline.
5. The extension creates and owns its one task and bounded queue during
   `start`. The host does not create or normally force-delete extension tasks.
6. Stable host services use explicitly versioned `pulse_host_*_v1` imports.
   Direct ESP-IDF and FreeRTOS imports remain target-refinement dependencies,
   not Pulse ABI.
7. Host allocation is absent from extension ABI v1. The synthetic proof must
   use declared static state, a statically provisioned queue, and a statically
   provisioned task.
8. The proof matrix adds an independent ESP32-C6 RISC-V member without
   changing the historical IF7 family-matrix result vocabulary or claims.

WDC-ABI-001 remains the Wasm/host contract. WDC-BUNDLE-001 remains the existing
single-Wasm bundle contract. This document does not overload either one with a
native ELF member.

## 3. Governing invariants

1. No extension constructor, lifecycle function, registration callback, or
   arbitrary entry point executes before pre-execution admission succeeds.
2. Relocation does not imply lifecycle admission. The descriptor and every
   lifecycle function pointer are validated before `init`.
3. The host owns loading, registry sealing, lifecycle order, supervision,
   event/effect bridging, deadlines, confirmation, fault policy, and recovery.
4. The extension owns its low-level implementation, one task, one queue, and
   all extension-local state.
5. No ISR, driver callback, or extension task enters Wasm directly.
6. The existing `wdc_events`, `wdc_runtime`, `wdc_abi`, `wdc_caps`,
   `wdc_activation`, `wdc_diag`, and `wdc_safety` paths remain the downstream
   Wasm and recovery authorities. The extension spine does not create a second
   guest runtime or dispatcher.
7. The event and operation catalog is provider-resolved, validated, and sealed
   before `init`. There is no runtime registration API in v1.
8. The host assigns correlation identities and owns their terminal state.
9. The first accepted completion wins. Duplicate, late, unknown, or
   post-quiescence completions have no effect and return an explicit error.
10. Candidate confirmation is host-owned. Extension health is evidence, not
    authority.
11. Clean quiescence is required and measured. A missed deadline, uncertain
    task state, or irrecoverable extension fault requires reset.
12. Reset remains the authoritative production hard teardown after extension
    tasks have started. Qualification may exercise clean unload cycles but does
    not establish hot replacement.
13. One logical candidate is atomic even though its common Wasm and selected
    native ELF remain distinct artifacts.
14. Provider resolution is explicit. Portable handlers contain no target
    detection and the host performs no hidden fallback between native ELFs.

## 4. ABI representation rules

The runtime ABI is an experimental C ABI for the two 32-bit little-endian proof
targets. All public declarations use the `pulse_` prefix and `extern "C"` when
compiled as C++.

The following rules are normative:

- `uint8_t`, `uint16_t`, `uint32_t`, and `int32_t` are the only scalar integer
  field types.
- A logical 64-bit value is represented as `{ uint32_t lo; uint32_t hi; }`.
  Native `uint64_t` is not stored in a public runtime struct.
- Public structs have 4-byte alignment and an exact frozen `struct_size`.
- Public structs are not compiler-packed. Fields are ordered so natural
  4-byte layout produces the specified offsets.
- `_Static_assert` checks for size, alignment, and every function-pointer
  offset are required in the C SDK introduced by HX2.
- `bool`, C enums, bitfields, `size_t`, `long`, `uintptr_t`, flexible arrays,
  variadic functions, and unbounded C strings are prohibited in the ABI.
- Runtime pointers and function pointers are 32-bit on both proof targets.
  Every pointer is checked to be in the appropriate admitted image or caller
  span before use.
- Reserved fields and unknown flags must be zero. A nonzero reserved value is
  an admission or call error, not a compatibility hint.
- On-disk integers are little-endian. Runtime structs use the target's native
  little-endian representation.
- A `(pointer, length)` span is borrowed only for the duration of the call.
  A callee that needs bytes after return must copy them into its own declared
  bounded storage before returning success.

The common status type is signed 32-bit:

| Value | Name | Meaning |
|---:|---|---|
| `0` | `PULSE_EXT_OK` | Operation accepted or completed successfully. |
| `-1` | `PULSE_EXT_ERR_ARGUMENT` | Invalid pointer, field, flag, or encoding. |
| `-2` | `PULSE_EXT_ERR_STATE` | Operation is invalid in the current lifecycle state. |
| `-3` | `PULSE_EXT_ERR_UNSUPPORTED` | Identity, ABI, or operation is unsupported. |
| `-4` | `PULSE_EXT_ERR_BUSY` | A bounded queue or in-flight limit is full. |
| `-5` | `PULSE_EXT_ERR_TIMEOUT` | The host-owned deadline expired. |
| `-6` | `PULSE_EXT_ERR_BOUNDS` | A declared or host limit was exceeded. |
| `-7` | `PULSE_EXT_ERR_DUPLICATE` | A completion or transition already terminated. |
| `-8` | `PULSE_EXT_ERR_STALE` | Correlation identity is unknown, expired, or quiesced. |
| `-9` | `PULSE_EXT_ERR_FAULT` | The extension or host service is faulted. |

An extension may define diagnostic detail codes, but they do not add status
semantics or change host policy.

## 5. Pre-execution ELF admission

### 5.1 Inspection order

The host or provider must inspect the raw ELF bytes before handing them to the
loader:

1. validate total byte length and ELF magic;
2. require `ELFCLASS32`, little-endian data, and current ELF version;
3. validate every ELF header, program header, section header, string-table
   range, symbol range, and relocation range with overflow-safe arithmetic;
4. validate `e_machine` against the selected realization;
5. locate exactly one `.pulse_ext_meta` section;
6. validate the fixed metadata record and normalized artifact digest;
7. enumerate exported and undefined symbols;
8. reject unexpected or unresolved imports;
9. enumerate relocation types and reject any type not explicitly qualified for
   the exact target and loader;
10. reject executable constructors or automatic initialization surfaces; and
11. only then pass the bytes to `wdc_elf` for relocation.

The accepted ELF `e_type`, relocation sets, and loader-specific section policy
remain HX1 evidence decisions. They must be closed independently for S3 and C6
before either target is classified positively.

### 5.2 Metadata-section decision

The canonical pre-execution record is an ELF `SHT_PROGBITS` section named
`.pulse_ext_meta` with 4-byte alignment and exactly 192 bytes. It must not have
`SHF_EXECINSTR`; it must be file-backed and contained wholly within the ELF.
There must be exactly one record and no alternate metadata source may override
it.

The loader adapter must preserve access to the original ELF bytes or run the
independent inspector before relocation. Candidate-loader convenience APIs are
not required to expose the section. A generated sidecar may be retained as
build evidence or a transport index, but admission recomputes and compares the
record from the ELF itself.

### 5.3 Metadata record v1

Magic is the eight bytes `PULSEXT1`. The format version is `1.0`. Unused
catalog entries and all reserved bytes are zero.

| Offset | Size | Field | Rule |
|---:|---:|---|---|
| 0 | 8 | `magic` | Exact bytes `PULSEXT1`. |
| 8 | 2 | `format_major` | `1`. |
| 10 | 2 | `format_minor` | `0`. |
| 12 | 4 | `record_size` | `192`. |
| 16 | 2 | `architecture_id` | Closed value from Section 5.4. |
| 18 | 2 | `soc_id` | Closed value from Section 5.4. |
| 20 | 4 | `flags` | Zero in v1. |
| 24 | 2 | `required_host_abi_major` | `1`. |
| 26 | 2 | `required_host_abi_min_minor` | Minimum compatible minor. |
| 28 | 2 | `extension_abi_major` | `1`. |
| 30 | 2 | `extension_abi_minor` | `0`. |
| 32 | 16 | `extension_id` | Nonzero provider-assigned fixed identity. |
| 48 | 4 | `descriptor_size` | `160`. |
| 52 | 4 | `descriptor_alignment` | `4`. |
| 56 | 2 | `event_count` | `1..4` for this proof. |
| 58 | 2 | `operation_count` | `1..4` for this proof. |
| 60 | 4 | `reserved0` | Zero. |
| 64 | 16 | `event_ids[4]` | Nonzero unique `uint32_t` IDs followed by zero fill. |
| 80 | 16 | `operation_ids[4]` | Nonzero unique `uint32_t` IDs followed by zero fill. |
| 96 | 4 | `task_count` | Exactly `1`. |
| 100 | 4 | `task_stack_bytes` | Declared static task stack. |
| 104 | 4 | `static_memory_bytes` | Extension-owned static state, excluding ELF text/rodata. |
| 108 | 4 | `queue_depth` | Declared bounded queue depth. |
| 112 | 4 | `queue_item_bytes` | Declared fixed queue item size. |
| 116 | 4 | `max_event_payload_bytes` | At most `128`. |
| 120 | 4 | `max_effect_request_bytes` | At most `256`. |
| 124 | 4 | `max_effect_completion_bytes` | At most `256`. |
| 128 | 32 | `artifact_sha256` | Normalized ELF digest defined below. |
| 160 | 32 | `reserved1` | All zero. |

The normalized artifact digest is SHA-256 over the complete raw ELF with the
32 bytes occupied by `artifact_sha256` replaced by zero bytes. This avoids a
self-referential digest while binding the metadata and runtime descriptor to
the exact artifact. The provider, inspector, and host must compute the same
value. A sidecar-supplied hash is never trusted without recomputation.

The normalized metadata digest is SHA-256 over the exact 192-byte metadata
record with those same bytes 128 through 159 replaced by zero. It is distinct
from the artifact digest and is stored in the runtime descriptor so the host
can compare the post-relocation descriptor to the admitted metadata without
introducing a second self-reference.

### 5.4 Target identities

| Realization | `e_machine` | `architecture_id` | `soc_id` |
|---|---:|---:|---:|
| `esp32s3-reference` | `EM_XTENSA` (`94`) | `1` | `1` |
| `esp32c6-compile` | `EM_RISCV` (`243`) | `2` | `2` |

Every identity must agree with the provider selection. An ELF that merely has
the right CPU architecture but the wrong SoC identity is rejected.

### 5.5 Constructor and dynamic-link policy

The proof rejects `.init_array`, `.fini_array`, `.ctors`, `.dtors`, TLS
initialization, `PT_INTERP`, `DT_NEEDED`, `DT_INIT`, and `DT_FINI`. The loader
must not call a module entry point, constructor, or registration hook as a side
effect of relocation. HX1 must confirm this behavior in source and evidence;
registry documentation alone is insufficient.

## 6. Runtime descriptor admission

After relocation, the host resolves exactly one export:

```c
const pulse_extension_descriptor_v1 *pulse_extension_entry_v1(void);
```

The entry call is the first admitted extension code. It must be pure: no task
or queue creation, registration, allocation, host-service call, or persistent
mutation. A fault or invalid return rejects the candidate before `init`.

The returned descriptor must be readable within the relocated image, aligned
to 4 bytes, and exactly 160 bytes:

| Offset | Size | Field | Rule |
|---:|---:|---|---|
| 0 | 4 | `magic` | `0x31545845` (`EXT1` in little-endian bytes). |
| 4 | 4 | `struct_size` | `160`. |
| 8 | 2 | `abi_major` | `1`. |
| 10 | 2 | `abi_minor` | `0`. |
| 12 | 4 | `flags` | Zero in v1. |
| 16 | 16 | `extension_id` | Exact metadata match. |
| 32 | 32 | `metadata_sha256` | Exact normalized metadata digest from Section 5.3. |
| 64 | 2 | `event_count` | Exact metadata match. |
| 66 | 2 | `operation_count` | Exact metadata match. |
| 68 | 4 | `reserved0` | Zero. |
| 72 | 16 | `event_ids[4]` | Exact metadata match. |
| 88 | 16 | `operation_ids[4]` | Exact metadata match. |
| 104 | 4 | `init_fn` | Non-null admitted executable address. |
| 108 | 4 | `start_fn` | Non-null admitted executable address. |
| 112 | 4 | `invoke_fn` | Non-null admitted executable address. |
| 116 | 4 | `health_fn` | Non-null admitted executable address. |
| 120 | 4 | `quiesce_fn` | Non-null admitted executable address. |
| 124 | 4 | `deinit_fn` | Non-null admitted executable address. |
| 128 | 32 | `reserved1` | All zero. |

Each function pointer must fall in a loader-reported executable range belonging
to this extension. The descriptor itself must fall in a loader-reported
readable range. No lifecycle pointer may alias a host function or another
extension image.

The immutable raw ELF buffer accepted by the inspector is the buffer handed to
the loader. Substitution, mutation, or re-fetch between admission and
relocation invalidates admission and requires inspection to restart.

## 7. Catalog identity and registry sealing

The runtime uses fixed identities only:

- extension identity: 16 bytes;
- event identity: nonzero `uint32_t`;
- operation identity: nonzero `uint32_t`.

Names such as `test:tick` and `test:echo` belong in source maps and evidence.
They are not passed as C strings through the runtime ABI. The provider assigns
their numeric identities deterministically.

The host performs this order for the complete candidate graph:

```text
inspect every ELF
  -> relocate every admitted ELF
  -> validate every descriptor
  -> reject duplicate extension IDs
  -> reject duplicate event IDs
  -> reject duplicate operation IDs
  -> verify metadata/descriptor/catalog agreement
  -> seal registry
  -> init extensions in deterministic provider order
  -> start extensions in the same order
```

There is no registration callback or post-seal catalog mutation. Partial
initialization unwinds successfully initialized extensions in reverse order.
If any `start` call has occurred, teardown follows the stronger rules in
Section 9.

## 8. Call records, spans, and deadlines

### 8.1 Common span and logical time

`pulse_byte_span_v1` is exactly 8 bytes and 4-byte aligned:

| Offset | Size | Field |
|---:|---:|---|
| 0 | 4 | `ptr` |
| 4 | 4 | `len` |

The pointer is borrowed for the call only. Zero length requires a null pointer;
nonzero length requires a non-null pointer and a range wholly valid in the
caller's admitted memory.

Logical 64-bit values use exactly 8 bytes:

| Offset | Size | Field |
|---:|---:|---|
| 0 | 4 | `lo` |
| 4 | 4 | `hi` |

The numeric value is `(hi << 32) | lo`.

### 8.2 Initialization record

`pulse_extension_init_args_v1` is 64 bytes:

| Offset | Size | Field |
|---:|---:|---|
| 0 | 4 | `struct_size` (`64`) |
| 4 | 4 | `flags` (zero) |
| 8 | 8 | `activation_epoch` |
| 16 | 8 | `boot_monotonic_ms` |
| 24 | 4 | `host_event_queue_capacity` |
| 28 | 4 | `host_max_event_payload_bytes` |
| 32 | 4 | `host_max_effect_completion_bytes` |
| 36 | 4 | `host_max_inflight_effects` |
| 40 | 16 | `extension_id` |
| 56 | 8 | `reserved` (zero) |

The record is borrowed for `init` only.

### 8.3 Invocation record

`pulse_extension_invoke_v1` is 48 bytes:

| Offset | Size | Field |
|---:|---:|---|
| 0 | 4 | `struct_size` (`48`) |
| 4 | 4 | `operation_id` |
| 8 | 8 | `correlation_id` |
| 16 | 8 | `deadline_ms` |
| 24 | 4 | `payload_ptr` |
| 28 | 4 | `payload_len` |
| 32 | 4 | `flags` (zero) |
| 36 | 12 | `reserved` (zero) |

The deadline is an absolute host monotonic time. The host rejects a zero,
expired, over-policy, or reused correlation identity before calling the
extension. The extension must copy an accepted request into its declared queue
before returning `PULSE_EXT_OK`. A non-OK return means the request was not
accepted and no completion is permitted.

### 8.4 Health record

`pulse_extension_health_v1` is 48 bytes:

| Offset | Size | Field |
|---:|---:|---|
| 0 | 4 | `struct_size` (`48`) |
| 4 | 4 | `state` |
| 8 | 4 | `fault_status` |
| 12 | 4 | `pending_count` |
| 16 | 4 | `queue_high_water` |
| 20 | 4 | `task_stack_high_water_bytes` |
| 24 | 8 | `last_progress_ms` |
| 32 | 4 | `flags` (zero) |
| 36 | 12 | `reserved` (zero) |

Allowed states are `1=initialized`, `2=running`, `3=quiescing`,
`4=quiesced`, and `5=faulted`. Unknown states fail health validation.

### 8.5 Quiescence record

`pulse_extension_quiesce_v1` is 32 bytes:

| Offset | Size | Field |
|---:|---:|---|
| 0 | 4 | `struct_size` (`32`) |
| 4 | 4 | `reason` |
| 8 | 8 | `deadline_ms` |
| 16 | 4 | `flags` (zero) |
| 20 | 12 | `reserved` (zero) |

The host owns the absolute deadline and never extends it based on extension
input. `quiesce` must stop accepting work immediately, deterministically drain
or reject queued work, terminate the extension-owned task, and return
`PULSE_EXT_OK` only after no extension task can call a host service. A timeout
or uncertain task state latches a fault and requires reset.

## 9. Lifecycle contract

The descriptor functions have these signatures:

```c
int32_t init(const pulse_extension_init_args_v1 *args);
int32_t start(void);
int32_t invoke(const pulse_extension_invoke_v1 *request);
int32_t health(pulse_extension_health_v1 *out_health);
int32_t quiesce(const pulse_extension_quiesce_v1 *request);
int32_t deinit(void);
```

The lifecycle state machine is:

```text
INSPECTED
  -> RELOCATED
  -> DESCRIPTOR_VALIDATED
  -> REGISTRY_SEALED
  -> INITIALIZED
  -> STARTED
  -> QUIESCING
  -> QUIESCED
  -> DEINITIALIZED
  -> UNLOADED
```

Rules:

- `init` validates and initializes declared static state only. It must not
  create a task or make the extension externally active.
- `start` creates exactly one statically provisioned task and one statically
  provisioned bounded queue. It is the only normal task-creation point.
- `invoke` is valid only in `STARTED`; it must never call Wasm.
- `health` is a bounded, nonblocking snapshot and is valid from `INITIALIZED`
  through `QUIESCED`.
- `quiesce` is valid after `start` was entered, including when `start` returned
  failure after partial task or queue creation.
- `deinit` releases or zeroes extension-owned state. It is allowed after
  successful `quiesce`, or after `init` when `start` was never entered.
- Duplicate and out-of-order transitions return `PULSE_EXT_ERR_STATE` without
  side effects.
- An `init` call that returns a non-OK status must still leave state safe for
  `deinit`; the host calls `deinit`. A trap, fault, or invalid control return
  from `init` does not establish reversibility, so the host records the fault
  and resets before activating a candidate.
- When `start` fails, the host assumes a task may exist, requests quiescence,
  and resets if quiescence is not positively confirmed by the deadline.
- Normal multi-extension teardown occurs in reverse start/init order.
- The host does not use arbitrary task deletion as normal cleanup.

Qualification may execute repeated clean
`load -> init -> start -> quiesce -> deinit -> unload` cycles to measure leaks.
That evidence does not authorize live application hot-swap. Production
activation continues to use a reset boundary.

## 10. Stable host-service imports

The synthetic proof admits exactly these stable Pulse imports:

| Import | Signature | Bound |
|---|---|---|
| `pulse_host_emit_event_v1` | `int32_t(const pulse_extension_event_v1 *)` | Existing host event queue and 128-byte payload ceiling. |
| `pulse_host_complete_effect_v1` | `int32_t(const pulse_extension_completion_v1 *)` | One terminal completion and 256-byte payload ceiling. |
| `pulse_host_monotonic_ms_v1` | `int32_t(pulse_u64_parts_v1 *)` | Fixed 8-byte output. |
| `pulse_host_log_v1` | `int32_t(const pulse_extension_log_v1 *)` | 96-byte message ceiling; no C string. |
| `pulse_host_report_health_v1` | `int32_t(const pulse_extension_health_v1 *)` | Fixed 48-byte snapshot. |
| `pulse_host_report_fault_v1` | `int32_t(const pulse_extension_fault_v1 *)` | Fixed 32-byte fault record. |

The service argument records have the following exact layouts. Every 64-bit
identity uses the two-word representation from Section 8.1.

### 10.1 Event record

`pulse_extension_event_v1` is exactly 40 bytes:

| Offset | Size | Field |
|---:|---:|---|
| 0 | 4 | `struct_size` (`40`) |
| 4 | 4 | `event_id` |
| 8 | 8 | `causation_id` |
| 16 | 4 | `payload_ptr` |
| 20 | 4 | `payload_len` |
| 24 | 4 | `flags` (zero) |
| 28 | 12 | `reserved` (zero) |

### 10.2 Completion record

`pulse_extension_completion_v1` is exactly 40 bytes:

| Offset | Size | Field |
|---:|---:|---|
| 0 | 4 | `struct_size` (`40`) |
| 4 | 4 | `status` (signed) |
| 8 | 8 | `correlation_id` |
| 16 | 4 | `payload_ptr` |
| 20 | 4 | `payload_len` |
| 24 | 4 | `flags` (zero) |
| 28 | 12 | `reserved` (zero) |

### 10.3 Log record

`pulse_extension_log_v1` is exactly 24 bytes:

| Offset | Size | Field |
|---:|---:|---|
| 0 | 4 | `struct_size` (`24`) |
| 4 | 4 | `level` |
| 8 | 4 | `diagnostic_code` |
| 12 | 4 | `message_ptr` |
| 16 | 4 | `message_len` |
| 20 | 4 | `flags` (zero) |

### 10.4 Fault record

`pulse_extension_fault_v1` is exactly 32 bytes:

| Offset | Size | Field |
|---:|---:|---|
| 0 | 4 | `struct_size` (`32`) |
| 4 | 4 | `status` (signed) |
| 8 | 4 | `fault_code` |
| 12 | 8 | `correlation_id` |
| 20 | 4 | `flags` (zero) |
| 24 | 8 | `reserved` (zero) |

### 10.5 Service behavior

Every host service validates lifecycle state, extension identity inferred from
the resolved caller/image, record size, flags, pointer range, declared catalog,
payload bound, queue capacity, correlation state, and deadline before changing
host state.

`pulse_host_emit_event_v1` copies accepted bytes into `wdc_events`. Queue-full
returns `PULSE_EXT_ERR_BUSY`; a required event is never silently dropped.
`wdc_events` remains the only ingress path to `wdc_runtime`.

`pulse_host_complete_effect_v1` performs an atomic terminal transition on the
host-owned correlation record:

- first in-deadline completion: accepted;
- second completion: `PULSE_EXT_ERR_DUPLICATE`;
- unknown, timed-out, canceled, or post-quiescence completion:
  `PULSE_EXT_ERR_STALE`;
- oversized payload: `PULSE_EXT_ERR_BOUNDS`.

Rejected duplicate or stale completions do not publish an event, mutate the
first result, revive a timeout, or affect candidate confirmation.

`pulse_host_report_health_v1` updates a bounded observed snapshot. It does not
confirm the candidate. `pulse_host_report_fault_v1` latches the first fatal
fault for the activation epoch and routes it through diagnostics and safety.

There is no allocation or release import in v1.

## 11. Target-refinement import policy

Undefined symbols belong to one of two closed sets:

1. the six stable `pulse_host_*_v1` imports in Section 10; or
2. an exact per-realization ESP-IDF/FreeRTOS allowlist frozen by HX1 evidence.

Direct ESP-IDF/FreeRTOS symbols are target-refinement dependencies. Their
names, providing component, version, source identity, and observed use must be
enumerated independently for S3 and C6. They are not stable Pulse ABI and must
not appear in portable Wasm or provider-neutral handler logic.

Wildcard symbol families, ambient global resolution, `dlsym`-style lookup,
unresolved weak imports, and silently ignored unsupported relocations are
prohibited. Unexpected or unresolved symbols fail inspection or build
qualification.

The proof also rejects dynamic allocation imports including `malloc`,
`calloc`, `realloc`, `free`, C++ `new/delete`, and ESP-IDF heap allocation.
Static FreeRTOS task and queue primitives may be admitted only after their
exact symbols are enumerated by HX1.

## 12. Resource budgets

The host compares metadata declarations to the selected proof profile before
relocation. HX0 ceilings are:

| Resource | Contract bound |
|---|---:|
| Extension task count | exactly `1` |
| Task stack | `2048..8192` bytes, multiple of 16 |
| Extension static state | at most `16384` bytes |
| Queue depth | `1..16` |
| Queue item size | `32..512` bytes, multiple of 4 |
| Queue storage | at most `4096` bytes |
| Declared event IDs | `1..4` |
| Declared operation IDs | `1..4` |
| Event payload | at most `128` bytes |
| Effect request payload | at most `256` bytes |
| Effect completion payload | at most `256` bytes |
| Log message | at most `96` bytes |

The provider may select smaller limits. It may not silently increase a host
profile or substitute a different realization to fit an extension.
`static_memory_bytes` includes writable extension state and static RTOS
control blocks. Task-stack and queue-storage bytes are declared and checked
separately, so they are not counted again in `static_memory_bytes`.

## 13. Event/effect round-trip semantics

The synthetic flow is:

```text
extension task
  -> pulse_host_emit_event_v1(numeric test:tick identity)
  -> wdc_events bounded queue
  -> existing event encoding
  -> wdc_runtime invokes one common Wasm handler
  -> host resolves numeric test:echo operation
  -> invoke with host correlation and deadline
  -> extension copies request into its bounded queue
  -> extension task processes request
  -> pulse_host_complete_effect_v1 exactly once
  -> host records bounded terminal result
```

The common Wasm bytes must be identical for the S3 and C6 realization outputs.
No target ID, ELF detail, ESP-IDF symbol, or extension task primitive enters
the Wasm artifact.

## 14. Failure and recovery policy

The host records and fails closed for:

- malformed ELF or metadata;
- target, ABI, identity, catalog, descriptor, or digest disagreement;
- unexpected import, unresolved symbol, or unsupported relocation;
- constructor or automatic-entry surface;
- descriptor entry fault or invalid pointer;
- duplicate identity;
- over-budget metadata;
- illegal lifecycle transition;
- init/start/invoke/health/quiesce/deinit failure;
- queue saturation;
- expired request or late/duplicate completion;
- health stagnation or fault report;
- unexplained retained memory; and
- uncertain task termination or ELF unload.

Before `start`, a fully reversible failure may unload the extension after
reverse cleanup. After `start` was entered, failure cleanup attempts bounded
quiescence. A missed deadline or uncertain task state records a retained fault
and requires reset. Any failed or partial ELF unload also preserves candidate
fault evidence and requires reset; the registry is never reusable after
uncertain loader ownership. The candidate is not confirmed by
extension-returned health alone.

## 15. Separate dual-ISA proof matrix

HX1 introduces `firmware/extension-proof-matrix.json`. It is separate from
`firmware/idf-family-matrix.json` and does not rewrite IF7 history.

| Proof member | ISA | Basis | HX0 state |
|---|---|---|---|
| `esp32s3-extension-proof` | Xtensa | `esp32s3-reference` | Contract only; no new build/runtime claim. |
| `esp32c6-extension-proof` | RISC-V | `esp32c6-compile` | Contract only; no new build/runtime claim. |

Each target later receives exactly one of `RUNTIME_PROVEN`, `BUILD_PROVEN`,
`CONTRACT_PROVEN`, `INCOMPATIBLE`, `HARDWARE_NOT_RUN`,
`INFRASTRUCTURE_FAILURE`, or `UNCLASSIFIED_FAILURE`. Aggregate decisions remain
limited to the HX handoff vocabulary. S3 evidence is never reused for C6.

## 16. HX0 negative contract

The following are prohibited in this ABI:

- unbounded C strings;
- ownership-ambiguous retained pointers;
- arbitrary runtime event or operation registration;
- extension-controlled candidate confirmation;
- host-created or host-force-deleted extension tasks as normal operation;
- direct extension-to-Wasm calls;
- silent event loss or completion replacement;
- implicit target detection or fallback;
- network, GPIO, BLE, LoRa, storage, RAX, OTA, partition, or transport
  semantics;
- a host allocation service;
- a general peripheral or capability catalog; and
- any runtime or hardware claim inferred from host tests or compile evidence.

## 17. HX1 evidence decisions remaining

HX0 intentionally leaves only loader- and target-evidence questions to HX1:

| Decision | Required HX1 evidence |
|---|---|
| Exact loader | Immutable source/version, license, IDF intersection, component locks. |
| Accepted ELF type | Exact `e_type` supported and actually produced per target. |
| Relocations | Complete supported/observed inventories for S3 and C6. |
| Symbol resolution | Exact export mechanism and per-target direct-import allowlists. |
| Constructor behavior | Source-backed proof that load/relocation executes no constructor or entry point. |
| Executable memory | Placement, permissions where available, IRAM/DRAM/PSRAM/flash deltas. |
| Loader ownership | Load, failure unwind, unload, and repeated-cycle behavior. |
| C6 fit | Exact extension-enabled build result under the declared realization. |
| Raw-byte inspection handoff | Exact adapter path that inspects `.pulse_ext_meta` before relocation. |

If any item cannot be classified independently for both targets, HX1 stops
with the exact blocker rather than broadening the ABI or weakening admission.

## 18. Deferred work

This contract does not define GPIO, network, BLE, LoRa, sensors, storage,
deployment transport, RAX, composite slots, application rollback, firmware
OTA, hot replacement, production signatures, secure boot, fleet provisioning,
or a public provider package. The existing prototype components may remain,
but they are not incorporated into the extension ABI by implication.

The next pass after the spine and named-board observations is HX5 hardening,
split into HX5a structural fault coverage and HX5b sustained pressure plus
targeted hardware reruns. Capability work must wait for that seal and must
reuse this lifecycle and event/effect path rather than reopen the host boundary
casually.

HX5b implements that pressure boundary through the machine-readable
`PULSE-ESP32-005b-extension-pressure-seal.json`, sustained host queue,
completion, Wasm-trap, and native-fault campaigns, plus opt-in fail-closed S3
and C6 hardware reruns. It deliberately adds no capability surface and does not
start HX6 or HX7.
