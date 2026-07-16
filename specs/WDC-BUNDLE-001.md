# WDC Bundle 001 — Bundle, Verification, and Activation Reference

**Status:** R9 scaffold reference  
**Container magic:** `WDCBNDL\0`  
**Container version:** `1`  
**Manifest format:** JSON, `manifest_format: 1`  
**Expanded human reference:** `docs/reference/BUNDLE_AND_ACTIVATION.md`  
**Primary source of truth:** `firmware/components/wdc_bundle/include/wdc_bundle.h`

## Container

```text
WdcBundleHeaderV1
manifest JSON bytes
payload bytes
signature bytes
```

The verifier checks exact length, header, manifest hash, payload hash, manifest/payload binding, signature policy, ABI compatibility, target compatibility, runtime limits, capability/profile compatibility, required WASM exports, and anti-rollback counter.

## Slots

```text
wasm_a     custom data partition, slot A
wasm_b     custom data partition, slot B
wasm_meta  custom metadata journal partition
```

## Slot states

```text
empty
downloaded
verified
pending
running_pending
confirmed
failed
```

## Activation

```text
verified
  -> pending
  -> running_pending/probation
  -> confirmed
```

Failure path:

```text
running_pending
  -> failed
  -> rollback to last_good_slot
```

## Development vs production signing

Development mode may use HMAC-SHA256 dev signing for local testing. Production mode rejects dev HMAC and requires a verifier callback for the configured production signature algorithm, currently represented as Ed25519-class.

The R9 scaffold defines the production verifier contract but does not include final deployment-grade Ed25519 math.


---

## R9 implementation note

The R9 scaffold implements a host-testable WDCB parser and admission verifier. Production policy is represented as a fail-closed verifier-hook contract: production mode rejects development HMAC signatures and requires a trusted key ID, anti-rollback floor, and installed production verifier callback.

Deployment-grade Ed25519 verification is intentionally not embedded in this scaffold. A production build must wire `WdcBundleSignatureVerifyFn` to a vetted crypto implementation.

Additional references:

```text
firmware/components/wdc_bundle/README.md
firmware/components/wdc_security/README.md
docs/BUNDLE_LIFECYCLE.md
docs/reference/SECURITY_PROFILE.md
```
