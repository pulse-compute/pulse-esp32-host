# Guest App Developer Guide

## Role of the guest

The WASM guest owns app behavior, not hardware authority.

Good guest responsibilities:

- state machines,
- command handling,
- telemetry formatting,
- rule evaluation,
- sensor interpretation,
- deciding which logical action to request.

Bad guest responsibilities:

- raw pin control by physical number,
- Wi-Fi credentials,
- TLS private keys,
- raw sockets,
- BLE stack construction,
- ISR callbacks,
- watchdog ownership,
- durable acceptance of its own update.

## Required exports

```c
int32_t wdc_module_init(void);
int32_t wdc_module_on_event(uint32_t event_ptr, uint32_t event_len);
int32_t wdc_module_health(void);
int32_t wdc_module_shutdown(int32_t reason);
```

Return `WDC_OK` on success. Non-zero/negative lifecycle results may cause probation failure or app stop depending on the stage.

## Required imports

```c
wdc_log
wdc_millis
wdc_random
wdc_yield
wdc_host_call
```

Use `wdc_host_call` for all effectful operations.

## Recommended guest design

Keep the guest event-driven:

```text
module_init initializes app state
module_on_event decodes event and updates state
host_call requests bounded native actions
module_health reports whether state is sane
module_shutdown releases guest state
```

Avoid long blocking loops. Yield or return to the host promptly.

## Logical resources

Use resource IDs from the active manifest/profile. Do not hard-code physical pins.

Example:

```text
resource_id=1 means relay_1 for relay-node rev-c
```

It does not mean “GPIO 1.”

## Network requests

Network calls are native-mediated. The guest may request:

- `NET_STATUS`,
- `MQTT_PUBLISH`,
- `MQTT_SUBSCRIBE`,
- `HTTP_REQUEST`.

The shell enforces topic/URL/method/payload/rate policy. The guest should treat denial as normal and recoverable.

## Error handling

The guest should handle at least:

```text
WDC_ERR_CAPABILITY_DENIED
WDC_ERR_INVALID_RESOURCE
WDC_ERR_INVALID_STATE
WDC_ERR_RESPONSE_TOO_SMALL
WDC_ERR_RATE_LIMITED
WDC_ERR_NOT_AVAILABLE
```

Do not spin on repeated denial. That can become a contract violation or rate-limit fault.

## Manifest discipline

Every guest should have a manifest that states only the capabilities it needs.

Good:

```json
{ "resource": "relay_1", "ops": ["write"], "max_rate_hz": 10 }
```

Bad:

```json
{ "resource": "*", "ops": ["read", "write", "publish", "request"] }
```

The current schema does not grant wildcard physical authority and should not be extended to do so casually.

## Health behavior

`wdc_module_health` should report app sanity, not network perfection. A device may be temporarily offline without requiring rollback unless the app explicitly depends on network availability for safe behavior.

## Bundle probation

A new bundle starts as a candidate. It is not confirmed until the shell confirms it. The guest cannot mark itself durable.

## Local WASM validation

After building a guest:

```bash
python3 tools/wasm_inspect.py path/to/app.wasm \
  --require-export wdc_module_init \
  --require-export wdc_module_on_event \
  --require-export wdc_module_health \
  --require-export wdc_module_shutdown
```

This check requires a locally built guest. Install `cargo`/`rustc` and run `make build-guest` first when the toolchain is not already available.

