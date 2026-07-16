# Codebase map

This document maps the repository to the safety boundary it implements.

## Top-level layout

```text
firmware/                 Native ESP-IDF shell scaffold
firmware/components/      Supervisor components
guest-sdk/                Guest-side bindings/examples
examples/                 Profiles, manifests, generated bundles
schemas/                  JSON schemas
specs/                    Normative design specs
reports/                  Generated local reports and logs; ignored by Git
tests/                    Host-side contract and smoke tests
tools/                    Validation/build/packaging/report scripts
docs/                     Project documentation
```

## Firmware components

### `wdc_abi`

Files:

- `firmware/components/wdc_abi/include/wdc_abi.h`
- `firmware/components/wdc_abi/include/wdc_cbor.h`
- `firmware/components/wdc_abi/include/wdc_guest_memory.h`
- `firmware/components/wdc_abi/wdc_host_call.c`
- `firmware/components/wdc_abi/wdc_cbor.c`
- `firmware/components/wdc_abi/wdc_pointer.c`
- `firmware/components/wdc_abi/wdc_errors.c`

Responsibilities:

- ABI major/minor constants;
- import/export names;
- status codes;
- host-call opcode constants;
- CBOR key constants;
- guest pointer/range validation;
- configurable host-call request/response limits;
- dispatcher and host-hook plumbing.

### `wdc_runtime`

Files:

- `firmware/components/wdc_runtime/include/wdc_runtime.h`
- `firmware/components/wdc_runtime/wdc_runtime.c`
- `firmware/components/wdc_runtime/wdc_static_wasm.c`
- `firmware/components/wdc_runtime/test_vectors/*.wasm`

Responsibilities:

- runtime config;
- runtime outcome reporting;
- WAMR/host-stub backend split;
- static payload loading;
- lifecycle export resolution;
- lifecycle calls;
- event dispatch with maximum event-size enforcement.

### `wdc_events`

Responsibilities:

- event envelope definition;
- event CBOR encode/decode;
- fixed-capacity event queue;
- dropped-count tracking.

### `wdc_profile`

Responsibilities:

- builtin relay-node profile;
- logical resource lookup;
- GPIO resources with pin/mode/active/safe-level data;
- network resources with topic/URL/method policy.

### `wdc_caps`

Responsibilities:

- capability manifest parsing;
- resource capability checks;
- config-key capability checks;
- rate-limit bookkeeping;
- authorization audit records;
- host-call authorizer installation.

### `wdc_safety`

Responsibilities:

- boot-safe/no-bundle/app-running/fault-stopped states;
- applying safe GPIO defaults;
- forcing outputs safe on fault;
- fail-closed guarded authorizer;
- stopped-state write denial;
- safety counters and status reporting.

### `wdc_bundle`

Responsibilities:

- WDCBNDL container header parsing;
- manifest and payload hash verification;
- manifest-to-payload binding;
- dev HMAC signing support for tests;
- production verifier callback support;
- manifest summary extraction;
- lifecycle export-section parsing;
- metadata record validation/sealing.

### `wdc_ota`

Responsibilities:

- slot label mapping;
- reading slot headers and slot images;
- host-side slot stubs;
- two-record metadata journal with commit markers and generation selection.

### `wdc_activation`

Responsibilities:

- pending candidate preparation;
- boot-time candidate/confirmed/rollback decision;
- candidate boot budget;
- confirmation;
- fault recording and fallback selection.

### `wdc_app`

Responsibilities:

- active-slot boot orchestration;
- combining activation, OTA, bundle verification, safety, runtime, and metadata writes;
- installing verified capability sets;
- clearing active authorizers on teardown.

### `wdc_net`

Responsibilities:

- native-managed network state;
- MQTT publish/subscribe policy checks;
- HTTP request URL/method policy checks;
- network operation counters and last-operation records.

### `wdc_security`

Responsibilities:

- development vs production security policy;
- production preflight requirements;
- bundle verifier policy construction;
- trusted key-id enforcement;
- anti-rollback floor derivation;
- provisioning validation.

## Tools

| Tool | Purpose |
|---|---|
| `tools/wdc_validate.py` | Validate profile/manifest examples. |
| `tools/wdc_bundle_tool.py` | Pack, inspect, install, activate, boot, confirm, fail, and status for local bundles/slots. |
| `tools/wasm_inspect.py` | Inspect imports/exports for WASM fixtures. |
| `tools/validate_wasm_exports.py` | Validate lifecycle exports. |
| `tools/check_deps.py` | Inventory local dependencies. |
| `tools/bootstrap_*.sh` | Bounded dependency bootstrap attempts. |
| `tools/build_guest_wasm.sh` | Build Rust guest bundle when Rust is installed. |
| `tools/build_firmware.sh` | Build firmware when ESP-IDF is installed. |
| `tools/check_r*.py` | Milestone gates. |
| `tools/run_contract_tests.py` | Aggregate contract test runner. |
| `tools/check_docs.py` | Documentation existence/link gate. |

## Tests

Contract tests live under `tests/contract/`. Firmware-unit host C smoke tests live under `tests/firmware-unit/`. Hardware-in-loop, OTA power-loss, and fault-injection directories exist as placeholders for future device-backed gates.
