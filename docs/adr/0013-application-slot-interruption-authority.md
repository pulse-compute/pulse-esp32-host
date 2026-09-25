# ADR 0013 — Application-slot interruption authority

## Status

Accepted.

## Context

HP3 writes only the inactive application slot and commits metadata bodies
before markers, but nominal success and one-record corruption do not prove the
behavior at every interrupted byte. A reset after a complete marker may also
make the new state durable even though the caller never receives success.
Keeping the caller's RAM mutation in that situation can disagree with the
journal. Confirmed-slot rejection and alternate selection were additionally
two separate commits.

## Decision

Host tests receive a private deterministic flash model with five one-shot
operations: slot erase, slot write, metadata erase, metadata body write, and
metadata marker write. The model retains partially written bytes across a
simulated power cycle and supports a one-based matching-operation trigger.

Qualification exercises every payload prefix; both journal records; every
record, body, and marker prefix; and every canonical transition used by
staging, verification, trial, boot attribution, confirmation, rejection, and
confirmed fallback. It also repeats the required semantic failures.

After a failed metadata write, the slot coordinator reloads the highest valid
durable generation. A complete new marker therefore adopts the new generation;
an incomplete marker restores the old generation. Rejection of an invalid
confirmed slot and selection of a validated confirmed alternate are committed
atomically.

The exhaustive result is host simulation. A separately frozen, inactive-only
safe subset and fail-closed dual-board evaluator define the physical promotion
gate without manufacturing passing hardware evidence.

## Consequences

- Torn inactive payloads never acquire boot authority.
- Either journal record can be interrupted or corrupted without ambiguity
  while the other valid generation remains.
- Reset during confirmation has only two valid outcomes: the old running trial
  later falls back, or the fully marked new generation is confirmed.
- Application code is never entered on an uncommitted boot attribution.
- The last confirmed application survives repeated traps, readiness timeout,
  watchdog attribution, bad hashes, bad signatures, and incompatible host
  fingerprints.
- The later physical promotion is valid only when two distinct named-board
  reports pass the frozen 13-checkpoint safe subset and the dual evaluator;
  the accepted external result now satisfies that gate.

## Excluded

This decision does not add protected administration, RAX, MQTT or other
transport, provider integration, Pulse-core changes, host-firmware OTA, or new
peripheral authority.
