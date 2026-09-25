# HP3.5 application-slot adversarial and power-loss seal

## Result

HP3.5 closes the exhaustive host-simulation portion of the HP3 interruption
boundary as `HOST_SLOT_ADVERSARIAL_POWER_LOSS_SEALED`. A deterministic,
one-shot flash fault model can stop inactive-slot erase/write and either
metadata record's erase, body write, or commit-marker write at an exact byte
prefix. A simulated power cycle clears only the volatile injection plan; all
flash bytes remain.

The separately frozen safe physical subset has also passed on both named
boards. Each lane produced 13 ordered passing checkpoints, and the fail-closed
dual evaluator closed as `DUAL_NAMED_BOARD_SAFE_SUBSET_OBSERVED`. The exact
accepted report, serial, campaign, source, and dual-evaluation identities are
in the [HP3.5 hardware evidence index](../evidence/hardware/HP3_5_INDEX.md).

The frozen addendum is
[`PULSE-ESP32-008a-application-slot-adversarial-seal.json`](../specs/PULSE-ESP32-008a-application-slot-adversarial-seal.json).
It preserves the HP3 artifact, slot, state, confirmation, HP2 fingerprint, and
HP1 admission authorities without adding a capability.

## Strong invariant

No injected failure may destroy the last confirmed application or create
ambiguous boot authority. An incomplete journal marker leaves the previous
complete generation authoritative. If all marker bytes reached flash, the new
generation may win even when the caller observed an I/O interruption. If no
valid generation exists, selection fails closed into recovery.

Application-slot commit wrappers now reload the durable journal winner after
an interrupted write, so their RAM view cannot run ahead of flash. Switching
away from an invalid confirmed slot is also one metadata commit: rejection and
transfer to the already-validated confirmed alternate can no longer be split
by a reset.

## Exact host matrix

The sealed relay-controller artifact is 2,361 bytes. The journal record is 256
bytes: 252 body bytes followed by a four-byte marker.

| Coverage | Cases |
|---|---:|
| Every inactive payload prefix, 0 through 2,361 bytes | 2,362 |
| Safe structural inactive-slot erase boundaries | 6 |
| Eight state transitions × two records × every erase/body/marker prefix | 8,240 |
| Confirmation reset matrix across both records and every journal prefix | 1,030 |
| One-record and two-record corruption outcomes | 3 |
| Semantic and transactional adversarial cases | 16 |
| **Total** | **11,657** |

The semantic set includes invalid header integrity, inner hashes and
signatures; a stored-artifact hash mismatch; incompatible running-host
fingerprints; stale candidates; readiness timeout; repeated traps; application
and host watchdog attribution; torn staging, trial, boot-attribution and
runtime-fault commits; and atomic confirmed fallback. Repeated guest traps run
32 complete reject/restage cycles while retaining the original confirmed
slot.

The slot coordinator never enters application code during the smoke. The
normal managed runtime edge remains governed by HP3's static and live
prelaunch checks.

## Named-board safe subset

The exhaustive matrix is deliberately host-only. The physical subset is
frozen in
[`campaign.json`](../tests/hardware-in-loop/hp3_5-slot-power-loss/campaign.json)
for the exact AITRIP ESP32-S3 N8R2 and Seeed XIAO ESP32-C6 4 MiB boards. It has
thirteen checkpoints per board and may touch only the inactive application
slot or non-authoritative journal record. A full-flash backup, attended run,
exact board/partition identities, and a restore path are mandatory.

The dual evaluator rejects synthetic origin, missing or reordered checkpoints,
serial-log hash mismatch, reused board identity, and any report that expands
scope. Promotion to `DUAL_NAMED_BOARD_SAFE_SUBSET_OBSERVED` requires both
physical reports.

The repository includes the sealed physical runner and per-board report
producer. Each build embeds the frozen campaign hash and relay-controller
bundle, uses the canonical HP3 partition table, checks the physical chip/flash
identity, persists its phase in NVS, and emits exact serial checkpoints. The
two watchdog cases use real task-watchdog resets; safe payload and journal
boundaries use controlled software resets. The runner never launches
application code.

No passing physical report is embedded in source. The external AITRIP S3 and
XIAO C6 reports both passed with origin `PHYSICAL_NAMED_BOARD`; their serial
hashes match and the dual evaluator accepted exactly two distinct board
identities. Source retains only the immutable closure index. The physical
claim remains the safe subset: it is not exhaustive target interruption or a
claim of uncontrolled power cutting.

## Operations

Run the contract and exhaustive host qualifier:

```bash
make check-hp3-5
HP3_5_OUT_DIR=reports/app-slots/hp3_5-local \
  make app-slots-adversarial-qualify
```

After two real board campaigns, evaluate them together:

```bash
python3 tools/evaluate_hp3_5_slot_hardware.py \
  --s3-run /path/to/s3-run \
  --c6-run /path/to/c6-run \
  --out-dir /path/to/dual-evaluation
```

The complete backup, fresh-erase, build, monitor, per-board evaluation, restore,
and dual-board procedure is in the campaign
[`README.md`](../tests/hardware-in-loop/hp3_5-slot-power-loss/README.md). A lane
must first run `tools/evaluate_hp3_5_slot_board.py`; the dual evaluator consumes
the resulting immediate `board-report.json`, not the unrelated
`build-report.json`.

## Claim boundary and next pass

HP3.5 adds no RAX, host-firmware OTA, protected remote administration, MQTT or
other transport, provider integration, peripheral authority, or Pulse-core
change. HP4.0 now freezes the protected local administration and exclusive
update/recovery contract without adding firmware; HP4.1 implements the bounded
host-native administration core, and HP4.2 owns the first exclusive update
transaction. Network transport and provider work remain stopped.
