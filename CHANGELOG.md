# Prototype changelog

This repository began as a contract-first ESP32-S3/Wasm host spike. The `R0`–`R9` labels describe internal prototype milestones, not public releases or compatibility guarantees.

## R9 — Production security profile

- Added development and production security policies.
- Added secure-boot, flash-encryption, provisioning, and OTA preflight contracts.
- Added trusted key-ID and anti-rollback-floor policy.
- Added a fail-closed verifier callback boundary for deployment-grade signatures.
- Added reset and fault breadcrumbs.

## R8.2 — Runtime-limit hardening

- Applied manifest request, response, event, payload, and rate limits at runtime.
- Cleared active authorization and limits during teardown.
- Added event-size and host-call limit enforcement.

## R8.1 — Audit hardening

- Disabled effectful boot self-tests by default.
- Made missing host-call authorization fail closed.
- Added a two-record metadata journal.
- Replaced export-name string matching with Wasm export-section parsing.
- Tightened network-policy enforcement.

## R8 — Active-slot runtime and network mediation

- Booted the verified payload from the selected active slot.
- Installed manifest capabilities and runtime limits before guest execution.
- Added native-mediated MQTT and HTTP intent contracts.

## R7 — A/B activation and rollback

- Added pending, probation, confirmed, failed, and last-good states.
- Added rollback simulation and generation tracking.
- Added candidate boot and fault counters.

## R6 — Bundle packaging and verification

- Added the `WDCBNDL\0` container format.
- Added manifest and payload hashes.
- Added development signing and production rejection of development signatures.
- Added ABI, target, capability, profile, and metadata checks.

## R5 — Safety-enforced hardware MVP

- Added explicit safety states.
- Applied safe GPIO defaults at boot, no-bundle, and fault-stop boundaries.
- Added a HAL-backed relay path.
- Denied physical writes when the guest is not in the running state.

## R4 — Events, profiles, and capabilities

- Added event envelopes and bounded queues.
- Added capability parsing, authorization, resource lookup, and audit records.

## R3.5 — Dependency and verification boundary

- Added bounded dependency inventory and bootstrap helpers.
- Added machine-readable `PASS`, `FAIL`, `SKIPPED_ENV`, and `SKIPPED_NO_HARDWARE` reports.
- Added a Wasm inspector.

## R3 — ABI dispatcher and guest SDK

- Added deterministic CBOR request and response payloads.
- Added guest-memory validation and host-call limits.
- Added system, timer, config, and GPIO opcodes.
- Added Rust and C guest wrappers.

## R2 — Runtime vertical slice

- Added the WAMR runtime integration boundary.
- Added static Wasm fixtures and guest lifecycle lookup/calls.
- Added a host-test backend for local contract verification.

## R1 — Native shell skeleton

- Added boot sequencing and diagnostics.
- Added static profile and safe GPIO initialization.
- Added NVS/partition reporting and no-bundle mode.

## R0 — Contract and repository foundation

- Established the native-supervisor/Wasm-guest split.
- Defined initial ABI names, versioning, status ranges, and opcode groups.
- Added profile and manifest schemas and example inputs.
- Drafted Wasm A/B partitions and metadata storage.
