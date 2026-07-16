# Field Operations Runbook

## Bundle lifecycle

```text
pack
  -> inspect
  -> install inactive slot
  -> verify
  -> activate pending
  -> boot probation
  -> confirm or rollback
```

## Local commands

Pack:

```bash
python3 tools/wdc_bundle_tool.py pack \
  --manifest examples/bundles/relay-controller/manifest.json \
  --payload firmware/components/wdc_runtime/test_vectors/wdc_static_hello_wasm.wasm \
  --out build/relay-controller.wdcb
```

Inspect:

```bash
python3 tools/wdc_bundle_tool.py inspect --bundle build/relay-controller.wdcb
```

Install inactive slot:

```bash
python3 tools/wdc_bundle_tool.py install \
  --bundle build/relay-controller.wdcb \
  --slot b \
  --slots-dir build/local-slots
```

Activate:

```bash
python3 tools/wdc_bundle_tool.py activate --slot b --slots-dir build/local-slots
```

Boot simulation:

```bash
python3 tools/wdc_bundle_tool.py boot --slots-dir build/local-slots
```

Confirm:

```bash
python3 tools/wdc_bundle_tool.py confirm --slots-dir build/local-slots
```

Fail candidate:

```bash
python3 tools/wdc_bundle_tool.py fail \
  --slot b \
  --failure-reason -15 \
  --slots-dir build/local-slots
```

Status:

```bash
python3 tools/wdc_bundle_tool.py status --slots-dir build/local-slots
```

## Operational rules

1. Never confirm a candidate from guest code alone.
2. Do not install a bundle with a lower security counter in production.
3. Do not use dev HMAC bundles in production.
4. Do not mutate a device profile in the field unless the profile itself has a verification process.
5. Treat repeated capability denials or rate-limit denials as app-health signals.
6. Keep last-good slot intact until the new bundle is confirmed.
7. Record fault breadcrumbs before forcing safe outputs.

## Rollback triage

If a device rolled back:

1. Read active slot and last-good slot.
2. Read candidate slot state and failure reason.
3. Read candidate boot/fault counters.
4. Read runtime outcome and diagnostic breadcrumb.
5. Verify whether rollback was caused by trap, non-OK health, watchdog reset, or contract violation.
6. Keep the failed bundle hash for reproduction.

## Production update policy

A production update must pass:

- bundle signature verification,
- trusted key ID check,
- anti-rollback check,
- target/profile compatibility,
- capability/profile validation,
- runtime limit validation,
- staged rollout policy,
- rollback telemetry monitoring.

