# ESP32-S3 WASM Shell Implementation Roadmap

**Document:** WDC-ESP32S3-002  
**Title:** ESP32-S3 WASM Application Shell Implementation Roadmap  
**Version:** Draft v0.1  
**Status:** Working Draft  
**Related spec:** WDC-ESP32S3-001, ESP32-S3 WASM Application Shell Contract Specification v0.1  
**Target:** ESP32-S3 native shell + replaceable WASM application bundle  

---

## 1. Purpose

This roadmap defines a practical implementation path for a trusted ESP32-S3 native firmware shell that executes replaceable WebAssembly application bundles behind a narrow contract boundary.

The roadmap is designed to prove the highest-risk ideas early:

1. A native shell can safely load and execute WASM app logic.
2. WASM can react to native events and request hardware actions only through the contract.
3. A bad WASM bundle can be detected and rolled back without replacing native firmware.
4. The ABI can remain narrow, auditable, versioned, and capability-enforced.

The roadmap intentionally avoids building a large platform before proving the trust boundary.

---

## 2. Core implementation principle

The first complete demo MUST be a vertical slice:

```text
button event
  -> native shell event queue
  -> WASM module_on_event(...)
  -> WASM requests relay toggle through host_call(...)
  -> native shell validates capability
  -> native shell changes GPIO
  -> shell logs action
  -> new WASM bundle is installed
  -> bad bundle fails health
  -> shell rolls back to previous confirmed bundle
```

This single flow proves the runtime, ABI, event model, capability model, OTA bundle mechanism, and fallback behavior.

Do not start by exposing every ESP32-S3 interface. Start by proving the boundary.

---

## 3. Roadmap summary

| Stage | Name | Primary outcome |
|---|---|---|
| R0 | Contract and repo foundation | Spec, repo layout, build skeleton, test strategy |
| R1 | Native shell skeleton | ESP-IDF app boots, logs, initializes safe hardware defaults |
| R2 | Runtime vertical slice | WAMR loads a static WASM module and calls lifecycle exports |
| R3 | ABI v0 | Guest imports, host dispatcher, pointer validation, basic SDK |
| R4 | Events and capabilities | Device profile, event queue, resource IDs, capability checks |
| R5 | Hardware MVP | GPIO, timers, config, one sensor abstraction |
| R6 | Bundle packaging | Signed bundle format, manifest validation, slot metadata |
| R7 | WASM A/B update and rollback | Candidate activation, health probation, fallback |
| R8 | Network-mediated app logic | Native Wi-Fi, MQTT/HTTP host calls, remote update transport |
| R9 | Hardening | watchdogs, fault injection, diagnostics, security profile |
| R10 | Expansion | BLE, AoT option, live hot-swap, richer SDKs, field operations |

The MVP target is R0 through R7. R8 makes it remotely useful. R9 makes it production-shaped. R10 is expansion, not required to prove the architecture.

---

## 4. Recommended repository layout

```text
wdc-esp32s3/
  firmware/
    CMakeLists.txt
    sdkconfig.defaults
    partitions.csv
    main/
      app_main.c
      shell_main.c
      shell_config.h
    components/
      wdc_abi/
        include/wdc_abi.h
        wdc_host_call.c
        wdc_errors.c
        wdc_pointer.c
      wdc_runtime/
        include/wdc_runtime.h
        wdc_wamr_runtime.c
        wdc_module_lifecycle.c
      wdc_events/
        include/wdc_events.h
        wdc_event_queue.c
        wdc_event_encode.c
      wdc_profile/
        include/wdc_profile.h
        wdc_profile_load.c
        wdc_resource_map.c
      wdc_caps/
        include/wdc_caps.h
        wdc_capability_check.c
      wdc_bundle/
        include/wdc_bundle.h
        wdc_bundle_parse.c
        wdc_bundle_verify.c
        wdc_bundle_slots.c
      wdc_ota/
        include/wdc_ota.h
        wdc_bundle_download.c
        wdc_activation.c
        wdc_rollback.c
      wdc_hal/
        include/wdc_gpio.h
        include/wdc_sensor.h
        wdc_gpio_espidf.c
        wdc_sensor_sht31.c
      wdc_net/
        include/wdc_net.h
        wdc_wifi_manager.c
        wdc_mqtt.c
        wdc_http_client.c
      wdc_diag/
        include/wdc_diag.h
        wdc_log_ring.c
        wdc_faults.c
        wdc_metrics.c

  guest-sdk/
    rust/
      wdc_guest/
        Cargo.toml
        src/lib.rs
        src/abi.rs
        src/events.rs
        src/host.rs
      examples/
        relay_toggle/
        bad_health/
        telemetry_demo/
    c/
      include/wdc_guest.h
      examples/relay_toggle/

  tools/
    wdc-pack/
      README.md
      src/main.rs
    wdc-sign/
      README.md
      src/main.rs
    wdc-inspect/
      README.md
      src/main.rs
    wdc-flash/
      README.md
      src/main.rs

  specs/
    WDC-ESP32S3-001-contract.md
    WDC-ESP32S3-002-roadmap.md
    WDC-ABI-001.md
    WDC-BUNDLE-001.md

  tests/
    contract/
      abi_golden_vectors/
      host_call_validation/
      manifest_validation/
    firmware-unit/
    hardware-in-loop/
    fault-injection/
    ota-power-loss/

  examples/
    device-profiles/
      relay-node-rev-c.json
    bundles/
      relay-controller/
      rollback-failure/
```

The important split is that the ABI, bundle format, and guest SDK live as first-class components, not incidental code inside `main/`.

---

## 5. Workstreams

### 5.1 Shell runtime workstream

Owns:

```text
- ESP-IDF app startup
- WAMR integration
- WASM loading
- guest lifecycle calls
- execution budget policy
- guest memory sizing
- runtime teardown
```

Early success condition:

```text
A static built-in WASM module logs "hello" through the host ABI and returns healthy.
```

### 5.2 ABI and contract workstream

Owns:

```text
- import/export definitions
- host_call dispatcher
- opcode registry
- error codes
- pointer and length validation
- request/response encoding
- ABI version negotiation
- contract test vectors
```

Early success condition:

```text
A WASM module can call sys.log, sys.millis, sys.random, and host_call(GPIO_SET) with all invalid pointer cases rejected.
```

### 5.3 Profile and capability workstream

Owns:

```text
- device profile format
- profile parser
- resource ID assignment
- capability manifest parser
- resource-to-hardware mapping
- capability enforcement
```

Early success condition:

```text
WASM can set logical resource relay_1, but cannot set an undeclared resource or physical pin.
```

### 5.4 Bundle and OTA workstream

Owns:

```text
- bundle container format
- manifest validation
- signature verification boundary
- wasm_a / wasm_b slot management
- activation metadata
- pending / confirmed / failed states
- rollback after reset or health failure
```

Early success condition:

```text
A valid local bundle can be installed into the inactive slot, marked pending, booted, confirmed, and retained as last-good.
```

### 5.5 Hardware abstraction workstream

Owns:

```text
- safe GPIO defaults
- GPIO get/set
- timer events
- one sensor abstraction
- optional raw-but-constrained I2C transaction support
- physical action audit logging
```

Early success condition:

```text
Button input becomes an event, WASM decides behavior, native shell toggles relay only after capability validation.
```

### 5.6 Network workstream

Owns:

```text
- native Wi-Fi manager
- network status events
- MQTT publish/subscribe host calls
- HTTP request host call
- bundle download transport
- TLS material native ownership
```

Early success condition:

```text
WASM publishes telemetry through a native-managed MQTT connection without seeing Wi-Fi credentials or TLS keys.
```

### 5.7 Diagnostics and test workstream

Owns:

```text
- structured logs
- ring-buffer crash breadcrumbs
- host-call audit records
- fault counters
- reset reason capture
- contract tests
- fuzzing malformed requests
- hardware-in-loop tests
- OTA interruption tests
```

Early success condition:

```text
Every app-driven physical action can be traced to bundle version, opcode, resource ID, decision, and result.
```

---

## 6. Milestone R0: Contract and repo foundation

### 6.1 Goal

Create the foundation needed to implement against a stable contract rather than ad hoc firmware code.

### 6.2 Deliverables

```text
- repository initialized
- ESP-IDF project skeleton
- partition table draft
- WDC contract spec checked into specs/
- ABI header checked into firmware/components/wdc_abi/include/
- bundle manifest schema draft
- guest SDK skeleton
- first example device profile
- test directory structure
```

### 6.3 Required decisions

| Decision | Recommendation for R0 |
|---|---|
| Runtime | WAMR interpreter first |
| Guest language | Rust first, C second |
| Host-call shape | small primitive imports + one dispatcher |
| Encoding | deterministic CBOR or compact TLV; choose one before R3 |
| Activation | reboot-based activation first |
| Slot model | `wasm_a`, `wasm_b`, `wasm_meta` |
| Hardware target | ESP32-S3 board with PSRAM preferred |

### 6.4 Acceptance criteria

```text
- firmware builds and boots with no WASM runtime yet
- partition table has native OTA and WASM bundle slots
- ABI header compiles in native firmware
- guest SDK compiles a no-op WASM module
- contract test suite can run on host machine, even if most tests are placeholders
```

### 6.5 Exit gate

Do not leave R0 until the ABI names, lifecycle export names, and basic error code ranges are fixed for the MVP.

---

## 7. Milestone R1: Native shell skeleton

### 7.1 Goal

Boot a native ESP-IDF shell that owns safe defaults, logging, reset diagnostics, and basic task structure.

### 7.2 Deliverables

```text
- app_main starts shell_main
- shell prints version, build ID, reset reason, partition info
- safe hardware defaults applied before app logic runs
- shell task created
- event queue created
- diagnostic ring buffer created
- NVS or metadata storage initialized
- no-bundle mode implemented
```

### 7.3 Modules touched

```text
firmware/main/shell_main.c
firmware/components/wdc_diag/
firmware/components/wdc_events/
firmware/components/wdc_profile/
firmware/partitions.csv
```

### 7.4 Acceptance criteria

```text
- device boots repeatedly without guest code
- all configured outputs are driven to safe values
- shell can report reset reason
- shell can enter no-bundle idle mode
- shell can enqueue and dequeue an internal test event
```

### 7.5 Failure cases to test

```text
- missing profile
- malformed profile
- empty WASM slots
- metadata region erased
- repeated reset
```

---

## 8. Milestone R2: Runtime vertical slice

### 8.1 Goal

Integrate the WASM runtime and call a static WASM module's lifecycle functions.

### 8.2 Deliverables

```text
- WAMR component integrated
- static embedded WASM blob linked into firmware for first bring-up
- module memory and stack limits configured
- lifecycle export lookup implemented
- module_init called
- module_health called
- module_shutdown called on shell stop
- basic runtime teardown implemented
```

### 8.3 Guest exports required

```c
int32_t wdc_module_init(void);
int32_t wdc_module_on_event(uint32_t event_ptr, uint32_t event_len);
int32_t wdc_module_health(void);
int32_t wdc_module_shutdown(int32_t reason);
```

### 8.4 Acceptance criteria

```text
- static WASM module loads from firmware image
- module_init returns OK
- module_health returns OK
- missing export is detected and reported
- module_init failure enters no-bundle or failed-bundle state
- module_shutdown is attempted during controlled stop
```

### 8.5 Failure cases to test

```text
- invalid WASM payload
- missing module_init
- module_init returns error
- module_health returns error
- guest traps during init
- guest requests more memory than allowed
```

### 8.6 Exit gate

The shell must be able to distinguish these outcomes:

```text
- runtime failed to initialize
- bundle failed to load
- required export missing
- guest trapped
- guest returned non-OK status
```

---

## 9. Milestone R3: ABI v0 and guest SDK

### 9.1 Goal

Implement the first narrow ABI and enough guest SDK support to write app logic without hand-encoding every call.

### 9.2 Deliverables

Primitive imports:

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

Host-side validation:

```text
- pointer bounds validation
- length validation
- response capacity validation
- maximum request size
- maximum response size
- opcode allowlist
- error code normalization
```

Guest SDK:

```text
- Rust bindings for primitive imports
- host_call wrapper
- error enum
- log macro or function
- millis/random helpers
- basic event decoding helper
```

### 9.3 First opcode set

```text
0x0001 SYS_GET_INFO
0x0101 TIMER_SET
0x0102 TIMER_CANCEL
0x0201 GPIO_GET
0x0202 GPIO_SET
0x0301 CONFIG_GET
0x0302 CONFIG_SET
```

### 9.4 Error code ranges

```text
0      OK
-1xx   guest ABI / pointer / encoding errors
-2xx   capability and resource errors
-3xx   hardware and driver errors
-4xx   timing, busy, timeout, queue errors
-5xx   bundle, profile, activation errors
-9xx   internal shell errors
```

### 9.5 Acceptance criteria

```text
- guest can log through wdc_log
- guest can read monotonic time
- guest can request random bytes
- guest can call host_call with valid request
- invalid guest pointers are rejected
- oversized request is rejected
- unsupported opcode is rejected
- guest SDK example compiles and runs
```

### 9.6 Contract tests

Add host-machine tests for:

```text
- all error code names and numeric values
- valid pointer / invalid pointer / overflow pointer
- zero-length request
- oversized request
- unsupported opcode
- too-small response buffer
- malformed request encoding
```

### 9.7 Exit gate

No hardware feature should be added until invalid memory and invalid request handling are boring, tested, and logged.

---

## 10. Milestone R4: Events, profile, and capabilities

### 10.1 Goal

Make the shell enforce logical resources and capabilities before hardware operations occur.

### 10.2 Deliverables

```text
- device profile parser
- logical resource registry
- resource ID assignment
- bundle capability parser
- capability check function
- event envelope format
- module_on_event dispatch
- event queue backpressure behavior
```

### 10.3 Event envelope v0

```text
field: abi_version
field: event_type
field: event_id
field: timestamp_ms
field: resource_id optional
field: payload bytes optional
```

### 10.4 Initial event types

```text
SYSTEM_BOOT
TIMER_FIRED
GPIO_CHANGED
CONFIG_CHANGED
MODULE_PROBATION_STARTED
MODULE_PROBATION_ENDING
```

### 10.5 Capability rules

Default rule:

```text
No declared capability means no access.
```

Examples:

```text
- GPIO_SET relay_1 is allowed only if manifest grants gpio.write:relay_1
- GPIO_GET button_1 is allowed only if manifest grants gpio.read:button_1
- CONFIG_SET app.threshold is allowed only if manifest grants config.write:app.*
- physical pin numbers are never exposed to the guest
```

### 10.6 Acceptance criteria

```text
- shell loads a profile with relay_1, status_led, button_1
- shell maps names to resource IDs
- guest manifest grants relay_1 but not status_led
- GPIO_SET relay_1 succeeds
- GPIO_SET status_led fails with capability denied
- request for unknown resource ID fails
- event is delivered to module_on_event
- guest trap during event handling is detected
```

### 10.7 Exit gate

The shell must be able to produce an audit record like:

```text
bundle=relay-controller@12
opcode=GPIO_SET
resource=relay_1
capability=gpio.write:relay_1
decision=allowed
result=OK
```

and for denial:

```text
bundle=relay-controller@12
opcode=GPIO_SET
resource=status_led
capability=gpio.write:status_led
decision=denied
result=ERR_CAPABILITY_DENIED
```

---

## 11. Milestone R5: Hardware MVP

### 11.1 Goal

Implement the minimum useful app-logic hardware surface.

### 11.2 Deliverables

```text
- GPIO read/write by logical resource
- GPIO input event generation
- debounce policy native-side
- timer set/cancel
- config get/set for app namespace
- one sensor abstraction
- physical action audit log
```

### 11.3 Recommended demo board resources

```text
relay_1       output, safe false
status_led    output, safe false
button_1      input_pullup, debounce 30 ms
temp_ambient  SHT31 or similar I2C sensor
```

### 11.4 Host-call opcodes added

```text
0x0401 SENSOR_READ
0x0501 DIAG_GET_COUNTERS
```

Optional but useful:

```text
0x0203 GPIO_PULSE
0x0303 CONFIG_DELETE
```

### 11.5 Acceptance criteria

```text
- button press event reaches WASM
- WASM toggles relay_1 by logical resource
- status LED can be controlled only if capability exists
- timer event reaches WASM
- config survives reboot
- sensor_read returns structured result or explicit timeout/error
- invalid sensor capability is denied
```

### 11.6 First vertical-slice demo

Guest app behavior:

```text
on SYSTEM_BOOT:
  log version
  set timer heartbeat every 1000 ms

on GPIO_CHANGED button_1 pressed:
  read current relay state
  toggle relay_1
  publish diagnostic log

on TIMER_FIRED heartbeat:
  toggle status_led if permitted
  health remains OK
```

### 11.7 Exit gate

A complete app behavior change must be possible by replacing only the WASM module in a local development flow.

---

## 12. Milestone R6: Bundle packaging and verification

### 12.1 Goal

Replace static embedded WASM with a signed bundle stored in flash.

### 12.2 Deliverables

```text
- bundle container format
- bundle manifest parser
- payload hash validation
- signature verification hook
- bundle compatibility checks
- wasm_a / wasm_b read path
- wasm_meta state record
- local install tool
- bundle inspect tool
```

### 12.3 Bundle container v0

Recommended binary layout:

```text
magic              8 bytes   "WDCBNDL\0"
container_version  u16
header_len         u16
manifest_len       u32
payload_len        u32
manifest_sha256    32 bytes
payload_sha256     32 bytes
signature_alg      u16
signature_len      u16
reserved           32 bytes
manifest_json      manifest_len bytes
payload_wasm       payload_len bytes
signature          signature_len bytes
```

The signature should cover:

```text
- fixed header fields except signature_len if needed
- manifest bytes
- payload bytes
- manifest hash
- payload hash
```

### 12.4 Manifest checks

The shell MUST reject the bundle if:

```text
- container magic is invalid
- manifest cannot be decoded
- manifest hash mismatch
- payload hash mismatch
- signature invalid
- ABI range unsupported
- target hardware mismatch
- required exports missing
- requested memory exceeds shell limit
- requested capabilities are not available in device profile
- bundle version violates anti-rollback policy
```

### 12.5 Slot metadata v0

```text
active_slot: A | B | none
last_good_slot: A | B | none
slot_a_state: empty | pending | confirmed | failed
slot_b_state: empty | pending | confirmed | failed
slot_a_version: u64
slot_b_version: u64
candidate_boot_count: u32
candidate_fault_count: u32
last_failure_reason: enum
metadata_generation: u32
metadata_crc: u32
```

### 12.6 Acceptance criteria

```text
- shell loads bundle from wasm_a
- shell rejects malformed bundle
- shell rejects unsupported ABI
- shell rejects invalid hash
- shell rejects invalid signature in production profile
- shell rejects manifest requesting unknown resource
- local install tool writes inactive slot
- inspect tool prints manifest and verification status
```

### 12.7 Exit gate

The static embedded WASM path may remain as a recovery/development path, but normal app startup must load from a bundle slot.

---

## 13. Milestone R7: WASM A/B activation and rollback

### 13.1 Goal

Implement the full WASM bundle update state machine with fallback.

### 13.2 State machine

```text
empty
  -> downloaded
  -> verified
  -> pending
  -> running_probation
  -> confirmed
```

Failure transitions:

```text
verified -> failed          if compatibility check fails late
pending -> failed           if boot attempt exceeds limit
running_probation -> failed if health fails, trap occurs, watchdog trips, or contract violations exceed threshold
failed -> empty             when overwritten
```

### 13.3 Activation flow

```text
1. active slot is A, confirmed
2. new bundle is written to B
3. B is verified
4. B is marked pending
5. shell reboots or restarts runtime into B
6. B enters running_probation
7. shell calls module_init
8. shell sends SYSTEM_BOOT event
9. shell periodically calls module_health
10. if health passes and no fatal faults occur, shell marks B confirmed and last_good
11. if B fails, shell marks B failed and returns to A
```

### 13.4 Health contract

For MVP:

```text
- module_init must return OK
- module_health must return OK while candidate is in probation
- guest must not trap
- guest must not exceed contract violation threshold
- guest must not cause repeated task watchdog resets
```

The shell decides confirmation. The guest only reports health.

### 13.5 Acceptance criteria

```text
- good candidate bundle becomes confirmed
- bad module_init candidate rolls back
- bad module_health candidate rolls back
- trapping candidate rolls back
- malformed candidate never activates
- reset during pending state rolls back or retries according to policy
- power loss while writing inactive slot does not corrupt active slot
- active confirmed bundle remains bootable after failed update
```

### 13.6 Fault-injection tests

```text
- erase part of inactive slot during write
- corrupt manifest byte
- corrupt payload byte
- corrupt metadata CRC
- candidate traps in module_init
- candidate traps in module_on_event
- candidate returns unhealthy
- candidate enters busy loop
- candidate repeatedly requests denied capability
- device resets before candidate confirmation
```

### 13.7 Exit gate

The project MVP is complete when this demo succeeds:

```text
1. Device boots confirmed bundle A.
2. Button toggles relay through WASM app logic.
3. Bundle B is installed locally.
4. Bundle B intentionally fails health.
5. Device reverts to bundle A.
6. Relay behavior from bundle A is restored.
7. Diagnostics show why B failed.
```

---

## 14. Milestone R8: Network-mediated app logic and remote bundle update

### 14.1 Goal

Add network functionality without exposing Wi-Fi credentials, TLS keys, raw sockets, or connection policy to the guest.

### 14.2 Deliverables

```text
- native Wi-Fi manager
- network status events
- MQTT client native-side
- MQTT publish host call
- optional MQTT subscribe event path
- HTTP request host call
- remote bundle download client
- update manifest fetch path
- TLS materials owned by shell
```

### 14.3 Host-call opcodes added

```text
0x0601 NET_STATUS
0x0602 MQTT_PUBLISH
0x0603 MQTT_SUBSCRIBE
0x0604 HTTP_REQUEST
```

### 14.4 Network event types added

```text
NET_CONNECTED
NET_DISCONNECTED
MQTT_CONNECTED
MQTT_DISCONNECTED
MQTT_MESSAGE
HTTP_RESPONSE
BUNDLE_DOWNLOAD_PROGRESS
BUNDLE_DOWNLOAD_COMPLETE
```

### 14.5 Guest restrictions

The guest MUST NOT access:

```text
- Wi-Fi SSID/password
- TLS private keys
- root certificate storage
- raw sockets
- arbitrary outbound hosts unless allowed by policy
- native MQTT client handle
```

### 14.6 Acceptance criteria

```text
- shell connects to Wi-Fi without guest involvement
- guest receives NET_CONNECTED event
- guest publishes telemetry through MQTT_PUBLISH
- shell enforces topic prefix or topic allowlist
- HTTP_REQUEST can be allowed or denied by manifest policy
- remote bundle downloads into inactive slot only
- failed remote download leaves active bundle untouched
```

### 14.7 Exit gate

A remotely delivered good WASM bundle can be downloaded, verified, activated, confirmed, and used without native firmware replacement.

---

## 15. Milestone R9: Hardening and production profile

### 15.1 Goal

Move from prototype behavior to production-shaped behavior.

### 15.2 Deliverables

```text
- production build profile
- development build profile
- secure bundle verification mandatory in production
- anti-rollback version policy
- crash breadcrumb persistence
- watchdog fault classification
- host-call rate limits
- event queue overflow policy
- diagnostic export path
- structured action audit log
- manufacturing/provisioning hooks
```

### 15.3 Production profile rules

Production builds SHOULD enforce:

```text
- unsigned bundles rejected
- debug backdoor disabled
- raw test opcodes disabled
- profile mutation restricted
- bundle anti-rollback enabled
- flash metadata integrity checks enabled
- OTA endpoint allowlist enabled
- guest memory ceilings enforced
- watchdog rollback enabled
```

### 15.4 Development profile allowances

Development builds MAY allow:

```text
- unsigned local bundles
- verbose logs
- serial install
- static embedded test bundle
- fault-injection commands
- host-call trace dump
```

Development allowances MUST be compile-time or provisioning-time explicit. They should not accidentally ship in production.

### 15.5 Hardening tests

```text
- malformed bundle corpus
- malformed host_call request corpus
- invalid pointer fuzz
- event queue saturation
- metadata corruption
- repeated rollback loop
- low-memory conditions
- Wi-Fi drop during update
- MQTT reconnect storms
- power loss during slot write
- power loss during metadata commit
- guest busy loop
- guest excessive logging
- guest excessive host calls
```

### 15.6 Acceptance criteria

```text
- all production rejection paths are logged
- all rollback causes are distinguishable
- no malformed bundle reaches module_init
- active confirmed slot survives interrupted update
- guest cannot access undeclared resources
- guest cannot use physical pins directly
- guest cannot read credentials
- bad bundle cannot permanently brick app layer
```

---

## 16. Milestone R10: Expansion features

### 16.1 BLE app logic

Add BLE only after the base contract is stable.

Recommended shape:

```text
- native shell owns BLE stack
- device profile declares BLE services/chars
- guest can set characteristic values
- guest can notify permitted characteristic
- guest receives BLE_WRITE event
- guest cannot construct arbitrary GATT database in MVP
```

Potential opcodes:

```text
0x0701 BLE_SET_VALUE
0x0702 BLE_NOTIFY
0x0703 BLE_GET_CONNECTION_STATE
```

### 16.2 AoT bundle option

Add AoT only after interpreter behavior is stable.

Requirements:

```text
- manifest declares payload kind: wasm | aot
- manifest declares runtime compatibility
- shell rejects AoT payload built for incompatible target/runtime
- test vectors cover interpreter and AoT payloads separately
```

### 16.3 Live hot-swap

Reboot-based activation is preferred for MVP. Live hot-swap can be added later if needed.

Live hot-swap requires:

```text
- graceful module_shutdown
- timer cancellation
- request draining
- network subscription cleanup
- resource lease cleanup
- runtime teardown verification
- new runtime startup
- fallback if replacement fails
```

### 16.4 Raw constrained bus access

Raw I2C/SPI access should remain deferred unless there is a clear need.

If added, require:

```text
- per-device allowlist
- max transaction length
- max bus frequency
- max timeout
- allowed register range, where possible
- no arbitrary pin selection
```

---

## 17. MVP definition

The MVP is not “all peripherals exposed.”

The MVP is:

```text
- ESP32-S3 native shell boots safely
- WASM runtime loads bundle from flash
- ABI v0 imports/exports work
- host_call validates pointers and lengths
- device profile maps logical resources to hardware
- manifest grants capabilities
- GPIO/timer/config/sensor basics work
- WASM receives events and requests actions
- A/B WASM bundle slots work
- bad bundle rolls back to last confirmed bundle
- diagnostics explain the decision path
```

Minimum MVP demo:

```text
1. Flash native shell once.
2. Install WASM bundle A.
3. Press button; relay toggles.
4. Install WASM bundle B that changes behavior.
5. Confirm behavior changed without native firmware update.
6. Install WASM bundle C that fails health.
7. Device rolls back to B or A according to last-good policy.
8. Logs show failure reason and active bundle identity.
```

---

## 18. Critical path

The critical path is:

```text
ESP-IDF shell boot
  -> WAMR lifecycle call
  -> ABI pointer-safe host calls
  -> event queue
  -> capability/resource mapping
  -> GPIO vertical slice
  -> bundle slot loading
  -> candidate activation
  -> rollback
  -> network download
```

Anything not on this path should be deferred until after R7.

Defer these until the boundary is proven:

```text
- BLE
- AoT
- live hot-swap
- raw SPI
- complex sensor drivers
- full remote management console
- app marketplace concepts
- multi-bundle scheduling
- WASI compatibility
```

---

## 19. First implementation commits

A practical first commit sequence:

```text
1. Add ESP-IDF project skeleton and partitions.csv.
2. Add WDC specs and ABI header.
3. Add shell_main with version/reset logging and no-bundle mode.
4. Add event queue component and internal test event.
5. Add WAMR component integration.
6. Add embedded no-op WASM module and lifecycle call path.
7. Add wdc_log and wdc_millis imports.
8. Add host_call dispatcher with unsupported-opcode response.
9. Add pointer/length validation tests.
10. Add Rust guest SDK hello-world module.
11. Add device profile parser with hardcoded development profile fallback.
12. Add GPIO_SET/GPIO_GET for logical resources.
13. Add button event and relay toggle example.
14. Add bundle container parser.
15. Add wasm_a/wasm_b slot loading.
16. Add local bundle install tool.
17. Add pending/confirmed metadata.
18. Add module_health probation.
19. Add rollback on failed health.
20. Add fault-injection bad bundle examples.
```

---

## 20. Test strategy

### 20.1 Contract tests

Run off-device where possible.

```text
- ABI constants match guest SDK
- error codes match spec
- event encoding golden vectors
- host_call request/response golden vectors
- manifest compatibility checks
- capability decision matrix
```

### 20.2 Firmware unit tests

```text
- metadata state transitions
- profile parser
- manifest parser
- hash validation
- capability matching
- resource lookup
- queue overflow policy
```

### 20.3 Hardware-in-loop tests

```text
- boot no-bundle mode
- load valid bundle
- GPIO output safe defaults
- button event delivery
- relay toggle through guest logic
- timer delivery
- sensor read
- watchdog fault path
```

### 20.4 OTA and power-loss tests

```text
- interrupted bundle write
- interrupted metadata write
- reset during pending candidate
- reset during probation
- corrupted inactive slot
- corrupted active metadata with intact last-good bundle
- Wi-Fi loss during remote download
```

### 20.5 Security-negative tests

```text
- unsigned bundle in production profile
- invalid signature
- valid signature but wrong target hardware
- valid signature but unsupported ABI
- manifest requests unknown resource
- manifest requests excessive memory
- guest requests denied resource
- guest passes invalid pointer
- guest passes oversized buffer
- guest loops or starves event processing
```

---

## 21. Diagnostics requirements by milestone

| Milestone | Required diagnostics |
|---|---|
| R1 | boot ID, reset reason, shell version, safe-default status |
| R2 | runtime init result, export lookup result, guest trap reason if available |
| R3 | host-call opcode, result, pointer validation failures |
| R4 | capability decision records, resource lookup failures |
| R5 | physical action audit records |
| R6 | bundle verification status, manifest summary, slot state |
| R7 | activation attempt, health result, rollback reason |
| R8 | network status, download progress, download failure reason |
| R9 | persistent crash breadcrumbs, fault counters, production rejection logs |

A field debugging record should answer:

```text
- which shell build is running?
- which bundle is active?
- which bundle was attempted?
- why was a bundle rejected or rolled back?
- what physical actions did the app request?
- were they allowed or denied?
- what reset or watchdog event occurred?
```

---

## 22. Implementation guardrails

### 22.1 Keep the ABI narrow

Do not add host calls just because ESP-IDF exposes them. Add host calls only when app logic needs a capability.

### 22.2 Prefer logical resources

The guest should not know physical pins, bus numbers, credentials, native handles, or partition names.

### 22.3 Validate before execute

The shell should validate request shape, resource identity, capability, hardware state, and response capacity before any physical action.

### 22.4 Log physical actions

Any operation that changes the physical world should be auditable.

Examples:

```text
- GPIO_SET
- BLE_NOTIFY
- MQTT_PUBLISH if externally meaningful
- CONFIG_SET
- actuator commands
```

### 22.5 Make fallback boring

Rollback should be a normal state transition, not an exceptional panic path.

### 22.6 Do not overfit to one app

The first app can be relay-toggle simple, but the contract should support other app logic without leaking board-specific details.

---

## 23. Risk register

| Risk | Impact | Mitigation |
|---|---|---|
| ABI grows into ESP-IDF clone | High | dispatcher + opcode review + capability model |
| Bundle rollback corrupts active app | High | inactive-slot writes only + metadata commit protocol |
| Guest busy loop starves shell | High | dedicated task, watchdog policy, probation rollback |
| Invalid pointer causes native fault | High | centralized pointer validation before decoding |
| Capability checks inconsistent | High | single enforcement function + decision matrix tests |
| Metadata corruption bricks app layer | Medium | CRC/generation records + last-good fallback |
| Flash wear from frequent updates | Medium | slot-level writes, wear-aware metadata, rate limits |
| Diagnostics too weak for field issues | Medium | persistent breadcrumbs and action audit logs from R1 onward |
| BLE complexity delays MVP | Medium | defer BLE until R10 |
| AoT compatibility issues | Medium | interpreter first, AoT manifest fields later |
| App SDK diverges from native ABI | High | golden vectors shared by firmware and guest SDK |

---

## 24. Open implementation questions

These should be resolved before or during R3/R6:

```text
1. Event/request encoding: deterministic CBOR or custom TLV?
2. Signature algorithm and key format?
3. Maximum WASM memory for first hardware target?
4. Should resource IDs be assigned by manifest, profile, or shell at load time?
5. Should CONFIG_SET be synchronous or journaled?
6. What is the exact probation confirmation rule?
7. What counts as a fatal contract violation?
8. How much diagnostic history should survive reboot?
9. Is local serial bundle install required in production, development only, or never?
10. Should remote update policy live in shell config, device profile, or provisioning data?
```

Recommended defaults:

```text
- Use deterministic CBOR first unless code size becomes a problem.
- Use shell-assigned resource IDs derived from profile + manifest at load time.
- Make CONFIG_SET synchronous for MVP.
- Confirm candidate only after init OK, health OK, and no fatal faults during probation.
- Treat invalid pointers, malformed requests, and denied capabilities as nonfatal initially, but count them.
- Treat guest traps, repeated health failures, and watchdog resets as fatal during probation.
```

---

## 25. Versioning policy

### 25.1 Shell versions

Shell versions identify native firmware behavior.

```text
shell_version = major.minor.patch
```

### 25.2 ABI versions

ABI versions identify the guest-host contract.

```text
abi_major: breaking semantic or binary change
abi_minor: compatible opcode/event addition
abi_patch: clarification or bugfix that does not change guest behavior
```

### 25.3 Bundle versions

Bundle versions identify application behavior and anti-rollback ordering.

```text
bundle_version: monotonically increasing integer per app identity
```

### 25.4 Compatibility rule

A bundle may run only if:

```text
bundle.abi_min <= shell.abi_version <= bundle.abi_max
```

and:

```text
bundle.target includes current device class / board revision
```

and:

```text
bundle capabilities are a subset of device profile resources and shell policy.
```

---

## 26. Definition of done for production candidate

A production candidate exists when:

```text
- native shell OTA and WASM bundle OTA are separate paths
- production build rejects unsigned bundles
- app bundle rollback is demonstrated under fault injection
- no-bundle safe mode works
- bad-bundle safe mode works
- all app physical actions pass capability enforcement
- diagnostic records survive reboot
- app SDK has at least one stable language binding
- contract tests run in CI
- hardware-in-loop tests cover the golden path
- security-negative tests cover invalid signatures, wrong ABI, and denied capabilities
- field update process is documented
```

---

## 27. Roadmap success criteria

The roadmap succeeds if, after the MVP, the team can say:

```text
We can change device behavior over the air by replacing a signed WASM bundle.
The native firmware remains the trust boundary.
The app cannot access undeclared resources.
A faulty app update rolls back to a known-good bundle.
A field log explains what happened.
The ABI is small enough to audit.
```

That is the product-defining capability.


---

## R9 and host-platform status note

The scaffold has implemented the roadmap through R9, added hardening passes
R8.1 and R8.2, closed the HP1–HP5 host-platform source authorities, and
implemented the HP5.5 dual-board execution/evidence harness. HP5.5 remains a
physical acceptance barrier: source readiness is not the two-board result.
The next recommended work is not broad feature expansion; it is the frozen
physical campaign and production hardening:

```text
1. Execute and accept HP5.5 on the exact AITRIP S3 N8R2 and XIAO C6 boards.
2. Wire production signature verification and credential/key lifecycle to vetted crypto.
3. Preserve the existing accepted safe-state/rollback evidence and extend only through explicit campaigns.
4. Keep HP6 thin external provider work blocked until HP5.5 acceptance.
5. After HP6, implement HP7 MQTT customer zero and the HP7.5 MQTT adversarial dual-board seal.
6. Finish with HP8 external conformance and reconciliation.
```

See `docs/STATUS.md`, `docs/TESTING.md`, and `docs/runbooks/HARDWARE_BRINGUP.md` for current bounded gaps.
