# HP3.5 named-board safe power-loss campaign

This directory freezes the physical subset of the HP3.5 slot campaign for the
AITRIP ESP32-S3 N8R2 and Seeed XIAO ESP32-C6 4 MiB boards. The exhaustive
11,657-case interruption matrix runs on the host; the physical subset repeats
only boundaries that leave the factory host and the confirmed application
untouched.

The campaign is operator-attended and intentionally does not ship a passing
board report. Before a run, capture a full-flash backup and verify the exact
board and canonical partition hashes in `campaign.json`. The campaign must
start after a full-chip erase: it provisions slot A as the baseline once, then
hashes and preserves those confirmed bytes for the rest of the run. Fault
operations may target only inactive slot B or the non-authoritative journal
record. They never write the factory host partition, GPIO, attached loads, a
network, or an external provider. NVS stores only the campaign phase so a
controlled reset or power interruption cannot silently restart provisioning.

The physical image uses production `wdc_app_slots`, `wdc_activation`, and
`wdc_ota` paths. The two watchdog checkpoints cause real ESP task-watchdog
resets; the other interruption boundaries use controlled software resets. No
application code is launched by this storage-and-authority campaign.

## Build and run one lane

Use a fresh run directory. An HX4.5/HX5b run is not interchangeable: its
factory-only partition table and serial markers cannot produce HP3.5 evidence.

```bash
export HP3_5_S3_RUN_DIR="$PWD/hardware/hp35-aitrip-001"
make hp3_5-s3-aitrip-build

export HP3_5_C6_RUN_DIR="$PWD/hardware/hp35-xiao-c6-001"
make hp3_5-c6-xiao-build
```

For each disconnected board, first record the visible module/board marking and
make a raw full-flash backup. The following S3 example assumes ESP-IDF's export
script has placed `esptool.py` on `PATH`:

```bash
export RUN_DIR="$HP3_5_S3_RUN_DIR"
export PORT=/dev/cu.usbmodem0001
esptool.py --chip esp32s3 --port "$PORT" \
  read_flash 0 0x800000 "$RUN_DIR/full-flash-before.bin"
python3 -c 'import pathlib,sys; assert pathlib.Path(sys.argv[1]).stat().st_size == 8388608' \
  "$RUN_DIR/full-flash-before.bin"

cd "$RUN_DIR/project"
idf.py -B "$RUN_DIR/build" --port "$PORT" erase-flash
idf.py -B "$RUN_DIR/build" --port "$PORT" flash monitor 2>&1 | \
  tee "$RUN_DIR/serial.log"
```

For the C6 lane, use `--chip esp32c6`, length `0x400000`, and require 4,194,304
backup bytes. Keep the monitor attached across the controlled resets. Exit it
only after `PULSE_HP35_FINAL` reports `PASS`. Any `PULSE_HP35_FATAL` marker
invalidates the run; restore the backup, diagnose, and use a new run directory.
On a fresh erase the runner emits `PULSE_HP35_ARMING` and waits ten seconds
before committing baseline state. This absorbs resets caused while a USB/JTAG
monitor attaches. Do not reset after the arming marker; if baseline is later
interrupted, the retained diagnostic marker names the exact substep.
If staging fails, `PULSE_HP35_STAGE_FAILURE` records whether the stored header,
bundle hash, inner bundle, host compatibility, security floor, and authority
checks passed, plus the number of durable metadata commits. Preserve that line
with the fatal marker when reporting a failure.
The per-board and dual evaluators require the correctly sized backup to remain
in the run directory. It may contain device secrets: retain it locally for
restore, do not include it in a published evidence archive.

Evaluate each completed lane. This is the step that creates the immediate
`board-report.json` expected by the dual evaluator:

```bash
HP3_5_S3_MARKING='ESP32-S3-WROOM-1-N8R2' \
  make hp3_5-s3-aitrip-evaluate
HP3_5_C6_MARKING='XIAO ESP32C6 / ESP32-C6FH4' \
  make hp3_5-c6-xiao-evaluate
```

To restore a board, erase it and write its raw backup at address zero with the
same `esptool.py --chip ... --port ... write_flash 0` toolchain. Do not attach
loads during the campaign or restore operation.

## Dual evaluation

Each lane produces a `board-report.json` plus its referenced `serial.log`.
Evaluate both directories together with:

```bash
python3 tools/evaluate_hp3_5_slot_hardware.py \
  --s3-run /path/to/s3-run \
  --c6-run /path/to/c6-run \
  --out-dir /path/to/dual-evaluation
```

Only reports whose origin is `PHYSICAL_NAMED_BOARD`, whose serial log hashes
match, and whose thirteen checkpoint IDs all pass can promote the result to
`DUAL_NAMED_BOARD_SAFE_SUBSET_OBSERVED`. Synthetic reports are rejected. The
accepted external AITRIP S3 and XIAO C6 reports now satisfy this gate; their
immutable identities are recorded in
[`evidence/hardware/hp3_5-index.json`](../../../evidence/hardware/hp3_5-index.json).
Fresh runs remain independent evidence and must pass the same evaluator.
