# Glossary

| Term | Meaning |
|---|---|
| ABI | Binary interface between WASM guest and native host. |
| Administrative plane | Host-private authority for status, application staging, recovery, and reboot handoff; it is not an application route or capability. |
| Administration session | One volatile, fixed-storage HP4.1 authorization and replay context issued by the host-private authorizer; it is not transport-owned. |
| Authenticated entry | Fixed host-private record issued by a replaceable authorizer after transport input passes identity, expiry, privilege, and channel-binding policy. |
| Activation | Process of selecting and running a bundle slot. |
| Application artifact | HP3 fixed 192-byte header plus an existing signed WDC bundle, stored in a Pulse application slot. |
| App-running | Safety state in which guest-originated effectful operations may be allowed. |
| Bundle | Container with manifest, WASM payload, and signature block. |
| Candidate | Newly activated bundle not yet confirmed healthy. |
| Capability | Manifest-granted permission for a logical resource and operation. |
| Confirmed | Bundle state after shell-owned health confirmation. |
| Device profile | Native-side description of physical resources and policies. |
| Effectful call | Host call that changes physical, persistent, or network state. |
| Guest | WASM application module. |
| Host | Native ESP-IDF shell. |
| Host build lock | Exact replayable record of one resolved board/profile/environment/source realization. |
| Host profile | Versioned host capability and resource-limit contract, distinct from board identity and application intent. |
| Last good | Confirmed slot used as fallback during rollback. |
| Metadata journal | Two host-owned records whose valid highest generation selects application state; the record commit marker is written last. |
| Manifest | Bundle metadata describing requested authority, limits, payload hash, target, and signature. |
| Native extension | Provider-selected owner-trusted but fault-prone target ELF admitted and supervised by the experimental HX spine. |
| No-bundle mode | Safety state entered when no runnable bundle is available. |
| Probation | Period when candidate bundle runs before confirmation. |
| Preaccept rejection | Administrative rejection before replay and HP1 command ownership commit; it consumes neither the one-command capacity nor replay state. |
| Recovery | Explicit host outcome when neither application slot is viable; it does not guess or enter application code. |
| Reboot handoff | Terminal volatile HP4 state that returns durable application choice to the existing HP3 boot selector. |
| Profile | See device profile. |
| Resource ID | Stable numeric ID for a logical resource. Not a physical pin number. |
| Rollback | Returning from failed candidate to last-good slot. |
| Running-host fingerprint | Fixed build-derived record carrying exact lock identity and the semantic surface used for prelaunch compatibility. |
| Reset required | Latched native-extension state where clean teardown is unconfirmed and reset is the authoritative hard boundary. |
| Shell | Native trusted supervisor firmware. |
| Serial normalizer | Allocation-free HP4.1 adapter that incrementally converts a bounded length-prefixed serial frame into one transport-neutral request; it has no authorization authority. |
| Slot | Persistent storage region such as `wasm_a` or `wasm_b`. |
| Trial | Verified replacement selected under host-owned boot attribution and probation but not yet durably confirmed. |
| Target intent | Provider-normalized, implementation-neutral application compatibility and bounded-resource requirements. |
| WAMR | WebAssembly Micro Runtime integration target. |
| WASM | WebAssembly payload containing app logic. |
