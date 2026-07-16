# ADR 0006 — Deterministic CBOR subset

## Status

Accepted for ABI v1.

## Decision

Use a small deterministic CBOR map subset for host-call and event payloads.

## Rationale

CBOR is compact and bounded enough for a device host while remaining inspectable in tooling.

## Consequences

- Integer keys and supported value shapes are part of the ABI.
- Host and guest SDK constants must remain synchronized.
- Parser fuzzing and generated bindings are desirable future work.
