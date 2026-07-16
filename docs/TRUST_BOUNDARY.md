# Trust boundary and safety model

## Core claim

A verified guest may request actions, but only the native supervisor decides whether an action is authorized, safe, and executable.

The guest is replaceable and treated as faulty by design.

## Trust model

| Component | Trust | Responsibility |
|---|---|---|
| ESP32 ROM and bootloader | Trusted foundation | Boot chain. |
| Native Pulse host | Trusted supervisor | Validation, policy, safety, drivers, recovery. |
| Verified device profile | Trusted physical truth | Maps logical resources to pins and policy. |
| Bundle manifest before verification | Untrusted input | Requests authority and limits. |
| Wasm guest | Untrusted/faulty | Replaceable application behavior. |
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

## Update safety

A downloaded bundle is not active merely because transfer succeeded.

```text
downloaded
  -> parsed and verified
  -> installed to inactive slot
  -> marked pending
  -> booted in probation
  -> confirmed by native policy
  -> promoted to last-good
```

An unconfirmed candidate that faults or resets must be marked failed and rolled back.

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
