# Documentation

This repository is an experimental Pulse host, not a production-ready embedded platform. The docs are organized around the host boundary and the implementation questions that remain open.

## Start here

1. [Architecture](ARCHITECTURE.md)
2. [Trust boundary and safety model](TRUST_BOUNDARY.md)
3. [Current status and risks](STATUS.md)
4. [Build and test](BUILD_AND_TEST.md)
5. [Hardware bring-up](runbooks/HARDWARE_BRINGUP.md)

## Architecture and implementation

| Document | Purpose |
|---|---|
| [Architecture](ARCHITECTURE.md) | Supervisor, guest, event, activation, and host-realization model. |
| [Trust boundary](TRUST_BOUNDARY.md) | Trusted/untrusted components, safety states, authorization, and fault handling. |
| [Current status](STATUS.md) | What is proven, what is only scaffolded, and the next high-value work. |
| [Codebase map](CODEBASE_MAP.md) | Firmware components, tools, tests, and dependency direction. |
| [Network mediation](NETWORK_MEDIATION.md) | Why network ownership stays native and how guest intent is bounded. |
| [Diagnostics](DIAGNOSTICS.md) | Audit goals, breadcrumbs, report outputs, and privacy constraints. |
| [Testing](TESTING.md) | Host-side coverage and the target/hardware gaps that remain. |
| [Troubleshooting](TROUBLESHOOTING.md) | Common build, bundle, policy, and runtime failures. |

## Reference

| Document | Purpose |
|---|---|
| [ABI reference](reference/ABI_REFERENCE.md) | Imports, exports, status codes, encoding, opcodes, and events. |
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

## Normative prototype specifications

- [ESP32-S3 host contract](../specs/WDC-ESP32S3-001-contract.md)
- [Prototype roadmap](../specs/WDC-ESP32S3-002-roadmap.md)
- [ABI contract](../specs/WDC-ABI-001.md)
- [Bundle contract](../specs/WDC-BUNDLE-001.md)

Run `make docs-check` to verify required documents and local links.
