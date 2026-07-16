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

## Slots

The partition model uses native ESP-IDF OTA for the shell and custom data partitions for bundles:

```text
ota_0 / ota_1   native firmware images
wasm_a          WASM bundle slot A
wasm_b          WASM bundle slot B
wasm_meta       bundle activation metadata journal
```

## Metadata state

Slot states:

```text
empty
downloaded
verified
pending
running_pending
confirmed
failed
```

`WdcBundleMetadataV1` tracks:

- active slot,
- last-good slot,
- slot A/B state,
- bundle version,
- security counter,
- payload hash,
- candidate boot count,
- candidate fault count,
- last failure reason,
- metadata generation,
- metadata CRC.

## Journaled metadata

R8.1 hardened `wasm_meta` into a two-record journal with commit markers and generation selection.

This reduces the risk of losing metadata during power loss. It is not a substitute for real hardware power-loss testing, which remains pending.

## Activation state machine

```text
install bundle into inactive slot
  -> verify R6/R9 policy
  -> mark slot verified
  -> prepare pending candidate
  -> reboot or simulated boot
  -> activation_on_boot selects candidate
  -> candidate runs in probation
  -> shell confirms if health policy passes
  -> slot becomes confirmed and last_good
```

Failure path:

```text
candidate running_pending
  -> runtime fault / health failure / unconfirmed reset
  -> candidate marked failed
  -> rollback to last_good_slot
```

## Confirmation rule

The WASM app may report health, but it does not decide durable acceptance. The shell owns confirmation.

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

