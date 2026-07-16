# Current status and risks

This repository is a strong host-side architecture prototype. It is not a qualified production firmware release.

## Implemented or scaffolded

| Area | Current state |
|---|---|
| Contract and schemas | Implemented and host-tested. |
| Native shell skeleton | Implemented. |
| WAMR integration boundary | Scaffolded and host-stub tested. |
| ABI dispatcher | Implemented and host-tested. |
| Event/profile/capability model | Implemented and host-tested. |
| GPIO safety MVP | Implemented against a host HAL; hardware validation pending. |
| Bundle parsing and verification | Implemented and host-tested. |
| A/B activation and rollback | Implemented as a state machine and local simulation. |
| Network mediation policy | Implemented; real transports pending. |
| Runtime limits | Implemented in host-side paths. |
| Production security policy | Implemented as a fail-closed contract; final crypto integration pending. |

## Unqualified boundaries

### Target build and hardware

The repository does not itself prove:

- an ESP-IDF build on the intended toolchain revision;
- WAMR behavior on the target memory configuration;
- GPIO levels and safe-state behavior on a real board;
- watchdog/reset integration;
- flash partition layout and power-loss behavior;
- hardware-in-loop rollback.

### Production cryptography

The verifier callback and policy are defined, but a vetted Ed25519 or platform-crypto implementation and known-answer tests must be integrated before production deployment.

### Native networking

The mediator enforces intent and policy in host tests. Real Wi-Fi, MQTT, and HTTP clients still need to be connected behind that boundary and validated on hardware.

### Device profiles

The current firmware uses a built-in static profile. Field-updatable profiles would require their own signing, validation, activation, rollback, and compatibility policy.

### Deferred capabilities

BLE, live Wasm hot-swap, raw I2C/SPI passthrough, multi-bundle scheduling, richer storage, and fleet management are intentionally deferred.

## Highest-value next work

1. Build the firmware in a pinned ESP-IDF environment.
2. Build the Rust guest examples and validate imports/exports.
3. Flash an ESP32-S3 and verify safe defaults electrically.
4. Run good-candidate confirmation and bad-candidate rollback on hardware.
5. Integrate and test a vetted production signature verifier.
6. Validate metadata writes under controlled power loss.
7. Connect real network transports behind `wdc_net` without expanding guest authority.
8. Add release CI lanes for host, guest, firmware, and hardware evidence.

## Risks to keep visible

- effectful boot self-tests returning accidentally;
- authorization becoming optional;
- manifest claims bypassing profile validation;
- raw platform APIs leaking into the guest contract;
- production anti-rollback or key policy being skipped;
- candidate confirmation occurring too early;
- outputs not being forced safe after guest failure;
- host-test confidence being mistaken for hardware qualification;
- generated reports being committed as if they were durable release evidence.

## Recommended stopping rule

Do not expand the guest API merely to make the demo broader. First reduce uncertainty in the real host boundary: toolchain, runtime, hardware, crypto, storage resilience, and network transport.
