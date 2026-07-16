idf_component_register(
    SRCS "wdc_runtime.c" "wdc_static_wasm.c"
    INCLUDE_DIRS "include"
    REQUIRES wdc_abi wdc_diag wdc_events wdc_events
    PRIV_REQUIRES wasm-micro-runtime esp_timer esp_hw_support freertos
)
