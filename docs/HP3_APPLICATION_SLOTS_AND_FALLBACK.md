# HP3 Pulse application slots and fallback

## Result

HP3 adds a host-owned application replacement authority with two
flash-resident Pulse application slots and at most one resident Wasm runtime.
An application is streamed only to the inactive slot, checked against the HP2
running-host fingerprint and HP1 resource authority, trialed under host
probation, and confirmed only from host-observed evidence. The last confirmed
application remains intact until its replacement is confirmed.

The host-synthetic qualifier closes as
`PULSE_APPLICATION_SLOT_AUTHORITY_PROVEN`. The machine-readable contract is
[`PULSE-ESP32-008-application-slots.json`](../specs/PULSE-ESP32-008-application-slots.json).

## Fixed artifact and slots

The application artifact is deliberately small and fixed. A 192-byte `PASP`
version-1 header carries total and inner-bundle lengths, application and
security versions, the HP2 application requirements, inner-bundle and
application-identity hashes, reserved zero bytes, and a header CRC. The payload
is the existing signed WDC bundle. This format is not RAX.

The canonical layouts retain a fixed factory host image and add encrypted
`wasm_a`, `wasm_b`, and `wasm_meta` data partitions:

| Target | Slot A | Slot B | Metadata |
|---|---:|---:|---:|
| ESP32-C6 4 MiB | 896 KiB | 896 KiB | 64 KiB |
| ESP32-S3 8 MiB | 2 MiB | 2 MiB | 64 KiB |

Host-firmware OTA is not part of this layout. HP3 replaces Pulse application
artifacts only.

## State and staging authority

The canonical states are `EMPTY`, `STAGED`, `VERIFIED`, `TRIAL`, `CONFIRMED`,
and `REJECTED`. `TRIAL_RUNNING` is a persisted internal boot-attribution
substate. Legacy R7 names remain source aliases but no longer define the
operator model.

Staging is sequential and bounded by the selected partition. The manager
refuses the active or last-confirmed slot. It hashes the stored artifact and
inner bundle from flash, verifies the existing bundle signature, cross-checks
the signed application identity and version, enforces the security-version
floor, and checks HP2 static compatibility. Production mode additionally
requires an installed artifact-authority callback. It never treats a CRC as a
signature.

Successful staging makes two journaled transitions: `STAGED`, then `VERIFIED`.
A failed verification records `REJECTED` without changing the confirmed slot.

## Journal and boot attribution

The existing R7 activation metadata is evolved rather than duplicated. Two
records carry a generation, sealed metadata, and a commit marker. Record bodies
are written before their markers; reads select the highest valid generation,
recover from one corrupt record, and fail closed on divergent equal
generations or two non-erased invalid records.

Before a trial application may launch, the host persists the active trial,
boot sequence, and boot-in-progress attribution. A subsequent attributed reset
rejects that trial and selects the last confirmed slot for a reboot. Attribution
distinguishes power-on, host software, guest trap, application watchdog, host
watchdog, and unknown reset causes.

HP3 establishes the journal and attribution algorithm. HP3.5 subsequently
closes the exhaustive host interruption matrix; see the
[application-slot adversarial seal](HP3_5_APPLICATION_SLOT_ADVERSARIAL_SEAL.md).
Its named-board safe physical subset subsequently passed on both retained
boards and closed as `DUAL_NAMED_BOARD_SAFE_SUBSET_OBSERVED`; that result is
external to the HP3 host-only qualification.

## Prelaunch and confirmation

Every selected artifact is reread and revalidated at boot. Application code
cannot be entered until the fixed header and bundle pass verification, HP2
fingerprint compatibility succeeds, and HP1 admits the live heap and
largest-block snapshot. The slot coordinator itself always reports
`application_code_launched=false`; the managed runtime bridge records the
actual transition immediately before `wdc_runtime_call_init`.

A trial cannot self-confirm. The host requires readiness, a successful health
check, responsive administration, preserved resource floors, and 30 seconds of
stable operation, with a 60-second readiness deadline. Premature evidence keeps
the trial open. Fatal evidence, timeout, attributed reset, or runtime failure
rejects it and falls back. If neither slot is viable, the host enters explicit
recovery without attempting application code.

## Operations

Run the HP3 contract and qualifier:

```bash
make check-hp3
HP3_OUT_DIR=reports/app-slots/hp3-local make app-slots-qualify
```

The qualifier compiles the slot path with `-Wall -Wextra -Werror`, executes 14
synthetic cases, replays both HP2 locks and fingerprints, checks both partition
layouts, and records exact evidence hashes.

## Claim boundary and hardening addendum

HP3 is host-executed synthetic evidence. It does not claim a current ESP-IDF
firmware build, flash or target execution, a physical power-loss campaign,
production signing deployment, external provider integration, RAX, MQTT,
transport, Pulse-core changes, or host-firmware OTA.

HP3.5 owns the additive torn-write and interruption seal while preserving this
fixed HP3 authority. The host matrix now passes 11,657 exact cases. The frozen
physical campaign still requires real reports from both named boards before a
dual-board observation may be claimed.
