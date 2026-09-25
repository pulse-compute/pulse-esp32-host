# Network mediation

> **Direction note:** `wdc_net` remains the application-facing outbound intent
> boundary. HP5 deliberately implements inbound HTTPS in the separate
> host-private `wdc_http` component so application networking cannot acquire
> administration authority.
> The post-IF7 [native target refinement addendum](../specs/PULSE-ESP32-003-native-target-refinement-addendum.md)
> moves future application networking toward an optional provider refinement,
> separate from the minimal deployment/recovery path.

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
| `HTTP_RESPOND` | Paired response to the active HP5 application request | Exact active request/resource, deadline, fixed body bound, first response wins. |

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

## HP5 inbound service

HP5 adds production-shaped ESP-IDF station Wi-Fi and two independently bounded
HTTPS listener sources. Application routes are exact `GET` or `POST` paths
below `/pulse/v1/app/`; they enter the common Wasm event handler as
`WDC_EVENT_HTTP_REQUEST`. Only the active handler may produce one bounded
`WDC_OP_HTTP_RESPOND`, and the first valid response wins.

The fixed `/pulse/v1/admin/` routes are not application routes. They normalize
into HP4's existing authenticated external entry, binary frame parser, session,
replay, deadline, command, terminal, audit, update, recovery, and HP3 reboot
authority. The application listener cannot occupy the separate administration
parser or socket reserve. See the
[HP5 host network mediator](HP5_HOST_NETWORK_MEDIATOR.md).

## Current implementation status

R8/R8.1 implemented outbound intent policy. HP5 implements the inbound
Wi-Fi/TLS/HTTP source and host-native service behavior. It has not been built
or executed on an ESP32 target; Wi-Fi association, TLS handshake, physical HTTP
traffic, and resource-floor observations are HP5.5. MQTT transport and a real
outbound HTTP client remain deferred.

The host mediator records:

- connected/disconnected state;
- publish/subscribe/request counts;
- last request ID;
- last operation data;
- denial/rejection counts.

## Deferred integration work

- HP5.5 dual-board Wi-Fi, TLS, application/admin HTTP, update/recovery, reset,
  response-loss, and resource-floor evidence.
- Production authenticator, Wi-Fi provisioning, certificate issuance,
  private-key storage, rotation, and cryptographic validation.
- Native MQTT client with bounded queues at HP7, after the HP6 provider path.
- Native outbound HTTP client with response events, if a customer-zero contract
  requires it.
- Per-topic QoS/retain policy, persistent metrics, and long-duration soak.
