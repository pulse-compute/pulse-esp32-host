# Production Release Checklist

Use this before any real deployment.

## Build/toolchain

- [ ] ESP-IDF installed and version recorded.
- [ ] Firmware builds for `esp32s3`.
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

