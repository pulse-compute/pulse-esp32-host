# ADR 0008 — Production verifier contract

## Status

Accepted as a boundary; final crypto integration is pending.

## Decision

Define a fail-closed production signature-verifier callback and policy contract rather than embedding an ad hoc cryptographic implementation in the prototype.

## Rationale

Production cryptography should be selected, reviewed, and tested for the target deployment and platform.

## Consequences

- Development signatures are rejected in production mode.
- Production bundles require a verifier, trusted key policy, and anti-rollback checks.
- Deployment remains incomplete until a vetted backend and known-answer tests are integrated.
