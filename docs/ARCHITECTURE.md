# Architecture

> **Direction note:** This document describes the implemented R0-R9 prototype.
> The post-IF7 [native target refinement addendum](../specs/PULSE-ESP32-003-native-target-refinement-addendum.md)
> the [HP0 boundary freeze](HP0_EVIDENCE_RECONCILIATION.md), and
> [HP1 resource authority](HP1_HOST_KERNEL_RESOURCE_AUTHORITY.md), and
> [HP2 build coherence](HP2_HOST_BUILD_COHERENCE.md), and
> [HP3 application slots](HP3_APPLICATION_SLOTS_AND_FALLBACK.md), the
> [HP4.0 protected-administration contract](HP4_0_PROTECTED_ADMINISTRATION_CONTRACT.md), and the
> [HP4.1 protected-administration core](HP4_1_PROTECTED_ADMINISTRATION_CORE.md), and the
> [HP4.2 exclusive update transaction](HP4_2_EXCLUSIVE_UPDATE_TRANSACTION.md),
> [HP4.3 host-only recovery](HP4_3_HOST_ONLY_RECOVERY.md), and the
> [HP4.4 administration adversarial seal](HP4_4_ADMINISTRATION_ADVERSARIAL_SEAL.md), and the
> [HP5 host network mediator](HP5_HOST_NETWORK_MEDIATOR.md), and the
> [HP5.5 physical audit implementation](HP5_5_NETWORK_ADMIN_PHYSICAL_SEAL.md)
> establish the
> current direction: durable mechanical services and recovery remain host-owned,
> common Pulse/Wasm carries portable behavior, and native ELF is scarce trusted
> target refinement rather than the default capability container.

## Purpose

The Pulse ESP32 host is a native ESP-IDF supervisor that runs replaceable Wasm application logic behind a narrow, audited contract.

The guest does not own the device. It expresses behavior and requests capabilities. The native host remains responsible for physical correctness, credentials, interrupts, storage, recovery, and policy.

```text
native shell       durable trust root and host realization
Wasm guest         replaceable application behavior
ABI                versioned boundary
bundle manifest    requested authority
device profile     verified physical and policy truth
```

The repository still uses `wdc_*` implementation names inherited from the original prototype.

## Boot and activation flow

```text
ESP-IDF bootloader
  -> native shell starts
  -> build-derived running-host fingerprint validated
  -> reset and diagnostic state recorded
  -> host control profile and fixed reserves validated
  -> device profile loaded and validated
  -> safe output defaults applied
  -> journaled A/B application metadata read
  -> confirmed or trial slot selected; trial boot attribution persisted
  -> fixed application artifact and inner bundle verified from flash
  -> artifact target/ABI/capability requirements checked against fingerprint
  -> total-free, largest-block, and update-transition admission passes
  -> runtime limits installed
  -> capability authorizer installed
  -> WAMR loads the verified guest
  -> lifecycle exports called
  -> queued events delivered
  -> every guest effect validated before native execution
```

Native firmware OTA and Pulse application replacement are separate:

```text
native firmware OTA
  rare; changes supervisor, runtime, drivers, and ABI implementation

Pulse application replacement
  frequent; changes application behavior
  uses bounded Wasm A/B slots, host-owned probation, confirmation, and rollback
```

## Guest boundary

The guest imports a small module named `wdc`:

```text
wdc_log
wdc_millis
wdc_random
wdc_yield
wdc_host_call
```

It exports lifecycle functions:

```text
wdc_module_init
wdc_module_on_event
wdc_module_health
wdc_module_shutdown
```

Non-trivial operations use the dispatcher:

```text
wdc_host_call(opcode, request_cbor, response_buffer)
```

The dispatcher validates:

1. opcode support;
2. guest pointer and range safety;
3. request and response limits;
4. deterministic CBOR shape;
5. installed fail-closed authorization;
6. current safety state;
7. manifest capability;
8. device-profile resource and policy;
9. operation-specific rate or payload limits;
10. native execution result.

## Event model

The embedded host must own interrupt and device-event mechanics.

```text
native ISR
  -> fixed allocation-free capture
  -> direct notification of a host-owned task
  -> fixed-priority bounded host lane
  -> event envelope
  -> guest event handler
```

The host must not call reentrantly from an ISR into Wasm. HP1 makes this
mechanical: the ISR record is fixed, its ring is bounded, overflow latches
recovery, and only the host task can convert captured state into later work.
Queueing provides a stable scheduling and memory boundary and allows the host
to account for drops, rate limits, and faults.

Long-running or asynchronous device operations should use explicit request/completion events or another bounded continuation contract rather than exposing native handles or callbacks to the guest.

## Component layers

```text
main/             boot and shell orchestration
wdc_security      development/production security policy
wdc_ota           slot and metadata storage abstraction
wdc_bundle        bundle parse, hash, signature, and manifest verification
wdc_activation    A/B candidate, probation, confirmation, and rollback
wdc_app_slots      inactive staging, stored-artifact checks, boot choice, and recovery
wdc_app           legacy and managed slot boot bridges into the runtime
wdc_runtime       WAMR and host-stub guest lifecycle
wdc_abi           dispatcher, CBOR, memory validation
wdc_control       ISR capture, fixed priorities, bounded work/completion, reserves, admission
wdc_admin         fixed administration core plus exclusive inactive-slot update transaction
wdc_host_identity build-derived fingerprint validation and fail-closed prelaunch gate
wdc_caps          capability parsing, authorization, and audit
wdc_safety        safety states and fault-stop behavior
wdc_profile       logical resource and physical profile mapping
wdc_hal           GPIO safe defaults and native hardware bridge
wdc_net           native-mediated network intent
wdc_events        bounded event encoding and queue
wdc_diag          reset/fault breadcrumbs and diagnostic ring
wdc_elf           pinned loader adapter; relocation is not admission
wdc_extension     admission, lifecycle, sealed operation bridge, and bounded completion
```

The experimental native-extension path is deliberately separate from the Wasm
ABI. Raw target ELF bytes pass bounded structural and compatibility inspection
before `wdc_elf` may relocate them. After relocation, `wdc_extension` calls
only the pure descriptor entry, validates all addresses and identities, and
seals the complete catalog before any lifecycle call. HX3 then owns ordered
initialization/start, reverse unwind, health probation, bounded quiescence,
deinitialization, and clean unload. The extension owns its one declared static
task and bounded queue; the host owns ordering, the absolute deadline, and the
reset-required latch. HX4 connects that task to the existing `wdc_events` queue,
`wdc_runtime` handler, and `wdc_abi` dispatcher, then resolves one numeric
operation through the sealed registry into one bounded completion slot. The
dispatcher remains fail closed and no target selector enters the common Wasm.
Neither the host smoke nor reproducible target builds are target runtime
evidence. HX4.5 additionally distinguishes pending, timed-out, and canceled
completion ownership and executes the full negative corpus without adding a
dispatcher. See [HX4 event/effect round trip](HX4_EXTENSION_EVENT_EFFECT.md)
and the [HX4.5 adversarial seal](HX4_5_EXTENSION_ADVERSARIAL.md).

HX5b and HP0 now bind this path to passing retained physical reports for the
named AITRIP S3 and XIAO C6 boards. That closes the single-refinement pressure
proof, not the platform. The next host model separates safety/recovery,
administration, application services, and native refinement even when all four
share one firmware image. An application cannot own listeners, credentials,
slot writes, boot choice, confirmation, watchdog policy, or recovery.

HP1 implements that lower host split in `wdc_control`. Safety/recovery,
administration, network maintenance, capability dispatch, and application work
have fixed descending priorities and independently reserved static slots.
Admission reserves stacks, queue/ticket state, metadata, administration,
verification, and recovery before application launch, then checks normal,
quiesce-transition, and exclusive-update peaks plus the largest contiguous
internal block. The C6 no-PSRAM profile defines portable minimum behavior. S3
PSRAM is an explicit target optimization and never holds control authority.

HP2 keeps compatibility policy distinct from firmware realization. A named
board describes physical resources; a host profile describes capabilities and
HP1 limits; normalized application intent describes target-neutral needs; a
plan selects a supported realization; an exact lock records the resolved build;
and a compact running fingerprint reports both exact lock identity and the
semantic compatibility surface. `wdc_host_identity` validates that record and
delegates live memory admission to `wdc_control` before application entry.
Matching intent yields `APP_ONLY_DEPLOYMENT`; a missing or incompatible running
surface yields `HOST_BUILD_PLAN_REQUIRED`. Neither path introduces ESP-IDF,
sdkconfig, partition, PSRAM, or loader concepts into Pulse core.

HP3 uses that compatibility surface without turning host firmware into the
application artifact. `wdc_app_slots` accepts a fixed header plus the existing
signed bundle only into the inactive partition. It persists trial boot
attribution before entry, rereads and verifies the stored artifact, applies the
HP2 static and HP1 live gates, and returns run, fallback-reboot, or recovery.
Only host-observed readiness, health, administration responsiveness, resource
floors, and stable time can confirm a trial; the last confirmed bytes remain
untouched until then. Exhaustive torn-write and physical power-loss evidence
belong to HP3.5.

HP4.0 froze the orchestration layer above those existing authorities. HP4.1
implements its allocation-free host-native core in `wdc_admin`: raw serial
input is incrementally normalized, then a replaceable host-private authorizer
produces a fixed authenticated-entry record. Replay, deadline, rate, and HP1
capacity admission precede accepted-command ownership, and accepted work keeps
exactly one terminal response until it is consumed.
The volatile mode machine is:

```text
NORMAL
  -> QUIESCE
  -> UPDATE or RECOVERY
  -> REBOOT_HANDOFF
  -> reboot through HP3 selection
```

There is no direct `NORMAL -> UPDATE` edge and no durable HP4 state competing
with the HP3 journal. C6 update requires the guest and native refinements to be
positively quiesced and unloaded before the existing exclusive-update budget
is admitted. HP4.1 implements the authority, replay, rate, HP1 ownership,
terminal, serial-normalization, and fixed audit mechanics. HP4.2 adds the first
exclusive transaction: it positively unloads guest/refinement work, applies
the exact C6 HP1 gate, streams and fully verifies only the inactive HP3 slot,
and durably reads back `TRIAL` before reboot handoff. Recovery transitions
are implemented by HP4.3: HP3 no-viable evidence or an authorized unload enters
application-free recovery; candidate failures return to recovery; and reboot
requires a read-only complete HP3/HP2 viability proof. Serial is the first transport class; HP5 may add authenticated
external entry only behind the same identity, replay, transition, audit, and
terminal contracts. HP4.4 adversarially seals those combined paths, including
every safe stored-artifact prefix and both journal records, and rejects command
sequence exhaustion before acceptance mutation.

HP5 adds the transport without changing that authority. `wdc_http` owns two
separately bounded HTTPS listeners, fixed parsers, and exact routes. A matched
application request becomes `WDC_EVENT_HTTP_REQUEST` on the common Wasm event
path and may consume one first-response-wins `WDC_OP_HTTP_RESPOND`. Fixed
administration routes supply bounded bytes and a host-observed channel binding
to HP4's authenticated external entry, then reuse the existing session,
replay, deadline, HP1 command, terminal, audit, update, recovery, and HP3 reboot
paths. `wdc_net` remains application-facing and cannot depend on `wdc_admin`.
HP5.5 now owns an exact physical execution harness around this adapter: it
stages external test credentials, runs a real common-Wasm response and the
existing HP4/HP3 update/recovery path, and accepts evidence only from both new
target-bound named-board locks. The harness and synthetic evaluator contracts
are not themselves a target or physical result; the aggregate remains pending
until two distinct physical reports pass.

See [Component map](reference/COMPONENT_MAP.md) and [Codebase map](CODEBASE_MAP.md) for source locations.

## Manifest authority versus device truth

The bundle manifest requests logical authority:

```json
{
  "capabilities": [
    {
      "id": 1,
      "kind": "gpio",
      "resource": "relay_1",
      "ops": ["read", "write"]
    }
  ]
}
```

The verified device profile maps that logical resource to hardware and policy:

```json
{
  "resources": {
    "gpio": {
      "relay_1": {
        "pin": 12,
        "mode": "output",
        "safe_value": false
      }
    }
  }
}
```

The guest never receives authority over raw pin numbers, interrupts, Wi-Fi credentials, TLS material, sockets, ESP-IDF handles, flash partitions, or rollback state.

## Network model

The guest requests intent-level operations such as MQTT publish/subscribe or HTTP request. The native mediator owns credentials, TLS, connection state, and transport objects.

Policy can constrain:

- logical network resource;
- topic or URL prefix;
- allowed HTTP methods;
- payload size;
- operation rate;
- current connectivity state.

See [Network mediation](NETWORK_MEDIATION.md).

## Why this is a Pulse boundary witness

The host can realize only the capabilities it actually has. An ESP32 host does not need a JavaScript fallback or a fake universal platform API.

The architectural test is whether Pulse application semantics can remain stable while:

- memory is bounded;
- the host owns event scheduling;
- hardware operations require authorization;
- networking is optional and native-mediated;
- failures must force safe physical state;
- deployment may be a signed bundle rather than a server process.

That containment is the point of the experiment.
