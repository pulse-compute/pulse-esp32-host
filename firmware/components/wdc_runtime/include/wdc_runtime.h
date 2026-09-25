#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "wdc_abi.h"
#include "wdc_events.h"

#ifdef __cplusplus
extern "C" {
#endif

#define WDC_RUNTIME_ERROR_MAX 128u

#define WDC_RUNTIME_DEFAULT_INSTANCE_STACK_BYTES  (16u * 1024u)
#define WDC_RUNTIME_DEFAULT_HOST_HEAP_BYTES       (64u * 1024u)
#define WDC_RUNTIME_DEFAULT_EXEC_STACK_BYTES      (16u * 1024u)
#define WDC_RUNTIME_DEFAULT_MAX_MODULE_BYTES      (256u * 1024u)
#define WDC_RUNTIME_DEFAULT_MAX_EVENT_BYTES       WDC_MAX_EVENT_BYTES_DEFAULT

typedef enum WdcRuntimeOutcome {
    WDC_RUNTIME_OUTCOME_NOT_STARTED = 0,
    WDC_RUNTIME_OUTCOME_OK = 1,
    WDC_RUNTIME_OUTCOME_RUNTIME_INIT_FAILED = 2,
    WDC_RUNTIME_OUTCOME_BUNDLE_LOAD_FAILED = 3,
    WDC_RUNTIME_OUTCOME_INSTANTIATE_FAILED = 4,
    WDC_RUNTIME_OUTCOME_EXEC_ENV_FAILED = 5,
    WDC_RUNTIME_OUTCOME_EXPORT_MISSING = 6,
    WDC_RUNTIME_OUTCOME_GUEST_TRAPPED = 7,
    WDC_RUNTIME_OUTCOME_GUEST_NON_OK_STATUS = 8,
    WDC_RUNTIME_OUTCOME_INVALID_PAYLOAD = 9,
    WDC_RUNTIME_OUTCOME_INVALID_STATE = 10,
} WdcRuntimeOutcome;

typedef enum WdcRuntimeBackend {
    WDC_RUNTIME_BACKEND_HOST_STUB = 0,
    WDC_RUNTIME_BACKEND_WAMR = 1,
} WdcRuntimeBackend;

typedef struct WdcRuntimeConfig {
    uint32_t instance_stack_bytes;
    uint32_t host_heap_bytes;
    uint32_t exec_stack_bytes;
    uint32_t max_module_bytes;
    uint32_t max_event_bytes;
    bool require_all_exports;
} WdcRuntimeConfig;

typedef struct WdcRuntimeReport {
    WdcRuntimeOutcome outcome;
    int32_t last_status;
    WdcRuntimeBackend backend;
    bool runtime_initialized;
    bool module_loaded;
    bool module_instantiated;
    bool exports_resolved;
    bool init_called;
    bool on_event_called;
    bool health_called;
    bool shutdown_called;
    uint32_t module_size;
    uint32_t init_result;
    uint32_t on_event_result;
    uint32_t health_result;
    uint32_t shutdown_result;
    char error[WDC_RUNTIME_ERROR_MAX];
} WdcRuntimeReport;

#ifndef ESP_PLATFORM
typedef int32_t (*WdcRuntimeHostStubEventFn)(void *ctx,
                                             const uint8_t *event_cbor,
                                             uint32_t event_len);
#endif

typedef struct WdcRuntime {
    WdcRuntimeConfig config;
    WdcRuntimeReport report;
    const uint8_t *wasm_bytes;
    uint32_t wasm_len;
    void *backend_runtime;
    void *backend_wasm_buffer;
    void *backend_module;
    void *backend_module_inst;
    void *backend_exec_env;
    void *backend_func_init;
    void *backend_func_on_event;
    void *backend_func_health;
    void *backend_func_shutdown;
#ifndef ESP_PLATFORM
    WdcRuntimeHostStubEventFn host_stub_event_fn;
    void *host_stub_event_ctx;
#endif
} WdcRuntime;

WdcRuntimeConfig wdc_runtime_default_config(void);
const char *wdc_runtime_outcome_name(WdcRuntimeOutcome outcome);

int32_t wdc_runtime_init(WdcRuntime *runtime, const WdcRuntimeConfig *config);
int32_t wdc_runtime_load_static(WdcRuntime *runtime, const uint8_t *wasm_bytes, uint32_t wasm_len);
int32_t wdc_runtime_lookup_exports(WdcRuntime *runtime);
int32_t wdc_runtime_call_init(WdcRuntime *runtime);
int32_t wdc_runtime_call_on_event(WdcRuntime *runtime, uint32_t event_ptr, uint32_t event_len);
int32_t wdc_runtime_call_event_cbor(WdcRuntime *runtime, const uint8_t *event_cbor, uint32_t event_len);
int32_t wdc_runtime_dispatch_event(WdcRuntime *runtime, const WdcEvent *event);
#ifndef ESP_PLATFORM
void wdc_runtime_set_host_stub_event_hook(WdcRuntime *runtime,
                                          WdcRuntimeHostStubEventFn fn,
                                          void *ctx);
#endif
int32_t wdc_runtime_call_health(WdcRuntime *runtime);
int32_t wdc_runtime_call_shutdown(WdcRuntime *runtime, int32_t reason);
void wdc_runtime_teardown(WdcRuntime *runtime);

int32_t wdc_runtime_run_static_smoke(const WdcRuntimeConfig *config,
                                     const uint8_t *wasm_bytes,
                                     uint32_t wasm_len,
                                     WdcRuntimeReport *out_report);

const WdcRuntimeReport *wdc_runtime_get_report(const WdcRuntime *runtime);
void wdc_runtime_copy_report(const WdcRuntime *runtime, WdcRuntimeReport *out_report);

#ifdef __cplusplus
}
#endif
