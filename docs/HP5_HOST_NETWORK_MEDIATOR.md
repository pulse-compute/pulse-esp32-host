# HP5 host network mediator

HP5 implements the first host-owned production-shaped Wi-Fi/TLS ingress and a
minimal Pulse HTTP service behind the sealed HP1–HP4 authorities. The
host-native qualification result is `HOST_NETWORK_MEDIATOR_IMPLEMENTED`, with
classification `HOST_NATIVE_NETWORK_MEDIATOR_ONLY`.

This is a source and host-execution result. It does not claim an ESP-IDF target
build, Wi-Fi association, TLS handshake, physical execution, production
authenticator, production cryptography, credential provisioning, certificate
issuance, or key lifecycle. The combined named-board proof is HP5.5.

## Sealed predecessor and source identity

HP5 begins from the deterministic HP4.4 archive:

- archive SHA-256
  `df9c4e5e92b0bbd18f04f439cd1cacf3459973a11fbfb9a3a7305f6abb2a7410`;
- 474 manifested files and 3,697,926 payload bytes;
- HP4.4 firmware SHA-256
  `ff9f571860eda289cc276c6418f887b0af42552380c50f4038b5163ea929a386`
  across 150 files;
- unchanged one-file native SDK SHA-256
  `a7ceb397ab009950a1ebbdea60280f7944020a6523252b7de0d781e3e798bdd4`.

The HP5 firmware tree contains 159 files at
`2e94b65a03a0612d4e770dc0f9b624dab874a75bf334bbd5173023427b7076a5`.
The portable guest SDK advances only for the paired HTTP response effect; no
administration identity, credential, certificate, private key, socket, or
transport policy enters the guest or native-extension SDK.

## Ownership and flow

The implemented application flow is:

```text
host Wi-Fi/TLS/listener
  -> fixed bounded parser
  -> exact registered /pulse/v1/app/ route
  -> WDC_EVENT_HTTP_REQUEST
  -> common wdc_module_on_event runtime path
  -> at most one WDC_OP_HTTP_RESPOND effect
  -> bounded host-owned HTTPS response
```

`wdc_http` owns ingress orchestration, parser storage, route registration, the
two listener budgets, and the ESP-IDF adapter. `wdc_net` remains the
application-facing network intent mediator and has no dependency on
`wdc_admin`. It exposes only a narrow host-private paired-response hook so the
active HTTP event can consume `WDC_OP_HTTP_RESPOND` without importing listener
or administration authority.

Application routes are exact `GET` or `POST` paths beneath
`/pulse/v1/app/`. Registration is fixed before service start. The four-entry
route table cannot register or shadow `/pulse/v1/admin/`. A matched request is
encoded as the existing bounded event and dispatched through the common Wasm
handler. During that handler, the first response with the exact active request
ID wins. Duplicate, late, cancelled, wrong-resource, wrong-request, oversized,
or out-of-range responses fail closed. A handler that returns successfully
without a response produces an empty 204 terminal response; a trap produces a
bounded 500 response.

## Protected administration reuse

The administration flow is:

```text
independent admin HTTPS listener and parser
  -> host-observed channel binding
  -> replaceable authenticated external entry
  -> existing HP4 session, replay, deadline, rate, and capacity gates
  -> existing HP1 command ownership
  -> existing HP4 update or recovery transaction
  -> existing HP3 journal, terminal, and reboot authority
```

The fixed routes are:

| Method | Path | Existing authority used |
|---|---|---|
| `POST` | `/pulse/v1/admin/session/begin` | HP4 challenge issuance and replaceable authorizer. |
| `POST` | `/pulse/v1/admin/session/finish` | HP4 authenticated-entry validation and session binding. |
| `DELETE` | `/pulse/v1/admin/session` | HP4 session close. |
| `POST` | `/pulse/v1/admin/command` | Existing HP4 bounded serial-frame normalizer and command admission. |
| `GET` | `/pulse/v1/admin/terminal` | Existing retained first-terminal-wins result. |

HTTP does not authenticate a principal, allocate a ticket, advance replay,
select a command, choose a slot, verify an artifact, write a journal, cancel
accepted work, or select a boot target. It supplies bounded bytes, a deadline,
connection state, and a host-observed TLS channel binding. HP4 alone performs
authenticated entry and owns every later transition. The HP4.3 no-viable-slot
recovery path remains available without an application.

Malformed, oversized, incomplete, slow, disconnected, unauthorized, stale,
replayed, or saturated requests reject before HP4 command-acceptance mutation.
Every accepted command still produces exactly one HP4 terminal. A response send
failure is counted explicitly but does not roll back an application, undo a
durable slot transition, or cancel an accepted command. Only the existing HP4
abort and absolute-deadline authorities can cancel accepted administrative
work.

## Fixed resource boundary

| Resource | HP5 bound |
|---|---:|
| HTTPS listeners | 2, one application and one administration |
| Open sockets per listener | 3 |
| Parser storage budget | 2,304 bytes per parser |
| Service storage budget | 8,192 bytes |
| Request body | 2,048 bytes |
| Application body | 1,024 bytes |
| Response body | 1,280 bytes |
| Application routes | 4 |
| Active application requests | 1 |
| Application request deadline | 5 seconds |
| Administration request deadline | 30 seconds |

The ESP-IDF source configures station-mode Wi-Fi and two independently bounded
HTTPS servers. Application and administration use different default ports
(443 and 8443), control ports, server tasks, parsers, and socket caps.
Application saturation therefore cannot occupy the administration parser or
socket reserve. Wi-Fi credentials, certificate/private-key pointers, reconnect
policy, TLS state, and sockets remain host-private.

HP1 remains the scheduling, fixed-reserve, administration/recovery lane, and
exclusive-update admission authority. HP3 remains the durable slot,
last-confirmed, trial, fallback, journal, and reboot-selection authority. HP5
does not change the partition table or repurpose either application slot.

## Qualification

Run the focused contract gate:

```sh
make check-hp5
```

Create a fresh manifested host-native result with:

```sh
HP5_OUT_DIR=reports/network/hp5-<fresh-id> \
  make host-network-qualify
```

The qualifier:

- verifies the exact HP1–HP4.4 model/evidence hashes and HP4.4 archive history;
- validates the fixed source surface and host-private dependency direction;
- compiles the actual parser, service, common-runtime adapter, paired response
  hook, HP4 core, and HP1 control code under C11 with `-Wall`, `-Wextra`,
  `-Werror`, `-pedantic`, and `-O2`;
- executes 35 HP5 native cases covering parser bounds, route isolation,
  first-response-wins, timeout, cancellation, trap behavior, external
  authenticated entry, command/terminal reuse, saturation, and response loss;
- reruns all 3,523 HP4.4 adversarial cases and 41 inherited HP4.1–HP4.3 cases;
  and
- emits a four-artifact manifest plus a qualification report.

The combined result is 35 new passing cases and 3,564 passing inherited HP4
cases. The host stub exercises the common Wasm event handler boundary, but no
application Wasm code or ESP32 target code is claimed as executed by HP5.

## HP5.5 gate and later roadmap

HP5.5 is a physical audit barrier, not more host-only feature implementation.
Its source implementation now builds the exact narrow HP5.5 successor for both
retained named boards and
retain auditable evidence for Wi-Fi association, TLS listeners, application
HTTP, protected administration, update/recovery/reset behavior, response-loss
semantics, and HP1 resource floors under application pressure. It must also
bind the actual authenticator and credential/provisioning assumptions used by
the campaign without upgrading those observations into a general production
security claim.

The implemented gate is documented in the
[HP5.5 physical runbook](HP5_5_NETWORK_ADMIN_PHYSICAL_SEAL.md). It introduces
new target contracts rather than relabelling HP2 evidence, externalizes all
test secrets, and can emit the promotion token only after two distinct exact
board reports. This snapshot remains `HARDWARE_PENDING` because those physical
runs have not been executed here.

HP6 (thin external ESP32 provider), HP7 (MQTT customer zero), HP7.5 (MQTT
adversarial dual-board seal), and HP8 (external conformance/reconciliation)
remain downstream. RAX, host/factory/bootloader/partition OTA, partition
redesign, broad peripherals, fleet management, attestation, secure boot,
flash encryption, eFuse expansion, and unvetted signing remain excluded.
