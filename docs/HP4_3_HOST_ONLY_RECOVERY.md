# HP4.3 host-only recovery

HP4.3 implements the host-private recovery authority frozen in HP4.0. It keeps
authenticated administration available with no Pulse application or native
refinement loaded, supports a bounded application-candidate transaction, and
returns application selection to HP3 through a reboot handoff.

The result is `HOST_ONLY_RECOVERY_IMPLEMENTED` with classification
`HOST_NATIVE_RECOVERY_TRANSACTION_ONLY`. It is a host-native C result. It does
not claim an ESP32 target build, a physical-board run, a production
authenticator, production cryptography, a serial driver, a network transport,
host-firmware OTA, factory-host writes, or a partition-layout change.

## Sealed predecessor

HP4.3 starts from the deterministic HP4.2 archive:

- archive SHA-256:
  `f028891506f01796e214f222763b3182ae91c24e541be9af32dfed8151738bd3`;
- HP4.2 firmware seal: 148 qualified files at
  `77f4d2044776c6828e443486ee21199f95b4e1f34ae704c7323e901d51602eca`;
- native SDK: one unchanged file at
  `a7ceb397ab009950a1ebbdea60280f7944020a6523252b7de0d781e3e798bdd4`.

HP4.3 advances the qualified firmware tree to 150 files at
`d36978214d8e1d892961e7239facafa49eb1ed4150843dd1eeb23dec5d8ceb5f`.
The two new firmware files are `wdc_admin_recovery.c` and its private header.
The native SDK remains unchanged.

## Entry authority

There are two recovery entry paths.

1. Automatic entry consumes an HP3 `BOOT_RECOVERY` result. The result must
   identify neither a selected nor fallback slot, must not request another
   reboot, and must prove that application code was not launched. The bound
   metadata must also have both active and last-good slots set to `NONE`.
   Malformed or metadata-inconsistent evidence fails initialization.
2. Administrative entry starts only from `NORMAL` after an authenticated,
   recovery-privileged `ENTER_RECOVERY` command is accepted. The host moves to
   `QUIESCE`, obtains positive ordered evidence that the guest and every native
   refinement were quiesced and unloaded, and only then enters `RECOVERY`.

Automatic entry does not manufacture a session identity: it records an
observed `RECOVERY_ENTRY` audit record. Every later administrative action still
requires the HP4.1 authenticated session and replay rules.

No-viable entry stays in recovery. It does not request another reboot and
therefore cannot form a recovery reboot loop.

## Host-only state

In `RECOVERY`:

- application code is not loaded or executed;
- native refinements are not loaded;
- guest, event, capability, and refinement surfaces cannot select the
  `RECOVERY` or `UPDATE` control source;
- the unchanged HP1 recovery reserve is 16,384 bytes;
- the authenticated administration core remains available;
- `STATUS` returns one fixed 64-byte, secret-free record;
- idle `ABORT` succeeds without leaving recovery or changing slot metadata.

The status record contains only mode, recovery reason, update state, slot
states, load-state facts, recovery latch, audit-loss count, metadata generation,
and enabled command mask. It contains no authorization proof, key, token,
principal, session nonce, or artifact content.

## Recovery candidate transaction

HP4.3 reuses the HP4.2 update engine and its external 65,536-byte working
buffer. A recovery-origin `BEGIN_UPDATE` skips guest quiescence because recovery
already proves that the guest and refinements are absent. It still requires:

- the deterministic HP3 inactive-slot selector;
- an exact slot, total-byte count, and complete-artifact SHA-256 on every
  transaction command;
- HP1 exclusive admission with 98,304 fixed bytes, 163,840 total internal free
  bytes, and a 98,304-byte largest block;
- sequential chunks of at most 1,024 bytes;
- the existing stream-idle, transaction-deadline, and rate windows;
- complete stored-artifact, bundle, HP2 compatibility, resource, security-floor,
  artifact-authority, and replaceable administration-verifier decisions.

Staging never launches application code. A verified slot has no boot authority.
Only a durable `TRIAL` journal read-back advances to `REBOOT_HANDOFF`.

Every recovery-origin abort, timeout, resource denial, stream failure,
verification failure, or pre-handoff journal failure returns to `RECOVERY`, not
`NORMAL`. Active and last-good authority remain unchanged until the durable
trial commit.

## Safe reboot

An idle recovery `REBOOT` command does not trust metadata state alone. HP4.3
calls the new read-only HP3 helper
`wdc_app_slots_validate_reboot_candidate`, which requires an active `CONFIRMED`
or `TRIAL` record and repeats complete stored-artifact validation plus the HP2
prelaunch resource decision. The helper does not write metadata and reports
that application code was not launched.

If no viable candidate exists, the command receives a failed terminal and
recovery is retained. If the proof succeeds, the command receives
`REBOOT_HANDOFF`; the next boot remains wholly owned by the HP3 selector and
probation state machine. HP4.3 itself does not resume an application directly.

## Audit and terminal behavior

Accepted commands remain bound to the HP4.1 authorization epoch, session nonce,
command sequence, request ID, and principal digest. Proof bytes are never
stored. Automatic entry is explicitly distinguished from authenticated entry.

Durable staging, verification, rejection, and trial commits emit bounded
`SLOT_TRANSITION` records with the slot and artifact SHA-256. The fixed audit
ring retains an explicit loss count under overflow. Each accepted command uses
the HP4.1 first-terminal-wins core and produces exactly one retained terminal.

Unauthorized, expired, stale, replayed, out-of-order, malformed, busy, or
wrong-state requests are rejected before ticket allocation, replay advance,
mode change, or slot mutation.

## Qualification

Run the HP4.3 host-native seal with:

```sh
make check-hp4-3
HP4_3_OUT_DIR=reports/administration/hp4_3-<fresh-id> \
  make administration-recovery-qualify
```

The native smoke executes twelve cases covering automatic entry, malformed
boot evidence, fixed status, idle abort, no-viable reboot denial,
recovery-origin stage/abort, HP1 denial, complete candidate activation,
administrative entry, malformed unload evidence, read-only viable reboot, and
preaccept request-shape rejection. The recovery engine is 3,112 bytes; the
embedded HP4.2 update engine remains 3,096 bytes.

## HP4.4 handoff (completed)

HP4.4 owns the adversarial administration seal: unauthorized, stale, replayed,
duplicate, saturation, quiesce, verifier, security-floor, journal, stream-cut,
resource-denial, reboot, and no-viable interactions across the complete HP4
surface. HP4.4 must preserve the exact HP1 priorities, queues, stacks, reserve
arithmetic, HP3 authority, private ABI boundary, and the narrow host-native
claim. No new physical result is due before HP5.5.

The successor is now closed as
[`HOST_ADMINISTRATION_ADVERSARIAL_SEALED`](HP4_4_ADMINISTRATION_ADVERSARIAL_SEAL.md).
The original boundary above remains the exact historical input to that seal.
