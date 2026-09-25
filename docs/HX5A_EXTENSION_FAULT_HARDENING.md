# HX5a extension fault-model hardening

HX5a hardens the native-extension host without expanding what the host can do.
It inventories the existing HX2 through HX4.5 fault behavior, adds a private
deterministic injection seam around lifecycle returns, repairs two concrete
error-path gaps, and emits one source-bound host qualification report.

No new host capability, public ABI function, extension import, peripheral,
provider, RAX format, OTA path, or multi-extension scheduling behavior is part
of this pass.

## Result

The host now has six explicit fault categories:

| Category | Required outcome | Reset policy |
|---|---|---|
| Admission rejection | Reject before relocation or lifecycle; execute zero lifecycle calls. | Not required. |
| Reversible pre-start lifecycle | Clean up in reverse order and retain no live task. | Not required when cleanup is proven. |
| Cooperative running lifecycle | Bound invoke, quiesce, deinitialize, and unload. | Not required when quiescence and cleanup are proven. |
| Uncertain native ownership | Preserve fault provenance and stop continued lifecycle use. | Required. |
| Runtime trap or extension fault | Contain the dispatch and preserve the exact failure class. | Wasm trap is contained; native ownership fault requires reset. |
| Bounded pressure or contract rejection | Reject identity, size, queue, deadline, or ownership violations without state corruption. | Not required unless native ownership becomes uncertain. |

The machine-readable authority is
[`PULSE-ESP32-005a-extension-fault-model.json`](../specs/PULSE-ESP32-005a-extension-fault-model.json).
It binds each category to inherited evidence and freezes the HX5b deferrals.

## Deterministic injection seam

`wdc_extension_internal.h` exposes nine one-shot return points only when
`PULSE_EXTENSION_HOST_TEST` is defined:

| Transition | Expected recovery |
|---|---|
| Service bind | Undo the successful bind and permit a clean retry. |
| Initialize | Reverse-deinitialize the partially initialized candidate and all earlier candidates. |
| Start | Reverse-quiesce every entered start, then reverse-deinitialize. |
| Health probation | Attempt bounded quiescence and preserve reset-required. |
| Invoke | Latch reset-required for the native fault. |
| Quiesce | Latch reset-required because task ownership is no longer proven. |
| Post-quiesce health | Reject the unproven quiesced state and require reset. |
| Deinitialize | Preserve the candidate and require reset. |
| ELF unload | Preserve the failed candidate and require reset, including after a partial reverse unload. |

The seam overrides a successful mock return after the boundary call. This is
intentional: the tests exercise partial side effects and the actual unwind
logic, not merely rejection before work begins. The seam has no symbols in a
production object and does not alter `native-sdk/c/include/pulse_extension.h`.

## Tightened production behavior

Two gaps were found during the inventory:

1. Initialization preflight returned `WDC_EXTENSION_ERR_BUDGET` for both an
   invalid candidate state and insufficient capacity. HX5a returns
   `WDC_EXTENSION_ERR_STATE` for state/shape failures and reserves
   `WDC_EXTENSION_ERR_BUDGET` for actual capacity failures.
2. A failed ELF unload returned `WDC_EXTENSION_ERR_LOADER` but did not latch
   reset-required. After a partial unload, native ownership is uncertain and
   reuse is unsafe. HX5a retains the failed candidate, records
   `WDC_EXTENSION_FAULT_UNLOAD`, latches registry and candidate reset state,
   and returns `WDC_EXTENSION_ERR_RESET_REQUIRED`.

The ABI version, descriptor layout, host imports, task/queue ownership, and
sealed S3/C6 extension ELF bytes are unchanged.

## Qualification

Run the narrow contract:

```bash
make check-hx5a
```

Create a fresh unified report with:

```bash
HX_OUT_DIR=reports/host-extension/hx5a-<fresh-id> \
  make host-extension-faults-qualify
```

The qualifier re-executes and binds:

- all 21 HX2 pre-lifecycle rejection cases;
- all 12 HX3 lifecycle cases;
- the HX4 bounded event/effect happy path and exact common Wasm execution;
- all 11 HX4.5 adversarial cases and the real Wasm trap; and
- 11 HX5a cases spanning all nine deterministic transition points plus the
  state-versus-budget classification checks.

The report schema remains `pulse.esp32.host-extension-report.v1`, with pass
`HX5a`, phase `FAULT_MODEL_HARDENED`, and aggregate
`HOST_HARDENING_PROVEN`. Every retained corpus is separately hashed.

## Hardware claim boundary

The preceding AITRIP ESP32-S3 N8R2 and Seeed Studio XIAO ESP32C6 gates reached
`NAMED_BOARD_OBSERVED` in their external physical runs. HX5a records those as
prior baselines with `external-not-ingested-by-hx5a`; it does not copy their
serial/build evidence into a host report and does not run either board.

Therefore an HX5a report says `hardware.execution_this_pass = NOT_RUN`. It
cannot upgrade, replace, or reconstruct named-board evidence.

## HX5b hard stop

HX5b remains deliberately separate and contains the pressure seal:

- sustained queue saturation and recovery;
- deadline and late-completion storms;
- repeated Wasm traps and native faults under memory pressure; and
- targeted reruns on both named S3 and C6 boards.

RAX blobs, provider composition, networking/peripheral expansion,
multi-extension scheduling, and HX6/HX7 work remain outside both HX5a and
HX5b.
