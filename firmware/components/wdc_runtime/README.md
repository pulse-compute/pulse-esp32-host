# wdc_runtime

Runtime facade for loading and executing WASM app modules.

On ESP-IDF builds, this component is intended to use WAMR through the dependency declared in `idf_component.yml`. On host test builds, it uses a small WASM header/export scanner and static fixtures so contract tests can run without ESP-IDF or WAMR.

Implemented through R9:

- static WASM payload fixtures;
- runtime init/load/instantiate lifecycle facade;
- required lifecycle export lookup;
- `wdc_module_init`, `wdc_module_on_event`, `wdc_module_health`, `wdc_module_shutdown` call wrappers;
- event dispatch status handling;
- active runtime limit handoff from manifest-derived config;
- native import registration path for the `wdc` import module.

HX4 adds one deterministic, target-neutral Wasm fixture whose event handler
requests a sealed extension operation through the existing `wdc_host_call`
import. The host stub exposes a test-only event hook so the C contract smoke can
exercise ownership and completion semantics; Node separately executes the
exact committed Wasm bytes.

On ESP-IDF, verified immutable Wasm input is copied to explicit internal
writable storage before `wasm_runtime_load`. WAMR may modify that buffer and
retain references to it, so the runtime releases the copy only after
`wasm_runtime_unload`.

Deployment work remaining:

- run real WAMR on ESP32-S3;
- bind manifest memory/stack/time limits to target runtime settings;
- validate behavior under PSRAM/internal-RAM pressure.
