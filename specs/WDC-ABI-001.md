# WDC ABI 001 — ABI v1.0 Reference

**Status:** R9 scaffold reference  
**Applies to:** ESP32-S3 WDC shell through R9  
**Encoding:** deterministic CBOR map subset for events, requests, and responses  
**Primary source of truth:** `firmware/components/wdc_abi/include/wdc_abi.h`  
**Expanded human reference:** `docs/reference/ABI_REFERENCE.md`

## Summary

The ABI is intentionally narrow. The guest imports only primitive system calls plus one dispatcher, and the native shell validates every guest request before execution.

```text
Guest imports module: wdc
Required imports: wdc_log, wdc_millis, wdc_random, wdc_yield, wdc_host_call
Required exports: wdc_module_init, wdc_module_on_event, wdc_module_health, wdc_module_shutdown
ABI: 1.0
```

## Required imports

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

```c
int32_t wdc_module_init(void);
int32_t wdc_module_on_event(uint32_t event_ptr, uint32_t event_len);
int32_t wdc_module_health(void);
int32_t wdc_module_shutdown(int32_t reason);
```

## Compatibility rule

```text
guest.abi.major == shell.abi.major
AND guest.abi.min_minor <= shell.abi.minor
AND guest.abi.max_minor >= shell.abi.minor
```

## Safety rule

All effectful operations must pass through the host-call safety pipeline:

```text
pointer/length validation
  -> CBOR validation
  -> opcode validation
  -> fail-closed authorizer
  -> safety state
  -> capability check
  -> profile policy check
  -> runtime limit check
  -> native execution
```

## Status codes and opcodes

See `docs/reference/ABI_REFERENCE.md` for the current full table. The canonical constants remain in `wdc_abi.h`.


---

## R9 implementation note

The R9 scaffold implements ABI 1.0 host-side validation and dispatch for the safety-boundary prototype. The most important implemented behavior is fail-closed authorization for effectful calls, manifest-derived request/response/event limits, and native-mediated GPIO/network operations.

Canonical implementation references:

```text
firmware/components/wdc_abi/include/wdc_abi.h
firmware/components/wdc_abi/wdc_host_call.c
guest-sdk/rust/wdc_guest/src/abi.rs
guest-sdk/c/include/wdc_guest.h
docs/reference/ABI_REFERENCE.md
```
