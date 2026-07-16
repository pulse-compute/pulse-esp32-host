# ADR 0003 — Logical resources and capabilities

## Status

Accepted.

## Decision

The guest requests operations against logical resources. The manifest requests authority; the verified device profile maps that authority to physical hardware and policy.

## Rationale

Board revisions can change physical pins without changing guest code, and a manifest cannot grant itself physical authority merely by naming a pin.

## Consequences

- Guests use names or stable IDs such as `relay_1`.
- Every effect resolves both a manifest capability and a profile resource.
- Device-profile update and verification policy remains host-owned.
