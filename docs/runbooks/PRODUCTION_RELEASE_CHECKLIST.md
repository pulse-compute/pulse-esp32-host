# Production Release Checklist

Use this before any real deployment.

## Build/toolchain

- [ ] [IDF family matrix seal](../reference/IDF_FAMILY_MATRIX.md) passes with exact lane, image, locks, source, and evidence archive recorded.
- [ ] S3 reference has two clean byte-reproducible builds in the pinned lane.
- [ ] Every exploratory target is attempted and explicitly classified; deterministic incompatibility is not treated as deployability.
- [ ] The workflow artifact contains the aggregate report, all cell reports, all build logs, generated configurations for successful cells, and build artifacts.
- [ ] The release source has a real Git revision recorded in addition to the firmware source-tree hash.
- [ ] Rust guest SDK builds with `wasm32-unknown-unknown`.
- [ ] Generated WASM imports/exports pass inspection.
- [ ] Bundle packaging is reproducible.

## Security

- [ ] Secure boot enabled and checked through real platform API.
- [ ] Flash encryption enabled and checked through real platform API.
- [ ] Production signing keys provisioned.
- [ ] Ed25519 verifier integrated with known-answer tests.
- [ ] Dev HMAC bundles rejected in production.
- [ ] Anti-rollback counter policy defined and tested.
- [ ] OTA endpoint and TLS/certificate policy defined.
- [ ] Key rotation/revocation process documented.

## Safety

- [ ] Safe GPIO defaults verified electrically.
- [ ] No-bundle mode verified electrically.
- [ ] Fault-stop verified electrically.
- [ ] Unauthorized GPIO writes denied.
- [ ] Invalid resource IDs denied.
- [ ] Rate/payload limits enforced.
- [ ] Watchdog reset triggers rollback for unconfirmed candidate.
- [ ] Metadata journal survives power-loss tests.

## Runtime

- [ ] WAMR runtime verified on target hardware.
- [ ] Manifest runtime limits are applied to runtime config.
- [ ] Event size limit enforced.
- [ ] Host-call size limits enforced.
- [ ] Runtime traps are surfaced to safety/activation logic.

## OTA/activation

- [ ] Good bundle installs to inactive slot.
- [ ] Candidate enters probation.
- [ ] Good candidate confirms and becomes last-good.
- [ ] Bad candidate rolls back.
- [ ] Failed candidate does not become confirmed.
- [ ] Slot metadata remains sane across reset/power loss.

## Network

- [ ] Wi-Fi credentials owned by native shell.
- [ ] MQTT publish topic prefix enforced.
- [ ] MQTT subscribe topic prefix enforced.
- [ ] HTTP URL prefix enforced.
- [ ] HTTP method allowlist enforced.
- [ ] Oversized payload denied.
- [ ] Disconnected network behavior is recoverable.

## Observability

- [ ] Reset reason recorded.
- [ ] Fault breadcrumb recorded.
- [ ] Physical actions auditable.
- [ ] Capability denials auditable.
- [ ] Rollback reason visible.
- [ ] Verification reports archived per release.

## Release decision

A production release should not proceed with unresolved `FAIL` gates or unclassified unknowns. `SKIPPED_NO_HARDWARE` is not acceptable for a production release. `SKIPPED_ENV` is acceptable only for development sandboxes, not release CI.

The IDF family build seal satisfies none of the unchecked hardware, runtime,
security, network, OTA, or observability requirements above.
