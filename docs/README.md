# Documentation

This repository is an experimental Pulse host, not a production-ready embedded platform. The docs are organized around the host boundary and the implementation questions that remain open.

## Start here

1. [HP5.5 network and administration physical seal](HP5_5_NETWORK_ADMIN_PHYSICAL_SEAL.md)
2. [HP5 host network mediator](HP5_HOST_NETWORK_MEDIATOR.md)
3. [HP4.4 administration adversarial seal](HP4_4_ADMINISTRATION_ADVERSARIAL_SEAL.md)
4. [HP4.3 host-only recovery](HP4_3_HOST_ONLY_RECOVERY.md)
5. [HP4.2 exclusive update transaction](HP4_2_EXCLUSIVE_UPDATE_TRANSACTION.md)
6. [HP4.1 protected administration core](HP4_1_PROTECTED_ADMINISTRATION_CORE.md)
7. [HP4.0 protected administration contract](HP4_0_PROTECTED_ADMINISTRATION_CONTRACT.md)
8. [HP3.5 application-slot adversarial seal](HP3_5_APPLICATION_SLOT_ADVERSARIAL_SEAL.md)
9. [HP3 application slots and fallback](HP3_APPLICATION_SLOTS_AND_FALLBACK.md)
10. [HP2 host build coherence and fingerprint](HP2_HOST_BUILD_COHERENCE.md)
11. [HP1 host-kernel resource authority](HP1_HOST_KERNEL_RESOURCE_AUTHORITY.md)
12. [HP0 evidence reconciliation and next-boundary freeze](HP0_EVIDENCE_RECONCILIATION.md)
13. [Native target refinement addendum](../specs/PULSE-ESP32-003-native-target-refinement-addendum.md)
14. [HX5b extension pressure seal](HX5B_EXTENSION_PRESSURE_SEAL.md)
15. [HX5a extension fault-model hardening](HX5A_EXTENSION_FAULT_HARDENING.md)
16. [HX4.5 XIAO ESP32C6 hardware run](HX4_5_C6_XIAO_HARDWARE.md)
17. [HX4.5 AITRIP S3 hardware run](HX4_5_S3_AITRIP_HARDWARE.md)
18. [HX4.5 event/effect adversarial seal](HX4_5_EXTENSION_ADVERSARIAL.md)
19. [HX4 event/effect round trip](HX4_EXTENSION_EVENT_EFFECT.md)
20. [HX3 extension lifecycle and task ownership](HX3_EXTENSION_LIFECYCLE.md)
21. [HX2 two-stage extension admission](HX2_EXTENSION_ADMISSION.md)
22. [Architecture](ARCHITECTURE.md)
23. [Trust boundary and safety model](TRUST_BOUNDARY.md)
24. [Current status and risks](STATUS.md)
25. [Build and test](BUILD_AND_TEST.md)
26. [Packaging and evidence](PACKAGING_AND_EVIDENCE.md)
27. [Hardware bring-up](runbooks/HARDWARE_BRINGUP.md)

## Architecture and implementation

| Document | Purpose |
|---|---|
| [HP5 host network mediator](HP5_HOST_NETWORK_MEDIATOR.md) | Host-owned Wi-Fi/TLS/HTTPS source, bounded application routes through the common Wasm handler, protected external administration reuse, 35 new and 3,564 inherited native cases, and the HP5.5 physical gate. |
| [HP5.5 physical seal](HP5_5_NETWORK_ADMIN_PHYSICAL_SEAL.md) | Frozen dual-board identities, secret-safe provisioning, exact build/client/backup procedure, 29 checkpoints, strict per-board evidence, dual promotion, and the still-pending physical claim boundary. |
| [HP4.4 administration adversarial seal](HP4_4_ADMINISTRATION_ADVERSARIAL_SEAL.md) | Exact 3,523-case negative matrix plus 41 inherited native cases, sequence-exhaustion hardening, source/authority replay, HP4 closure, and HP5 handoff. |
| [HP4.3 host-only recovery](HP4_3_HOST_ONLY_RECOVERY.md) | Deterministic no-viable and authorized recovery entry, application-free administration, recovery-origin candidate staging, read-only viability proof, abort, and reboot handoff. |
| [HP4.2 exclusive update transaction](HP4_2_EXCLUSIVE_UPDATE_TRANSACTION.md) | Positive quiesce/unload, exact C6 HP1 admission, bounded inactive-slot streaming, complete verification, durable `TRIAL` read-back, abort, and reboot handoff. |
| [HP4.1 protected administration core](HP4_1_PROTECTED_ADMINISTRATION_CORE.md) | Fixed host-private session, authorization/rate/replay gates, HP1 command ownership, terminal response, serial normalizer, audit ring, and replaceable verifier seam. |
| [HP4.0 protected administration contract](HP4_0_PROTECTED_ADMINISTRATION_CONTRACT.md) | Host-private authenticated-entry identity, replay and terminal ownership, fixed bounds, five-state administration/update/recovery machine, serial-first transport seam, and exact HP1/HP2/HP3 authority bindings. |
| [HP3.5 slot adversarial seal](HP3_5_APPLICATION_SLOT_ADVERSARIAL_SEAL.md) | Deterministic flash/journal interruption model, 11,657-case exhaustive host matrix, durable-authority resynchronization, atomic confirmed fallback, and the passing 13-checkpoint dual-board safe-subset gate. |
| [HP3 application slots](HP3_APPLICATION_SLOTS_AND_FALLBACK.md) | Fixed artifact, dual flash slots, inactive streaming, journaled trial/reset attribution, host probation, fallback, recovery, and HP3.5 boundary. |
| [HP2 host build coherence](HP2_HOST_BUILD_COHERENCE.md) | Board/profile/intent/plan/lock/fingerprint separation, exact replay, and prelaunch compatibility. |
| [HP1 host-kernel resource authority](HP1_HOST_KERNEL_RESOURCE_AUTHORITY.md) | Fixed ISR, priority, bounded work/completion, C6 reserve/admission, explicit S3 optimization, and synthetic seal. |
| [HP0 evidence reconciliation](HP0_EVIDENCE_RECONCILIATION.md) | Exact v17/S3/C6/dual evidence closure, manifested package boundary, old HX6/HX7 supersession, and HP1-HP5.5 exclusions. |
| [Native target refinement addendum](../specs/PULSE-ESP32-003-native-target-refinement-addendum.md) | Post-IF7 direction: stable host, provider-composed native ELF refinements, and Pulse application deployment focus. |
| [HX5a fault-model hardening](HX5A_EXTENSION_FAULT_HARDENING.md) | Fault taxonomy, private deterministic lifecycle injection, cleanup tightening, unified host report, and the HX5b boundary. |
| [HX5b pressure seal](HX5B_EXTENSION_PRESSURE_SEAL.md) | Sustained queue/completion/fault pressure, recovery metrics, and opt-in S3/C6 rerun gates without capability expansion. |
| [AITRIP S3 hardware run](HX4_5_S3_AITRIP_HARDWARE.md) | Isolated N8R2 target harness, retained evidence contract, and shortest physical qualification path. |
| [XIAO ESP32C6 hardware run](HX4_5_C6_XIAO_HARDWARE.md) | Isolated 4 MB/no-PSRAM C6 harness, internal-memory gate, retained evidence contract, and shortest physical qualification path. |
| [HX4.5 adversarial seal](HX4_5_EXTENSION_ADVERSARIAL.md) | Executed event/effect identity, overflow, oversize, deadline, stale/duplicate completion, quiescence, Wasm-trap, and extension-fault corpus. |
| [HX4 event/effect round trip](HX4_EXTENSION_EVENT_EFFECT.md) | Provisional extension event through existing Wasm dispatch and back through a sealed-registry effect with bounded exactly-once completion. |
| [HX3 extension lifecycle](HX3_EXTENSION_LIFECYCLE.md) | Implemented host lifecycle, static task/queue ownership, health, deterministic teardown, reset policy, and dual-ISA build evidence. |
| [HX2 extension admission](HX2_EXTENSION_ADMISSION.md) | Implemented public ABI, bounded two-stage admission, synthetic dual-ISA artifacts, negative vectors, and exact build evidence. |
| [HX1 loader qualification](HX1_ELF_LOADER_QUALIFICATION.md) | Exact loader identity, supported relocations, executable-memory behavior, and build-only proof. |
| [Architecture](ARCHITECTURE.md) | Supervisor, guest, event, activation, and host-realization model. |
| [Trust boundary](TRUST_BOUNDARY.md) | Trusted/untrusted components, safety states, authorization, and fault handling. |
| [Current status](STATUS.md) | What is proven, what is only scaffolded, and the next high-value work. |
| [Codebase map](CODEBASE_MAP.md) | Firmware components, tools, tests, and dependency direction. |
| [Network mediation](NETWORK_MEDIATION.md) | Why network ownership stays native and how guest intent is bounded. |
| [Diagnostics](DIAGNOSTICS.md) | Audit goals, breadcrumbs, report outputs, and privacy constraints. |
| [Testing](TESTING.md) | Host-side coverage and the target/hardware gaps that remain. |
| [Packaging and evidence](PACKAGING_AND_EVIDENCE.md) | Lean deterministic source snapshots, installed toolchains, and separate host/hardware evidence artifacts. |
| [Accepted HX5b hardware evidence](../evidence/hardware/INDEX.md) | Source-distributed identities for the reconciled HX5b S3, C6, and dual reports. |
| [Accepted HP3.5 hardware evidence](../evidence/hardware/HP3_5_INDEX.md) | Source-distributed identities for the passing HP3.5 S3, C6, and dual safe-subset reports. |
| [ESP-IDF family build matrix](reference/IDF_FAMILY_MATRIX.md) | Exact IF7 source, lane, realization, configuration, lock, result, and evidence identities. |
| [Troubleshooting](TROUBLESHOOTING.md) | Common build, bundle, policy, and runtime failures. |

## Reference

| Document | Purpose |
|---|---|
| [ABI reference](reference/ABI_REFERENCE.md) | Imports, exports, status codes, encoding, opcodes, and events. |
| [ESP-IDF family build matrix](reference/IDF_FAMILY_MATRIX.md) | Canonical build-evidence claim and complete target inventory. |
| [Bundle and activation](reference/BUNDLE_AND_ACTIVATION.md) | Container, verification, slots, probation, confirmation, and rollback. |
| [Device profiles and capabilities](reference/DEVICE_PROFILE_AND_CAPABILITIES.md) | Logical resources, physical mappings, and requested authority. |
| [Runtime limits](reference/RUNTIME_LIMITS.md) | Manifest and host limits applied to guest execution. |
| [Security profile](reference/SECURITY_PROFILE.md) | Development/production policy and the production crypto boundary. |
| [Guest SDK](reference/GUEST_APP_DEVELOPER_GUIDE.md) | Guest lifecycle, host calls, logical resources, and bundle discipline. |
| [Component map](reference/COMPONENT_MAP.md) | Native component ownership and dependency direction. |
| [Glossary](reference/GLOSSARY.md) | Shared terms. |

## Runbooks

- [Local bring-up](runbooks/LOCAL_BRINGUP.md)
- [Hardware bring-up](runbooks/HARDWARE_BRINGUP.md)
- [AITRIP HX4.5 named-board stop](HX4_5_S3_AITRIP_HARDWARE.md)
- [XIAO ESP32C6 HX4.5 named-board gate](HX4_5_C6_XIAO_HARDWARE.md)
- [Field operations](runbooks/FIELD_OPERATIONS.md)
- [Production release checklist](runbooks/PRODUCTION_RELEASE_CHECKLIST.md)

## Decision records

- [ADR 0001 — Native supervisor boundary](adr/0001-native-supervisor-boundary.md)
- [ADR 0002 — Dispatcher-based ABI](adr/0002-dispatcher-based-abi.md)
- [ADR 0003 — Logical resources and capabilities](adr/0003-logical-resources-and-capabilities.md)
- [ADR 0004 — Reboot-based activation](adr/0004-reboot-based-activation.md)
- [ADR 0005 — Native network mediation](adr/0005-native-network-mediation.md)
- [ADR 0006 — Deterministic CBOR subset](adr/0006-deterministic-cbor-subset.md)
- [ADR 0007 — Fail-closed host-call authorization](adr/0007-fail-closed-host-call-authorization.md)
- [ADR 0008 — Production verifier contract](adr/0008-production-verifier-contract.md)
- [ADR 0009 — IDF family build matrix](adr/0009-idf-family-build-matrix.md)
- [ADR 0010 — Native extension loader and experimental ABI](adr/0010-native-extension-loader-and-abi.md)
- [ADR 0011 — Host build coherence and fingerprint](adr/0011-host-build-coherence-and-fingerprint.md)
- [ADR 0012 — Application slots and host-owned confirmation](adr/0012-application-slots-and-host-owned-confirmation.md)
- [ADR 0013 — Application-slot interruption authority](adr/0013-application-slot-interruption-authority.md)
- [ADR 0014 — Protected host administration authority](adr/0014-protected-host-administration-authority.md)
- [ADR 0015 — Host-owned HTTP ingress](adr/0015-host-owned-http-ingress.md)

## Normative prototype specifications

- [Native target refinement addendum](../specs/PULSE-ESP32-003-native-target-refinement-addendum.md)
- [Host extension spine contract](../specs/PULSE-ESP32-004-host-extension-spine.md)
- [HP1 host-kernel resource model](../specs/PULSE-ESP32-006-host-kernel-resource-authority.json)
- [HP2 host-build coherence model](../specs/PULSE-ESP32-007-host-build-coherence.json)
- [HP3 application-slot authority model](../specs/PULSE-ESP32-008-application-slots.json)
- [HP3.5 application-slot adversarial model](../specs/PULSE-ESP32-008a-application-slot-adversarial-seal.json)
- [HP4.0 protected-administration model](../specs/PULSE-ESP32-009-protected-administration.json)
- [HP4.1 protected-administration core model](../specs/PULSE-ESP32-010-protected-administration-core.json)
- [HP4.2 exclusive-update transaction model](../specs/PULSE-ESP32-011-exclusive-update-transaction.json)
- [HP5 host-network mediator model](../specs/PULSE-ESP32-014-host-network-mediator.json)
- [HP5.5 network/administration physical model](../specs/PULSE-ESP32-015-network-administration-physical-seal.json)
- [HP4.3 host-only recovery model](../specs/PULSE-ESP32-012-host-only-recovery.json)
- [HP4.4 administration adversarial seal model](../specs/PULSE-ESP32-013-administration-adversarial-seal.json)
- [ESP32-S3 host contract](../specs/WDC-ESP32S3-001-contract.md)
- [Prototype roadmap](../specs/WDC-ESP32S3-002-roadmap.md)
- [ABI contract](../specs/WDC-ABI-001.md)
- [Bundle contract](../specs/WDC-BUNDLE-001.md)

Run `make docs-check` to verify required documents and local links.
