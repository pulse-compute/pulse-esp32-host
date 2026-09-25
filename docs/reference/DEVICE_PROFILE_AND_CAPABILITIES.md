# Device Profile and Capability Guide

## Principle

The device profile is physical truth. The manifest is requested authority. The shell decides.

```text
manifest capability -> logical resource -> device profile -> native execution
```

The WASM app never gets direct authority over physical pins or native handles.

The HP2 host profile is separate from this physical device profile. The current
S3 and C6 host profiles advertise `pulse.application-slots.v1` together with
Wasm, event/effect, and native-refinement support. An HP3 artifact must require
the slot capability and pass the running fingerprint before it can be trialed;
the application cannot use that capability to choose, erase, or confirm a
slot.

## Example device profile

The checked-in example is:

```text
examples/device-profiles/relay-node-rev-c.json
```

Logical GPIO resources:

| Resource | ID | Pin | Mode | Active | Safe value |
|---|---:|---:|---|---|---|
| `relay_1` | 1 | 12 | output | high | false |
| `status_led` | 2 | 48 | output | low | true |
| `button_1` | 3 | 0 | input_pullup | n/a | n/a |

Other logical resources:

| Resource | ID | Kind | Purpose |
|---|---:|---|---|
| `temp_ambient` | 10 | sensor | SHT31 on `i2c0` at `0x44`. |
| `mqtt_telemetry` | 20 | network | MQTT publish resource. |
| `mqtt_commands` | 21 | network | MQTT subscribe resource. |
| `http_api` | 22 | network | HTTP request resource. |
| `app_state` | 30 | storage/config | Scoped app state placeholder. |

## Network policy fields

`mqtt_telemetry`:

```json
{
  "kind": "mqtt_publish",
  "topic_prefix": "devices/demo/telemetry",
  "max_payload_bytes": 512
}
```

`mqtt_commands`:

```json
{
  "kind": "mqtt_subscribe",
  "topic_filter": "devices/demo/commands/",
  "max_payload_bytes": 256
}
```

`http_api`:

```json
{
  "kind": "http_request",
  "allowlist": ["https://api.example.invalid/devices/demo/"],
  "methods": ["GET", "POST"],
  "max_payload_bytes": 1024
}
```

## Example manifest capabilities

```json
{
  "id": 1,
  "kind": "gpio",
  "resource": "relay_1",
  "ops": ["read", "write"],
  "max_rate_hz": 10
}
```

A capability is invalid if:

- resource does not exist in profile,
- kind mismatches profile resource kind,
- operation is unsupported for opcode,
- payload limit exceeds shell policy,
- rate limit is violated at runtime,
- shell safety state does not permit execution.

## Capability operations

| Operation | Meaning |
|---|---|
| `read` | Read resource/config/sensor state. |
| `write` | Write state or physical output. |
| `subscribe` | Subscribe to event source. |
| `publish` | Publish to native-mediated network resource. |
| `request` | Make native-mediated request such as HTTP. |
| `notify` | Reserved for BLE-style notifications. |

## Profile validation path

The validation tool checks the example profile/manifest relationship:

```bash
python3 tools/wdc_validate.py profile \
  --profile examples/device-profiles/relay-node-rev-c.json

python3 tools/wdc_validate.py manifest \
  --manifest examples/bundles/relay-controller/manifest.json \
  --profile examples/device-profiles/relay-node-rev-c.json
```

## Resource-ID convention

Current fixed IDs:

| ID | Name |
|---:|---|
| 1 | `relay_1` |
| 2 | `status_led` |
| 3 | `button_1` |
| 10 | `temp_ambient` |
| 20 | `mqtt_telemetry` |
| 21 | `mqtt_commands` |
| 22 | `http_api` |
| 30 | `app_state` |

These IDs are part of the ABI/profile boundary. Avoid renumbering once a device class is deployed.

## Design rule for new resources

When adding a resource, define all of the following before adding guest access:

1. logical resource name,
2. stable resource ID,
3. resource kind,
4. device-profile representation,
5. manifest capability shape,
6. host-call opcode or event type,
7. safety behavior on boot/no-bundle/fault,
8. negative-path tests for unauthorized, invalid, wrong-kind, rate-limited, and oversized requests.
