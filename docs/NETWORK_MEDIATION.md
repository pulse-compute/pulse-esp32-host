# Network mediation

WDC keeps network ownership native. The WASM app can request intent-level operations, but cannot own Wi-Fi, TLS, sockets, credentials, or raw MQTT/HTTP clients.

## Why native-owned networking

Network stacks are sensitive because they contain credentials, TLS state, reconnection policy, buffering, certificates, and remote command ingress. Giving WASM raw network access would turn the ABI into a large, unstable, hard-to-secure surface.

Instead:

```text
WASM requests: publish this telemetry on this resource.
Native decides: is this resource allowed, topic permitted, payload bounded, network connected, and safe?
```

## Current opcodes

| Opcode | Operation | Policy source |
|---|---|---|
| `NET_STATUS` | Query state | Safe unauthenticated status. |
| `MQTT_PUBLISH` | Publish payload | Manifest capability + profile topic prefix. |
| `MQTT_SUBSCRIBE` | Subscribe to command topic | Manifest capability + profile subscribe prefix. |
| `HTTP_REQUEST` | Request URL | Manifest capability + profile URL prefix and methods. |

## Device-profile network policy

A network resource may include:

- publish topic prefix;
- subscribe topic prefix;
- HTTP URL prefix;
- allowed HTTP methods;
- maximum payload bytes.

The native mediator rejects requests outside these boundaries.

## Example allowed/denied behavior

```text
resource: mqtt_telemetry
allowed publish prefix: devices/relay-node/telemetry/

publish devices/relay-node/telemetry/state  => allowed
publish devices/relay-node/commands/reset   => denied
```

```text
resource: http_api
allowed URL prefix: https://api.example.internal/devices/
allowed methods: POST,GET

POST https://api.example.internal/devices/abc/events => allowed
DELETE https://api.example.internal/devices/abc       => denied
POST http://untrusted.example/                        => denied
```

## Current implementation status

R8/R8.1 implemented the policy boundary and host-side mediator. Real ESP-IDF Wi-Fi/MQTT/HTTP client integration still needs a target implementation pass.

The host mediator records:

- connected/disconnected state;
- publish/subscribe/request counts;
- last request ID;
- last operation data;
- denial/rejection counts.

## Future integration work

- Native Wi-Fi provisioning and connection state.
- Native TLS root/certificate storage.
- Native MQTT client with bounded queues.
- Native HTTP client with response events.
- Backpressure and queue overflow policy.
- Per-topic QoS and retain policy from profile.
- Metrics and persistent failure counters.
