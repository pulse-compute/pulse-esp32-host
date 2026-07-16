# ADR 0002 — Dispatcher-based ABI

## Status

Accepted for ABI v1.

## Decision

Expose a small set of primitive imports plus a single `wdc_host_call` dispatcher instead of many native imports.

## Rationale

A dispatcher centralizes memory validation, decoding, authorization, execution, response encoding, and audit behavior.

## Consequences

- Request and response payloads require a bounded encoding.
- Opcode metadata and SDK constants must remain synchronized.
- The dispatcher should continue to evolve toward explicit decode, authorize, execute, encode, and audit stages.
