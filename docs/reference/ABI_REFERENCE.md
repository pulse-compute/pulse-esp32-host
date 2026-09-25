# ABI Reference

## Version

```text
ABI major: 1
ABI minor: 0
import module: wdc
```

Compatibility rule:

```text
guest.abi.major == shell.abi.major
AND guest.abi.min_minor <= shell.abi.minor
AND guest.abi.max_minor >= shell.abi.minor
```

## Required imports

The guest imports these native functions from module `wdc`:

```c
int32_t  wdc_log(int32_t level, uint32_t ptr, uint32_t len);
uint64_t wdc_millis(void);
int32_t  wdc_random(uint32_t ptr, uint32_t len);
int32_t  wdc_yield(void);
int32_t  wdc_host_call(uint32_t opcode,
                       uint32_t req_ptr,
                       uint32_t req_len,
                       uint32_t rsp_ptr,
                       uint32_t rsp_cap);
```

## Required exports

The guest must export:

```c
int32_t wdc_module_init(void);
int32_t wdc_module_on_event(uint32_t event_ptr, uint32_t event_len);
int32_t wdc_module_health(void);
int32_t wdc_module_shutdown(int32_t reason);
```

## Status codes

| Code | Name | Meaning |
|---:|---|---|
| `0` | `WDC_OK` | Success. |
| `-1` | `WDC_ERR_UNKNOWN` | Unknown error. |
| `-2` | `WDC_ERR_UNSUPPORTED_ABI` | ABI mismatch. |
| `-3` | `WDC_ERR_BAD_POINTER` | Invalid guest pointer/range. |
| `-4` | `WDC_ERR_BAD_LENGTH` | Invalid length. |
| `-5` | `WDC_ERR_BAD_ENCODING` | Request/event encoding invalid. |
| `-6` | `WDC_ERR_UNSUPPORTED_OPCODE` | Opcode unknown or unsupported. |
| `-7` | `WDC_ERR_CAPABILITY_DENIED` | Capability/policy denied request. |
| `-8` | `WDC_ERR_INVALID_RESOURCE` | Resource ID/name invalid for profile. |
| `-9` | `WDC_ERR_INVALID_STATE` | Shell state does not permit operation. |
| `-10` | `WDC_ERR_BUSY` | Operation busy. |
| `-11` | `WDC_ERR_TIMEOUT` | Operation timed out. |
| `-12` | `WDC_ERR_NO_MEMORY` | Allocation/buffer unavailable. |
| `-13` | `WDC_ERR_RESPONSE_TOO_SMALL` | Response buffer too small. |
| `-14` | `WDC_ERR_RATE_LIMITED` | Capability rate limit denied request. |
| `-15` | `WDC_ERR_CONTRACT_VIOLATION` | Guest violated contract. |
| `-16` | `WDC_ERR_IO` | Native I/O error. |
| `-17` | `WDC_ERR_NOT_AVAILABLE` | Resource/service unavailable. |
| `-18` | `WDC_ERR_NOT_SYNCHRONIZED` | Clock/sync state unavailable. |

## Host-call request/response encoding

ABI v1 uses a deterministic CBOR subset. Requests and responses are CBOR maps keyed by small unsigned integer keys.

Common keys:

| Key | Name |
|---:|---|
| `0` | `status` |
| `1` | `abi_major` |
| `2` | `abi_minor` |
| `3` | `resource_id` |
| `4` | `value` |
| `5` | `timer_id` |
| `6` | `delay_ms` |
| `7` | `repeat` |
| `8` | `key` |
| `9` | `data` |
| `10` | `build_stage` |
| `11` | `shell_version` |
| `12` | `abi_version` |
| `13` | `event_type` |
| `14` | `event_id` |
| `15` | `timestamp_ms` |
| `16` | `payload` |
| `17` | `capability` |
| `18` | `decision` |
| `19` | `result` |
| `20` | `resource_name` |
| `21` | `bundle_name` |
| `22` | `bundle_version` |
| `23` | `queue_dropped` |
| `24` | `connected` |
| `25` | `topic` |
| `26` | `qos` |
| `27` | `retain` |
| `28` | `request_id` |
| `29` | `method` |
| `30` | `url` |
| `31` | `http_status` |
| `32` | `network_state` |
| `33` | `slot` |
| `34` | `security_counter` |
| `35` | `pending_count` |
| `36` | `payload_len` |
| `37` | `causation_id` |
| `38` | `operation_id` |
| `39` | `correlation_id` |
| `40` | `deadline_ms` |
| `41` | `encoding` |
| `42` | `completion_latency_ms` |

## Opcodes

| Opcode | Name | Authorization |
|---:|---|---|
| `0x0001` | `SYS_GET_INFO` | Safe status call. |
| `0x0002` | `SYS_GET_METRIC` | Diagnostics capability. |
| `0x0003` | `TIME_GET` | Optional clock capability. |
| `0x0101` | `TIMER_SET` | Timer capability. |
| `0x0102` | `TIMER_CANCEL` | Timer capability. |
| `0x0201` | `CONFIG_GET` | Config read capability. |
| `0x0202` | `CONFIG_SET` | Config write capability. |
| `0x0203` | `CONFIG_DELETE` | Config write/delete capability. |
| `0x0301` | `GPIO_GET` | GPIO read capability. |
| `0x0302` | `GPIO_SET` | GPIO write capability and `APP_RUNNING` safety state. |
| `0x0303` | `GPIO_SUBSCRIBE` | GPIO subscribe capability. |
| `0x0401` | `SENSOR_READ` | Sensor read capability. |
| `0x0402` | `SENSOR_SUBSCRIBE` | Sensor subscribe capability. |
| `0x0410` | `I2C_TRANSFER` | Deferred; named-device only. |
| `0x0501` | `NET_STATUS` | Safe status call. |
| `0x0502` | `MQTT_PUBLISH` | Network publish capability, topic policy, payload/rate limits. |
| `0x0503` | `MQTT_SUBSCRIBE` | Network subscribe capability, topic policy. |
| `0x0504` | `HTTP_REQUEST` | Network request capability, URL/method policy, payload/rate limits. |
| `0x0505` | `HTTP_RESPOND` | HP5 paired effect; valid only for the exact active HTTP request, bounded body, first response wins. |
| `0x0601` | `BLE_SET_VALUE` | Deferred. |
| `0x0602` | `BLE_NOTIFY` | Deferred. |
| `0x0603` | `BLE_ADVERTISE_SET` | Deferred. |
| `0x0701` | `KV_GET` | Storage read capability. |
| `0x0702` | `KV_SET` | Storage write capability. |
| `0x0703` | `KV_DELETE` | Storage delete capability. |
| `0x0801` | `EFFECT_INVOKE` | HX4 sealed native-extension registry; requires an installed authorizer and `APP_RUNNING` safety state. |

## Events

Event payloads are CBOR envelopes. Event ABI version is `(major << 16) | minor`.

Common event types:

| Value | Name |
|---:|---|
| `0x0001` | `SYSTEM_BOOT` / `BOOT` |
| `0x0002` | `SHUTDOWN_REQUEST` |
| `0x0003` | `CONFIG_CHANGED` |
| `0x0004` | `MODULE_PROBATION_STARTED` |
| `0x0005` | `MODULE_PROBATION_ENDING` |
| `0x0101` | `TIMER_FIRED` |
| `0x0201` | `GPIO_CHANGED` |
| `0x0701` | `FAULT` |
| `0x0702` | `SAFETY_STATE_CHANGED` |
| `0x0703` | `PHYSICAL_ACTION` |
| `0x0801` | `NET_STATE_CHANGED` / `NET_CONNECTED` |
| `0x0802` | `NET_DISCONNECTED` |
| `0x0803` | `MQTT_MESSAGE` |
| `0x0804` | `HTTP_RESPONSE` |
| `0x0805` | `HTTP_REQUEST` |

HP5 inbound request events carry the registered logical network resource,
host-assigned request ID, method/path/body data, and absolute deadline. They do
not carry sockets, credentials, TLS objects, certificate/private-key material,
or administration authority. `HTTP_RESPOND` is rejected outside the active
handler and on a wrong ID, duplicate response, cancellation, or timeout.

## Runtime limits

Defaults from the ABI/runtime scaffolding:

```text
max_request_bytes:  2048
max_response_bytes: 2048
max_event_bytes:    2048
```

R8.2 makes these live per-bundle values derived from the verified manifest, then enforces them in the runtime and dispatcher.

## Fail-closed authorization

As of R8.1, the dispatcher must fail closed when an authorizer is absent. Only explicitly safe status calls may bypass the authorizer. This is a core invariant and should not be weakened when new opcodes are added.

HX4 keeps `EFFECT_INVOKE` effectful. The installed capability authorizer may
delegate it to the extension bridge, where sealed catalog identity, candidate
state, request bounds, host correlation, and deadline are enforced. It is not
in the safe-without-authorizer set.
