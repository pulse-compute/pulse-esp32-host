# HX4 provisional extension event/effect round trip

## Result and phase boundary

HX4 implements the complete synthetic happy path through the existing Pulse
event, Wasm runtime, and host-call dispatcher. Its phase is
`PROVISIONAL_HAPPY_PATH`: the host path and the exact common Wasm bytes execute,
while S3/C6 native ELFs and firmware remain build-only evidence. Target runtime
is `HARDWARE_NOT_RUN`.

HX4 is intentionally not the adversarial seal. HX4.5 must execute the deferred
identity, overflow, oversize, deadline, stale completion, trap, quiescence, and
extension-fault cases. Hardware testing follows HX4.5; HX5 must not begin before
that stop and S3 review.

Those deferred cases are subsequently executed and closed by the
[HX4.5 adversarial seal](HX4_5_EXTENSION_ADVERSARIAL.md). This document retains
the original HX4 phase boundary and happy-path evidence.

The accepted sandbox run and report hashes are recorded in the durable
[native-extension host evidence index](../evidence/host-extension/INDEX.md#native-extension-host-evidence-index).
Artifact-level hashes, including the executed event/effect transcript, remain
inside the separately packaged machine-readable evidence tree rather than
being copied into this source document.
The nested dual-target firmware report has SHA-256
`9f9e49562af8876ad3e465f30929dd8a1c2e41dc5bb88bb0f5cbf78a9962935b`.

## Implemented path

```text
synthetic extension task
  -> pulse_host_emit_event_v1 (bounded, caller-attributed copy)
  -> existing wdc_events queue
  -> wdc_extension_bridge_process_next
  -> existing wdc_runtime_dispatch_event
  -> common Wasm wdc_module_on_event
  -> existing wdc_host_call dispatcher, WDC_OP_EFFECT_INVOKE
  -> sealed numeric extension registry
  -> extension invoke copies request into its static queue
  -> extension task calls pulse_host_complete_effect_v1 exactly once
  -> host-owned bounded completion slot and CBOR response
```

There is no alternate event queue, second Wasm dispatcher, direct
extension-to-Wasm call, or target selector in the guest artifact. The bridge
pops only from `wdc_events`, calls only `wdc_runtime_dispatch_event`, and
resolves the operation only from a sealed registry whose candidate is
`STARTED`.

The synthetic identities remain numeric catalog values:

| Purpose | Symbolic evidence name | Numeric ID |
|---|---|---:|
| Extension event | `test:tick` | `0x5449434b` |
| Extension operation | `test:echo` | `0x4543484f` |
| Wasm dispatcher operation | `WDC_OP_EFFECT_INVOKE` | `0x0801` |

## Ownership and bounds

The event service identifies the calling candidate from the return address in
its admitted executable range. It requires the record and payload to be inside
that candidate's admitted memory, checks the sealed event catalog and candidate
state, enforces the metadata payload limit, copies into `wdc_events`, and
returns a visible busy error if the queue is full.

For an effect, the host assigns a nonzero correlation ID and absolute monotonic
deadline before invoking the resolved candidate. The extension must copy the
borrowed request before returning from `invoke`. One statically allocated,
host-owned completion slot accepts only the matching candidate and correlation,
only while the candidate is `STARTED`, and only before the deadline. The first
valid completion is copied; a second completion is explicitly duplicate. An
active effect is canceled before lifecycle quiescence.

The dispatcher remains fail closed. `WDC_OP_EFFECT_INVOKE` is effectful in the
safety guard and can delegate to the bridge only when an authorizer is
installed. A missing authorizer still emits capability denial; the effect hook
does not make the opcode safe by default.

## Common Wasm artifact

`wdc_hx4_event_effect_wasm.wasm` is generated without an external Wasm
toolchain and is byte deterministic. It imports only `wdc.wdc_host_call`,
exports the four required lifecycle functions plus memory, and contains no S3,
C6, Xtensa, RISC-V, or `IDF_TARGET` selector.

Its SHA-256 is
`ef8b21a4b7a423923c09f5e38fc626ff7d1cda856c4935db7f191695a333e5c4`;
its length is 306 bytes. Qualification independently copies these canonical
bytes into both target realization directories and rejects any hash mismatch.

## Executed happy-path evidence

The native host smoke executes the complete ownership path with a started mock
descriptor. It observes one queued event, one Wasm-handler entry, one resolved
invoke, one accepted completion, queue depth `1 -> 0`, causation `42`,
correlation `1`, absolute deadline `2000` ms, and 8-byte CBOR request and
completion payloads. It also checks the required exactly-once sentinel by
observing an explicit duplicate result for a second completion.

A separate Node smoke instantiates and executes the exact committed Wasm bytes.
It observes one opcode `0x0801` request for operation `0x4543484f` with payload
`hx4-echo`; all four lifecycle exports return success. This is a real Wasm
execution, but it is not the WAMR target runtime.

## Accepted dual-target build evidence

The exact ESP-IDF v5.4.4 source commit is
`296b6eab9445fd720e71aecab961e2d3fbca9944`. Both lanes use Espressif GCC
14.2.0 (`esp-14.2.0_20260121`) and the same offline managed-component mirror.
Baseline and extension-enabled firmware link for each target, and both isolated
extension runs reproduce the firmware binary, firmware ELF, bootloader,
partition table, configuration, lock, and size report byte-for-byte.

| Target | Synthetic ELF | Firmware delta | Internal RAM delta | Linked internal RAM remaining | Runtime |
|---|---:|---:|---:|---:|---|
| ESP32-S3 / Xtensa | 9,544 B | +9,712 B | +544 B | 2,157 B | `HARDWARE_NOT_RUN` |
| ESP32-C6 / RISC-V | 8,008 B | +10,112 B | +520 B | 114,098 B | `HARDWARE_NOT_RUN` |

The S3 number is static link headroom under the pinned realization, not live
heap proof. Dedicated IRAM still has the inherited one-byte margin, although
HX4 adds no dedicated-IRAM use. The admitted synthetic extension separately
declares 7,424 bytes of task stack, static memory, and queue backing that is
allocated at runtime. Heap/PSRAM stages, task stack high-water marks, queue
depth, completion latency, WAMR execution, and loader lifecycle therefore stay
unmeasured until the named-board run after HX4.5.

## Qualification commands

```bash
make check-hx0 check-hx1 check-hx2 check-hx3 check-hx4
HX_OUT_DIR=reports/host-extension/hx4-<fresh-id> \
  make host-extension-runtime-qualify
```

The qualifier runs inherited HX3 lifecycle checks, the HX4 native and real-Wasm
smokes, two deterministic synthetic ELF builds for each ISA, identical common
Wasm realization checks, and two isolated firmware builds per target. Its
aggregate cannot exceed `BUILD_ONLY_PROVEN` without named board evidence.

## Deferred at HX4 and sealed by HX4.5

- unknown event and operation identities;
- event queue full;
- oversized event and effect frames;
- expired deadline and completion after timeout;
- completion after quiescence;
- Wasm trap during event handling; and
- extension fault during operation.

GPIO, network, BLE, storage, RAX, firmware OTA, and all HX5+ work remain out of
scope.
