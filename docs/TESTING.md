# Testing and coverage

The current suite is strongest at host-side contract verification. It is intentionally not a device qualification suite.

## Test layers

| Layer | Location | Purpose |
|---|---|---|
| Python contract tests | `tests/contract/` | Schemas, tools, state machines, policy, and milestone behavior. |
| Native C smoke tests | `tests/firmware-unit/` | Selected firmware components compiled and exercised on the host. |
| Milestone gates | `tools/check_r*.py` | Narrow regression checks and bounded reports. |
| Documentation check | `tools/check_docs.py` | Required docs and local links. |
| Hardware-in-loop | `tests/hardware-in-loop/` | Placeholder for target execution. |
| OTA power-loss | `tests/ota-power-loss/` | Placeholder for flash/journal resilience. |
| Fault injection | `tests/fault-injection/` | Placeholder for runtime and driver fault campaigns. |

## Covered well in host tests

- ABI constants, status codes, and deterministic encoding;
- profile and manifest validation;
- capability allow/deny decisions;
- event envelopes and queue accounting;
- safety-state transitions and safe-output model;
- bundle container, hash, signature-policy, and metadata checks;
- activation and rollback state machine;
- native network-policy decisions;
- runtime-limit policy;
- production security-policy behavior.

## Requires target evidence

- real WAMR memory and trap behavior;
- actual GPIO levels and electrical safety;
- watchdog and reset integration;
- flash slot and metadata persistence;
- power-loss recovery;
- secure boot, flash encryption, and provisioning state;
- native Wi-Fi/MQTT/HTTP behavior;
- production cryptographic verification;
- sustained event and rate-limit behavior on constrained memory.

## Qualification principle

```text
host-side PASS + bounded skips = useful development evidence
host-side FAIL                 = regression
hardware skip                  = not a production qualification
unclassified absence          = test or documentation gap
```

Before production use, build a hardware matrix covering boot safety, good activation, bad rollback, power-loss windows, network policy, runtime limits, and production security.
