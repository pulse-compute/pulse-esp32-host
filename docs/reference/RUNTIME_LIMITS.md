# Runtime limits

## Why limits matter

A verified bundle can still be unsafe if it consumes too much memory, sends oversized requests, or receives events larger than the runtime can safely process. R8.2 tightened the link between manifest-declared limits and active runtime behavior.

## Manifest limits

The example manifest declares:

```json
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
}
```

## Enforced in R8.2

R8.2 derives active runtime config from the verified manifest and enforces:

- max event size before dispatching to WASM;
- max host-call request size;
- max host-call response size;
- clearing limits when the app is torn down;
- avoiding stale rate-limit windows on app-running transition.

## Not fully enforced yet

The following are specified or represented, but need target/runtime-backed enforcement before deployment:

- WAMR linear memory maximum allocation behavior on ESP32-S3;
- stack size enforcement tied to actual runtime instantiation;
- lifecycle timeout enforcement with target watchdog/task integration;
- max outstanding async requests for real network operations.

## Limit-change process

When changing limits:

1. Update the manifest schema if needed.
2. Update verifier policy bounds.
3. Update `wdc_app` runtime-limit derivation.
4. Update `wdc_runtime` and `wdc_abi` enforcement paths.
5. Add tests for under-limit and over-limit cases.
6. Confirm the limit is logged in active app boot reports.
7. Run memory-pressure tests on hardware.

## Recommended production stance

Start with conservative defaults. A small app-logic bundle should not need large requests or responses. Prefer async chunked patterns for larger data instead of expanding host-call buffers broadly.
