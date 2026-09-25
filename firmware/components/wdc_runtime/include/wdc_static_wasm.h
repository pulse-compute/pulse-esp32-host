#pragma once

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

extern const uint8_t wdc_static_hello_wasm[];
extern const uint32_t wdc_static_hello_wasm_len;
extern const uint8_t wdc_static_missing_shutdown_wasm[];
extern const uint32_t wdc_static_missing_shutdown_wasm_len;
extern const uint8_t wdc_static_init_fail_wasm[];
extern const uint32_t wdc_static_init_fail_wasm_len;
extern const uint8_t wdc_static_health_fail_wasm[];
extern const uint32_t wdc_static_health_fail_wasm_len;
extern const uint8_t wdc_static_init_trap_wasm[];
extern const uint32_t wdc_static_init_trap_wasm_len;
extern const uint8_t wdc_static_event_trap_wasm[];
extern const uint32_t wdc_static_event_trap_wasm_len;
extern const uint8_t wdc_static_event_fail_wasm[];
extern const uint32_t wdc_static_event_fail_wasm_len;
extern const uint8_t wdc_hx4_event_effect_wasm[];
extern const uint32_t wdc_hx4_event_effect_wasm_len;

#ifdef __cplusplus
}
#endif
