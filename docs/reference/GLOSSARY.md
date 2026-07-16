# Glossary

| Term | Meaning |
|---|---|
| ABI | Binary interface between WASM guest and native host. |
| Activation | Process of selecting and running a bundle slot. |
| App-running | Safety state in which guest-originated effectful operations may be allowed. |
| Bundle | Container with manifest, WASM payload, and signature block. |
| Candidate | Newly activated bundle not yet confirmed healthy. |
| Capability | Manifest-granted permission for a logical resource and operation. |
| Confirmed | Bundle state after shell-owned health confirmation. |
| Device profile | Native-side description of physical resources and policies. |
| Effectful call | Host call that changes physical, persistent, or network state. |
| Guest | WASM application module. |
| Host | Native ESP-IDF shell. |
| Last good | Confirmed slot used as fallback during rollback. |
| Manifest | Bundle metadata describing requested authority, limits, payload hash, target, and signature. |
| No-bundle mode | Safety state entered when no runnable bundle is available. |
| Probation | Period when candidate bundle runs before confirmation. |
| Profile | See device profile. |
| Resource ID | Stable numeric ID for a logical resource. Not a physical pin number. |
| Rollback | Returning from failed candidate to last-good slot. |
| Shell | Native trusted supervisor firmware. |
| Slot | Persistent storage region such as `wasm_a` or `wasm_b`. |
| WAMR | WebAssembly Micro Runtime integration target. |
| WASM | WebAssembly payload containing app logic. |

