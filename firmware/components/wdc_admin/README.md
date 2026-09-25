# `wdc_admin`

HP4.1 implements the host-private protected-administration core. It owns one
fixed authenticated session, one accepted command, strict replay sequencing,
authorization backoff, exactly-one terminal completion, a bounded status
response, and the fixed audit ring defined by HP4.0.

The component submits only derived `ADMINISTRATION`, `UPDATE`, or `RECOVERY`
work to `wdc_control`; callers cannot choose a control source. Its serial
adapter is a fixed, little-endian, length-prefixed request normalizer. The
adapter cannot issue an authenticated-entry record and does not implement a
UART driver. Only the configured replaceable authorizer can establish a
session.

HP4.2 adds `wdc_admin_update`: a C6-minimum, host-private exclusive update
transaction. `BEGIN_UPDATE` first enters `QUIESCE`, requires positive evidence
that the guest and every native refinement are quiesced and unloaded, takes a
post-unload heap snapshot, and admits HP1's exact 98,304-byte fixed reserve plus
65,536-byte update working set and 98,304-byte largest-block requirement. Only
then may HP3 erase and stream the inactive application slot.

Writes are sequential, limited to 1,024 bytes, capped at 64 chunks/65,536 bytes
per one-second window, and governed by the 30-second stream-idle and 15-minute
transaction deadlines. `FINISH_UPDATE` invokes the existing complete stored
artifact, HP2 compatibility, security-floor, and artifact-authority checks,
then the replaceable administration verifier. `ACTIVATE_TRIAL` rechecks live
authorization and verification before asking HP3 for a durable `TRIAL` journal
commit. Only a read-back-confirmed commit enters `REBOOT_HANDOFF`.

For normal-origin HP4.2 transactions, every quiesce, admission, stream,
verification, or pre-commit journal failure aborts staging, returns to
`NORMAL`, and preserves the last confirmed record and pre-transaction boot
authority.

HP4.3 adds `wdc_admin_recovery`. It binds automatic entry to an HP3 no-viable
result with no application launch or reboot loop, and administrative entry to
positive guest/refinement unload evidence. Recovery keeps fixed status and
abort available without an application, reuses the HP4.2 candidate transaction
while returning recovery-origin failures to `RECOVERY`, and requires a
read-only complete HP3/HP2 viability proof before reboot handoff.

HP4.4 seals the host-private administration path with deterministic adversarial
coverage. In addition to authorization, replay, quiesce, resource-floor,
stream-cut, verifier, journal-interruption, saturation, terminal/audit, and
recovery-interaction cases, command-sequence exhaustion is rejected before a
ticket or replay high-water mark can mutate. The session remains explicitly
closable so a later authenticated epoch can recover without sequence wrap.

HP5 realizes the transport kind that HP4 reserved for an authenticated
external entry. Only `REPLACEABLE_AUTHENTICATOR` with a host-observed boot/TLS
channel binding is admitted; an external request cannot assert physical
attendance or issue its own authenticated-entry record. The HTTP adapter feeds
the existing session, frame normalizer, replay, queue, terminal, and audit
state. No second administrative authority or response table is introduced.

The component exposes no application ABI and claims no UART driver, production
authenticator or credential lifecycle, target execution, physical result,
host/factory OTA, or partition redesign. HP5's network listener remains in
`wdc_net`; this component only accepts its bounded normalized entry.
