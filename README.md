# Pulse ESP32 Host

`pulse-esp32-host` is an experimental ESP32-family host for running replaceable WebAssembly application logic behind a native, fail-closed supervisor.

It exists primarily as an architectural boundary witness for [Pulse](https://github.com/pulsecompute): the application model should remain coherent even when JavaScript fallback, abundant memory, a general operating system, and an HTTP-centric lifecycle are removed.

This repository is **not production firmware** and is not currently a supported Pulse provider. It is a focused implementation spike for the host boundary, safety model, bundle lifecycle, and embedded constraints.

```text
native ESP-IDF shell  = trusted supervisor and contract enforcer
Wasm guest            = replaceable application behavior
bundle manifest       = requested authority
verified device profile = physical and policy truth
ABI                    = narrow, versioned boundary
```

> The implementation retains `wdc_*` C symbols and `WDC` bundle identifiers from the original prototype. They are internal prototype identifiers, not a separate product surface.

## Why this host matters

A cloud or edge host can accidentally hide weak abstractions behind a large runtime. ESP32-S3 cannot.

The device host forces Pulse to be explicit about:

- who owns hardware, interrupts, clocks, storage, and networking;
- how guest effects are authorized and bounded;
- how an event suspends and resumes guest work without reentrant interrupt calls;
- what happens when a guest traps, exceeds limits, or requests unauthorized work;
- how application bundles activate, prove health, and roll back;
- which capabilities exist on this host and which do not.

The intended event path is:

```text
native ISR or device event
  -> host-owned queue
  -> bounded Pulse/Wasm event frame
  -> guest handler
  -> authorized host effects
```

The host must never call reentrantly from an interrupt directly into Wasm.

## Current scope

Implemented or scaffolded with host-side contract tests:

- native supervisor boot and safe-default flow;
- WAMR integration boundary and guest lifecycle exports;
- dispatcher-based ABI with deterministic CBOR payloads;
- logical resources, device profiles, and manifest capabilities;
- fail-closed host-call authorization;
- GPIO safety states and fault-stop behavior;
- bundle packaging, verification, A/B activation, probation, and rollback;
- manifest-derived runtime limits;
- native-mediated network intent and policy checks;
- production security-profile and verifier contracts;
- bounded two-stage native-extension admission plus host-owned lifecycle,
  health, static task/queue ownership, reset-required teardown policy, and the
  HX4 event/Wasm/effect happy path with the HX4.5 host adversarial seal and
  HX5a deterministic fault-model hardening;
- HX5b sustained-pressure recovery and retained physical execution on the
  named AITRIP S3 and XIAO C6 boards, reconciled by HP0 to
  `DUAL_ISA_PRESSURE_OBSERVED`;
- HP1 fixed host priorities, allocation-free ISR capture, independently
  bounded work/completion lanes, a C6 no-PSRAM reserve/admission profile, and
  64 synthetic pressure rounds with zero retained tickets;
- HP2 separation of named-board identity, host capability/resource profile,
  normalized application intent, deterministic host plan, exact replayable
  build lock, and a build-derived running-host fingerprint with prelaunch
  compatibility/admission enforcement;
- HP3 fixed Pulse application artifacts, two flash-resident application slots,
  inactive-only streaming verification, journaled trial/reset attribution,
  host-owned readiness probation and confirmation, deterministic fallback,
  and explicit recovery when neither slot is viable;
- HP3.5 deterministic slot/journal interruption with 11,657 exact host cases,
  durable-authority resynchronization, atomic confirmed fallback, and 13
  passing safe physical checkpoints on both named boards, closing as
  `DUAL_NAMED_BOARD_SAFE_SUBSET_OBSERVED`;
- HP4.0 frozen protected-administration identities, fixed records and bounds,
  atomic replay/acceptance semantics, five-state host mode machine, serial-first
  transport seam, HP1/HP2/HP3 authority bindings, and host-model qualifier
  closing as `HOST_ADMINISTRATION_CONTRACT_FROZEN` without changing firmware;
- HP4.1 fixed-storage `wdc_admin` firmware core with attended replaceable
  authorization, strict replay and rate gates, HP1-partitioned command
  ownership, exactly-one terminal response, bounded serial normalization,
  replaceable artifact-verifier seam, and a 32-record audit ring, closing as
  `HOST_PROTECTED_ADMINISTRATION_CORE_IMPLEMENTED` under host-native tests;
- HP4.2 exclusive C6 update transaction with positive guest/refinement unload,
  exact HP1 working-set admission, bounded inactive-slot streaming, complete
  HP3/HP2/security/verifier checks, durable `TRIAL` read-back, abort, and safe
  reboot handoff, closing as `HOST_EXCLUSIVE_UPDATE_TRANSACTION_IMPLEMENTED`
  under host-native tests;
- HP4.3 host-only recovery with deterministic HP3 no-viable or authorized
  administrative entry, fixed secret-free status, no loaded application or
  native refinement, recovery-origin candidate staging and abort, and a
  read-only complete HP3/HP2 viability proof before reboot handoff, closing as
  `HOST_ONLY_RECOVERY_IMPLEMENTED` under host-native tests;
- HP4.4 exhaustive administration/update/recovery sealing with 3,523 new
  negative native cases, 41 inherited cases, every safe artifact prefix, both
  journal records, resource and terminal/audit saturation, recovery
  interactions, and preaccept command-sequence-exhaustion hardening, closing
  HP4 as `HOST_ADMINISTRATION_ADVERSARIAL_SEALED`;
- HP5 host-owned station Wi-Fi and dual HTTPS listener source, fixed parsers
  and route table, common-Wasm application request dispatch, first-response-
  wins paired effect, and an authenticated external administration adapter
  that reuses HP4 session/command/update/recovery authority, closing as
  `HOST_NETWORK_MEDIATOR_IMPLEMENTED` under 35 new and 3,564 inherited
  host-native cases;
- HP5.5 source-ready dual-board audit tooling: new S3/PSRAM and C6/no-PSRAM
  target contracts, deterministic real-Wasm/update fixtures, external
  test-provision staging, strict build/client/per-board/dual evaluators, and a
  29-checkpoint campaign. The readiness result is
  `READY_FOR_PHYSICAL_EXECUTION`; no board result or promotion aggregate is
  claimed;
- diagnostic and audit surfaces.

Not yet qualified:

- execution of the local ESP-IDF workflow definition on GitHub-hosted CI;
- physical HP1 resource/priority/control-reserve behavior for the current
  firmware tree under production-shaped pressure;
- a current ESP-IDF firmware build and physical execution of the HP2
  fingerprint/prelaunch path;
- exhaustive physical byte-prefix or real power-cut execution beyond the
  frozen HP3.5 safe subset;
- physical execution and acceptance of the implemented HP5.5 exact dual-board
  Wi-Fi/TLS/application/administration/update/recovery/resource-floor proof;
- deployment-grade Ed25519 integration;
- target and physical execution of the HP5 Wi-Fi/TLS/HTTP service, plus MQTT;
- flash power-loss qualification;
- production provisioning, fleet rollout, or recovery operations.

The AITRIP S3 and XIAO C6 HX5b sessions both reached
`NAMED_BOARD_OBSERVED`; the final dual qualifier reached
`DUAL_ISA_PRESSURE_OBSERVED`. Their complete run directories remain external
to source in a separate manifested artifact. See the
[HP0 reconciliation](docs/HP0_EVIDENCE_RECONCILIATION.md) and accepted
[hardware evidence index](evidence/hardware/INDEX.md).

The later HP3.5 safe physical campaign also passed both named boards with 13
ordered checkpoints per board. Its dual evaluator reached
`DUAL_NAMED_BOARD_SAFE_SUBSET_OBSERVED`; source carries only the immutable
[HP3.5 evidence identities](evidence/hardware/HP3_5_INDEX.md), while complete
run directories and private pre-run flash backups remain external.

The S3 reference firmware is reproducibly build-qualified under the pinned
ESP-IDF lane. Additional family targets have explicit compile-probe results.
See the [ESP-IDF family build matrix](docs/reference/IDF_FAMILY_MATRIX.md) and
[current status and risks](docs/STATUS.md) for the exact evidence and claim
boundary.

## Quick start

Run the host-side contract checks:

```bash
make validate
make test
make check-hp0
make check-hp1
make check-hp2
make check-hp3
make check-hp3-5
make check-hp4-0
make check-hp4-1
make check-hp4-2
make check-hp4-3
make check-hp4-4
make check-hp5
make check-hx5a
make check-r9
make check-full
```

Validate the sealed matrix inputs and documentation without entering IDF:

```bash
make idf-family-seal-check
```

From a host with Docker or Podman, reproduce the complete build mapping in the
exact pinned environment:

```bash
WDC_IDF_MATRIX_OUT_DIR=reports/idf-family/local-rerun \
  tools/run_pinned_idf_matrix.sh
```

Do not use an ambient `idf.py set-target` flow as matrix evidence. Flashing and
monitoring belong to the separate hardware runbook and are not part of this
build seal.

The AITRIP and XIAO runbooks remain the reproduction paths for the exact named
boards. New runs must use fresh directories and are not accepted merely
because the HP0 identities already pass.

With Rust installed:

```bash
rustup target add wasm32-unknown-unknown
make build-guest
```

Generated reports and logs are written under `reports/` and are intentionally not committed.
Create source and evidence artifacts through the explicit
[packaging boundary](docs/PACKAGING_AND_EVIDENCE.md); never archive the working
tree wholesale.

## Documentation

- [Documentation index](docs/README.md)
- [HP0 evidence reconciliation and next-boundary freeze](docs/HP0_EVIDENCE_RECONCILIATION.md)
- [HP1 host-kernel resource authority](docs/HP1_HOST_KERNEL_RESOURCE_AUTHORITY.md)
- [HP2 host build coherence and fingerprint](docs/HP2_HOST_BUILD_COHERENCE.md)
- [HP3 application slots and fallback](docs/HP3_APPLICATION_SLOTS_AND_FALLBACK.md)
- [HP3.5 application-slot adversarial seal](docs/HP3_5_APPLICATION_SLOT_ADVERSARIAL_SEAL.md)
- [HP4.0 protected administration contract](docs/HP4_0_PROTECTED_ADMINISTRATION_CONTRACT.md)
- [HP4.1 protected administration core](docs/HP4_1_PROTECTED_ADMINISTRATION_CORE.md)
- [HP4.2 exclusive update transaction](docs/HP4_2_EXCLUSIVE_UPDATE_TRANSACTION.md)
- [HP4.3 host-only recovery](docs/HP4_3_HOST_ONLY_RECOVERY.md)
- [HP4.4 administration adversarial seal](docs/HP4_4_ADMINISTRATION_ADVERSARIAL_SEAL.md)
- [HP5 host network mediator](docs/HP5_HOST_NETWORK_MEDIATOR.md)
- [HP5.5 network and administration physical seal](docs/HP5_5_NETWORK_ADMIN_PHYSICAL_SEAL.md)
- [Native target refinement addendum](specs/PULSE-ESP32-003-native-target-refinement-addendum.md)
- [HX5a extension fault-model hardening](docs/HX5A_EXTENSION_FAULT_HARDENING.md)
- [HX4.5 event/effect adversarial seal](docs/HX4_5_EXTENSION_ADVERSARIAL.md)
- [HX4.5 AITRIP S3 hardware run](docs/HX4_5_S3_AITRIP_HARDWARE.md)
- [HX4.5 XIAO ESP32C6 hardware run](docs/HX4_5_C6_XIAO_HARDWARE.md)
- [HX4 event/effect happy path](docs/HX4_EXTENSION_EVENT_EFFECT.md)
- [HX3 extension lifecycle evidence](docs/HX3_EXTENSION_LIFECYCLE.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Trust boundary and safety model](docs/TRUST_BOUNDARY.md)
- [Current status and risks](docs/STATUS.md)
- [Build and test](docs/BUILD_AND_TEST.md)
- [Packaging and evidence](docs/PACKAGING_AND_EVIDENCE.md)
- [ESP-IDF family build matrix](docs/reference/IDF_FAMILY_MATRIX.md)
- [Hardware bring-up](docs/runbooks/HARDWARE_BRINGUP.md)
- [ABI reference](docs/reference/ABI_REFERENCE.md)
- [Bundle and activation lifecycle](docs/reference/BUNDLE_AND_ACTIVATION.md)
- [Device profiles and capabilities](docs/reference/DEVICE_PROFILE_AND_CAPABILITIES.md)
- [Security profile](docs/reference/SECURITY_PROFILE.md)
- [Prototype changelog](CHANGELOG.md)

## Repository layout

```text
firmware/       ESP-IDF supervisor and native host components
guest-sdk/      Rust and C guest SDK scaffolding
examples/       Example device profiles and application bundles
schemas/        Bundle-manifest and device-profile schemas
specs/          Normative prototype contracts
docs/           Architecture, reference material, ADRs, and runbooks
evidence/       Compact accepted-run indexes; no generated build products
tools/          Validators, packagers, build helpers, and report tools
tests/          Contract tests and native smoke fixtures
reports/        Generated local evidence; ignored by Git
```

## Design rule

The native shell is the trusted component. A guest is treated as replaceable and potentially faulty until its bundle, capabilities, inputs, limits, and requested effects are verified.

```text
Wasm host call
  -> validate memory and encoding
  -> require an installed authorizer
  -> check safety state
  -> check manifest capability
  -> resolve logical resource through device profile
  -> enforce limits and policy
  -> execute natively only when allowed
  -> record an audit or diagnostic result
```

Do not add a peripheral or host API unless it can be represented as a bounded capability and can fail safely.
