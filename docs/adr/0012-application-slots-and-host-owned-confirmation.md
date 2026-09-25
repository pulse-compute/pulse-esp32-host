# ADR 0012 — Application slots and host-owned confirmation

## Status

Accepted.

## Context

Pulse application replacement must not overwrite the only known-good
application, mix application artifacts with host firmware, or let untrusted
application code declare itself healthy. The HP2 fingerprint provides static
compatibility and HP1 provides live resource admission, but neither defines
flash ownership, trial attribution, or fallback.

## Decision

The host owns two fixed flash application slots and one journaled metadata
authority. It accepts writes only to the inactive slot and preserves the last
confirmed slot until a replacement completes host-observed probation.

An HP3 artifact has a fixed 192-byte header followed by the existing signed WDC
bundle. Verification binds the stored bytes, signed bundle identity and
version, security floor, and HP2 requirements. Production mode requires an
artifact-authority verifier in addition to the bundle verifier.

The host persists a trial boot attempt before application entry. It attributes
the next reset, rejects failed trials, and requests a reboot into the last
confirmed slot. Confirmation requires stable time, readiness, health,
administration responsiveness, and preserved resource floors. Neither a guest
call nor readiness alone can confirm a trial.

If no slot passes verification, compatibility, and admission, the host enters
an explicit recovery outcome. Application-slot transitions do not update host
firmware.

## Consequences

- Interrupted or invalid staging cannot overwrite the confirmed application.
- A staged application is checked against both static and live host authority
  before lifecycle entry.
- Reset attribution and probation decisions are persistent and auditable.
- The managed runtime bridge is the only application-entry edge and records it
  after the slot gate.
- The fixed artifact remains intentionally separate from RAX.
- Larger C6 slot artifacts are rejected even if they fit the S3 realization.

## Deferred

HP3.5 closes the exhaustive host torn-write and interruption matrix under
[ADR 0013](0013-application-slot-interruption-authority.md). Its separately
retained dual-board safe physical subset subsequently passed all 13 checkpoints
per board and closed as `DUAL_NAMED_BOARD_SAFE_SUBSET_OBSERVED`.
Production signing deployment, RAX, protected remote administration, MQTT or
other transport, provider integration, Pulse-core changes, and host-firmware
OTA remain outside HP3.
