# Component Map

## Native components

| Component | Responsibility | Key boundary |
|---|---|---|
| `wdc_abi` | ABI constants, CBOR helpers, pointer validation, host-call dispatch. | First line of guest request validation. |
| `wdc_runtime` | WAMR/host-stub lifecycle loading and calls. | Runs verified payload and records runtime outcome. |
| `wdc_events` | Event envelope encode/decode and queue. | Converts native events into bounded guest inputs. |
| `wdc_control` | Fixed ISR capture, priority classes, per-class work/completion slots, control reserves, and admission. | Keeps safety, administration, verification, and recovery solvent under application pressure. |
| `wdc_admin` | Fixed attended session, authorization backoff, replay and exhaustion guards, HP1-owned command, exactly-one terminal response, serial normalization, verifier seam, update/recovery engines, and audit ring. | Keeps administration host-private and prevents application submission, impersonation, replay wrap, shadowing, or capacity consumption. |
| `wdc_host_identity` | Fixed build-derived fingerprint validation and target/ABI/capability/placement/resource prelaunch checks. | Binds application admission to the running host without launching application code or exposing build mechanics to the guest. |
| `wdc_profile` | Built-in relay-node profile and resource lookup. | Maps logical resources to physical truth. |
| `wdc_caps` | Manifest capability parsing, authorization, audit, rate/payload limits. | Decides whether active app may request a resource operation. |
| `wdc_safety` | Safety state, safe outputs, fault-stop, guarded authorizer. | Denies effectful calls outside safe app-running state. |
| `wdc_hal` | GPIO safe defaults and host-call bridge. | Native hardware execution layer for GPIO. |
| `wdc_bundle` | Bundle parse/hash/signature/manifest/compatibility verification. | Admits or rejects candidate bundles. |
| `wdc_ota` | Bounded slot streaming/range reads and two-record metadata journal. | Owns flash I/O and body-before-marker persistence mechanics. |
| `wdc_activation` | Trial boot attribution, host probation, confirmation, rejection, and fallback state machine. | Decides which slot may run and whether a trial becomes durable. |
| `wdc_app_slots` | Fixed artifact validation, inactive staging, boot gates, fallback, and recovery. | Preserves the last confirmed application and returns decisions without entering application code. |
| `wdc_app` | Legacy and managed slot bridges plus manifest-derived runtime config. | Enters the runtime only after the canonical HP3 slot/prelaunch gate. |
| `wdc_net` | Native-mediated network status/MQTT/HTTP intents. | Prevents raw network authority in WASM. |
| `wdc_http` | HP5 host-private Wi-Fi/TLS/HTTPS ingress, fixed parsers/routes, common-Wasm request dispatch, paired response, and protected administration transport bridge. | Keeps credentials/sockets/listeners native, isolates the admin reserve, and reuses HP4 without creating another authority. |
| `wdc_security` | Dev/production policy, preflight, anti-rollback floor, verifier policy. | Production admission boundary. |
| `wdc_diag` | Diagnostic ring, reset/fault breadcrumbs, status summaries. | Observability for rollback/fault analysis. |
| `wdc_elf` | Opaque adapter over the exact pinned ELF loader. | Relocates only bytes that already passed independent admission. |
| `wdc_extension` | Raw ELF/metadata inspection, descriptor validation, fixed registry sealing, lifecycle supervision, event/effect bridging, bounded completion, health, and teardown. | Prevents pre-admission execution, alternate dispatch, ambiguous completion ownership, illegal transitions, and unconfirmed post-start cleanup. |

## Main application

`firmware/main/app_main.c` calls into `shell_main.c`.

The shell startup path initializes diagnostics, profile, safe defaults, event queue, metadata, app/runtime path, and no-bundle/fault behavior.

## HP4 administration boundary

HP4.0 froze the
[`PULSE-ESP32-009`](../../specs/PULSE-ESP32-009-protected-administration.json)
model for host-private inputs, fixed storage, HP1 control sources, HP2
compatibility binding, HP3 slot/journal binding, volatile modes, and the
serial-first transport seam. HP4.1 implements the bounded `wdc_admin` core and
incremental serial normalizer under
[`PULSE-ESP32-010`](../../specs/PULSE-ESP32-010-protected-administration-core.json).
Its default command policy admits only status and its verifier fails closed;
HP4.2 implements update execution, HP4.3 implements host-only recovery, and
[`PULSE-ESP32-013`](../../specs/PULSE-ESP32-013-administration-adversarial-seal.json)
seals the complete path with 3,523 new and 41 inherited native cases. HP4.4
also rejects command-sequence exhaustion before acceptance mutation. None of
these milestones adds
anything to `wdc_abi`, either guest SDK, or the native-extension ABI.

## HP5 network ingress boundary

[`PULSE-ESP32-014`](../../specs/PULSE-ESP32-014-host-network-mediator.json)
binds `wdc_http` to the sealed HP1–HP4 authorities. `wdc_http` may depend on
`wdc_admin` because it is host-private orchestration. `wdc_net` cannot: it
remains an application-facing intent mediator and exposes only the generic
paired-response hook used during one active HTTP event. The separate component
edge is a tested security invariant, not only a build organization choice.

## Important headers

| Header | Contains |
|---|---|
| `wdc_abi.h` | ABI version, constants, opcodes, status codes, slot states. |
| `wdc_bundle.h` | Bundle container structs, verification policy/result, metadata. |
| `wdc_activation.h` | Activation policy and decisions. |
| `wdc_app_slots.h` | Fixed HP3 artifact, staging, boot, probation, fallback, and recovery APIs. |
| `wdc_safety.h` | Safety states, fault kinds, safety status. |
| `wdc_security.h` | Production/development policy and preflight contracts. |
| `wdc_profile.h` | Resource mapping structs and lookup APIs. |
| `wdc_runtime.h` | Runtime config/report and lifecycle APIs. |
| `wdc_control.h` | Host-private priority, queue, ISR, reserve, heap-snapshot, and admission contracts. |
| `wdc_admin.h` | Host-private authenticated-entry, request, terminal, audit, session, authorizer, verifier, and bounded serial contracts. |
| `wdc_host_identity.h` | Fixed fingerprint format, application requirements, prelaunch result, and running-fingerprint APIs. |
| `wdc_net.h` | Network state and mediated host-call handlers. |
| `wdc_http.h` / `wdc_http_service.h` / `wdc_http_platform.h` | Host-private HP5 service, parser/routes, fixed listener configuration, and ESP-IDF adapter APIs. |
| `wdc_extension.h` / `wdc_extension_bridge.h` | Private host admission, candidate, sealed-registry, lifecycle, event/effect, completion, health, and reset-required authority. |
| `pulse_extension.h` | Sole experimental public native-extension ABI authority. |

The HP4.0 authenticated-entry, request, terminal, and audit layouts are now
implemented exactly in host-private `wdc_admin.h`; they remain absent from all
guest and native-extension headers.

## Component dependency direction

Preferred dependency direction:

```text
build-derived host identity validates compatibility
  -> control resource authority establishes live solvency
  -> security/profile/bundle/activation decide eligibility
  -> app-slot authority preserves and selects verified flash bytes
  -> app derives runtime/capability config
  -> runtime invokes guest
  -> ABI receives guest requests
  -> safety/caps/profile authorize
  -> HAL/net execute native operations
  -> diag/events record outcomes

host-private HTTP ingress
  -> fixed parser and exact route
  -> common runtime event or existing HP4 administration authority
  -> bounded host-owned response
```

Avoid adding dependencies that let low-level execution layers bypass safety/capability checks.

## Adding a new component

A new component should document:

1. what it owns,
2. what it must never own,
3. which safety invariant it supports,
4. which tests prove negative paths,
5. whether it is active in production or host-test only.
