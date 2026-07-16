# ESP32-S3 WASM Shell Contract Specification

**Document:** WDC-ESP32S3-001  
**Title:** ESP32-S3 WASM Application Shell Contract  
**Version:** Draft v0.1  
**Status:** Working Draft  
**Target hardware:** ESP32-S3-class devices  
**Primary runtime assumption:** ESP-IDF native firmware shell + WAMR-compatible WebAssembly runtime  

---

## 1. Abstract

This specification defines a thin trusted firmware shell for ESP32-S3 devices that executes replaceable WebAssembly application bundles. The native shell owns boot, hardware drivers, network stacks, OTA, security, watchdogs, resource mapping, and fallback. The WASM bundle owns application behavior and may request actions only through a narrow, versioned, capability-enforced ABI.

The design goal is to allow frequent over-the-air application-logic updates without replacing the entire native firmware image, while preserving a clear trust boundary and reliable rollback path.

---

## 2. Goals

The shell MUST provide:

1. A stable ABI between native firmware and WASM application logic.
2. A trust boundary that treats WASM bundles as replaceable and potentially faulty.
3. Capability-based access to device resources.
4. A signed WASM bundle format.
5. A/B WASM bundle update with fallback.
6. A lifecycle model for initialization, events, health checks, shutdown, and rollback.
7. Safe host APIs for GPIO, timers, monotonic clock, configuration, I2C-like devices, Wi-Fi-mediated networking, and optional BLE.
8. Diagnostics sufficient to debug OTA behavior and app-driven physical actions.

---

## 3. Non-goals

This specification does NOT attempt to provide:

1. A full POSIX/WASI environment.
2. Direct WASM access to ESP-IDF APIs.
3. Direct WASM ISR callbacks.
4. Direct WASM Wi-Fi credential management.
5. Direct WASM BLE stack construction in v0.1.
6. Hard real-time execution inside WASM.
7. A generic abstraction for all microcontrollers.
8. A replacement for native firmware OTA.

---

## 4. Design summary

```text
ESP-IDF bootloader
    ↓
Native trusted shell
    - secure boot / flash encryption policy
    - native app OTA
    - WASM bundle OTA
    - bundle verification
    - WAMR runtime
    - watchdogs
    - GPIO/I2C/SPI/UART/BLE/Wi-Fi native drivers
    - event queue
    - capability enforcement
    ↓
WASM application bundle
    - application state machines
    - policy decisions
    - sensor interpretation
    - telemetry formatting
    - command handling
```

The native shell is the durable trust root. The WASM bundle is replaceable behavior. The ABI is the contract. The bundle manifest requests authority. The device profile defines physical truth. The shell enforces the contract.

---

## 5. Definitions

| Term | Meaning |
|---|---|
| Shell | Native ESP-IDF firmware that supervises WASM execution. |
| Bundle | Signed package containing manifest and WASM/AOT payload. |
| Guest | The WASM application module. |
| Host | The native shell. |
| ABI | The binary interface between guest and host. |
| Capability | Permission to use a resource or operation. |
| Device profile | Native-side mapping of logical resources to physical hardware. |
| Resource | A named device object such as `relay_1`, `status_led`, `temp_sensor`, `mqtt.telemetry`. |
| Slot | One of two persistent WASM bundle storage regions, normally `wasm_a` and `wasm_b`. |
| Candidate | A newly downloaded bundle that has not yet been confirmed healthy. |
| Confirmed | A bundle that has passed shell health criteria and may be used as fallback. |

---

## 6. Trust model

### 6.1 Trusted components

The following components are trusted:

1. ROM bootloader.
2. ESP-IDF second-stage bootloader.
3. Native shell firmware.
4. Shell-embedded bundle verification key material.
5. Device profile, after shell verification.
6. Shell OTA and rollback state machine.

### 6.2 Untrusted or semi-trusted components

The following components MUST be treated as untrusted or semi-trusted:

1. WASM bundle code.
2. WASM bundle manifest until verified.
3. Network-delivered updates.
4. Remote commands delivered to the WASM application.
5. Persistent app state controlled by the WASM application.

### 6.3 Security stance

The shell MUST assume that a WASM bundle may be:

1. Buggy.
2. Compiled for the wrong ABI.
3. Compiled for the wrong device profile.
4. Malicious if signature verification fails.
5. Too memory hungry.
6. Stuck in a loop.
7. Repeatedly violating the contract.
8. Unable to safely manage hardware.

The shell MUST validate all guest-originated pointers, lengths, resource IDs, opcodes, message encodings, timeouts, and capability requests before executing native operations.

---

## 7. Native shell responsibilities

The native shell MUST own:

1. Boot and boot diagnostics.
2. Native firmware OTA.
3. WASM bundle OTA.
4. Bundle verification.
5. Bundle A/B fallback.
6. Device profile loading and validation.
7. Wi-Fi connection state and credentials.
8. TLS certificates and private credentials.
9. BLE stack ownership.
10. GPIO/I2C/SPI/UART native drivers.
11. Interrupt handlers.
12. Hardware watchdogs and software watchdogs.
13. Power-management policy.
14. Event queueing and scheduling.
15. Capability enforcement.
16. Safe hardware defaults during boot, failure, rollback, and no-bundle mode.

The shell MUST NOT expose raw native pointers, raw ESP-IDF structs, raw driver handles, raw Wi-Fi credentials, or raw ISR registration to the guest.

---

## 8. WASM bundle responsibilities

The WASM bundle SHOULD own:

1. Application behavior.
2. State machines.
3. Rules and automation logic.
4. Sensor interpretation.
5. Command parsing at the application layer.
6. Telemetry payload construction.
7. User-facing app configuration, when permitted.
8. BLE value behavior, when permitted.
9. MQTT or HTTP payload decisions, when permitted.

The WASM bundle MUST NOT assume direct control over physical pins, Wi-Fi credentials, task scheduling, ISR behavior, boot state, rollback state, flash partitions, or watchdog configuration.

---

## 9. Device profile

The device profile maps logical resources to physical hardware. The guest sees logical resource IDs, not physical pins or raw bus addresses.

Example device profile:

```json
{
  "profile_format": 1,
  "device_class": "relay-node",
  "hardware": {
    "soc": "esp32-s3",
    "board": "relay-node",
    "board_rev": "c"
  },
  "resources": {
    "gpio": {
      "relay_1": {
        "pin": 12,
        "mode": "output",
        "active": "high",
        "safe_value": false
      },
      "status_led": {
        "pin": 48,
        "mode": "output",
        "active": "low",
        "safe_value": false
      },
      "button_1": {
        "pin": 0,
        "mode": "input_pullup",
        "debounce_ms": 30
      }
    },
    "i2c_devices": {
      "temp_ambient": {
        "driver": "sht31",
        "bus": "i2c0",
        "address": "0x44",
        "max_hz": 400000
      }
    },
    "network": {
      "mqtt_telemetry": {
        "kind": "mqtt_publish",
        "topic_prefix": "devices/{device_id}/telemetry/"
      }
    },
    "ble": {
      "battery_level": {
        "service": "180F",
        "characteristic": "2A19",
        "ops": ["read", "notify"]
      }
    }
  }
}
```

The shell MUST validate the device profile before loading a bundle. The shell SHOULD store the device profile in a protected partition or provisioned configuration region. Production devices SHOULD reject unsigned or malformed profiles.

---

## 10. Bundle format

A WDC bundle contains:

```text
bundle header
manifest JSON
WASM or WAMR-AOT payload
signature block
```

### 10.1 Bundle header

The bundle header SHOULD include:

```c
struct WdcBundleHeaderV1 {
    char     magic[4];          // "WDCB"
    uint16_t header_version;    // 1
    uint16_t flags;
    uint32_t header_len;
    uint32_t manifest_offset;
    uint32_t manifest_len;
    uint32_t payload_offset;
    uint32_t payload_len;
    uint32_t signature_offset;
    uint32_t signature_len;
    uint8_t  manifest_sha256[32];
    uint8_t  payload_sha256[32];
};
```

The shell MUST reject bundles with invalid magic, unsupported header version, invalid offsets, invalid lengths, hash mismatches, unsupported payload format, unsupported ABI range, unsupported target hardware, or invalid signature.

### 10.2 Manifest

The manifest is UTF-8 JSON. It describes identity, compatibility, limits, capabilities, payload hash, and signature metadata.

Example:

```json
{
  "manifest_format": 1,
  "bundle_id": "com.example.relay-controller",
  "bundle_version": 17,
  "bundle_semver": "0.17.0",
  "security_counter": 17,
  "abi": {
    "major": 1,
    "min_minor": 0,
    "max_minor": 0
  },
  "target": {
    "soc": ["esp32-s3"],
    "device_class": ["relay-node"],
    "board_rev_min": "c"
  },
  "runtime": {
    "engine": "wamr",
    "payload_kind": "wasm",
    "wasm_features": {
      "threads": false,
      "shared_memory": false,
      "wasi": false
    }
  },
  "entrypoints": {
    "init": "wdc_module_init",
    "event": "wdc_module_on_event",
    "health": "wdc_module_health",
    "shutdown": "wdc_module_shutdown"
  },
  "limits": {
    "linear_memory_max_bytes": 131072,
    "stack_bytes": 16384,
    "max_event_bytes": 2048,
    "max_request_bytes": 2048,
    "max_response_bytes": 2048,
    "init_timeout_ms": 2000,
    "event_timeout_ms": 100,
    "health_timeout_ms": 50,
    "host_call_timeout_ms": 50,
    "max_outstanding_async_requests": 4
  },
  "capabilities": [
    {
      "id": 1,
      "kind": "gpio",
      "resource": "relay_1",
      "ops": ["read", "write"],
      "max_rate_hz": 10
    },
    {
      "id": 2,
      "kind": "gpio",
      "resource": "status_led",
      "ops": ["write"],
      "max_rate_hz": 20
    },
    {
      "id": 3,
      "kind": "gpio",
      "resource": "button_1",
      "ops": ["read", "subscribe"]
    },
    {
      "id": 10,
      "kind": "sensor",
      "resource": "temp_ambient",
      "ops": ["read"],
      "max_rate_hz": 1
    },
    {
      "id": 20,
      "kind": "network",
      "resource": "mqtt_telemetry",
      "ops": ["publish"],
      "max_payload_bytes": 1024,
      "max_rate_hz": 1
    },
    {
      "id": 30,
      "kind": "config",
      "resource": "app.relay-controller.*",
      "ops": ["read", "write"],
      "max_bytes": 4096
    }
  ],
  "payload": {
    "encoding": "wasm",
    "size_bytes": 84231,
    "sha256": "hex-encoded-sha256"
  },
  "signature": {
    "alg": "ed25519",
    "key_id": "prod-2026-01",
    "value": "base64-signature"
  }
}
```

### 10.3 Signature coverage

The signature MUST cover:

1. Bundle header, excluding mutable transport-only fields if any.
2. Manifest with the `signature.value` field removed or set to an empty canonical value.
3. Payload hash.
4. Payload length.

The shell MUST verify the payload hash before activation. The shell MUST verify the signature before activation. HTTPS transport MAY be used for confidentiality and server authentication, but the bundle signature is the final authority for execution.

### 10.4 Anti-rollback

The shell MUST reject a bundle whose `security_counter` is lower than the minimum accepted counter for that bundle namespace and device policy.

For network-originated rollback resistance, the shell MAY store the minimum accepted counter in protected flash state. For physical rollback resistance, the implementation SHOULD use an eFuse-backed monotonic mechanism, a secure element, or a product-specific trusted counter strategy.

---

## 11. Partition model

The native firmware SHOULD use normal ESP-IDF app OTA slots for shell updates. WASM bundles SHOULD use separate data partitions.

Example 16 MB layout:

```csv
# Name,      Type, SubType, Offset, Size,   Flags
nvs,         data, nvs,     ,      64K,
otadata,     data, ota,     ,      8K,
ota_0,       app,  ota_0,   ,      2M,
ota_1,       app,  ota_1,   ,      2M,
wasm_a,      0x40, 0x00,    ,      2M,     encrypted
wasm_b,      0x40, 0x01,    ,      2M,     encrypted
wasm_meta,   0x40, 0x02,    ,      64K,    encrypted
storage,     data, littlefs,,      4M,     encrypted
```

The exact partition sizes are product-specific. The shell MUST ensure that a bundle cannot overwrite native firmware partitions, device profile partitions, NVS, or the inactive native OTA slot.

---

## 12. WASM bundle state machine

Each bundle slot has one of these states:

| State | Meaning |
|---|---|
| `empty` | No valid bundle present. |
| `downloaded` | Bytes were written, but not yet verified. |
| `verified` | Hash, signature, target, and ABI checks passed. |
| `pending` | Candidate selected for next activation. |
| `running_pending` | Candidate is currently running but not confirmed. |
| `confirmed` | Bundle passed health checks and can be used as fallback. |
| `failed` | Bundle failed validation, boot, health, or contract checks. |

### 12.1 Boot metadata

The shell MUST maintain power-loss-tolerant bundle metadata. The metadata SHOULD be journaled across at least two records with sequence counters and CRCs.

Minimum metadata:

```json
{
  "format": 1,
  "seq": 1234,
  "active_slot": "wasm_a",
  "last_confirmed_slot": "wasm_a",
  "pending_slot": "wasm_b",
  "slot_a_state": "confirmed",
  "slot_b_state": "pending",
  "slot_a_version": 16,
  "slot_b_version": 17,
  "boot_attempts_remaining": 1,
  "last_error": 0
}
```

### 12.2 Bundle update flow

```text
1. Shell downloads candidate to inactive WASM slot.
2. Shell verifies hash.
3. Shell verifies signature.
4. Shell checks target hardware compatibility.
5. Shell checks ABI compatibility.
6. Shell checks resource capabilities against device profile.
7. Shell marks candidate slot as pending.
8. Shell activates candidate, preferably after reboot.
9. Shell runs init and health probation.
10. If probation succeeds, shell marks candidate confirmed.
11. If probation fails, shell marks candidate failed and reverts to last confirmed slot.
```

Reboot-based activation is REQUIRED for v0.1 production compliance. Live hot-swap MAY be added later but MUST obey the same state machine.

### 12.3 Confirmation criteria

The shell, not the guest, decides whether a candidate is confirmed.

A candidate SHOULD be confirmed only if:

1. `wdc_module_init()` returns `WDC_OK` within `init_timeout_ms`.
2. No watchdog reset occurs during probation.
3. `wdc_module_health()` returns `WDC_OK` for the configured probation window.
4. No severe contract violation occurs during probation.
5. Required resources are available.
6. Required network condition, if declared by manifest, is satisfied or explicitly waived by shell policy.

### 12.4 Safe mode

If no confirmed bundle is available, the shell MUST enter safe mode.

Safe mode SHOULD:

1. Apply safe hardware defaults.
2. Keep native OTA recovery available if possible.
3. Keep device identity and provisioning intact.
4. Expose diagnostics locally or through a safe network path.
5. Avoid loading unverified bundles.

---

## 13. Runtime model

### 13.1 Single guest instance

ABI v1 supports one active WASM guest instance per device. Multiple bundles or multi-tenant execution are out of scope for v0.1.

### 13.2 Single-threaded guest

The guest MUST be single-threaded in ABI v1. The shell MUST reject bundles requiring WASM threads or shared memory unless a future ABI explicitly supports them.

### 13.3 No reentrant guest calls

The shell MUST NOT call guest exports reentrantly. If an event occurs while the guest is executing, the shell MUST enqueue, coalesce, or drop the event according to policy.

### 13.4 No ISR guest calls

Native ISRs MUST NOT call into WASM. ISRs may enqueue native events. The shell later serializes and delivers those events to the guest.

### 13.5 Blocking rules

Guest code SHOULD return quickly from lifecycle and event calls. The shell MUST enforce timeouts. Long-running native operations SHOULD be asynchronous and complete through events.

---

## 14. Guest imports

The guest imports functions from module name `wdc`.

### 14.1 Required imports

```c
// Write a log message owned by the guest.
// level: 0=debug, 1=info, 2=warn, 3=error
int32_t wdc_log(int32_t level, uint32_t ptr, uint32_t len);

// Monotonic milliseconds since shell boot.
uint64_t wdc_millis(void);

// Fill guest memory with random bytes.
int32_t wdc_random(uint32_t ptr, uint32_t len);

// Cooperative yield point. The shell may use this as a scheduling hint.
int32_t wdc_yield(void);

// General host dispatcher.
int32_t wdc_host_call(
    uint32_t opcode,
    uint32_t req_ptr,
    uint32_t req_len,
    uint32_t rsp_ptr,
    uint32_t rsp_cap
);
```

The shell MUST validate all pointer and length pairs before reading or writing guest memory.

### 14.2 Host dispatcher rationale

ABI v1 uses a hybrid interface:

1. Small primitive imports for logging, monotonic time, randomness, yielding, and host dispatch.
2. A single `wdc_host_call()` dispatcher for resource operations.

This keeps the native import surface small while allowing non-breaking expansion through new opcodes and optional fields.

---

## 15. Guest exports

The guest MUST export the following functions:

```c
// Called once after module instantiation.
int32_t wdc_module_init(void);

// Called for each shell-delivered event.
int32_t wdc_module_on_event(uint32_t event_ptr, uint32_t event_len);

// Called periodically during probation and optionally during normal runtime.
int32_t wdc_module_health(void);

// Called before unloading, rollback, shell OTA, or reboot when possible.
int32_t wdc_module_shutdown(int32_t reason);
```

The shell MUST reject a bundle missing required exports.

The guest MUST NOT depend on a WASM start function. Production shells SHOULD reject modules with a WASM start section unless explicitly allowed by policy.

---

## 16. ABI versioning

ABI version consists of:

```text
major.minor
```

Rules:

1. Major version changes indicate breaking changes.
2. Minor version changes indicate backward-compatible additions.
3. Unknown event fields MUST be ignored by the guest.
4. Unknown response fields MUST be ignored by the guest.
5. Unknown request fields MUST be ignored by the shell unless the field is marked required by the opcode schema.
6. A bundle is compatible only if its manifest ABI range overlaps the shell-supported ABI range for the same major version.

Example:

```json
"abi": {
  "major": 1,
  "min_minor": 0,
  "max_minor": 2
}
```

---

## 17. Message encoding

ABI v1 uses deterministic CBOR maps for events, host-call requests, and host-call responses.

Production messages SHOULD use integer keys. String keys MAY be used by development builds but SHOULD NOT be required by production guests.

### 17.1 Common integer keys

| Key | Name | Type | Meaning |
|---:|---|---|---|
| 0 | `version` | uint | Message schema version. |
| 1 | `type` | uint | Event type, response type, or subtype. |
| 2 | `seq` | uint | Shell-assigned sequence number. |
| 3 | `timestamp_ms` | uint | Shell monotonic timestamp. |
| 4 | `resource_id` | uint | Manifest-assigned resource ID. |
| 5 | `request_id` | uint | Async request correlation ID. |
| 6 | `status` | int | Status code. |
| 7 | `data` | map/bytes/text | Opcode-specific payload. |
| 8 | `required_len` | uint | Required response buffer length when too small. |
| 9 | `flags` | uint | Message-specific flags. |

### 17.2 Event envelope

Event payload passed to `wdc_module_on_event(ptr, len)` MUST be a deterministic CBOR map:

```cbor-diag
{
  0: 1,              // version
  1: 0x0301,         // event type
  2: 981,            // seq
  3: 12345678,       // timestamp_ms
  4: 3,              // resource_id, optional
  7: { ... }         // event-specific data
}
```

### 17.3 Host-call request

The request buffer passed to `wdc_host_call()` MUST be a deterministic CBOR map with opcode-specific fields.

### 17.4 Host-call response

If `rsp_cap` is nonzero, the shell MAY write a deterministic CBOR response map to `rsp_ptr`.

If the response buffer is too small, `wdc_host_call()` MUST return `WDC_ERR_RESPONSE_TOO_SMALL` and SHOULD write a response map containing key `8`, `required_len`, if possible.

---

## 18. Status and error codes

| Code | Name | Meaning |
|---:|---|---|
| 0 | `WDC_OK` | Success. |
| -1 | `WDC_ERR_UNKNOWN` | Unclassified error. |
| -2 | `WDC_ERR_UNSUPPORTED_ABI` | ABI mismatch. |
| -3 | `WDC_ERR_BAD_POINTER` | Guest pointer invalid. |
| -4 | `WDC_ERR_BAD_LENGTH` | Length invalid or over limit. |
| -5 | `WDC_ERR_BAD_ENCODING` | Message could not be decoded. |
| -6 | `WDC_ERR_UNSUPPORTED_OPCODE` | Opcode not supported by shell. |
| -7 | `WDC_ERR_CAPABILITY_DENIED` | Capability missing. |
| -8 | `WDC_ERR_INVALID_RESOURCE` | Resource ID unknown or wrong kind. |
| -9 | `WDC_ERR_INVALID_STATE` | Operation invalid in current shell state. |
| -10 | `WDC_ERR_BUSY` | Resource busy. |
| -11 | `WDC_ERR_TIMEOUT` | Operation timed out. |
| -12 | `WDC_ERR_NO_MEMORY` | Shell or guest memory unavailable. |
| -13 | `WDC_ERR_RESPONSE_TOO_SMALL` | Response buffer too small. |
| -14 | `WDC_ERR_RATE_LIMITED` | Operation exceeded rate policy. |
| -15 | `WDC_ERR_CONTRACT_VIOLATION` | Guest violated contract. |
| -16 | `WDC_ERR_IO` | Native I/O error. |
| -17 | `WDC_ERR_NOT_AVAILABLE` | Feature/resource temporarily unavailable. |
| -18 | `WDC_ERR_NOT_SYNCHRONIZED` | Wall clock or network state not synchronized. |

Severe or repeated `WDC_ERR_CONTRACT_VIOLATION` events SHOULD count against candidate confirmation and MAY trigger rollback or safe mode.

---

## 19. Event types

| Event type | Name | Meaning |
|---:|---|---|
| `0x0001` | `BOOT` | Guest has been loaded and shell is beginning runtime. |
| `0x0002` | `SHUTDOWN_REQUEST` | Shell requests graceful shutdown. |
| `0x0003` | `CONFIG_CHANGED` | A permitted config key changed. |
| `0x0101` | `TIMER_FIRED` | Guest timer fired. |
| `0x0201` | `GPIO_CHANGED` | Logical GPIO changed. |
| `0x0301` | `SENSOR_READY` | Sensor reading available. |
| `0x0401` | `NET_CONNECTED` | Network became available. |
| `0x0402` | `NET_DISCONNECTED` | Network became unavailable. |
| `0x0403` | `MQTT_MESSAGE` | MQTT message received. |
| `0x0404` | `HTTP_RESPONSE` | Async HTTP response received. |
| `0x0501` | `BLE_CONNECTED` | BLE central connected. |
| `0x0502` | `BLE_DISCONNECTED` | BLE central disconnected. |
| `0x0503` | `BLE_WRITE` | BLE characteristic write received. |
| `0x0601` | `OTA_STATUS` | Bundle update status changed. |
| `0x0701` | `FAULT` | Shell reports a fault or warning. |

The shell MAY coalesce noisy events such as GPIO changes or network status changes. Coalescing policy SHOULD be visible through diagnostics.

---

## 20. Host-call opcodes

### 20.1 System opcodes

| Opcode | Name | Capability | Description |
|---:|---|---|---|
| `0x0001` | `SYS_GET_INFO` | none | Return shell ABI, device class, bundle state, and uptime. |
| `0x0002` | `SYS_GET_METRIC` | `diagnostics.read` | Return selected runtime metric. |
| `0x0003` | `TIME_GET` | `clock.wall` | Return wall-clock time if synchronized. |

`wdc_millis()` is always available and does not require a capability. Wall-clock time is optional and may return `WDC_ERR_NOT_SYNCHRONIZED`.

### 20.2 Timer opcodes

| Opcode | Name | Capability | Description |
|---:|---|---|---|
| `0x0101` | `TIMER_SET` | none | Schedule a one-shot or repeating logical timer. |
| `0x0102` | `TIMER_CANCEL` | none | Cancel a logical timer. |

Timers deliver `TIMER_FIRED` events. The shell MAY enforce a maximum number of timers per guest.

### 20.3 Configuration opcodes

| Opcode | Name | Capability | Description |
|---:|---|---|---|
| `0x0201` | `CONFIG_GET` | `config:read` | Read permitted app config. |
| `0x0202` | `CONFIG_SET` | `config:write` | Write permitted app config. |
| `0x0203` | `CONFIG_DELETE` | `config:write` | Delete permitted app config. |

The guest MUST NOT read Wi-Fi credentials, TLS private keys, signing keys, device identity secrets, or shell-private configuration.

### 20.4 GPIO opcodes

| Opcode | Name | Capability | Description |
|---:|---|---|---|
| `0x0301` | `GPIO_GET` | `gpio:read` | Read logical GPIO value. |
| `0x0302` | `GPIO_SET` | `gpio:write` | Set logical GPIO value. |
| `0x0303` | `GPIO_SUBSCRIBE` | `gpio:subscribe` | Subscribe to debounced logical GPIO changes. |

The guest addresses GPIO by manifest resource ID. The guest MUST NOT address raw physical pin numbers in ABI v1.

### 20.5 I2C and sensor opcodes

| Opcode | Name | Capability | Description |
|---:|---|---|---|
| `0x0401` | `SENSOR_READ` | `sensor:read` | Read a shell-defined logical sensor. |
| `0x0402` | `SENSOR_SUBSCRIBE` | `sensor:subscribe` | Subscribe to periodic sensor events. |
| `0x0410` | `I2C_TRANSFER` | `i2c:transfer` | Perform transfer to a named I2C device only. |

`SENSOR_READ` is preferred for production app logic. `I2C_TRANSFER` is optional and MUST be restricted to a named device from the device profile. The guest MUST NOT select arbitrary I2C pins, buses, speeds, or addresses unless a future privileged ABI profile explicitly allows it.

### 20.6 Network opcodes

| Opcode | Name | Capability | Description |
|---:|---|---|---|
| `0x0501` | `NET_STATUS` | none | Return network state. |
| `0x0502` | `MQTT_PUBLISH` | `network:mqtt_publish` | Publish to a permitted topic/prefix. |
| `0x0503` | `MQTT_SUBSCRIBE` | `network:mqtt_subscribe` | Subscribe to permitted topic/prefix. |
| `0x0504` | `HTTP_REQUEST` | `network:http_request` | Start an async HTTP request to a permitted endpoint. |

The shell owns Wi-Fi configuration and connection management. The guest MUST NOT receive raw Wi-Fi credentials. HTTP requests SHOULD complete asynchronously through `HTTP_RESPONSE` events.

### 20.7 BLE opcodes

| Opcode | Name | Capability | Description |
|---:|---|---|---|
| `0x0601` | `BLE_SET_VALUE` | `ble:set_value` | Set a permitted characteristic value. |
| `0x0602` | `BLE_NOTIFY` | `ble:notify` | Notify a permitted characteristic. |
| `0x0603` | `BLE_ADVERTISE_SET` | `ble:advertise` | Adjust shell-approved advertising data. |

In ABI v1, the shell owns the BLE stack. The guest MAY update permitted values and respond to write events. Dynamic GATT construction by the guest is out of scope.

### 20.8 Storage opcodes

| Opcode | Name | Capability | Description |
|---:|---|---|---|
| `0x0701` | `KV_GET` | `storage:read` | Read app namespace key-value state. |
| `0x0702` | `KV_SET` | `storage:write` | Write app namespace key-value state. |
| `0x0703` | `KV_DELETE` | `storage:write` | Delete app namespace key-value state. |

Storage namespaces MUST be scoped by bundle ID or explicit manifest resource. The shell MAY enforce per-bundle storage quotas.

---

## 21. Capability enforcement

The default rule is:

```text
No capability, no access.
```

For every host call, the shell MUST check:

1. Is the opcode supported?
2. Is the request encoding valid?
3. Is the resource ID present when required?
4. Does the resource ID exist in the manifest?
5. Does the manifest resource name exist in the device profile?
6. Does the capability kind match the opcode?
7. Is the requested operation permitted?
8. Are rate limits and payload limits satisfied?
9. Is the resource safe to operate right now?

Example:

```text
gpio.set(resource_id=1, value=true)
  → resource_id 1 maps to relay_1
  → manifest allows gpio:write on relay_1
  → device profile maps relay_1 to GPIO12
  → rate policy allows operation
  → shell writes GPIO12
```

Counterexample:

```text
gpio.set(resource_id=99, value=true)
  → resource_id 99 not present in manifest
  → WDC_ERR_INVALID_RESOURCE
```

Counterexample:

```text
gpio.set(resource_id=3, value=true)
  → resource_id 3 maps to button_1
  → manifest allows read/subscribe, not write
  → WDC_ERR_CAPABILITY_DENIED
```

---

## 22. Memory and pointer safety

The shell MUST validate all guest memory access.

Rules:

1. Every pointer/length pair MUST refer to guest linear memory.
2. Zero-length buffers are allowed only where specified.
3. Request length MUST NOT exceed manifest `max_request_bytes`.
4. Response length MUST NOT exceed manifest `max_response_bytes`.
5. The shell MUST NOT retain raw guest pointers after a host call returns.
6. The shell MUST copy guest data needed for asynchronous work.
7. The shell MUST NOT pass raw native pointers to the guest.
8. The guest MUST NOT assume stable addresses across module restart.

---

## 23. Watchdog and fault policy

The shell MUST maintain watchdog protection around guest execution.

Fault classes:

| Class | Examples | Candidate behavior |
|---|---|---|
| Soft fault | Unsupported opcode, missing capability | Return error, log. |
| Contract fault | Bad pointer, invalid length, malformed repeated requests | Increment fault counter; may fail probation. |
| Runtime fault | Trap, stack overflow, memory exhaustion | Restart or rollback. |
| Liveness fault | Init timeout, event timeout, health timeout | Fail probation or restart confirmed bundle. |
| Safety fault | Unsafe resource request, repeated actuator abuse | Fail probation or safe mode. |

During candidate probation, severe runtime, liveness, or safety faults MUST prevent confirmation and SHOULD trigger rollback.

For confirmed bundles, the shell MAY attempt a bounded number of module restarts before entering safe mode or reverting to the previous confirmed bundle if available.

---

## 24. Hardware safety defaults

The device profile MUST define safe states for safety-relevant outputs.

The shell MUST apply safe states during:

1. Cold boot before bundle activation.
2. Bundle validation failure.
3. Candidate rollback.
4. No-bundle safe mode.
5. Severe safety fault.
6. Native shell OTA, when feasible.

The guest MUST NOT be required for hardware to enter a safe state.

---

## 25. Native firmware OTA

Native shell OTA is separate from WASM bundle OTA.

Native OTA SHOULD use ESP-IDF application OTA slots. The shell SHOULD perform diagnostics on first boot after native OTA and confirm or roll back the native image according to ESP-IDF rollback semantics.

The native shell MUST preserve the last confirmed WASM bundle metadata across native firmware updates unless an explicit migration policy says otherwise.

---

## 26. WASM bundle OTA

WASM bundle OTA is implemented by the shell and does not rely on the ESP-IDF bootloader selecting a WASM partition.

The shell MUST:

1. Download to inactive slot.
2. Verify before activation.
3. Never overwrite the last confirmed bundle during download.
4. Mark candidate as pending using power-loss-safe metadata.
5. Activate candidate under probation.
6. Mark confirmed only after shell-owned health criteria pass.
7. Revert to last confirmed bundle after failure.

The guest MAY request an update check if granted an update-related capability, but the shell owns all update decisions.

---

## 27. Logging and diagnostics

The shell SHOULD log:

1. Bundle ID and version on load.
2. ABI compatibility result.
3. Signature verification result.
4. Capability validation result.
5. Guest lifecycle calls and return codes.
6. Host-call opcode, resource ID, status, and duration.
7. Contract violations.
8. Watchdog events.
9. Rollback reason.
10. Safe-mode entry reason.

Logs SHOULD avoid recording secrets or sensitive payloads. Network payload logging MUST be redacted by default.

---

## 28. Development profile vs production profile

### 28.1 Development profile

Development builds MAY allow:

1. Unsigned bundles.
2. Verbose logs.
3. Test-only opcodes.
4. JSON event encoding.
5. Raw I2C transfer to named devices.
6. Relaxed rate limits.
7. Serial recovery console.

Development builds MUST be clearly distinguishable from production builds.

### 28.2 Production profile

Production builds MUST require:

1. Signed bundles.
2. ABI compatibility checks.
3. Capability checks.
4. Hash verification.
5. Rollback metadata.
6. Watchdog enforcement.
7. Safe output defaults.

Production builds SHOULD enable secure boot and flash encryption where supported by the product security model.

---

## 29. Recommended MVP

The first implementation SHOULD include only:

### Required lifecycle

```text
wdc_module_init
wdc_module_on_event
wdc_module_health
wdc_module_shutdown
```

### Required imports

```text
wdc_log
wdc_millis
wdc_random
wdc_yield
wdc_host_call
```

### Required opcodes

```text
SYS_GET_INFO
TIMER_SET
TIMER_CANCEL
CONFIG_GET
CONFIG_SET
GPIO_GET
GPIO_SET
SENSOR_READ
NET_STATUS
MQTT_PUBLISH
```

### Deferred features

```text
BLE
HTTP_REQUEST
raw I2C transfer
live hot-swap
multiple guest modules
WASI
threads
user-defined GATT
SPI/UART raw access
```

---

## 30. Reference test plan

### 30.1 Contract tests

1. Load valid bundle.
2. Reject unsigned bundle.
3. Reject invalid signature.
4. Reject payload hash mismatch.
5. Reject unsupported ABI.
6. Reject wrong target device class.
7. Reject missing required export.
8. Reject forbidden import.
9. Reject WASM start section if policy disallows it.
10. Reject oversized memory declaration.

### 30.2 Capability tests

1. Allowed GPIO write succeeds.
2. GPIO write without capability fails.
3. GPIO write to read-only resource fails.
4. Unknown resource ID fails.
5. MQTT publish outside prefix fails.
6. Config read outside namespace fails.
7. Rate-limited operation returns `WDC_ERR_RATE_LIMITED`.

### 30.3 OTA tests

1. Download candidate to inactive slot.
2. Power loss during download preserves confirmed bundle.
3. Power loss during metadata update recovers one valid record.
4. Candidate init failure rolls back.
5. Candidate watchdog reset rolls back.
6. Candidate health failure rolls back.
7. Candidate success confirms slot.
8. Native firmware OTA preserves WASM confirmed state.

### 30.4 Fuzz and robustness tests

1. Fuzz host-call CBOR decoder.
2. Fuzz event decoder in guest test harness.
3. Fuzz pointer and length validation.
4. Stress event queue overflow.
5. Stress repeated contract violations.
6. Stress low-memory module load.

### 30.5 Hardware-in-loop tests

1. Safe GPIO state before guest load.
2. Safe GPIO state after failed load.
3. Debounced button events.
4. Sensor reads under bus failure.
5. MQTT publish under network loss.
6. Watchdog reset during guest infinite loop.
7. Rollback after candidate crash.

---

## 31. Open issues for v0.2

1. Exact binary bundle container finalization.
2. Whether CBOR remains the production message encoding or is replaced by a smaller TLV.
3. Whether AOT payloads are supported in the first production release.
4. Whether hot-swap is worth supporting before v1.0.
5. How much BLE dynamism should be allowed.
6. Whether app state migration should be explicit through `wdc_module_migrate()`.
7. Whether multiple isolated WASM modules are needed.
8. Whether a formal IDL should generate Rust/C headers and manifest validation schemas.

---

## 32. External implementation anchors

This specification assumes the following implementation anchors:

1. ESP-IDF native application OTA and rollback for shell firmware updates.  
   https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/api-reference/system/ota.html

2. ESP-IDF custom partition tables for native app slots and separate WASM bundle storage.  
   https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/api-guides/partition-tables.html

3. ESP-IDF HTTPS OTA as one suitable mechanism for native firmware transport.  
   https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/api-reference/system/esp_https_ota.html

4. WAMR native API export/registration model for host functions imported by WASM.  
   https://github.com/bytecodealliance/wasm-micro-runtime/blob/main/doc/export_native_api.md

5. WAMR ESP-IDF integration as a standard ESP-IDF component.  
   https://components.espressif.com/components/espressif/wasm-micro-runtime/versions/2.4.0/examples/esp-idf?language=

6. ESP-IDF secure boot and flash encryption guidance for production security posture.  
   https://docs.espressif.com/projects/esp-idf/en/v5.2/esp32s3/security/host-based-security-workflows.html

---

## 33. Summary

WDC-ESP32S3 defines a trusted native supervisor and a replaceable WASM app bundle separated by a narrow contract. The shell owns safety, security, hardware, update, and rollback. The WASM bundle owns behavior. Capabilities, manifests, device profiles, and explicit lifecycle rules keep the boundary auditable and resilient.

The first production-quality milestone should focus on a small ABI, signed A/B WASM bundles, reboot-based activation, health-based confirmation, GPIO/timer/config/sensor/MQTT primitives, and strong diagnostics.
