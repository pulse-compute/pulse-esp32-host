# HX4.5 extension event/effect adversarial seal

## Result and phase boundary

HX4.5 seals the deferred host event/effect negative corpus without widening the
native-extension architecture. The phase is `ADVERSARIAL_HOST_SEALED`: all 11
required cases execute through the existing queue, runtime, ABI, sealed
registry, lifecycle, and completion machinery. The exact HX4 common Wasm bytes
remain unchanged and target-neutral.

This is still not target-runtime evidence. S3/C6 native ELFs and firmware are
build-qualified only, and both targets remain `HARDWARE_NOT_RUN`. The next
action is the prepared [AITRIP ESP32-S3 N8R2 hardware qualification](HX4_5_S3_AITRIP_HARDWARE.md).
HX5 and physical
peripheral work must not begin before that stop and review.

The accepted sandbox run and report hashes are recorded in the durable
[native-extension host evidence index](../evidence/host-extension/INDEX.md#native-extension-host-evidence-index).
Artifact hashes remain in the separately packaged machine-readable evidence
tree rather than being copied back into this source document.

## Closed adversarial corpus

| Case | Required fail-closed result | Preserved state |
|---|---|---|
| Unknown event identity | `WDC_ERR_UNSUPPORTED_OPCODE` | Wasm handler is not entered; the forged event is consumed once. |
| Unknown operation identity | `WDC_ERR_UNSUPPORTED_OPCODE` | No candidate invoke or completion slot is opened. |
| Event queue full | `PULSE_EXT_ERR_BUSY` | Capacity stays 16, drop-newest is counted, and queued events are retained. |
| Oversized event frame | `PULSE_EXT_ERR_BOUNDS` | No event is queued. |
| Oversized effect frame | `WDC_ERR_BAD_LENGTH` | No candidate invoke occurs. |
| Expired deadline | `WDC_ERR_TIMEOUT` | The completion slot is released and the candidate remains started. |
| Completion after timeout | `PULSE_EXT_ERR_STALE` | Timed-out ownership cannot be resurrected. |
| Duplicate completion | `PULSE_EXT_ERR_DUPLICATE` | The first accepted terminal result remains authoritative. |
| Completion after quiescence | `PULSE_EXT_ERR_STALE` | Registry quiescence cancels the active slot without requiring reset. |
| Wasm trap during event handling | `WDC_ERR_CONTRACT_VIOLATION` | Runtime outcome is `GUEST_TRAPPED`; no extension operation is invoked. |
| Extension fault during operation | `WDC_ERR_IO` | Candidate and registry latch `RESET_REQUIRED`. |

The native corpus uses a started mock descriptor because an Xtensa or RISC-V
ELF cannot execute on the development host. It still calls the production
event service, global `wdc_events` queue, bridge, runtime dispatcher, host-call
dispatcher, operation resolver, completion service, registry quiescence, and
reset-required latch. It introduces no alternate queue or Wasm dispatcher.

## State-machine hardening

HX4.5 separates three completion-slot outcomes that HX4 had represented with
one pending-style status:

- `NOT_READY` means the matching effect is still active;
- `TIMEOUT` means the deadline terminally expired; and
- `STATE` means the effect was canceled, including lifecycle quiescence.

The bridge now releases the slot on every host-side timeout path. A canceled
effect returns immediately instead of waiting until its old deadline. A
deadline that expires between effect admission and candidate invoke is
classified as timeout rather than bad encoding.

Extension fault remains intentionally stronger than a normal operation error.
`PULSE_EXT_ERR_FAULT` from `invoke` latches the candidate and registry into the
existing HX3 reset-required path before the bridge reports host I/O failure.

## Real WebAssembly evidence

The exact 306-byte HX4 common Wasm module executes in Node for each relevant
host rejection. It returns unknown-operation, oversize, timeout,
extension-I/O, and canceled-state codes unchanged, proving that the handler
does not substitute success, select a target, or silently retry.

A separate existing deterministic Wasm fixture executes `unreachable` inside
`wdc_module_on_event`; the real engine raises `WebAssembly.RuntimeError`. The
host runtime corpus independently maps the corresponding event trap to
`WDC_RUNTIME_OUTCOME_GUEST_TRAPPED`.

## Qualification commands

```bash
make check-hx0 check-hx1 check-hx2 check-hx3 check-hx4 check-hx4-5
HX_OUT_DIR=reports/host-extension/hx45-<fresh-id> \
  make host-extension-adversarial-qualify
```

The qualifier reruns the inherited HX3 lifecycle proof and HX4 happy path,
executes the full HX4.5 native and real-Wasm adversarial corpus, builds both
synthetic target ELFs twice, verifies identical common Wasm realizations, and
builds extension-enabled S3/C6 firmware twice from isolated copies.

The aggregate cannot exceed `BUILD_ONLY_PROVEN` without named-board evidence.
Host queue depth and status observations are not FreeRTOS scheduling, target
WAMR, heap/PSRAM, stack high-water, loader lifecycle, or serial evidence.

The sealed S3 link retains 2,157 bytes of internal-RAM headroom and the
inherited one-byte dedicated-IRAM margin. C6 retains 114,098 bytes of internal
RAM and has no separately reported dedicated-IRAM region. These are static
link observations; the extension's declared 7,424 bytes of runtime task,
static, and queue backing still require the named-board measurement.

## Hard stop

HX4.5 completes the sandbox implementation phase. The next step is not HX5.
It is the named S3 board run covering boot, load/admission, lifecycle, the
sealed event/effect path, quiescence, reset behavior, memory/stack/queue
measurements, and retained serial evidence. C6 hardware and all peripheral
vertical slices remain later work.

The isolated AITRIP N8R2 app, exact-input builder, and retained-evidence
evaluator are implemented. They remain preparation, not target evidence, until
the exact lane builds the image and the named board produces a passing retained
report.
