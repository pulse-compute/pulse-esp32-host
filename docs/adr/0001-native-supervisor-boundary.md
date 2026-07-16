# ADR 0001 — Native supervisor boundary

## Status

Accepted for the prototype.

## Decision

The native ESP-IDF shell is the trusted supervisor. The Wasm bundle is replaceable application behavior and does not directly own hardware, credentials, flash layout, interrupts, or rollback policy.

## Rationale

Application behavior can change more frequently than firmware while safety-critical and security-sensitive mechanics remain native and auditable.

## Consequences

- Effectful guest behavior crosses a host-call boundary.
- The host validates safety state, manifest capability, and device profile before execution.
- The guest API stays narrow even when the native implementation grows.
