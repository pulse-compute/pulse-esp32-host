# Diagnostics and observability

Diagnostics belong to the trusted host. The guest must not be able to rewrite the evidence used to explain a denial, fault, or rollback.

The host should be able to answer:

- which bundle and slot were active;
- whether the bundle was confirmed or in probation;
- why admission succeeded or failed;
- which host calls were allowed or denied;
- which safety transitions occurred;
- whether outputs were forced safe;
- whether events were dropped;
- which runtime limit was exceeded;
- why a candidate rolled back;
- whether production security preflight passed.

## Current surfaces

The scaffold includes reset reporting, a diagnostic ring, host-call audit records, safety counters, event-drop accounting, bundle-verification results, activation decisions, and machine-readable local reports.

Generated reports live under `reports/` and are not committed.

## Recommended persistent breadcrumb

```text
generation
slot
bundle id/version/security counter
fault code and reason
last opcode and logical resource
safety state
reset reason
monotonic time when available
```

## Privacy and security

Do not record raw credentials, private keys, bearer tokens, Wi-Fi passwords, TLS material, or sensitive application payloads. Prefer stable identifiers, hashes, counters, and reason codes.
