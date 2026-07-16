# Security Profile Reference

## Development vs production

R9 introduces explicit development and production policy modes.

Development policy exists to make the scaffold testable without external crypto dependencies. Production policy exists to prevent dev-mode shortcuts from silently becoming deployment behavior.

## Development policy

Development mode may allow:

- dev HMAC-SHA256 bundle signatures,
- local serial install flows,
- diagnostic probes,
- test-vector verifier callbacks,
- host-stub runtime tests.

Development policy must not be used as production policy.

## Production policy

Production mode requires:

- secure bundle signature policy,
- rejection of dev HMAC signatures,
- anti-rollback enabled,
- watchdog rollback enabled,
- effectful self-tests disabled,
- serial install/profile mutation disabled unless explicitly controlled,
- trusted signature key ID,
- OTA endpoint prefix provisioning,
- production security preflight pass.

## Preflight flags

Production preflight requires:

```text
secure boot
flash encryption
provisioned signing keys
provisioned OTA endpoint
```

The scaffold represents these as flags in `WdcSecurityDeviceState`. Real production code must bind them to actual ESP-IDF/SoC state.

## Signature policy

Production bundle admission uses `WdcBundleVerifyPolicy` derived from `WdcSecurityPolicy` and persisted metadata.

Important fields:

```text
production_mode = true
allow_unsigned_dev = false
required_signature_alg = "ed25519"
trusted_signature_key_id = <provisioned key id>
signature_verify = <vetted verifier callback>
min_security_counter = metadata-derived anti-rollback floor
```

## Ed25519 verifier boundary

R9 implements the verifier contract, not final production cryptography.

The callback shape is:

```c
typedef int32_t (*WdcBundleSignatureVerifyFn)(
    void *ctx,
    const WdcBundleManifestSummary *manifest,
    uint16_t signature_alg,
    const uint8_t *header,
    uint32_t header_len,
    const uint8_t *manifest_bytes,
    uint32_t manifest_len,
    const uint8_t *payload,
    uint32_t payload_len,
    const uint8_t *signature,
    uint32_t signature_len);
```

Before production, wire this to a vetted Ed25519 implementation or platform crypto provider and add known-answer tests.

## Anti-rollback

The shell computes a security-counter floor from metadata. A candidate bundle must have a security counter that is not below the floor.

This prevents installing older signed bundles after a newer bundle has been confirmed.

## Provisioning validation

Production provisioning validates:

- record is provisioned,
- device class matches profile,
- board revision matches profile as needed,
- trusted signature key ID exists and matches policy,
- OTA endpoint prefix exists and matches policy.

## Reset/fault diagnostics

R9 adds reset classification and persistent fault breadcrumbs. Watchdog reset classification is part of the security/safety feedback loop because an unconfirmed candidate reset must contribute to rollback decisions.

## Production release blockers

Do not treat the R9 scaffold as production-ready until these are complete:

1. real ESP-IDF build passes,
2. secure boot/flash encryption checks are bound to actual platform APIs,
3. Ed25519 verifier is integrated and tested with known-answer vectors,
4. signing keys and key rotation policy are defined,
5. hardware power-loss tests validate metadata journal behavior,
6. hardware watchdog rollback tests pass,
7. OTA transport and TLS/certificate validation are implemented,
8. release-signing process is documented and reproducible.

