# Trust boundary and safety model

> **Direction note:** This document records the implemented prototype's
> adversarial/faulty-guest posture. The post-IF7
> [native target refinement addendum](../specs/PULSE-ESP32-003-native-target-refinement-addendum.md)
> distinguishes browser-style adversarial isolation from the ESP32 provider's
> owner-trusted deployment and native-refinement model. The fail-closed safety,
> validation, and rollback mechanisms remain relevant for faulty candidates.

## Core claim

A verified guest may request actions, but only the native supervisor decides whether an action is authorized, safe, and executable.

The guest is replaceable and treated as faulty by design.

## Trust model

| Component | Trust | Responsibility |
|---|---|---|
| ESP32 ROM and bootloader | Trusted foundation | Boot chain. |
| Native Pulse host | Trusted supervisor | Validation, policy, safety, drivers, recovery. |
| Exact host build lock | Trusted release input | Reproduces one coherent host realization; replay performs no dependency selection. |
| Running-host fingerprint | Build-derived trusted record | Reports exact build identity and semantic compatibility; CRC detects corruption but is not attestation. |
| Application-slot metadata journal | Host-owned persistent authority | Selects trial/confirmed bytes, records boot attribution, and preserves fallback; one valid record survives one corrupt peer. |
| Raw administrative transport input | Untrusted input | Supplies bounded bytes and transport observations only; cannot assert principal, priority, slot, verification, or boot authority. |
| Authenticated-entry record | Host-issued bounded authority | Carries authorizer-established identity, privileges, expiry, and channel binding for one fixed HP4 session; contains no credential or key. |
| Verified device profile | Trusted physical truth | Maps logical resources to pins and policy. |
| Bundle manifest before verification | Untrusted input | Requests authority and limits. |
| Wasm guest | Untrusted/faulty | Replaceable application behavior. |
| Provider-selected native ELF extension | Owner-trusted but fault-prone | Target refinement admitted by fixed metadata, import, relocation, budget, descriptor, and lifecycle policy. Shares the firmware address space; not adversarial isolation. |
| Remote messages and commands | Untrusted input | Must be decoded and policy-checked. |
| Guest-owned persisted state | Semi-trusted | May be corrupt or adversarially influenced. |

## Safety states

```text
UNINITIALIZED
BOOT_SAFE
NO_BUNDLE
APP_RUNNING
APP_FAULT_STOPPED
```

Only `APP_RUNNING` permits guest-originated physical writes. Boot, no-bundle, and fault states force outputs to profile-defined safe values and deny later writes.

## Host-call safety pipeline

```text
Wasm host call
  -> validate guest memory range
  -> validate request and response lengths
  -> validate deterministic encoding
  -> verify opcode support
  -> require an authorizer unless the call is explicitly safe
  -> verify safety state
  -> verify manifest capability
  -> resolve device-profile resource and policy
  -> enforce payload and rate limits
  -> execute native operation
  -> record result and diagnostics
```

Only narrow status queries may bypass capability authorization. State-changing, physical, configuration, storage, and network operations must fail closed when authorization is missing.

## Control resource authority

HP1 reserves control authority before an application is admitted. A fixed ISR
record may only enter an allocation-free ring and directly notify a bound
host-owned task. Safety/recovery, administration, network maintenance,
capability dispatch, and application work have descending fixed priorities and
independent bounded slots. Application work cannot select a class, priority, or
unbounded allocation and cannot consume a higher class's completion capacity.

Admission checks the normal application peak, quiesce/update transition, and
exclusive update peak against total internal free memory. It separately checks
the largest contiguous block required by application and update phases. C6
requires all application behavior to fit without PSRAM. S3 PSRAM is explicit,
non-portable optimization and never backs the control/recovery reserve. See
[HP1 resource authority](HP1_HOST_KERNEL_RESOURCE_AUTHORITY.md).

## Build identity and prelaunch boundary

HP2 separates application compatibility from host build realization. The
application supplies normalized target, ABI, capability, placement, and bounded
resource requirements. It cannot select an ESP-IDF lane, component version,
sdkconfig, partition, board wiring, loader, task priority, or HP1 reserve.

Before application entry, `wdc_host_identity` validates the fixed running
fingerprint, checks semantic compatibility, and calls HP1 live resource
admission. Any malformed record, target/ABI mismatch, missing capability,
unavailable target optimization, or insufficient memory fails closed with
`application_code_launched=0`. The fingerprint's CRC is corruption detection;
secure boot and future signing/attestation policy remain separate. See
[HP2 build coherence](HP2_HOST_BUILD_COHERENCE.md).

## Logical resources

The guest addresses logical resources such as `relay_1`, never raw GPIO numbers.

A request is denied when:

- the capability is absent;
- the operation is not listed;
- the resource is missing from the device profile;
- the resource kind does not match the opcode;
- the safety state is not running;
- payload or rate limits are exceeded;
- host policy rejects the request.

## Fault-stop behavior

The host should stop the guest and force safe outputs after:

- runtime traps;
- lifecycle failure during initialization, probation, or health checks;
- contract violations;
- unsafe or invalid state transitions;
- native I/O errors that make continued operation unsafe;
- watchdog/reset behavior while a candidate is unconfirmed.

A persistent breadcrumb should record enough context to diagnose the stop without exposing secrets.

## Native-extension lifecycle boundary

An admitted native extension is owner-trusted but fault-prone and shares the
firmware address space. The host owns lifecycle order, health interpretation,
the absolute quiescence deadline, and reset policy. The extension owns its
declared static task and queue. After `start` was entered, the host permits
clean deinitialization and unload only after the extension reports `QUIESCED`
with no pending work and FreeRTOS confirms that its static task was reaped.

The host does not force-delete an arbitrary extension task as normal cleanup.
An unhealthy candidate, expired or missed deadline, failed teardown, or
uncertain task state latches `RESET_REQUIRED`; reset remains the authoritative
hard boundary. See [HX3 lifecycle evidence](HX3_EXTENSION_LIFECYCLE.md).

## Application replacement safety

Transferred bytes are not active merely because streaming succeeded.

```text
EMPTY
  -> inactive slot streamed and checked
  -> STAGED
  -> VERIFIED
  -> TRIAL with boot attempt persisted
  -> host-observed probation
  -> CONFIRMED and promoted to last-good
```

An unconfirmed trial that faults, misses readiness, violates resource floors, or
resets is marked `REJECTED`; the last confirmed slot is selected for a reboot.
The guest has no confirmation API. If neither slot is viable, the host enters
explicit recovery. Host-firmware OTA, exhaustive torn-write injection, and
physical power-loss qualification are not implied by this application-slot
contract. See [HP3 application slots](HP3_APPLICATION_SLOTS_AND_FALLBACK.md).

## Protected administration boundary

HP4.0 freezes, and HP4.1 implements the host-native core of, a host-private
administrative plane with no application ABI, event/effect, native-refinement,
or application-route entry. A replaceable authorizer, not the transport,
issues the fixed authenticated-entry record.
One session and one accepted command use strictly consecutive replay sequence;
capacity admission, replay reservation, and command ownership commit together.
Every accepted command retains exactly one terminal result.

The volatile `NORMAL`, `QUIESCE`, `UPDATE`, `RECOVERY`, and
`REBOOT_HANDOFF` machine cannot shadow HP3. The active guest and native
refinements must positively quiesce and unload before `UPDATE`. Staging may
touch only the inactive HP3 slot, and reboot returns to HP3 boot selection.
Authentication, replay, timeout, quiesce, staging, verification, slot
transition, recovery, and reboot events use a fixed bounded audit record that
contains no credentials, authenticators, keys, or artifact bytes.

HP4.1 is allocation-free firmware source with a bounded serial normalizer and
fixed audit ring, but it is not a UART integration, production authentication
or cryptography claim, update transaction, recovery implementation, target
execution, or physical result. See the
[HP4.0 protected-administration contract](HP4_0_PROTECTED_ADMINISTRATION_CONTRACT.md)
and [HP4.1 protected-administration core](HP4_1_PROTECTED_ADMINISTRATION_CORE.md).

## HTTP ingress boundary

HP5 implements host-owned station Wi-Fi and two independently bounded HTTPS
listener sources in `wdc_http`. The application listener accepts only exact
registered `GET` or `POST` routes below `/pulse/v1/app/`, dispatches one
bounded event through the common Wasm handler, and admits at most one matching
paired response. The application cannot register or shadow the fixed
`/pulse/v1/admin/` namespace.

The administration listener is transport only. It supplies bounded bytes,
connection/deadline observations, and a host-observed TLS channel binding to
HP4's replaceable authenticated-entry seam. It cannot assert identity, advance
replay, allocate a command, select a slot, verify an artifact, write a journal,
cancel accepted work, or choose a boot target. Malformed, oversized, slow,
disconnected, unauthorized, stale, replayed, and saturated requests reject
before command-acceptance mutation.

Application and administration listeners have separate ports, control ports,
server tasks, parsers, and socket caps. Response loss is counted but cannot
roll back an application or cancel an accepted command. `wdc_net` remains
independent of `wdc_admin`; the host-private `wdc_http` component alone joins
network ingress to the sealed HP4 authority. See the
[HP5 host network mediator](HP5_HOST_NETWORK_MEDIATOR.md).

## Production policy boundary

Production mode must reject development allowances. The current scaffold includes policy contracts for:

- development-signature rejection;
- required verifier callback;
- trusted key ID;
- anti-rollback floor;
- secure-boot and flash-encryption preflight;
- provisioning-state checks.

A deployment-grade signature implementation is still required before production use.

## Invariants

1. No raw ESP-IDF pointer crosses into Wasm.
2. No guest controls a physical pin number directly.
3. No effectful operation runs without authorization.
4. Manifest claims are never authority without device-profile validation.
5. Credentials, TLS state, interrupts, and transport handles remain native.
6. Boot, no-bundle, fault, and failed-update paths force safe outputs.
7. Candidate confirmation is controlled by the host, not the guest.
8. Unsupported or malformed requests fail closed.
9. Diagnostics must not expose credentials or secret payloads.
10. Hardware features are added only when they can be expressed as bounded capabilities.
11. No native extension constructor, loader entry, lifecycle function, or registration callback executes before raw-byte admission succeeds.
12. Relocation is not lifecycle admission; the descriptor and complete numeric catalog are validated and sealed before `init`.
13. No application, event, effect, native refinement, or transport callback can invoke or shadow an administrative transition.
14. No update reaches `REBOOT_HANDOFF` before complete verification and a durable HP3 `TRIAL` journal commit.
15. Reset during HP4 quiesce/update discards volatile HP4 state and returns durable authority to HP3.
16. An application route cannot register in, shadow, or consume the independent administration listener reserve.
17. Network response loss cannot roll back application state or cancel an accepted administrative command.
