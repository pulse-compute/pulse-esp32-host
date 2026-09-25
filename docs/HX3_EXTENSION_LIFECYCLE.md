# HX3 extension lifecycle and task ownership

## Result

HX3 is `PASS` with aggregate `BUILD_ONLY_PROVEN` evidence. The host lifecycle
smoke executes all 12 required cases, including reverse unwind, duplicate and
out-of-order rejection, three simulated reset boundaries, and 32 clean repeated
cycles with zero retained host-structure bytes. The exact ESP32-S3/Xtensa and
ESP32-C6/RISC-V synthetic ELFs and extension-enabled firmware are
byte-reproducible across two isolated builds per target.

This is not target runtime evidence. No board loaded an extension or ran its
FreeRTOS task. Task scheduling, deletion-callback execution, stack high-water,
target heap deltas, loader unload, watchdog/reset behavior, and retained
diagnostics remain `HARDWARE_NOT_RUN`.

The accepted run and report hashes are recorded in the durable
[native-extension host evidence index](../evidence/host-extension/INDEX.md#native-extension-host-evidence-index).

## Host-owned lifecycle

`firmware/components/wdc_extension/wdc_extension_lifecycle.c` owns this ordered
state machine:

```text
REGISTRY_SEALED
  -> INITIALIZING -> INITIALIZED
  -> STARTING -> STARTED
  -> QUIESCING -> QUIESCED
  -> DEINITIALIZED -> unloaded
```

`RESET_REQUIRED` is a latched terminal branch for the current boot. It is set
after an unhealthy started candidate, a quiescence timeout, uncertain task
termination, a post-start health or service fault, or failed teardown. Reset is
the authoritative hard teardown after `start` was entered.

The host enforces these rules:

- inspection and descriptor admission remain lifecycle-call-free;
- `init` runs in registry order and partial initialization unwinds in reverse;
- `start` marks task creation as possible before entering extension code;
- a failed `start` receives one bounded reverse-order quiescence attempt;
- a host-owned absolute deadline is never extended by the extension;
- an expired quiescence deadline latches reset without calling the extension;
- `invoke` is valid only in `STARTED` and checks catalog, correlation, deadline,
  pointer/length agreement, and payload bounds;
- normal quiescence and deinitialization run in reverse order;
- duplicate or out-of-order calls have no extension-side effect; and
- only never-started or positively quiesced candidates may be deinitialized and
  cleanly unloaded.

The host never imports or calls `vTaskDelete` from lifecycle code. It does not
know the extension task handle.

## Extension-owned task and queue

`native-extensions/synthetic-loopback` creates resources only during `start`:

| Resource | Declared bound |
|---|---:|
| Static task count | 1 |
| Task stack | 4,096 bytes |
| Static state and RTOS control backing | 3,072 bytes |
| Static task-control array | 2,048 bytes |
| Static queue-control array | 256 bytes |
| Queue | 4 items x 64 bytes |
| Queue storage | 256 bytes |
| Total declared writable backing | 7,424 bytes |

The larger task-control array is intentional: the pinned ESP-IDF
`StaticTask_t` does not fit in 256 bytes. Target compilation asserts that both
the task and queue control types fit their arrays and that ESP-IDF expresses
the stack depth in bytes.

The task stops accepting work when quiescence starts, drains its bounded queue,
publishes `QUIESCED`, and self-deletes. A registered FreeRTOS thread-local
deletion callback sets the completion flag only when the kernel reaps the
static TCB. `quiesce` waits for that confirmation before deleting the static
queue or permitting `deinit` to zero its backing. Missing confirmation by the
absolute deadline returns timeout and requires reset; a pre-deletion flag is
not accepted as proof that the task stopped.

No dynamic allocator, GPIO, network, BLE, storage, RAX, or firmware-OTA symbol
is imported.

## Direct target-refinement imports

The synthetic ELF imports exactly these 11 symbols on both targets:

```text
pulse_host_monotonic_ms_v1
pulse_host_report_health_v1
uxTaskGetStackHighWaterMark
vQueueDelete
vTaskDelay
vTaskDelete
vTaskSetThreadLocalStoragePointerAndDelCallback
xQueueGenericCreateStatic
xQueueGenericSend
xQueueReceive
xTaskCreateStatic
```

At the HX3 snapshot, only the two listed `pulse_host_*` names were stable live
Pulse service imports. The nine
FreeRTOS names are enumerated target-refinement dependencies. The host resolves
them through the inspector-derived exact table; ambient ESP-IDF, libc, weak,
and wildcard resolution remain disabled.

Host services identify the calling candidate from the immediate return address
inside its admitted executable range and require service records to reside in
that candidate's writable range. Monotonic time and health reporting were live
in HX3. HX4 subsequently adds the two admitted event/completion imports and
connects them to the existing Pulse/Wasm path. Logging remains closed.

## Synthetic ELF evidence

| Target | Machine | ELF SHA-256 | ELF bytes | Allocated writable | Declared backing |
|---|---|---|---:|---:|---:|
| ESP32-S3 | `EM_XTENSA` | `ece0f61666212062f7d979d6ca06e48244c8ed111e909ad585203ed7f6ed665c` | 9,080 | 7,092 | 7,424 |
| ESP32-C6 | `EM_RISCV` | `01db1b76dfb626fae83fe416fb39081d77fb1edac061e3bba5d9ad068b0fe958` | 7,848 | 7,128 | 7,424 |

Both artifacts have an empty constructor surface, only loader-supported
relocations, exact metadata/descriptor agreement, and identical direct import
inventories. Each target build is repeated in a separate output directory and
compared byte for byte.

## Executed host cases

The native host smoke covers:

- happy lifecycle;
- `init` failure with reverse unwind;
- `start` failure before task creation;
- `start` failure after partial task state;
- unhealthy probation and simulated reset;
- duplicate `start`;
- invoke before `start` and after quiescence;
- extension-reported quiescence timeout and simulated reset;
- expired host deadline and simulated reset;
- duplicate `deinit`; and
- 32 complete lifecycle cycles with zero retained host-structure bytes.

The smoke uses mock descriptors on the development host. It proves control
ordering and fail-closed policy, not target task, loader, heap, or hardware
behavior.

## Firmware cost and residual risk

The values compare the complete loader + HX3 host with the fresh IF7-derived
baseline used by the qualification tool.

| Target | Firmware binary delta | Internal RAM delta | Remaining internal RAM |
|---|---:|---:|---:|
| ESP32-S3 | +9,600 bytes | +200 bytes | 2,637 bytes |
| ESP32-C6 | +9,984 bytes | +200 bytes | 114,554 bytes |

Against HX2 alone, HX3 adds 1,968 bytes to the S3 firmware binary, 2,160 bytes
to C6, and 16 bytes of internal RAM on each target. S3 still has only one byte
of dedicated IRAM remaining; this pre-existing limit is the dominant build
risk.

HX3 pass score is **8.6/10**, capped by build-only evidence. The risk factor is
**high**: the source and dual-ISA builds close the lifecycle contract, but no
hardware run has yet demonstrated task cleanup, heap recovery, reset
diagnostics, or loader unload, and S3 memory headroom remains critical.

## HX4 handoff

HX4 subsequently enabled only the synthetic event/effect round trip. It reuses
`wdc_events`, `wdc_runtime`, the existing Wasm handler, host-owned correlation,
and the sealed numeric catalog. It does not add GPIO, network, BLE, storage,
RAX, firmware OTA, an alternate event system, or direct task-to-Wasm calls.

See [HX4 event/effect round trip](HX4_EXTENSION_EVENT_EFFECT.md).
