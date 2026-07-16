# Pulse ESP32 Host

`pulse-esp32-host` is an experimental ESP32-S3 host for running replaceable WebAssembly application logic behind a native, fail-closed supervisor.

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
- diagnostic and audit surfaces.

Not yet qualified:

- a complete ESP-IDF build in release CI;
- repeatable validation on real ESP32-S3 hardware;
- deployment-grade Ed25519 integration;
- real Wi-Fi/MQTT/HTTP transport behind the existing mediator;
- flash power-loss qualification;
- production provisioning, fleet rollout, or recovery operations.

See [Current status and risks](docs/STATUS.md) for the precise boundary.

## Quick start

Run the host-side contract checks:

```bash
make validate
make test
make check-r9
make check-full
```

With ESP-IDF installed:

```bash
cd firmware
idf.py set-target esp32s3
idf.py build
idf.py flash monitor
```

With Rust installed:

```bash
rustup target add wasm32-unknown-unknown
make build-guest
```

Generated reports and logs are written under `reports/` and are intentionally not committed.

## Documentation

- [Documentation index](docs/README.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Trust boundary and safety model](docs/TRUST_BOUNDARY.md)
- [Current status and risks](docs/STATUS.md)
- [Build and test](docs/BUILD_AND_TEST.md)
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
