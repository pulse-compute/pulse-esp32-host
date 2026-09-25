# Bundle and Activation Lifecycle

## Bundle container

R6 introduced a versioned bundle container.

```text
magic:     WDCBNDL\0
version:   1
header:    fixed v1 header
manifest:  JSON manifest bytes
payload:   raw WASM payload
signature: dev HMAC or production verifier-backed signature
```

The native verifier checks:

1. container header,
2. exact total length; trailing unsigned bytes are rejected,
3. manifest SHA-256,
4. payload SHA-256,
5. manifest `payload.sha256` and `payload.size_bytes` binding,
6. signature policy,
7. ABI compatibility,
8. target hardware/profile compatibility,
9. runtime feature compatibility,
10. runtime limit bounds,
11. capability claims against the device profile,
12. required lifecycle exports using a real WASM export-section parser,
13. anti-rollback security counter.

## Manifest summary

The manifest declares:

```text
bundle_id
bundle_version
bundle_semver
security_counter
abi range
target soc/device class/board revision
runtime engine/payload kind/features
entrypoints
limits
capabilities
payload hash/size
signature algorithm/key/value
```

The manifest is not authority by itself. It is a request that must be verified against the shell policy and device profile.

## HP3 application artifact and slots

The signed bundle is wrapped in a fixed 192-byte HP3 application header. The
header binds application identity/version, security counter, HP2 application
requirements, bundle hash, total sizes, and a CRC. Production staging also
requires an artifact-authority verifier. The fixed format is not RAX.

The partition model keeps one fixed factory host image and custom data
partitions for Pulse applications:

```text
factory         native host firmware
wasm_a          WASM bundle slot A
wasm_b          WASM bundle slot B
wasm_meta       bundle activation metadata journal
```

Only the inactive application slot may be erased or streamed. Host-firmware
OTA is not part of HP3.

## Metadata state

Slot states:

```text
EMPTY
STAGED
VERIFIED
TRIAL
TRIAL_RUNNING (internal boot-attribution substate)
CONFIRMED
REJECTED
```

`WdcBundleMetadataV1` tracks:

- active slot,
- last-good slot,
- slot A/B state,
- bundle version,
- security counter,
- payload hash,
- artifact format, byte count, and artifact hash,
- candidate boot count,
- candidate fault count,
- trial boot-in-progress and boot generation,
- last reset attribution and rejected slot,
- last failure reason,
- metadata generation,
- metadata CRC.

## Journaled metadata

R8.1 introduced the two-record journal; HP3 evolves the same authority for
application artifacts and trial attribution. Record bodies are written before
their commit markers. Reads select the highest valid generation, tolerate one
corrupt peer, and reject two invalid non-erased records or divergent records at
the same generation.

This establishes the persistence algorithm. Exhaustive interruption and real
hardware power-loss testing remain HP3.5.

## Activation state machine

```text
stream fixed artifact into inactive slot
  -> hash stored artifact and inner bundle
  -> verify bundle, production authority, security floor, and HP2 compatibility
  -> journal STAGED then VERIFIED
  -> mark TRIAL
  -> boot persists attempt/reset attribution before entry
  -> reread artifact; apply HP2 fingerprint and HP1 live admission
  -> trial runs in host-owned probation
  -> host confirms after stable readiness/health/resource evidence
  -> slot becomes CONFIRMED and last_good
```

Failure path:

```text
trial running
  -> runtime fault / health failure / readiness timeout / attributed reset
  -> trial marked REJECTED
  -> fallback reboot to last_good_slot, or explicit recovery if none is viable
```

## Confirmation rule

The Wasm app may participate in readiness and health checks, but it does not
decide durable acceptance. The host requires readiness, successful health,
responsive administration, preserved resource floors, and a stable-time
window before confirmation.

## Local activation simulation

Use the bundle tool:

```bash
python3 tools/wdc_bundle_tool.py install --bundle <bundle.wdcb> --slot b --slots-dir build/local-slots
python3 tools/wdc_bundle_tool.py activate --slot b --slots-dir build/local-slots
python3 tools/wdc_bundle_tool.py boot --slots-dir build/local-slots
python3 tools/wdc_bundle_tool.py confirm --slots-dir build/local-slots
python3 tools/wdc_bundle_tool.py status --slots-dir build/local-slots
```

Failure simulation:

```bash
python3 tools/wdc_bundle_tool.py fail \
  --slots-dir build/local-slots \
  --slot b \
  --failure-reason -15
```

## Production signature boundary

R9 distinguishes development and production admission.

Development:

- dev HMAC-SHA256 is allowed only in dev policy,
- useful for proving the signing/verifier boundary in a sandbox.

Production:

- dev HMAC is rejected,
- required algorithm defaults to `ed25519`,
- trusted key ID must match policy/provisioning,
- verifier callback must be provided,
- anti-rollback security counter must meet or exceed the metadata-derived floor.

The current scaffold does not include deployment-grade Ed25519 math. Production integration must provide a vetted implementation through `WdcBundleSignatureVerifyFn`.
