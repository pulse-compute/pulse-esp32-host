# ADR 0005 — Native network mediation

## Status

Accepted.

## Decision

Keep Wi-Fi, TLS, sockets, MQTT clients, HTTP clients, and credentials native. The guest may request bounded intent-level operations through logical network resources.

## Rationale

The guest needs useful network behavior, not raw network authority.

## Consequences

- Topic, URL, method, payload, and rate policy are enforced natively.
- Credentials and native transport handles never cross the guest boundary.
- New protocols require an explicit mediated capability.
