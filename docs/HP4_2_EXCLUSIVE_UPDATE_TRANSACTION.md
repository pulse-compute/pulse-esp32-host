# HP4.2 exclusive update transaction

## Result

HP4.2 implements the C6-minimum, host-private transaction that stages one
complete Pulse application artifact into the inactive HP3 slot and, only after
all checks pass, commits that candidate as durable `TRIAL`. Its aggregate is
`HOST_EXCLUSIVE_UPDATE_TRANSACTION_IMPLEMENTED` with classification
`HOST_NATIVE_UPDATE_TRANSACTION_ONLY`.

The implementation extends the `wdc_admin` firmware component with
`wdc_admin_update`. It is linked before the application pthread is created and
has no guest ABI, application event/effect, native-refinement, or network entry.
The machine-readable authority is
[`PULSE-ESP32-011-exclusive-update-transaction.json`](../specs/PULSE-ESP32-011-exclusive-update-transaction.json).

This is a native-host transaction qualification. It does not build or flash an
ESP32 target, install a UART or USB driver, supply a production authenticator or
cryptographic verifier, execute application code, create a physical result,
update host firmware, or implement HP4.3 recovery.

## Source continuity

HP4.2 begins from the deterministic HP4.1 archive:

```text
archive SHA-256: 7d36f89fab2ed62b30cdb14841dcb96ee736d7720ce2bcf692315f865afa82d5
manifested files: 455
manifested payload: 3,291,858 bytes
```

The HP4.1 firmware seal remains recorded as 146 files at
`4f7b56a99adfedfa57c1d5179ad5ca03e6f57dd258a73fa3a6f71f747973253c`.
HP4.2 intentionally advances the firmware tree to 148 files at
`77f4d2044776c6828e443486ee21199f95b4e1f34ae704c7323e901d51602eca`.
The native SDK remains unchanged at
`a7ceb397ab009950a1ebbdea60280f7944020a6523252b7de0d781e3e798bdd4`.

The HP3.5 physical campaign, accepted board reports, serial logs, dual
evaluation, and their hashes remain historical evidence. Exact successor
validation replays their source history; it does not relabel those runs as
HP4.2 execution.

## Command and state boundary

HP4.2 enables exactly:

- `STATUS`;
- `BEGIN_UPDATE`;
- `WRITE_CHUNK`;
- `FINISH_UPDATE`;
- `ABORT`; and
- `ACTIVATE_TRIAL`.

`ENTER_RECOVERY` and `REBOOT` remain unsupported for HP4.3. Every update
request repeats the target inactive slot, expected total artifact bytes, and
complete-artifact SHA-256. The core validates that shape before accepting the
command, while retaining HP4.1's atomic replay and HP1 command ownership.

The transaction permits only these transitions:

1. `NORMAL -> QUIESCE` after an accepted `BEGIN_UPDATE`;
2. `QUIESCE -> UPDATE` after positive unload evidence, resource admission, and
   inactive-slot stage begin;
3. `QUIESCE -> NORMAL` on failure;
4. `UPDATE -> NORMAL` on abort or failure before durable `TRIAL`; and
5. `UPDATE -> REBOOT_HANDOFF` after the durable `TRIAL` record is read back.

There is no direct `NORMAL -> UPDATE` transition and no recovery-origin update
in this pass.

## Exclusive quiescence and HP1 admission

The update engine requires a host-private lifecycle callback to quiesce and
unload both the Wasm guest and loaded native refinements. It accepts the result
only when the positive evidence reports all four operations complete, reports
neither class still loaded, retains zero flags/reserved fields, and completes
strictly before the ten-second quiescence deadline.

Only then may it take a post-unload heap snapshot and call
`wdc_control_admit_exclusive_update`. The fixed C6-minimum gate is:

| Bound | Bytes |
|---|---:|
| HP1 fixed internal control reserve | 98,304 |
| Exclusive update working set | 65,536 |
| Required internal free space | 163,840 |
| Update's largest allocation | 65,536 |
| HP1 largest-block floor | 32,768 |
| Required largest internal block | 98,304 |

The engine accepts an exactly 65,536-byte caller-provided working buffer and
does not allocate dynamically. Application requests cannot select sizes,
priorities, or an HP1 source.

## Inactive-slot streaming

Staging uses the existing HP3 APIs and can target only
`wdc_app_slots_inactive_slot`. The active and last-good slots must identify the
same confirmed authority before a transaction begins.

Streaming is sequential and bounded:

| Limit | Value |
|---|---:|
| Maximum chunk | 1,024 bytes |
| Maximum chunks per window | 64 |
| Maximum bytes per window | 65,536 |
| Rate window | 1,000 ms |
| Stream-idle deadline | 30,000 ms |
| Whole-transaction deadline | 900,000 ms |

An oversized chunk rejects before replay ownership. A mismatched slot, total,
or artifact hash; nonsequential or excess data; a rate violation; or either
deadline aborts the transaction and returns the host mode to `NORMAL`.

## Verification and durable activation

`FINISH_UPDATE` delegates complete stored-artifact verification to HP3. The
candidate must pass the fixed artifact header and stored-artifact hash, inner
bundle hash and bundle policy, HP2 running-host compatibility, security-version
floor, and artifact authority. No application code is launched.

The expected complete-artifact SHA-256 must also match the stored result. The
HP4.1 replaceable `WdcAdminArtifactVerifyFn` then makes its independent
complete-artifact, compatibility, security-floor, and authority decision. This
callback remains a seam and is not a production-cryptography claim.

`ACTIVATE_TRIAL` rechecks current session authorization and invokes the
replaceable verifier again. It then uses only `wdc_app_slots_mark_trial` and the
existing two-record HP3 journal. The engine reads durable metadata back and
enters `REBOOT_HANDOFF` only when it observes:

- the candidate slot as both active and `TRIAL`;
- the original last-good slot unchanged and still exactly confirmed; and
- the candidate artifact size and SHA-256 matching the transaction.

A successful transaction reports three metadata commits: the two HP3
verification commits and the final `TRIAL` commit. The existing HP3 boot
selector remains the only next-boot authority.

## Failure authority

Before a durable `TRIAL` commit, failure or explicit abort preserves the active
slot, last-good slot, and exact last-confirmed record. Staging is aborted when
active, the accepted command receives its one terminal result, and the host
returns to `NORMAL`.

The transaction never writes the active application slot, factory host
partition, bootloader, or partition table. A verified but inactive candidate
may remain after post-verification abort; it has no boot authority. HP4.3 owns
recovery-mode staging, abort, and reboot behavior.

## Qualification

Run the contract gate:

```bash
make check-hp4-2
```

Create a fresh host-native evidence bundle:

```bash
HP4_2_OUT_DIR=reports/administration/hp4_2-<fresh-id> \
  make administration-update-qualify
```

The native smoke executes 15 cases covering the exact C6 admission gate,
positive quiesce/unload, active-slot denial, quiescence failure, both resource
denials, preaccept chunk bounds, explicit abort, stream timeout and rate limits,
complete-artifact hash mismatch, security rollback, replaceable-verifier
denial, interrupted `TRIAL` journaling, and durable trial/reboot handoff.

The observed update engine is 3,096 bytes and uses the external 65,536-byte
working buffer. The terminal qualification is
`HOST_EXCLUSIVE_UPDATE_TRANSACTION_IMPLEMENTED`; it is not an ESP32 target or
physical-board result.

## HP4.3 handoff

HP4.3 completed this handoff by adding host-only recovery entry,
recovery-origin staging and abort, fixed status, and read-only viable reboot
against the sealed HP4.2 transaction, HP3 durable authority, and HP1 resource
gate. Recovery remains host-private and does not widen transport, provider,
host-firmware OTA, partition-layout, RAX, network, or production-key scope. See
[HP4.3 host-only recovery](HP4_3_HOST_ONLY_RECOVERY.md).
