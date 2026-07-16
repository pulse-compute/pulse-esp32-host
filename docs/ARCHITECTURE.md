# Architecture

## Purpose

The Pulse ESP32 host is a native ESP-IDF supervisor that runs replaceable Wasm application logic behind a narrow, audited contract.

The guest does not own the device. It expresses behavior and requests capabilities. The native host remains responsible for physical correctness, credentials, interrupts, storage, recovery, and policy.

```text
native shell       durable trust root and host realization
Wasm guest         replaceable application behavior
ABI                versioned boundary
bundle manifest    requested authority
device profile     verified physical and policy truth
```

The repository still uses `wdc_*` implementation names inherited from the original prototype.

## Boot and activation flow

```text
ESP-IDF bootloader
  -> native shell starts
  -> reset and diagnostic state recorded
  -> device profile loaded and validated
  -> safe output defaults applied
  -> A/B bundle metadata read
  -> confirmed or candidate slot selected
  -> bundle and manifest verified
  -> runtime limits installed
  -> capability authorizer installed
  -> WAMR loads the verified guest
  -> lifecycle exports called
  -> queued events delivered
  -> every guest effect validated before native execution
```

Native firmware OTA and guest-bundle OTA are separate:

```text
native firmware OTA
  rare; changes supervisor, runtime, drivers, and ABI implementation

guest bundle OTA
  frequent; changes application behavior
  uses Wasm A/B slots, probation, confirmation, and rollback
```

## Guest boundary

The guest imports a small module named `wdc`:

```text
wdc_log
wdc_millis
wdc_random
wdc_yield
wdc_host_call
```

It exports lifecycle functions:

```text
wdc_module_init
wdc_module_on_event
wdc_module_health
wdc_module_shutdown
```

Non-trivial operations use the dispatcher:

```text
wdc_host_call(opcode, request_cbor, response_buffer)
```

The dispatcher validates:

1. opcode support;
2. guest pointer and range safety;
3. request and response limits;
4. deterministic CBOR shape;
5. installed fail-closed authorization;
6. current safety state;
7. manifest capability;
8. device-profile resource and policy;
9. operation-specific rate or payload limits;
10. native execution result.

## Event model

The embedded host must own interrupt and device-event mechanics.

```text
native ISR or driver callback
  -> bounded host queue
  -> event envelope
  -> guest event handler
```

The host must not call reentrantly from an ISR into Wasm. Queueing provides a stable scheduling and memory boundary and allows the host to account for drops, rate limits, and faults.

Long-running or asynchronous device operations should use explicit request/completion events or another bounded continuation contract rather than exposing native handles or callbacks to the guest.

## Component layers

```text
main/             boot and shell orchestration
wdc_security      development/production security policy
wdc_ota           slot and metadata storage abstraction
wdc_bundle        bundle parse, hash, signature, and manifest verification
wdc_activation    A/B candidate, probation, confirmation, and rollback
wdc_app           active-slot boot into the runtime
wdc_runtime       WAMR and host-stub guest lifecycle
wdc_abi           dispatcher, CBOR, memory validation
wdc_caps          capability parsing, authorization, and audit
wdc_safety        safety states and fault-stop behavior
wdc_profile       logical resource and physical profile mapping
wdc_hal           GPIO safe defaults and native hardware bridge
wdc_net           native-mediated network intent
wdc_events        bounded event encoding and queue
wdc_diag          reset/fault breadcrumbs and diagnostic ring
```

See [Component map](reference/COMPONENT_MAP.md) and [Codebase map](CODEBASE_MAP.md) for source locations.

## Manifest authority versus device truth

The bundle manifest requests logical authority:

```json
{
  "capabilities": [
    {
      "id": 1,
      "kind": "gpio",
      "resource": "relay_1",
      "ops": ["read", "write"]
    }
  ]
}
```

The verified device profile maps that logical resource to hardware and policy:

```json
{
  "resources": {
    "gpio": {
      "relay_1": {
        "pin": 12,
        "mode": "output",
        "safe_value": false
      }
    }
  }
}
```

The guest never receives authority over raw pin numbers, interrupts, Wi-Fi credentials, TLS material, sockets, ESP-IDF handles, flash partitions, or rollback state.

## Network model

The guest requests intent-level operations such as MQTT publish/subscribe or HTTP request. The native mediator owns credentials, TLS, connection state, and transport objects.

Policy can constrain:

- logical network resource;
- topic or URL prefix;
- allowed HTTP methods;
- payload size;
- operation rate;
- current connectivity state.

See [Network mediation](NETWORK_MEDIATION.md).

## Why this is a Pulse boundary witness

The host can realize only the capabilities it actually has. An ESP32 host does not need a JavaScript fallback or a fake universal platform API.

The architectural test is whether Pulse application semantics can remain stable while:

- memory is bounded;
- the host owns event scheduling;
- hardware operations require authorization;
- networking is optional and native-mediated;
- failures must force safe physical state;
- deployment may be a signed bundle rather than a server process.

That containment is the point of the experiment.
