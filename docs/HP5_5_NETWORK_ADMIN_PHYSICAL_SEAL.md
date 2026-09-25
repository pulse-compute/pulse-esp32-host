# HP5.5 network and administration physical seal

HP5.5 implements the blocking dual-board audit for the HP5 host network
mediator. The source result is `READY_FOR_PHYSICAL_EXECUTION`; the physical
aggregate remains `HARDWARE_PENDING` until both exact named-board runs pass.
Only the dual evaluator may emit
`DUAL_NAMED_BOARD_HP5_NETWORK_ADMIN_OBSERVED`.

No ESP-IDF target build or board execution is claimed by the source snapshot.
This document is the operator runbook for creating that evidence.

## Frozen authority

The execution starts from the exact HP5 source archive:

- `pulse-esp32-host-hp5-source-v1.zip`;
- SHA-256
  `e7df20f0909afbf2b3b8e4bea9b2b5a4ac40682471ea31c60b3ce344405ed347`;
- 1,181,638 archive bytes;
- 489 manifested files and 3,880,933 manifested payload bytes; and
- fixed ZIP timestamp `1980-01-01T00:00:00`.

HP5.5 permits one narrow firmware correction: HP4.2 update initialization now
accepts either the exact S3/PSRAM profile plus S3 fingerprint or the exact
C6/no-PSRAM profile plus C6 fingerprint. Crossed pairs still fail closed. The
HP5.5 execution firmware is sealed at
`d60e2669cd3b2dd5869e2305c92e39913b270ba9d54844d3a34d614681c5a98a`
across 168 files. HP2 plans, locks, and running fingerprints remain historical
authorities and are not relabelled.

The new HP5.5 target identities are:

| Lane | Plan | Canonical lock | Running fingerprint |
|---|---|---|---|
| AITRIP ESP32-S3-DevKitC-1 N8R2 | `6dfbe6ce23d4f3fdedefbc1c63dfac5d4f770418ba75c0bdc920ace2b244a50a` | `88fdf8cf491215342717c0546984660a04211b88b2ff540fdf5e91bb297c8533` | `ba7ec4000735f4bb1cb64d05c512a8f455d11d9ae50bbe15c46f018209c9b066` |
| Seeed Studio XIAO ESP32C6, 4 MB/no PSRAM | `f20a4ad3f38382ca531cfe5e7c579acba2894eef8523388c156605dcb6c17772` | `9114579dc7e213dcec95effaaa1fb400961d93e6a2c9fb204cb3bc40112b2053` | `6fe1b5728634e2eed8564e8cc9fb0d0d32f72c7fe8c04240035f71dacbd504ee` |

Both builds must use ESP-IDF `v5.4.4` at source commit
`296b6eab9445fd720e71aecab961e2d3fbca9944` and the checked-in dependency
lock for that target.

## What the run proves

Each lane must complete all 29 frozen checkpoints, including:

- exact physical chip, flash, PSRAM, target lock, and running fingerprint;
- station association and a forced, bounded station disconnect/reconnect;
- independent TLS application port 443 and administration port 8443;
- real common-Wasm HTTP response, empty response, first-response-wins,
  wrong-ID, oversize, trap, timeout, cancellation, client loss, and pressure;
- replaceable-proof administration, preaccept authentication/deadline/order
  negatives, replay rejection, capacity isolation under application pressure,
  retained terminal, and forced TCP-reset response loss;
- abort, inactive-slot stage/verify, durable version-9 trial and confirmation,
  unconfirmed version-10 reset/fallback, administrative recovery, authorization
  backoff/recovery, and physical no-viable recovery initialization; and
- target-specific internal/PSRAM floors with no factory-host, bootloader,
  partition-table, or host-firmware update.

Version 8 baseline and version 9 do not self-confirm from fabricated flags.
Each remains a real running trial for the fixed 30-second probation; confirmation
requires a successful WAMR health call, live Wi-Fi and both listeners, an
accepted administration STATUS, and the target-specific heap floors before the
HP3 journal commit. While a trial is pending, STATUS is the only accepted
campaign command; after confirmation the same command completes through the
normal HP4.3 engine. Version 10 is deliberately reset without confirmation.

The development bundle signature, self-signed test certificate, and
replaceable proof are campaign fixtures. They do not establish production
cryptography, identity, credential issuance, key lifecycle, secure boot, flash
encryption, or remote attestation.

## Secret and restoration boundary

Create the provision outside the source tree and outside any publishable
evidence directory. The helper requires an 8–31 byte test SSID and an 8–63
byte test password, generates a 14-day self-signed certificate/private key,
random 32-byte administrator proof, and certificate-derived channel binding,
keeps the directory at mode `0700`, and writes every file with mode `0600`.

```sh
export HP5_5_WIFI_SSID='<test-network-ssid>'
export HP5_5_WIFI_PASSWORD='<test-network-password>'
export HP5_5_PROVISION_DIR=/private/pulse-hp55-provision
make hp5_5-provision
unset HP5_5_WIFI_SSID HP5_5_WIFI_PASSWORD
```

The provision directory, staged project, raw full-flash backups, and any
credential-bearing terminal history are nonpublishable. Before erasing either
board, make a complete local flash backup and record a tested restore command.
The backup must be exactly 8,388,608 bytes for S3 or 4,194,304 bytes for C6.
Do not continue if a backup, board marking, attended operator, fresh full-flash
erase, or restore path is missing.

## Source readiness gate

Run the host-native gate before touching hardware. Supplying the sealed HP5
archive makes the qualifier re-verify every manifested payload as well.

```sh
make check-hp5-5

export HP5_SOURCE_ARCHIVE=/sealed/pulse-esp32-host-hp5-source-v1.zip
export HP5_5_OUT_DIR=/evidence/hp55-readiness-<fresh-id>
make hp5_5-readiness-qualify
```

The expected result is `READY_FOR_PHYSICAL_EXECUTION` with aggregate
`HARDWARE_PENDING`. It is not a substitute for either board run.

## AITRIP S3 lane

Use one freshly created run directory and the exact physical AITRIP
ESP32-S3-DevKitC-1 N8R2. Point the build variables at the pinned ESP-IDF tree.

```sh
export HP5_5_S3_RUN_DIR=/evidence/hp55-s3-<fresh-id>
export HP5_5_IDF_PATH=/opt/esp/idf-v5.4.4
make hp5_5-s3-aitrip-build
```

Follow the `commands` object in `build-report.json` in this order:

1. Read the complete 8 MiB flash into
   `$HP5_5_S3_RUN_DIR/full-flash-backup.bin`.
2. Record the module/board marking and a concrete restore command.
3. Erase the full flash.
4. Flash the built image and retain the uninterrupted monitor output as
   `$HP5_5_S3_RUN_DIR/serial.log` across every expected reboot.
5. From a second terminal, run the client after the board obtains its address:

```sh
export HP5_5_S3_DEVICE_HOST='<board-ip>'
make hp5_5-s3-aitrip-client
```

The client creates `network-transcript.jsonl`. Keep monitoring through the
final marker, then evaluate:

```sh
export HP5_5_S3_MARKING='AITRIP ESP32-S3-DevKitC-1 N8R2 <unit-marking>'
export HP5_5_S3_RESTORE_COMMAND='esptool.py --chip esp32s3 -p <port> write_flash 0 full-flash-backup.bin'
make hp5_5-s3-aitrip-evaluate
```

The evaluator re-hashes the build, target inputs, firmware artifacts, serial
log, transcript, backup, and provision binding; scans retained evidence for all
six raw secret values; enforces resource/counter floors; and writes
`board-report.json` only on exact PASS.

## XIAO C6 lane

Use a distinct physical Seeed Studio XIAO ESP32C6 with 4 MB flash and no PSRAM
and a distinct fresh run directory.

```sh
export HP5_5_C6_RUN_DIR=/evidence/hp55-c6-<fresh-id>
make hp5_5-c6-xiao-build
```

Repeat the same attended sequence using the 4 MiB backup command in the C6
build report, then run:

```sh
export HP5_5_C6_DEVICE_HOST='<board-ip>'
make hp5_5-c6-xiao-client

export HP5_5_C6_MARKING='Seeed Studio XIAO ESP32C6 4MB <unit-marking>'
export HP5_5_C6_RESTORE_COMMAND='esptool.py --chip esp32c6 -p <port> write_flash 0 full-flash-backup.bin'
make hp5_5-c6-xiao-evaluate
```

Restore each board from its private backup after retained evidence has been
hashed, or preserve the board and backup under the operator's controlled
recovery procedure.

## Dual-board promotion

Only after both `board-report.json` files pass:

```sh
export HP5_5_HARDWARE_OUT_DIR=/evidence/hp55-dual-<fresh-id>
make hp5_5-hardware-evaluate
```

The aggregate evaluator reopens the fixed campaign and source model, validates
both run directories and every retained evidence hash, requires two distinct
physical UID hashes and two distinct operator markings, and preserves the 29
ordered observations per board. It emits `dual-board-evaluation.json`, copies
the two secret-free board reports, and writes `evidence-manifest.json`.

A single, missing, synthetic, reordered, secret-bearing, crossed-target,
same-UID, or otherwise unbound lane cannot emit the promotion token and remains
`HARDWARE_PENDING`. HP6 is blocked until the resulting dual evidence is
reviewed and accepted.

## Publication boundary

The dual output directory is designed for publication after normal operator
review. Publish the dual evaluation, its evidence manifest, and the two copied
board reports. Do not publish either raw flash backup, provision directory,
staged project, private key, administrator proof, Wi-Fi credential, or local
credential-bearing shell history. Retain the original build reports, serial
logs, and transcripts under the evidence policy needed to independently replay
their hashes.
