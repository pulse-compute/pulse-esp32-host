# Pulse ESP32 Native Target Refinement Addendum

**Document:** PULSE-ESP32-003  
**Version:** Draft v0.1  
**Status:** Proposed architectural direction; implementation remains paused  
**Prepared:** 2026-08-06  
**Baseline:** IF7 sealed snapshot, SHA-256 `a6e2812327cc924081d17441053708e0e080b4923681b17a08358b9f145cbaa1`  
**Related documents:** WDC-ESP32S3-001, WDC-ESP32S3-002, WDC-ABI-001, WDC-BUNDLE-001, ADR 0009

## 1. Purpose

This addendum captures the architectural refinement discovered after completing
the IF0-IF7 ESP-IDF family build matrix.

The earlier prototype placed GPIO, networking, BLE, storage, and other native
capabilities directly behind an expanding firmware-owned host ABI. That work
proved useful safety, event, capability, bundle, and rollback mechanics, but it
also made the native host the location where every future device feature would
accumulate.

The refined direction inverts that relationship:

```text
stable Pulse device host
  + versioned native-extension spine
  + provider-selected target refinements
  + portable Pulse application behavior
```

The host becomes smaller and changes rarely. GPIO, BLE, network orchestration,
LoRa, sensors, control systems, specialized model runtimes, and application
specific native libraries become isolated provider realizations added one at a
time.

This addendum freezes the direction and proof boundaries. It does not authorize
implementation, select a final ELF loader version, freeze a native-extension
ABI, or claim runtime or hardware support.

## 2. Relationship to the existing prototype

### 2.1 What remains valid

The following implemented or specified properties remain useful and are not
discarded:

- the exact ESP-IDF lane and explicit family realization matrix;
- the WAMR-backed Pulse/Wasm execution path;
- queued native-event delivery rather than ISR-to-Wasm reentrancy;
- logical resources and board mappings;
- typed, bounded event and effect frames;
- pointer, length, encoding, and runtime-limit validation;
- safe output defaults and fault-stop behavior;
- host-observed candidate health;
- A/B Pulse application activation, confirmation, and rollback;
- reproducibility evidence and fail-closed build classification; and
- explicit separation between build mapping and hardware qualification.

These mechanisms continue to protect correctness, availability, physical safe
state, and recovery from broken deployments.

### 2.2 What this addendum refines

This addendum supersedes the following future-direction assumptions in
WDC-ESP32S3-001 and WDC-ESP32S3-002:

1. No hardware or protocol capability needs to become a permanent component or
   opcode inside the base firmware merely because one provider exposes it.
2. Native networking does not need to be a mandatory host subsystem. It may be
   composed as an optional provider refinement, subject to a separate minimal
   recovery/deployment channel.
3. Wasm is not primarily an adversarial security boundary on an owner-operated
   ESP32 device. It is the portable application grammar and orchestration
   boundary.
4. A trusted Pulse deployment may eventually contain target-native ELF
   refinements paired with guest-visible bindings.
5. Remote native firmware OTA is not an immediate requirement. Physical
   firmware updates are acceptable while the stable host is still experimental.
6. Pulse application deployment and rollback are the immediate update-system
   priority.

The existing implementation remains a prototype baseline. This addendum does
not require opportunistic refactoring of `wdc_hal`, `wdc_net`, the dispatcher,
or the v1 bundle format before a new proof plan is accepted.

## 3. Refined architectural thesis

Pulse is not defined by one universal host implementation. It defines a stable
relationship between portable behavior and a sovereign host:

```text
sovereign host
    <-> explicit events, effects, and capabilities
portable Pulse behavior
```

That relationship survives very different host postures:

| Environment | Primary value of Wasm | Capability posture | Provider responsibility |
|---|---|---|---|
| Traditional server or edge | Deployable compute | Conventional host realization | Preserve familiar application behavior across deployment targets |
| Browser with Filament | Isolation and deterministic hosted behavior | Restrict effects to host-granted authority | Hold application boundaries while exposing useful host effects |
| ESP32 | Portable grammar and replaceable behavior | Enrich behavior through physical target refinement | Encapsulate drivers, tasks, radios, and hardware-specific code |

The shapes are intentionally not equivalent. The invariant is that the host is
sovereign, capabilities remain visible, and provider realization does not leak
throughout portable application logic.

For ESP32 specifically:

```text
Wasm/Pulse       portable behavior and event reasoning
native ELF       trusted target refinement and low-level realization
device profile   board-specific resource binding
provider         selection, composition, build, and evidence
host             stable lifecycle, bridge, supervision, and recovery
```

## 4. Goals

The refined ESP32 direction aims to:

1. Keep the base firmware small, stable, and infrequently updated.
2. Preserve Pulse event/effect semantics across ESP32-family realizations.
3. Allow a provider package to carry a guest-facing binding and one or more
   target-native realizations.
4. Keep low-level ESP-IDF, FreeRTOS, ISR, driver, radio, and buffer mechanics
   locally encapsulated in native refinements.
5. Build one target-specific deployment from one logical Pulse application
   without target detection in handlers.
6. Add capabilities independently, beginning with one GPIO vertical slice.
7. Make capability compatibility and resource conflicts fail before deployment.
8. Activate the Wasm application, native refinements, bindings, and board map as
   one atomic candidate.
9. Roll back the entire candidate after initialization failure, health failure,
   trap, watchdog reset, or unconfirmed restart.
10. Focus remote update work on Pulse application bundles rather than native
    firmware images.

## 5. Non-goals and explicit deferrals

This addendum does not currently pursue:

- remote ESP-IDF firmware OTA;
- bootloader or partition-table OTA;
- a general untrusted native-plugin marketplace;
- adversarial isolation of native ELF code from the firmware address space;
- live replacement of an active extension graph;
- arbitrary dynamic linking between independently versioned native modules;
- a comprehensive GPIO, BLE, network, LoRa, sensor, or storage API catalog;
- hard real-time control loops inside Wasm;
- direct calls from an ISR into Wasm;
- a promise that one binary runs unchanged on every ESP32-family target;
- hidden provider fallback or runtime target detection;
- a production fleet-management system;
- production signature-policy selection; or
- new runtime or hardware claims based only on IF7 compile evidence.

Physical firmware installation remains the accepted update path for the host.
Firmware OTA may be designed later without becoming a prerequisite for the
native-refinement proof.

## 6. Target architecture

### 6.1 Stable host kernel

The target base host should contain only durable mechanisms:

```text
boot and reset diagnostics
Wasm runtime
Pulse event/effect frame bridge
native-extension loader and registry
extension lifecycle supervision
bounded queues and invocation accounting
safe-state and watchdog integration
application slot selection and rollback
minimal deployment/recovery transport
```

The host should not contain permanent semantic knowledge of every future
peripheral or protocol. It understands how a native extension joins the
application, not what every extension means.

### 6.2 Native target refinements

A target refinement may own low-level mechanics such as:

- ESP-IDF driver calls;
- GPIO interrupts and debounce;
- DMA and peripheral registers;
- FreeRTOS tasks, queues, and core affinity;
- I2C, SPI, UART, and external device drivers;
- BLE GAP/GATT lifecycle;
- Wi-Fi, lwIP, TLS, HTTP, and webhook orchestration;
- LoRa radio and mesh behavior;
- DSP, control, inference, or other optimized native computation; and
- domain-specific state machines best kept close to the device.

The extension converts those mechanics into named Pulse events and operations.

### 6.3 Board profiles

Board-specific facts remain separate from both portable behavior and capability
implementation:

```text
application behavior      shared when contracts are satisfied
capability realization    selected for the target/SoC
board binding             pins, buses, radios, limits, and physical resources
```

Changing a pin should change the board binding. Changing the SoC may select a
different native refinement. Neither should require target checks throughout
the Pulse application.

## 7. Trust, safety, and encapsulation

### 7.1 ESP32 trust posture

The device owner controls the physical device and chooses the deployed Pulse
application. A verified deployment unit, including its native refinements, is
trusted to express the intended device behavior.

> For the ESP32 provider, the native-extension boundary is encapsulation and
> target refinement, not adversarial isolation.

Therefore:

- Wasm is not the primary security sandbox in this provider.
- Native ELF is not considered a lesser-trust plugin merely because it is
  loaded separately from firmware.
- The extension ABI exists for stable composition, encapsulation, lifecycle,
  diagnostics, and target compatibility.
- Capability declarations describe requirements, realizations, resources, and
  limits; they are not solely an adversarial permission system.

### 7.2 Fault posture remains fail-closed

Trusted code can still be wrong. The host must continue to treat a candidate as
fault-prone until it proves operable.

The host should retain protection against:

- corrupt or incomplete artifacts;
- target or ABI mismatch;
- invalid guest memory accesses;
- extension initialization failure;
- missing event or operation registrations;
- resource conflicts;
- unbounded execution or queue growth;
- traps, watchdog resets, and repeated restart loops;
- unsafe output state after application failure; and
- power loss during candidate staging or metadata updates.

This is recovery and physical-correctness containment, not a claim that native
code is isolated from the device it is intended to control.

## 8. Provider package and application grammar

A native-capability package may eventually contain:

```text
@vendor/pulse-environment-controller/
  author API
  Pulse lowering metadata
  guest binding or generated shim
  native/
    esp32s3.elf
    esp32c6.elf
  schemas/
  capability manifest
  conformance vectors
```

The author-facing application remains event-oriented:

```ts
app.on("environment:sample", evaluate)
app.on("control:unstable", dampen)
app.on("network:offline", enterLocalMode)
```

The native refinement may expose effects through a package-owned API or through
provider-bound context capabilities. The exact author API is deferred. The
required invariant is that target-specific mechanics do not leak into portable
handlers.

Event namespaces such as `gpio:*`, `ble:*`, `lora:*`, or `network:*` describe
capability families. A namespace is not automatically a wildcard authority
grant. The compiler/provider must resolve actual subscriptions and operations
into an explicit deployment manifest.

## 9. Candidate native-extension spine

The final ABI must be pressure-tested before it is frozen. The following shape
is illustrative and defines the minimum questions the proof must answer:

```c
typedef struct {
    uint32_t abi_version;
    const char *extension_id;
    const char *extension_version;
    const char *target;
    int (*init)(const pulse_extension_context_t *context);
    int (*start)(void);
    int (*invoke)(uint32_t operation, pulse_frame_t *frame);
    int (*stop)(uint32_t reason);
    void (*deinit)(void);
} pulse_native_extension_v1;
```

A host-services table may provide stable composition helpers:

```c
emit_event(...)
complete_effect(...)
monotonic_time(...)
log(...)
allocate_bounded(...)
release_bounded(...)
report_health(...)
```

The ABI is not intended to hide all ESP-IDF APIs from a trusted refinement. It
must instead answer:

1. How is compatibility checked before code executes?
2. How are extension identity and version recorded?
3. How are event namespaces and operations registered without collision?
4. How are board resources claimed and conflicts rejected?
5. How does an ISR or driver callback enqueue an event without entering Wasm?
6. How are operation completion, failure, cancellation, and timeout represented?
7. How is initialization reversed after partial failure?
8. How does the host know whether a candidate may be confirmed?
9. Which diagnostics survive a reset caused by a trial extension?
10. Which calls are stable host services and which may bind directly to the
    exact pinned ESP-IDF realization?

The first implementation must not expand this into a comprehensive peripheral
ABI. It should implement only what the first vertical slice requires.

## 10. ELF loading boundary

Espressif's `elf_loader` component is a candidate mechanism because it can load
and relocate target-native ELF objects and advertises multiple ESP32-family
targets. That fact is discovery evidence, not repository qualification.

Before adoption, an implementation pass must:

- select and pin one exact component version;
- prove compatibility with the exact `idf-5.4.4` lane;
- record the resolved component lock;
- identify executable-memory and PSRAM behavior for the S3 reference;
- define the exported-symbol and relocation model;
- measure firmware, RAM, PSRAM, and flash cost;
- test load, invoke, unload, partial-init failure, and repeated load cycles;
- classify C3, classic ESP32, and C6 results independently; and
- preserve IF7's distinction between compile mapping and device behavior.

The smallest proof may embed or physically flash a known ELF artifact. It does
not need remote delivery, A/B composite bundles, or a final package format.

## 11. Event and effect flow

### 11.1 Native ingress

```text
ISR or driver callback
  -> extension-owned bounded queue/task
  -> extension emits typed event
  -> host event bridge
  -> Pulse handler
```

The native extension owns debounce, DMA, driver callbacks, radio timing, and
other low-level details. Pulse receives a typed domain event.

### 11.2 Effect realization

```text
Pulse handler
  -> declared effect or package operation
  -> provider/extension registry
  -> native refinement
  -> physical or protocol action
  -> completion event/result
```

The extension may use GPIO, FreeRTOS, networking, or other ESP-IDF mechanisms
directly. The bridge preserves application grammar and observable completion
semantics.

### 11.3 Domain events over driver leakage

Provider packages should be free to expose domain-level semantics rather than
raw register operations:

```text
environment:sample
environment:variance.exceeded
environment:sensor.degraded
control:response.unstable
control:settled
lora:mesh.message
ble:characteristic.write
```

Raw capability families remain possible when they are the truthful level of
abstraction, but the framework should not force every application to reason in
pins, handles, and callbacks.

## 12. Provider toolchain responsibilities

The ESP32 provider should become a composition and evidence engine. Given a
Pulse application, selected target profile, and board binding, it should:

1. resolve required and optional capabilities;
2. select exact guest and native realizations;
3. reject missing or ambiguous realizations;
4. verify target, IDF, host ABI, and extension ABI compatibility;
5. detect pin, bus, peripheral, namespace, task, and memory conflicts;
6. link or package guest bindings;
7. build target-native extensions in the pinned lane;
8. emit a resolved realization manifest with hashes and provenance;
9. assemble one target-specific candidate artifact; and
10. produce evidence suitable for activation and migration review.

No portable handler should contain `if target == esp32s3`. The provider performs
selection from declared requirements and target facts.

A logical application version may have a common Wasm artifact and several
target realization bundles:

```text
environment-controller@1.4
  common application.wasm
  esp32s3 realization
  esp32c6 realization
  compatibility index
```

The device receives only the selected target artifact, not an unnecessary fat
bundle containing every family variant.

## 13. Pulse application deployment and rollback

### 13.1 Update classes

The near-term system has two deliberately different update paths:

| Update class | Contents | Initial transport |
|---|---|---|
| Native firmware | Boot, host kernel, WAMR, ELF loader, extension ABI implementation, partitions | Physical flashing |
| Pulse application deployment | Wasm behavior, guest bindings, native target refinements, board/resource manifest, optional assets or models | Host-owned application deployment path |

Native firmware OTA is deferred. Keeping the host small and stable reduces the
pressure to implement it prematurely.

### 13.2 Composite candidate

The future application slot should activate one complete unit:

```text
slot B
  application.wasm
  selected native extensions
  guest bindings
  resolved capability/resource manifest
  optional models/assets
  integrity and compatibility metadata
```

The existing WDC bundle v1 contains one Wasm payload. It must not be silently
overloaded to mean a composite deployment. A future container version or index
must be designed after the ELF/GPIO proof establishes the actual requirements.

### 13.3 Trial activation

```text
stage inactive slot
  -> verify every member and relationship
  -> persist candidate/trial state
  -> reboot or enter a clean activation epoch
  -> load native extensions
  -> instantiate Wasm
  -> register events and operations
  -> run host-observed health probes
  -> confirm complete slot
```

If reset occurs before confirmation, the host must count the failed trial and
select the previous confirmed slot without loading the failed candidate again
after its retry budget is exhausted.

The host must distinguish:

- mechanical failure: load, trap, timeout, reset, missing registration, or
  failed health probe; and
- logical failure: the application remains responsive but behaves incorrectly.

Automatic rollback addresses the first class. Remote rollback, richer
acceptance probes, or delayed confirmation are needed for the second.

### 13.4 Persistent state

An unconfirmed candidate must not irreversibly migrate shared state needed by
the last confirmed application. Initial implementations should prefer per-slot
state namespaces, backward-compatible schemas, or staged migration. A final
state-migration contract is deferred.

## 14. Communications and network orchestration

Communications should be decomposed rather than embedded as one permanent host
feature:

```text
physical connectivity
  -> native transport/provider refinements
  -> typed events and effects
```

Potential provider refinements include:

- Wi-Fi connection orchestration;
- HTTP route hosting;
- outbound webhooks;
- BLE/GATT;
- LoRa and mesh protocols; and
- application-specific telemetry or command transports.

Different TCP ports may be useful implementation detail, but ports are not the
ownership or isolation boundary.

One separation is required: application communications must not be the only
way to recover a broken application. A minimal host-owned or provider-pinned
deployment/recovery path must remain available independently, or the candidate
must roll back automatically without remote intervention.

Network orchestration should be implemented after simpler extensions have
proved lifecycle, events, effects, resources, and rollback. It introduces
shared radio, TLS, buffer, retry, and FreeRTOS scheduling pressure and should
not be allowed to define the first extension ABI by itself.

## 15. One-feature-at-a-time proof sequence

### NTR0 - Contract and loader discovery

Outcome:

- this addendum accepted or revised;
- exact ELF loader candidate selected;
- load/link/symbol/memory assumptions recorded;
- no capability expansion.

Gate:

- the pinned S3 lane builds the host with the exact loader dependency;
- ambient toolchains and moving component ranges are rejected;
- the report distinguishes compile evidence from device evidence.

### NTR1 - Minimal ELF lifecycle

Outcome:

- one known extension descriptor is loaded;
- compatibility is checked;
- `init`, `start`, `stop`, and `deinit` execute in order;
- partial initialization and duplicate identity fail cleanly.

Evidence:

- exact host, IDF, component-lock, and ELF hashes;
- size and memory deltas;
- serial or hardware log when device execution is performed;
- negative fixtures for mismatch and lifecycle failure.

### NTR2 - Synthetic event/effect bridge

Outcome:

- the extension emits one synthetic typed event;
- the existing Pulse event path invokes one handler;
- the handler invokes one registered extension operation;
- completion returns through a bounded result or event.

This proves composition without requiring physical I/O.

### NTR3 - GPIO vertical slice

Outcome:

```text
button edge
  -> native GPIO refinement
  -> gpio:button.press
  -> Pulse handler
  -> GPIO write operation
  -> native refinement
  -> LED state change
```

This is the first hardware-required proof. It should validate ISR queueing,
debounce, board mapping, event ordering, effect completion, safe startup state,
and fault cleanup.

### NTR4 - Provider packaging and family compile mapping

Outcome:

- the GPIO package contains author API, guest binding, target refinement, board
  mapping, schemas, and evidence metadata;
- the provider selects the S3 realization without target checks in handlers;
- extension compilation is attempted against the existing matrix with results
  classified explicitly.

The S3 reference remains the only required hardware proof. C6 or other cells do
not become device claims merely because they compile.

### NTR5 - Composite candidate and rollback

Outcome:

- one staged unit contains Wasm plus its selected native refinement;
- incomplete or mismatched units are rejected;
- candidate initialization and confirmation are host-observed;
- a trial extension crash/reset returns to the confirmed slot.

Remote network transport is not required. Physical or serial staging is
acceptable for this proof.

### Subsequent independent capabilities

After NTR0-NTR5:

1. BLE, to pressure asynchronous lifecycle, identity, callbacks, and buffers.
2. Network orchestration, to pressure shared resources, retries, TLS, and
   protected recovery.
3. LoRa/mesh, to pressure external peripherals, airtime, and peer events.
4. Sensors/control, to prove domain event vocabularies and specialized native
   computation.

Each addition should extend the provider graph without changing the stable host
unless it reveals a missing general lifecycle primitive.

## 16. Fail-closed gates

The target-refinement path must reject:

- unknown host or extension ABI versions;
- target, architecture, IDF lane, or host-build mismatch;
- unpinned native dependencies;
- unexpected or unresolved native symbols;
- duplicate extension, event namespace, or operation identities;
- unresolved logical resources;
- conflicting pins, buses, radios, or exclusive peripherals;
- missing memory, stack, flash, or task-budget declarations;
- incomplete composite bundles;
- artifact hash or manifest mismatch;
- an extension that fails any required lifecycle stage;
- candidate confirmation controlled solely by the candidate;
- reset loops that repeatedly reload an unconfirmed failed extension;
- hidden substitution between guest, native, or provider realizations; and
- migration or build reports that imply unsupported runtime or hardware claims.

## 17. Reproducibility requirements

For the S3 reference proof:

1. Build the host and selected extension in the exact pinned ESP-IDF lane.
2. Resolve and preserve target-specific component locks.
3. Build from isolated clean copies.
4. Disable or normalize compiler caches as required by the existing matrix
   contract.
5. Record host firmware, ELF extension, Wasm, manifest, configuration, and
   partition hashes separately.
6. Require two clean runs when making a reproducibility claim.
7. Report binary size and memory-map deltas from the IF7 baseline.
8. Preserve raw build logs and machine-readable reports.
9. Treat infrastructure and unclassified failures as failed gates.
10. Keep runtime, electrical, radio, and rollback evidence in separate hardware
    reports.

Adding an ELF loader changes the build inputs and firmware source identity. It
creates a new qualification result; it must not reuse IF7 evidence as if the
binary were unchanged.

## 18. Hardware work explicitly deferred by this addendum

Until a hardware pass is separately authorized, this document does not prove:

- execution of an ELF extension on an ESP32-S3 board;
- executable PSRAM behavior;
- GPIO interrupt timing, debounce, or electrical safe state;
- watchdog recovery from a native extension fault;
- composite application rollback after a real reset;
- flash behavior under interrupted writes;
- BLE coexistence or GATT behavior;
- Wi-Fi, TLS, HTTP, webhook, or reconnect behavior;
- LoRa/SPI behavior;
- sensor accuracy or control-loop safety; or
- deployment transport on a real device.

Hardware evidence should be introduced one feature at a time and must name the
board, wiring, power conditions, firmware hash, application hash, extension
hash, test procedure, observed output, and recovery result.

## 19. Cross-host migration consequence

This refinement strengthens a future analysis-only `pulse migrate` command.
The command should compare two provider realization plans and report exact
seams rather than rewriting application code:

```text
portable unchanged
provider substitution available
board/resource binding required
semantic limit changed
native refinement selected
capability unavailable
manual review required
```

For example, migration from browser to ESP32 may preserve handlers, schemas,
and pure guest libraries while selecting new clock, network, storage, sensor,
or native refinements. The tool should expose those differences and fail a
`--check` gate when required seams remain unresolved.

This tool is a Pulse-wide future direction and is not part of the initial
native-refinement proof.

## 20. Stopping rule

Do not resume broad capability implementation from the old roadmap.

The next implementation unit, if authorized, should prove only:

```text
one pinned ELF loader
  -> one extension lifecycle
  -> one synthetic event/effect round trip
  -> one physical GPIO vertical slice
```

Do not add BLE, network, LoRa, remote deployment, a new bundle format, or
firmware OTA merely to make the first proof appear complete.

The architecture succeeds when a new capability can be added as an isolated
provider refinement without expanding the stable host's semantic surface.

## 21. Open decisions

The following decisions remain intentionally unresolved:

1. Exact ELF loader version and supported IDF-lane intersection.
2. Static embedding versus partition loading for the first proof.
3. Native extension descriptor and host-services ABI.
4. Symbol resolution and dependency policy.
5. Whether extensions may create FreeRTOS tasks directly or register task
   requirements through the host.
6. Resource-claim and conflict schema.
7. Event and operation identity encoding.
8. Composite bundle/container format and partition sizing.
9. Minimal deployment/recovery transport.
10. Trial confirmation policy for native refinements.
11. Persistent state compatibility across rollback.
12. Provider package layout and Pulse compiler integration.

These should be decided under implementation pressure from NTR0-NTR3, not by
enumerating every future ESP32 capability in advance.
