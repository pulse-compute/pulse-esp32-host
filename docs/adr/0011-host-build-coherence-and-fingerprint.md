# ADR 0011 — Host build coherence, exact locks, and running fingerprints

## Status

Accepted.

## Context

The provider must be able to determine whether an existing ESP32 host can run
an application without leaking ESP-IDF or board-realization details into Pulse
core. Reproducibility also requires exact component resolution, but a permanent
global version pin would conflate one supported environment with the abstract
host contract.

## Decision

Board identity, host profile, normalized target intent, host build plan, exact
build lock, and running-host fingerprint are separate versioned artifacts.

One lock resolves one exact environment and is replayed without dependency
selection. Creating a different lock is an explicit operation. The lock binds
host realization inputs and does not include application identity, allowing a
compatible application to use `APP_ONLY_DEPLOYMENT`.

The running fingerprint carries both the exact build-lock digest and a semantic
compatibility digest. Application compatibility uses the semantic surface;
the exact lock remains available for reproduction and diagnosis. Static
compatibility is followed by HP1 live heap and largest-block admission before
application entry.

The build-derived C fingerprint is excluded from the source-tree hash because
including its lock digest would be circular. It must reproduce byte-for-byte
from the committed locks in every contract and qualification run.

## Consequences

- A future provider can compare intent with the running host before deciding
  between app-only deployment and an explicit host build plan.
- Adding another IDF lane is possible but requires a catalog and qualification
  change; existing locks do not move.
- Pulse core receives no IDF, sdkconfig, partition, PSRAM, or loader concept.
- HP3 binds slot compatibility to this stable fingerprint contract without
  defining host-firmware OTA.
- A fingerprint CRC is corruption detection, not remote attestation or a
  substitute for secure boot.

## Deferred

External provider ergonomics, Pulse-core extension registration, protected
administration, transport, RAX, MQTT, remote attestation, and host-firmware OTA
remain outside HP2. Application slots are defined by ADR 0012.
