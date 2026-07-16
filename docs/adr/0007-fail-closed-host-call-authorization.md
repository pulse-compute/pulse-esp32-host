# ADR 0007 — Fail-closed host-call authorization

## Status

Accepted.

## Decision

Effectful host calls fail when no authorizer is installed. Only explicitly classified status queries may bypass authorization.

## Rationale

A missing authorizer is a supervisor failure and must never become implicit full access.

## Consequences

- Application boot installs authorization before guest effects are enabled.
- Teardown clears authorization and active limits.
- Negative tests cover missing-authorizer denial.
