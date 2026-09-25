# HP4.0 protected administration contract

## Result

HP4.0 freezes the host-private authority, identity, replay, resource, audit,
and mode-transition contract needed by HP4.1 through HP4.4. Its terminal
result is `HOST_ADMINISTRATION_CONTRACT_FROZEN` with classification
`HOST_MODEL_ONLY`.

The machine-readable authority is
[`PULSE-ESP32-009-protected-administration.json`](../specs/PULSE-ESP32-009-protected-administration.json).
[ADR 0014](adr/0014-protected-host-administration-authority.md) records the
architectural decision.

HP4.0 does not add a firmware component, serial driver, network listener,
authenticator, update transaction, recovery implementation, physical result,
or production-cryptography claim. The purpose of the pass is to make those
later implementations conform to one authority rather than grow competing
administrative paths.

## Source reconciliation

The accepted HP4 base is the intentionally closure-sealed successor to the
pre-physical HP3.5 source package:

| Input | Predecessor v8 | Accepted closure seal |
|---|---:|---:|
| Archive SHA-256 | `7be285c47d268721e4a419074d8a551a7db59968bed8738a8ab7ee0c979c4a9a` | `928b74de36f5d25d48caecb08a3412314b02f0aece7c804046b5b7942466d00f` |
| Manifested files | 438 | 440 |
| Manifested payload | 3,022,784 bytes | 3,033,334 bytes |

The successor adds the immutable HP3.5 closure indexes and terminal closure
text. It retains the exact firmware source seal
`c7b4341e00911b3b26b4d9b8abcd831af4abdf7754503a79298e86aa2b9d2c31`
at 141 files and the native-SDK seal
`a7ceb397ab009950a1ebbdea60280f7944020a6523252b7de0d781e3e798bdd4`
at one file. It does not rewrite the campaign, board reports, serial logs,
dual evaluation, or their claims.

## Authority flow

The only admitted shape is:

```text
bounded serial/physical entry now, authenticated external entry later
  -> replaceable host-private authorizer
  -> replay, deadline, rate, and capacity gate
  -> one bounded accepted command
  -> HP1 administration/update/recovery lane
  -> HP4 volatile mode transition
  -> HP2 running-host compatibility and security policy
  -> HP3 inactive-slot staging and journaled TRIAL
  -> terminal reboot handoff to the HP3 boot selector
```

A transport may supply bytes and transport observations. It may not supply an
authoritative principal, authorize itself, reserve a session, select a control
priority, write a slot, declare verification, lower the security floor, mark a
trial, or choose the next boot.

The application-facing ABI, event/effect paths, native-refinement ABI, and
application network routes expose no administrative command or transition.
No application work item may select the HP1 `ADMINISTRATION`, `UPDATE`, or
`RECOVERY` source.

## Identities and authenticated entry

Administrative identity is deliberately split:

- the running host is the validated HP2 fingerprint plus a boot-scoped channel
  binding;
- the principal is a 32-byte identity hash issued by the authorizer, never a
  transport assertion;
- a session is `(authorization_epoch, session_nonce)`;
- a command is that session plus a strictly consecutive command sequence;
- `request_id` is diagnostic correlation only; and
- an application candidate is the HP3 fixed header plus the SHA-256 of the
  complete stored artifact.

The transport-neutral authenticated-entry record is exactly 128 bytes,
version 1.0. It carries transport and authorization method, privileges,
issuance and expiry time, the session identity, principal hash, channel
binding, and zeroed reserved bytes. It contains no credential, authenticator,
challenge, key, or artifact content.

The replaceable host-private authorizer is the only producer of that record.
`LOCAL_PHYSICAL` and `REPLACEABLE_AUTHENTICATOR` are the two frozen method
classes. This names an interface, not a cryptographic implementation. A
production signing or remote-authentication claim requires a vetted verifier,
known-answer tests, provisioning, and key lifecycle in a later pass.

## Session, replay, and command ownership

HP4 v1 admits one fixed session and one accepted in-flight command. There is
no allocation and no capacity owned by an application or transport.

Authorization moves through `UNAUTHENTICATED`, `CHALLENGE_ISSUED`,
`AUTHORIZED`, and then one of `EXPIRED`, `REVOKED`, or `CLOSED`. A command
sequence starts at one and is strictly consecutive. The replay identity is:

```text
authorization_epoch + session_nonce + command_sequence
```

Older epochs, reused or lower sequences, and gaps reject before acceptance.
Capacity admission, replay reservation, and accepted-command ownership commit
atomically. Bounds, authorization, rate, or capacity rejection therefore does
not advance the sequence high-water and does not create a completion owner.

An accepted command has exactly this lifecycle:

```text
RECEIVED -> ACCEPTED -> IN_PROGRESS -> TERMINAL
```

The terminal vocabulary is `SUCCEEDED`, `FAILED`, `TIMED_OUT`, `CANCELLED`,
`ABORTED`, and `REBOOT_HANDOFF`. The first terminal write wins. Duplicate and
late terminal writes are explicit contract errors and cannot replace the
retained result.

The frozen command vocabulary is `STATUS`, `BEGIN_UPDATE`, `WRITE_CHUNK`,
`FINISH_UPDATE`, `ABORT`, `ENTER_RECOVERY`, `ACTIVATE_TRIAL`, and `REBOOT`.
Authentication exchanges remain outside the command vocabulary and cannot be
confused with accepted administrative work.

## Fixed bounds and deadlines

| Resource | Bound |
|---|---:|
| Sessions | 1 |
| In-flight accepted commands | 1 |
| Transport frame | 2,048 bytes |
| Normalized request | 112 bytes |
| Command payload | 1,024 bytes |
| Stream chunk | 1,024 bytes |
| Status response | 1,024 bytes |
| Terminal record | 64 bytes |
| Audit record | 160 bytes |
| Audit ring | 32 records |

| Deadline | Value |
|---|---:|
| Authorization challenge | 10 seconds |
| Command default | 30 seconds |
| Quiescence | 10 seconds |
| Stream idle | 30 seconds |
| Session idle | 30 seconds |
| Reboot handoff | 5 seconds |
| Session lifetime | 15 minutes |
| Complete update transaction | 15 minutes |

Deadlines use absolute host monotonic time. A caller may request a shorter
deadline but cannot extend policy. Zero, expired, overflowing, or over-policy
deadlines reject before acceptance.

Eight failed authorization attempts in a 60-second window invoke a 30-second
backoff. This rate state is fixed and host-owned; failed attempts cannot consume
HP1 recovery queue slots.

## Administrative mode machine

HP4 mode is volatile orchestration state. It never becomes another slot or
boot journal. Initialization asks HP3 whether a viable application exists:

- viable HP3 authority initializes `NORMAL`;
- no viable application initializes `RECOVERY`; and
- reset during `QUIESCE` or `UPDATE` discards HP4 mode and lets HP3 establish
  `NORMAL` or `RECOVERY` from its existing durable journal.

The states are `NORMAL`, `QUIESCE`, `UPDATE`, `RECOVERY`, and terminal
`REBOOT_HANDOFF`. The only legal changing transitions are:

| From | Trigger | To | Required authority |
|---|---|---|---|
| `NORMAL` | `BEGIN_UPDATE` | `QUIESCE` | authorized fresh session; HP1 administration acceptance; intent becomes `UPDATE` |
| `NORMAL` | `ENTER_RECOVERY` | `QUIESCE` | recovery privilege and HP1 recovery acceptance; intent becomes `RECOVERY` |
| `NORMAL` | `NO_VIABLE_APPLICATION` | `RECOVERY` | HP3 reports no viable application; recovery reserve intact |
| `QUIESCE` | `QUIESCE_COMPLETE` | `UPDATE` | update intent; guest and refinements quiesced and unloaded; exclusive update admitted |
| `QUIESCE` | `QUIESCE_COMPLETE` | `RECOVERY` | recovery intent; guest and refinements quiesced and unloaded; boot authority unchanged |
| `QUIESCE` | `ABORT_OR_TIMEOUT` | `NORMAL` | staging not started; last confirmed application viable; boot authority unchanged |
| `QUIESCE` | `ABORT_OR_TIMEOUT` | `RECOVERY` | no viable application; boot authority unchanged; recovery reserve intact |
| `UPDATE` | `TRIAL_COMMITTED` | `REBOOT_HANDOFF` | inactive-only complete artifact verified; authorization current; HP2/security/authority checks pass; HP3 TRIAL commit durable |
| `UPDATE` | `ABORT_OR_FAILURE` | `NORMAL` | staging aborted; last confirmed viable and preserved; boot authority unchanged |
| `UPDATE` | `ABORT_OR_FAILURE` | `RECOVERY` | staging aborted; no viable application; boot authority unchanged |
| `RECOVERY` | `BEGIN_UPDATE` | `UPDATE` | application absent; refinements unloaded; exclusive update admitted; inactive slot selected |
| `RECOVERY` | `REBOOT` | `REBOOT_HANDOFF` | reboot privilege and a viable HP3 boot authority |

`STATUS` is read-only in every state. `WRITE_CHUNK` and `FINISH_UPDATE` are
legal only in `UPDATE` and do not themselves change HP4 mode. `ABORT` in
`RECOVERY` succeeds without leaving recovery or mutating a slot.

There is no direct `NORMAL -> UPDATE` edge. A loaded guest and all native
refinements must positively quiesce and unload before C6 admits its 65,536-byte
exclusive update working set. There is no `RECOVERY -> NORMAL` edge: recovery
returns to ordinary operation only by rebooting through HP3 selection.
`REBOOT_HANDOFF` has no outgoing HP4 transition.

## HP1, HP2, and HP3 bindings

HP4 does not create substitute authorities:

- HP1 retains the 98,304-byte fixed control reserve. Administration uses
  priority 11 with an eight-item queue and 6,144-byte stack. Update uses the
  same HP1 class through source `UPDATE`. Recovery uses priority 13 with an
  eight-item queue and 4,096-byte stack. C6 update admission additionally
  requires the 65,536-byte working set and largest allocation.
- HP2 retains running-host structure, target, ABI, capability, placement, and
  live resource compatibility. An administrative authorizer cannot waive
  fingerprint or prelaunch rejection.
- HP3 retains inactive-slot selection, bounded staging, complete stored-byte
  verification, security floor, artifact authority, `TRIAL` journal commit,
  boot attribution, confirmation, fallback, and recovery selection.

The factory host partition, bootloader, partition table, active application
slot, last-confirmed application slot, and raw flash outside HP3 are not HP4
write targets.

## Serial first, transport-neutral authority

`SERIAL_PHYSICAL_V1` is the first concrete transport class. It uses bounded
length-prefixed binary frames normalized into the fixed request record. The
platform must establish an attended physical/serial entry condition before
the authorizer may issue an authenticated-entry record. Serial bytes cannot
self-assert presence or identity.

The existing production security profile still decides whether serial install
is allowed. Physical presence is not described as production cryptography.

HP5 may add `AUTHENTICATED_EXTERNAL_V1` behind the same ingress and
authenticated-entry contracts. It may not change session identity, replay,
terminal ownership, state transitions, control reserves, slot verification,
or reboot authority.

## Audit contract

The fixed 160-byte v1 record distinguishes authorization, replay, command
acceptance, quiescence, staging, verification, slot transition, terminal
result, recovery entry, and reboot handoff. It binds the event to principal
hash, session epoch/nonce, command sequence, request correlation, state change,
slot, and optional artifact hash.

The 32-record host-owned ring overwrites the oldest record on pressure and
latches an exact loss count. Audit backpressure cannot block recovery and an
application cannot reserve or drain the ring. Credentials, authenticators,
challenges, keys, and artifact bytes are never logged.

## Negative contract and exclusions

HP4.0 explicitly does not implement or authorize:

- an application route, event, effect, or native-refinement administrative
  surface;
- Wi-Fi, TLS, HTTP, MQTT, or another external listener;
- a provider or Pulse-core concept;
- RAX or another packaging envelope;
- host-firmware, bootloader, or partition-table OTA;
- redundant-versus-capacity partition redesign;
- broad peripheral work;
- production signing, remote attestation, or key-lifecycle claims; or
- a new physical S3/C6 result.

## Operations and handoff

Run the HP4.0 contract gate:

```bash
make check-hp4-0
```

Produce a host-model qualification report in a fresh external directory:

```bash
HP4_0_OUT_DIR=reports/administration/hp4_0-local \
  make administration-contract-qualify
```

The qualifier validates exact record layouts, state and transition closure,
authority hashes, source reconciliation, guard-failure immutability, terminal
ownership, and the unchanged HP3.5 firmware/native-SDK seals. It does not
manufacture firmware or physical evidence.

HP4.1 now implements the protected administrative core using these fixed
identities, bounds, replay rules, control sources, and terminal semantics. See
[HP4.1 protected administration core](HP4_1_PROTECTED_ADMINISTRATION_CORE.md).
HP4.2 implements the exclusive update transaction, HP4.3 recovery, and HP4.4
the adversarial host seal.
