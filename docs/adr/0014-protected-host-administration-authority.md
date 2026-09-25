# ADR 0014 — Protected host administration authority

## Status

Accepted for HP4.0 through HP4.4.

## Context

The host must remain administrable when a Pulse application is absent,
trapped, saturated, incompatible, or rejected. Application routes and future
network transports cannot be allowed to own update keys, resource reserves,
slot writes, verification, recovery, or boot selection. HP1 already owns
priority and memory solvency, HP2 owns running-host compatibility, and HP3 owns
durable application-slot and boot authority.

HP4 needs one orchestration contract that can begin with attended serial entry
and later accept an authenticated external transport without changing those
authorities.

## Decision

Administration is a host-private plane with no application ABI, event/effect,
native-refinement, or application-route entry. A transport supplies bounded
bytes only. A replaceable host authorizer emits one fixed authenticated-entry
record containing principal hash, privileges, expiry, channel binding, and the
session replay identity.

HP4 v1 has one fixed session, one accepted in-flight command, strictly
consecutive sequence numbers, and exactly one retained terminal result for
each accepted command. Capacity admission, replay reservation, and command
ownership are one atomic acceptance step. Pre-acceptance rejection creates no
ticket and mutates no authority.

The host uses a volatile five-state machine: `NORMAL`, `QUIESCE`, `UPDATE`,
`RECOVERY`, and terminal `REBOOT_HANDOFF`. There is no direct
`NORMAL -> UPDATE` edge. A loaded application and native refinements must
quiesce and unload before exclusive C6 update admission. A reset discards the
volatile HP4 mode and returns durable selection to HP3; HP4 never creates a
second slot or boot journal.

Administration, update, and recovery submit only through their fixed HP1
sources. Candidate staging and verification use only the inactive HP3 slot,
the HP2 running fingerprint, the existing security floor and artifact
authority, and the existing HP3 journaled `TRIAL` transition. The reboot
handoff returns to HP3 boot selection.

`SERIAL_PHYSICAL_V1` is the first concrete transport class. Its attended entry
condition is platform evidence for the replaceable authorizer, not a
production-cryptography claim. A future authenticated external transport must
normalize into the same entry, session, command, audit, and state contracts.

HP4.0 freezes this decision and validates a host model only. Firmware,
authenticator, serial driver, update transaction, and recovery implementation
begin in later HP4 passes.

## Consequences

- Application saturation cannot consume administrative or recovery ownership.
- A transport cannot assign principal identity, priority, slot, verification,
  or boot authority.
- Replay and capacity races cannot accept the same command twice.
- Failed quiescence, admission, staging, verification, or commit preserves the
  existing HP3 authority and last confirmed application.
- Host-only recovery exists conceptually without requiring an application to
  be loaded.
- Adding the HP5 network path does not require a second administrative state
  machine.
- The fixed audit ring remains bounded and records loss without logging
  credentials or artifact bytes.

## Deferred

HP4.1 implements the protected session, authorization, replay, rate, command,
terminal, and audit core. HP4.2 implements exclusive update, HP4.3 recovery,
and HP4.4 adversarial host evidence. Network transport, provider ergonomics,
MQTT, RAX, host-firmware OTA, partition-mode redesign, production key
lifecycle, and new physical evidence remain outside this decision.
