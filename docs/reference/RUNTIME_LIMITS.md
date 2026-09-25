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

## Native-extension proof budgets

HX3 separately admits one target-native refinement task, a 4,096-byte stack,
3,072 bytes of static state/control backing, and one four-by-64-byte static
queue. The ELF inspector verifies the allocated writable sections fit the
declared 7,424-byte combined backing before relocation. These are extension
proof budgets, not Wasm manifest limits, and their target heap effect remains
unmeasured without hardware. See
[HX3 extension lifecycle](../HX3_EXTENSION_LIFECYCLE.md).

## HP1 host-control and admission budgets

HP1 adds a lower host-owned gate before guest runtime limits are installed. The
C6 minimum profile reserves 98,304 bytes for fixed task stacks, static
queue/ticket state, metadata, administration, verification, and recovery. It
then checks normal, quiesce-transition, and exclusive-update totals plus the
largest contiguous internal block. The application cannot request a priority
or unbounded allocation. S3 external memory must be declared and produces a
non-portable admission classification; it never reduces the internal control
reserve. See [HP1 resource authority](../HP1_HOST_KERNEL_RESOURCE_AUTHORITY.md).

## HP4 protected-administration bounds

HP4.0 freezes a separate host-private budget: one session, one accepted
command, a 2,048-byte transport frame, 1,024-byte payload/stream chunk,
1,024-byte status response, 64-byte terminal record, and 32 fixed 160-byte
audit records. Quiescence is bounded to 10 seconds; command, stream-idle, and
session-idle windows are 30 seconds; session and update transactions are
bounded to 15 minutes. These values fit inside the existing HP1
administration/control plan and do not increase the 98,304-byte reserve.

HP4.1 demonstrates the fixed storage and rate/replay behavior in host-native
execution: the observed 7,712-byte core plus 2,072-byte serial adapter totals
9,784 bytes, below HP1's 12,288-byte administration reserve. This is not a
target linker/RAM observation, UART execution result, or production
authentication/cryptography qualification.

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
