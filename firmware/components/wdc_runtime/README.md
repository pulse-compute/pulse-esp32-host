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

Deployment work remaining:

- run real WAMR on ESP32-S3;
- bind manifest memory/stack/time limits to target runtime settings;
- validate behavior under PSRAM/internal-RAM pressure.
