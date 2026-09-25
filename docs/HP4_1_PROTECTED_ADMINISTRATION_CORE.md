# HP4.1 protected administration core

## Result

HP4.1 implements the fixed-storage, host-private administrative core frozen by
HP4.0. Its aggregate is
`HOST_PROTECTED_ADMINISTRATION_CORE_IMPLEMENTED` with classification
`HOST_NATIVE_CORE_ONLY`.

The implementation is the `wdc_admin` firmware component. It is linked before
the application pthread is created and has no guest ABI, application route,
event/effect, native-refinement, or application-network entry. The
machine-readable implementation authority is
[`PULSE-ESP32-010-protected-administration-core.json`](../specs/PULSE-ESP32-010-protected-administration-core.json).

This pass executes a native host qualification. It does not build or flash a
target, attach a UART driver, stage an application artifact, change an HP3
slot, run recovery, execute application code, create physical evidence, or
claim production authentication or cryptography.

## Source continuity

HP4.1 begins from the deterministic HP4.0 source archive:

```text
archive SHA-256: e2387f4974b2425267b29bf8285c387ca5e7d9d4fbfc6f3e75796001d6058722
manifested files: 445
manifested payload: 3,122,110 bytes
```

The historical HP4.0 firmware seal remains recorded as 141 files at
`c7b4341e00911b3b26b4d9b8abcd831af4abdf7754503a79298e86aa2b9d2c31`.
HP4.1 intentionally advances the firmware tree to 146 files at
`4f7b56a99adfedfa57c1d5179ad5ca03e6f57dd258a73fa3a6f71f747973253c`.
The native SDK remains unchanged at
`a7ceb397ab009950a1ebbdea60280f7944020a6523252b7de0d781e3e798bdd4`.

The HP3.5 physical campaign, dual evaluation, board reports, serial logs, and
their hashes remain immutable external evidence. HP4.1 does not relabel them.

## Fixed host ownership

The component embeds all mutable state. It calls no allocator.

| Storage | Native-host size or bound |
|---|---:|
| `WdcAdminCore` | 7,712 bytes |
| `WdcAdminSerialAdapter` | 2,072 bytes |
| Combined observed storage | 9,784 bytes |
| HP1 administration reserve | 12,288 bytes |
| Core compile-time ceiling | 8,192 bytes |
| Serial compile-time ceiling | 2,304 bytes |

Compile-time assertions retain the exact HP4.0 records:

| Record | Bytes |
|---|---:|
| Authenticated entry | 128 |
| Normalized request | 112 |
| Terminal | 64 |
| Audit | 160 |

The core owns one session, one accepted command, a 1,024-byte payload copy, a
1,024-byte status response, one retained terminal, rate/replay state, and 32
audit records. Application pressure cannot allocate or reserve any of them.

## Authorization and session flow

The first entry class is `SERIAL_PHYSICAL_V1`. Authorization has two distinct
steps:

1. host-private platform code begins an attended, boot-channel-bound challenge;
2. the configured `WdcAdminAuthorizeFn` evaluates opaque proof bytes and is the
   only producer of a `WdcAdminAuthenticatedEntry`.

The serial normalizer has no function that can begin or finish authorization
and never sees an authenticated-entry type. Raw serial bytes therefore cannot
self-assert physical presence, principal identity, privilege, epoch, nonce, or
control priority.

The core validates version, zeroed reserved bytes, transport and method,
privilege mask, boot channel binding, principal hash, issuance, expiry,
strictly increasing authorization epoch, and nonzero session nonce before
opening a session. The session has a 30-second idle deadline and a 15-minute
maximum lifetime.

Eight failed authorization completions in 60 seconds latch a 30-second
backoff. Backoff state is fixed and host-owned; failed attempts submit no HP1
work and consume no command capacity.

`WdcAdminArtifactVerifyFn` is a second replaceable host-private seam. It names
the complete-artifact, host-compatibility, security-floor, and artifact-authority
decision needed by HP4.2. It fails closed outside an in-progress update
verification context and does not claim a vetted verifier or key lifecycle.

## Replay and atomic acceptance

Command sequencing begins at one and is strictly consecutive. Acceptance is
ordered so that no fallible operation follows replay ownership:

1. validate the fixed request and payload bounds;
2. validate authorization, absolute deadline, epoch/nonce, sequence, command,
   privilege, state, and one-command capacity;
3. derive the HP1 source from the command and host mode;
4. submit to the partitioned HP1 lane; and
5. copy into fixed host storage and advance the replay high-water.

`BAD_FRAME`, `BOUNDS`, `UNAUTHORIZED`, `EXPIRED`, `STALE_REPLAY`,
`OUT_OF_ORDER`, `RATE_LIMITED`, `BUSY`, `UNSUPPORTED`, and `WRONG_STATE` are
explicit pre-acceptance outcomes. They create no control ticket, completion
owner, or replay advance. Audit observation of a rejection is not command
ownership.

Callers cannot select a `WdcControlSource`. The core derives:

- `STATUS` → `ADMINISTRATION`;
- update commands → `UPDATE`; and
- recovery commands → `RECOVERY`.

HP4.1 enables only `STATUS`. The full frozen vocabulary is encoded, but
`BEGIN_UPDATE`, `WRITE_CHUNK`, `FINISH_UPDATE`, `ABORT`, `ENTER_RECOVERY`,
`ACTIVATE_TRIAL`, and `REBOOT` reject as `UNSUPPORTED` until HP4.2 or HP4.3
installs the owning transaction machinery. This prevents a command from being
accepted before its mutation authority exists.

## Terminal ownership

An accepted command moves through `ACCEPTED`, `IN_PROGRESS`, and `TERMINAL`.
The first valid terminal write completes the matching HP1 ticket and retains
the fixed terminal record. A duplicate or late write returns
`WDC_ERR_INVALID_STATE` without replacing that record.

The terminal and its optional bounded status response are consumed together.
An undersized response buffer leaves both retained; a successful take frees
the HP1 completion and command slot exactly once. Both queued expiry and
in-progress expiry still produce `TIMED_OUT`, so accepted ownership cannot be
lost at a deadline boundary.

## Serial normalization

The serial adapter implements incremental, bounded framing only:

```text
u32 little-endian body length
112-byte little-endian normalized request
0..1024 payload bytes
```

The full frame, including the four-byte prefix, is limited to 2,048 bytes.
Malformed or oversized prefixes reset the adapter with an explicit rejection.
Fragmented feeds are supported. A complete frame is copied into the core
before the adapter resets.

There is no UART or USB driver in HP4.1. `SERIAL_PHYSICAL_V1` describes the
normalization and authority boundary, not a physical or production transport
claim.

## Audit behavior

The fixed 32-record ring records authorization, replay, acceptance, terminal,
and future HP4 transition observations. On pressure it overwrites the oldest
record and saturating-increments a loss counter; recovery cannot be blocked by
audit backpressure.

Records contain only the frozen principal hash, session/command identity,
request correlation, state, status, slot, and optional artifact hash. Proof
bytes, credentials, challenges, keys, and artifact bytes are never fields.

## Application isolation

Only the firmware main component depends on `wdc_admin`. `wdc_app`,
`wdc_events`, `wdc_extension`, and `wdc_net` have no component dependency on
it. The public guest ABI, C and Rust guest SDKs, and native extension SDK expose
no administrative symbol.

The main firmware calls only the side-effect-free link anchor before creating
the application pthread. Runtime task/driver installation is deferred, but the
component's linkage is not dependent on a guest starting or remaining healthy.

## Qualification

Run the contract gate:

```bash
make check-hp4-1
```

Create a fresh host-native evidence bundle:

```bash
HP4_1_OUT_DIR=reports/administration/hp4_1-<fresh-id> \
  make administration-core-qualify
```

The native smoke executes 14 cases covering layouts and storage, attended
authorization, rate backoff, replay and rejection immutability, application
lane saturation, exactly-one completion, fragmented serial frames, serial
self-authorization denial, frame bounds, queued and in-flight timeout,
authorization epoch high-water, audit overwrite/loss, and the fail-closed
artifact-verifier seam.

The terminal qualification is
`HOST_PROTECTED_ADMINISTRATION_CORE_IMPLEMENTED`. It is host-native evidence,
not an ESP32 target or physical-board result.

## HP4.2 handoff

HP4.2 may enable the update command subset only when it adds the complete
exclusive transaction: positive guest/refinement quiescence and unload, HP1
C6 working-set admission, inactive-slot-only streaming, complete verifier and
HP2/security checks, HP3 `TRIAL` journal commit, abort, and safe terminal
handoff.

HP4.1 does not implement update or recovery mode transitions. HP3 remains the
only durable slot and boot authority. Network transport, provider work, MQTT,
RAX, host-firmware OTA, partition redesign, production signing, and new
physical evidence remain stopped.
