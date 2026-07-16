# wdc_abi

ABI 1.0 constants, deterministic-CBOR helpers, guest-memory pointer validation, and the native host-call dispatcher.

Boundary responsibilities:

- validate guest pointers and lengths;
- enforce active request/response limits;
- decode host-call request maps;
- fail closed when an authorizer is required but absent;
- route safe unauthenticated calls explicitly;
- invoke capability/safety/profile-aware execution paths;
- encode bounded responses;
- expose canonical status/opcode/key constants.

Primary files:

```text
include/wdc_abi.h
include/wdc_cbor.h
include/wdc_guest_memory.h
wdc_host_call.c
wdc_pointer.c
wdc_cbor.c
wdc_errors.c
```
