# Component Map

## Native components

| Component | Responsibility | Key boundary |
|---|---|---|
| `wdc_abi` | ABI constants, CBOR helpers, pointer validation, host-call dispatch. | First line of guest request validation. |
| `wdc_runtime` | WAMR/host-stub lifecycle loading and calls. | Runs verified payload and records runtime outcome. |
| `wdc_events` | Event envelope encode/decode and queue. | Converts native events into bounded guest inputs. |
| `wdc_profile` | Built-in relay-node profile and resource lookup. | Maps logical resources to physical truth. |
| `wdc_caps` | Manifest capability parsing, authorization, audit, rate/payload limits. | Decides whether active app may request a resource operation. |
| `wdc_safety` | Safety state, safe outputs, fault-stop, guarded authorizer. | Denies effectful calls outside safe app-running state. |
| `wdc_hal` | GPIO safe defaults and host-call bridge. | Native hardware execution layer for GPIO. |
| `wdc_bundle` | Bundle parse/hash/signature/manifest/compatibility verification. | Admits or rejects candidate bundles. |
| `wdc_ota` | Slot image and metadata read/write abstraction. | Bridges bundle slots and metadata journal. |
| `wdc_activation` | Pending/candidate/confirmed/rollback state machine. | Decides which slot may run. |
| `wdc_app` | Active-slot boot path and manifest-derived runtime config. | Connects activation, verification, capabilities, and runtime. |
| `wdc_net` | Native-mediated network status/MQTT/HTTP intents. | Prevents raw network authority in WASM. |
| `wdc_security` | Dev/production policy, preflight, anti-rollback floor, verifier policy. | Production admission boundary. |
| `wdc_diag` | Diagnostic ring, reset/fault breadcrumbs, status summaries. | Observability for rollback/fault analysis. |

## Main application

`firmware/main/app_main.c` calls into `shell_main.c`.

The shell startup path initializes diagnostics, profile, safe defaults, event queue, metadata, app/runtime path, and no-bundle/fault behavior.

## Important headers

| Header | Contains |
|---|---|
| `wdc_abi.h` | ABI version, constants, opcodes, status codes, slot states. |
| `wdc_bundle.h` | Bundle container structs, verification policy/result, metadata. |
| `wdc_activation.h` | Activation policy and decisions. |
| `wdc_safety.h` | Safety states, fault kinds, safety status. |
| `wdc_security.h` | Production/development policy and preflight contracts. |
| `wdc_profile.h` | Resource mapping structs and lookup APIs. |
| `wdc_runtime.h` | Runtime config/report and lifecycle APIs. |
| `wdc_net.h` | Network state and mediated host-call handlers. |

## Component dependency direction

Preferred dependency direction:

```text
security/profile/bundle/activation decide eligibility
  -> app derives runtime/capability config
  -> runtime invokes guest
  -> ABI receives guest requests
  -> safety/caps/profile authorize
  -> HAL/net execute native operations
  -> diag/events record outcomes
```

Avoid adding dependencies that let low-level execution layers bypass safety/capability checks.

## Adding a new component

A new component should document:

1. what it owns,
2. what it must never own,
3. which safety invariant it supports,
4. which tests prove negative paths,
5. whether it is active in production or host-test only.

