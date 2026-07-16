# ADR 0004 — Reboot-based activation

## Status

Accepted for the prototype.

## Decision

Activate a verified candidate by marking it pending and rebooting into probation. Confirm it only after host-owned health policy succeeds; otherwise roll back to the last-good slot.

## Rationale

Reboot-based activation has a simpler cleanup and recovery model than live hot-swap of timers, handles, queues, subscriptions, and in-flight operations.

## Consequences

- Guest updates cause a reboot.
- Metadata must be journaled and power-loss safe.
- Live Wasm hot-swap remains deferred.
