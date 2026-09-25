# HX5b extension pressure seal

## Reconciled terminal result

HP0 ingested the retained S3, C6, and final dual-qualifier directories and
verified their raw build, serial, evaluator, corpus, source-tree, and embedded
hash references. Both named boards report `PASS` and
`NAMED_BOARD_OBSERVED`; the final aggregate is
`DUAL_ISA_PRESSURE_OBSERVED` with hardware result
`DUAL_NAMED_BOARD_OBSERVED`.

The source-distributed identities are in the
[accepted hardware evidence index](../evidence/hardware/INDEX.md), while the
full evidence remains in a separate manifested artifact. See
[HP0 evidence reconciliation](HP0_EVIDENCE_RECONCILIATION.md) for the exact
authority and the superseded HX6/HX7 path.

HX5b closes the hardening phase with sustained bounded pressure and explicit
recovery. No new host capability, public ABI function, extension import,
peripheral, provider, RAX format, OTA path, or multi-extension scheduling
behavior is introduced.

## Host seal

The machine-readable authority is
[`PULSE-ESP32-005b-extension-pressure-seal.json`](../specs/PULSE-ESP32-005b-extension-pressure-seal.json).
The host campaign executes:

- 64 full 16-entry queue rounds, each with an exact drop-newest rejection and
  complete FIFO recovery;
- 128 timed-out/late completions followed by 128 accepted/duplicate
  completions and slot reuse;
- a 128-sample deterministic latency distribution;
- 64 native fault/reset-simulated cycles while a 256 KiB reservation remains
  live;
- 64 real WebAssembly `unreachable` traps, each followed by a successful run of
  the unchanged common Wasm while a 4 MiB reservation remains live; and
- zero tracked retained bytes after the explicit pressure reservation is
  released.

Run the narrow contract:

```bash
make check-hx5b
```

Create a fresh, source-bound host report:

```bash
HX_OUT_DIR=reports/host-extension/hx5b-<fresh-id> \
  make host-extension-pressure-qualify
```

This re-executes the complete 56-case HX5a baseline before the HX5b workloads.
Without physical reports it emits aggregate `HOST_PRESSURE_PROVEN` and
`hardware.execution_this_pass = NOT_RUN`. It creates no empty `serial.log` and
does not infer either board from prior runs.

## Opt-in named-board campaign

The existing HX4.5 image remains the default. HX5b is enabled only by the new
targets; they add `PULSE_HX5B_PRESSURE=1` to the isolated HIL project. In the
first measured cycle the board fills and drains the 16-entry host queue eight
times, executes 128 real native-extension/common-Wasm effect round trips,
rejects eight overflow attempts, and emits an ordered latency distribution.
The existing five measured load/unload cycles, WAMR trap, reset-required latch,
software reset, heap floors, stack measurements, and retained breadcrumb still
run unchanged. Each cycle now also records load, start, quiesce, and deinitialize
timings.

For the AITRIP ESP32-S3 N8R2:

```bash
RUN_DIR="$PWD/reports/hardware/hx5b-aitrip-<fresh-id>"
test ! -e "$RUN_DIR"
HX_AITRIP_OUT_DIR="$RUN_DIR" make hx5b-s3-aitrip-build
idf.py -B "$RUN_DIR/build" -p <PORT> flash monitor \
  2>&1 | tee "$RUN_DIR/serial.log"
# Exit monitor with Ctrl+]
HX_AITRIP_OUT_DIR="$RUN_DIR" make hx5b-s3-aitrip-evaluate
```

For the Seeed Studio XIAO ESP32C6:

```bash
RUN_DIR="$PWD/reports/hardware/hx5b-xiao-c6-<fresh-id>"
test ! -e "$RUN_DIR"
HX_XIAO_OUT_DIR="$RUN_DIR" make hx5b-c6-xiao-build
idf.py -B "$RUN_DIR/build" -p <PORT> flash monitor \
  2>&1 | tee "$RUN_DIR/serial.log"
# Exit monitor with Ctrl+]
HX_XIAO_OUT_DIR="$RUN_DIR" make hx5b-c6-xiao-evaluate
```

Both builders require the already pinned ESP-IDF 5.4.4 environment and sealed
native ELF fixtures. A build report remains `HARDWARE_NOT_RUN` until its serial
transcript passes the fail-closed evaluator.

After both evaluations pass, create a new final report rather than reusing the
host-only output directory:

```bash
HX_OUT_DIR=reports/host-extension/hx5b-dual-<fresh-id> \
HX5B_HARDWARE_ARGS='--s3-evaluation reports/hardware/hx5b-aitrip-<id>/evaluation/qualification-report.json --c6-evaluation reports/hardware/hx5b-xiao-c6-<id>/evaluation/qualification-report.json' \
  make host-extension-pressure-qualify
```

The qualifier accepts both named-board reports or neither. A partial pair,
missing raw artifact, fatal serial signature, failed pressure marker, timing
outside the bound, unexplained heap retention, or hash mismatch fails the gate.

## Claim boundary

Host execution proves deterministic host pressure and recovery. Only the two
physical evaluators can close `DUAL_ISA_PRESSURE_OBSERVED`. HX5b does not prove
electronic board-vendor identity, production peripherals, networking, BLE,
GPIO, I2C, storage, OTA, security provisioning, or a production workload.

HX6 and HX7 remain stopped and are superseded by the HP platform/recovery unit.
Provider composition, MQTT, GPIO breadth, RAX, and host-firmware OTA must not
begin by implication from this pressure seal.
