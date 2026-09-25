# HP4.4 administration adversarial seal

HP4.4 closes the protected-administration phase by adversarially exercising the
complete HP4.1 core, HP4.2 exclusive update transaction, and HP4.3 host-only
recovery path. The result is
`HOST_ADMINISTRATION_ADVERSARIAL_SEALED` with classification
`HOST_NATIVE_ADMINISTRATION_ADVERSARIAL_ONLY`.

This is a deterministic host-native result. It does not claim an ESP32 target
build, physical execution, a serial driver, network transport, production
authenticator, production cryptography, host-firmware OTA, factory-host writes,
partition changes, or application execution. The combined physical
administration/web gate remains HP5.5.

## Sealed predecessor and current source

HP4.4 starts from the deterministic HP4.3 source archive:

- archive SHA-256:
  `78407faf0981ac1d8d39f449136c613ee9aa4ca92ca168715ea0aed1b5f38eee`;
- manifest count: 469 files;
- HP4.3 firmware: 150 files at
  `d36978214d8e1d892961e7239facafa49eb1ed4150843dd1eeb23dec5d8ceb5f`;
- native SDK: one unchanged file at
  `a7ceb397ab009950a1ebbdea60280f7944020a6523252b7de0d781e3e798bdd4`.

The HP4.4 firmware tree remains 150 files and advances to
`ff9f571860eda289cc276c6418f887b0af42552380c50f4038b5163ea929a386`.
No administration symbol entered the guest ABI or native-extension SDK, and no
partition, factory-host, or host-OTA surface changed.

## Finding and fix

The adversarial matrix found one boundary condition: an otherwise valid
session whose next command sequence was `UINT64_MAX` could accept the final
representable value and then wrap its replay high-water mark to zero.

`wdc_admin_submit` now rejects sequence exhaustion as
`WDC_ADMIN_REJECTION_RATE_LIMITED` before ownership is allocated. The rejection
does not allocate a ticket, advance replay state, enqueue control work, change
mode, emit a terminal or accepted-command audit record, or mutate slot state.
The session remains explicitly closable; a strictly newer authenticated epoch
starts a fresh session at sequence one. The finding is sealed as
`COMMAND_SEQUENCE_EXHAUSTION_REJECTED_PREACCEPT`.

## Exact adversarial matrix

The new native harness executes 3,523 deterministic cases:

| Category | Cases | Boundary |
|---|---:|---|
| Preaccept and mutation | 21 | Malformed identity, shape, deadline, command, state, payload, and busy rejections preserve all authority snapshots. |
| Authorization and replay | 13 | Unauthorized, expired, stale, replayed, duplicate, out-of-order, epoch, nonce, backoff, and sequence-exhaustion behavior. |
| Quiesce and unload | 12 | Guest/refinement refusal, timeout, trap, failure, and reordered evidence. |
| Resource floor | 4 | Exact fixed-reserve, total-free, largest-block, and admission boundaries. |
| Safe stream cut | 2,362 | Every prefix from zero bytes through the complete 2,361-byte stored artifact. |
| Stream transaction | 14 | Wrong transaction/slot/hash/length/offset, rate, timeout, and abort races. |
| Verification rejection | 9 | Artifact, bundle, compatibility, resource, security-floor, authority, and replaceable-verifier denials. |
| Journal interruption | 1,030 | Both target records across every erase, record-body, and commit-marker prefix. |
| Capacity saturation | 10 | Ticket, replay, terminal, audit, ISR, control-lane, and exclusive-resource saturation. |
| Terminal and audit | 8 | Exactly-one terminal, first-terminal-wins, bounded response, overflow/loss, and identity retention. |
| Recovery interaction | 40 | Automatic no-viable and administrative entry, status, abort, staging, reboot, denial, and timeout combinations. |

The journal count is exact:

```text
2 target records * ((256 + 1) erase prefixes
                  + (252 + 1) record-body prefixes
                  + (4 + 1) commit-marker prefixes) = 1,030
```

The harness also reruns the 14 HP4.1, 15 HP4.2, and 12 HP4.3 native cases.
That yields 41 inherited cases and 3,564 aggregate host-native cases, all
passing with zero failures.

## Preserved authority

HP4.4 does not redefine earlier ownership:

- HP1 remains the sole priority, queue, ticket, completion, fixed-memory,
  exclusive-admission, and reserved-lane authority. Application pressure
  cannot consume administration or safety-recovery capacity.
- HP3 remains the sole durable slot, last-confirmed, trial, fallback, journal,
  and reboot-selection authority. Interrupted records never become
  authoritative.
- Rejected requests remain preaccept and cannot mutate replay, mode, audit,
  terminal, queue, resource, or slot state.
- Every accepted command produces exactly one retained, first-terminal-wins
  completion.
- Every failure before durable trial handoff aborts staging and returns to
  `NORMAL` or `RECOVERY` according to transaction origin.
- Administration remains private to the host and absent from application,
  event, capability, guest, and native-refinement entry surfaces.

## Qualification

Run the focused contract gate:

```sh
make check-hp4-4
```

Create fresh manifested evidence with:

```sh
HP4_4_OUT_DIR=reports/administration/hp4_4-<fresh-id> \
  make administration-adversarial-qualify
```

The qualifier compiles the integrated C harness under C11 with `-Wall`,
`-Wextra`, `-Werror`, `-pedantic`, `-O2`, and the C6-minimum profile. It also
replays every HP1–HP4.3 authority hash, the exact HP4.3 archive/source history,
the unchanged native SDK, the private ABI boundary, the historical successor
validators, and all inherited native smoke programs.

## HP5 handoff

HP4 is complete after HP4.4. HP5 may add a minimal host-owned network transport
only behind the same authenticated-entry, replay, deadline, ticket, terminal,
audit, resource, update, recovery, and HP3 boot-authority rules. A transport
must not become authentication authority or create an application route into
administration.

MQTT, provider ergonomics, RAX, host-firmware OTA, partition redesign, and
production key lifecycle remain deferred. HP5.5 owns the first combined
physical administration and web evidence; HP4.4 itself creates no new physical
result.
