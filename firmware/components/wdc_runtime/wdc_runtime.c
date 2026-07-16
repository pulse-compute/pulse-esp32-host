#include "wdc_runtime.h"

#include <inttypes.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>

#include "wdc_diag.h"
#include "wdc_events.h"

#ifdef ESP_PLATFORM
#include "esp_random.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "wasm_export.h"
#endif

#ifdef ESP_PLATFORM
static bool s_wamr_runtime_initialized;
#endif

static void wdc_runtime_set_error(WdcRuntime *runtime,
                                  WdcRuntimeOutcome outcome,
                                  int32_t status,
                                  const char *message)
{
    if (runtime == NULL) {
        return;
    }
    runtime->report.outcome = outcome;
    runtime->report.last_status = status;
    if (message == NULL) {
        message = "";
    }
    (void)snprintf(runtime->report.error, sizeof(runtime->report.error), "%s", message);
    if (status != WDC_OK && message[0] != '\0') {
        (void)wdc_diag_log(WDC_LOG_ERROR, message);
    }
}

static bool wdc_bytes_contains(const uint8_t *haystack,
                               uint32_t haystack_len,
                               const char *needle)
{
    if (haystack == NULL || needle == NULL) {
        return false;
    }
    const size_t needle_len = strlen(needle);
    if (needle_len == 0u || needle_len > haystack_len) {
        return false;
    }
    for (uint32_t i = 0u; i + needle_len <= haystack_len; ++i) {
        if (memcmp(&haystack[i], needle, needle_len) == 0) {
            return true;
        }
    }
    return false;
}

static int32_t wdc_host_meta_value(const uint8_t *wasm_bytes,
                                   uint32_t wasm_len,
                                   const char *key,
                                   int32_t default_value)
{
    if (wasm_bytes == NULL || key == NULL) {
        return default_value;
    }
    const size_t key_len = strlen(key);
    if (key_len == 0u || key_len + 1u >= wasm_len) {
        return default_value;
    }

    for (uint32_t i = 0u; i + key_len + 1u < wasm_len; ++i) {
        if (memcmp(&wasm_bytes[i], key, key_len) == 0 && wasm_bytes[i + key_len] == '=') {
            uint32_t j = i + (uint32_t)key_len + 1u;
            int32_t value = 0;
            bool saw_digit = false;
            while (j < wasm_len && wasm_bytes[j] >= '0' && wasm_bytes[j] <= '9') {
                saw_digit = true;
                value = (value * 10) + (int32_t)(wasm_bytes[j] - '0');
                j++;
            }
            return saw_digit ? value : default_value;
        }
    }
    return default_value;
}

static bool wdc_runtime_valid_wasm_magic(const uint8_t *wasm_bytes, uint32_t wasm_len)
{
    static const uint8_t k_magic[8] = {0x00u, 0x61u, 0x73u, 0x6du, 0x01u, 0x00u, 0x00u, 0x00u};
    return wasm_bytes != NULL && wasm_len >= sizeof(k_magic) && memcmp(wasm_bytes, k_magic, sizeof(k_magic)) == 0;
}

static void wdc_runtime_apply_default_config(WdcRuntimeConfig *config)
{
    if (config == NULL) {
        return;
    }
    if (config->instance_stack_bytes == 0u) {
        config->instance_stack_bytes = WDC_RUNTIME_DEFAULT_INSTANCE_STACK_BYTES;
    }
    if (config->host_heap_bytes == 0u) {
        config->host_heap_bytes = WDC_RUNTIME_DEFAULT_HOST_HEAP_BYTES;
    }
    if (config->exec_stack_bytes == 0u) {
        config->exec_stack_bytes = WDC_RUNTIME_DEFAULT_EXEC_STACK_BYTES;
    }
    if (config->max_module_bytes == 0u) {
        config->max_module_bytes = WDC_RUNTIME_DEFAULT_MAX_MODULE_BYTES;
    }
    if (config->max_event_bytes == 0u) {
        config->max_event_bytes = WDC_RUNTIME_DEFAULT_MAX_EVENT_BYTES;
    }
}

WdcRuntimeConfig wdc_runtime_default_config(void)
{
    WdcRuntimeConfig config = {
        .instance_stack_bytes = WDC_RUNTIME_DEFAULT_INSTANCE_STACK_BYTES,
        .host_heap_bytes = WDC_RUNTIME_DEFAULT_HOST_HEAP_BYTES,
        .exec_stack_bytes = WDC_RUNTIME_DEFAULT_EXEC_STACK_BYTES,
        .max_module_bytes = WDC_RUNTIME_DEFAULT_MAX_MODULE_BYTES,
        .max_event_bytes = WDC_RUNTIME_DEFAULT_MAX_EVENT_BYTES,
        .require_all_exports = true,
    };
    return config;
}

const char *wdc_runtime_outcome_name(WdcRuntimeOutcome outcome)
{
    switch (outcome) {
    case WDC_RUNTIME_OUTCOME_NOT_STARTED: return "not_started";
    case WDC_RUNTIME_OUTCOME_OK: return "ok";
    case WDC_RUNTIME_OUTCOME_RUNTIME_INIT_FAILED: return "runtime_init_failed";
    case WDC_RUNTIME_OUTCOME_BUNDLE_LOAD_FAILED: return "bundle_load_failed";
    case WDC_RUNTIME_OUTCOME_INSTANTIATE_FAILED: return "instantiate_failed";
    case WDC_RUNTIME_OUTCOME_EXEC_ENV_FAILED: return "exec_env_failed";
    case WDC_RUNTIME_OUTCOME_EXPORT_MISSING: return "export_missing";
    case WDC_RUNTIME_OUTCOME_GUEST_TRAPPED: return "guest_trapped";
    case WDC_RUNTIME_OUTCOME_GUEST_NON_OK_STATUS: return "guest_non_ok_status";
    case WDC_RUNTIME_OUTCOME_INVALID_PAYLOAD: return "invalid_payload";
    case WDC_RUNTIME_OUTCOME_INVALID_STATE: return "invalid_state";
    default: return "unknown";
    }
}

#ifdef ESP_PLATFORM
static int32_t wdc_wamr_native_log(wasm_exec_env_t exec_env,
                                   int32_t level,
                                   uint32_t ptr,
                                   uint32_t len)
{
    wasm_module_inst_t module_inst = wasm_runtime_get_module_inst(exec_env);
    if (module_inst == NULL) {
        return WDC_ERR_INVALID_STATE;
    }
    if (len >= WDC_DIAG_MESSAGE_MAX) {
        len = WDC_DIAG_MESSAGE_MAX - 1u;
    }
    if (len > 0u && !wasm_runtime_validate_app_addr(module_inst, ptr, len)) {
        return WDC_ERR_BAD_POINTER;
    }

    char msg[WDC_DIAG_MESSAGE_MAX];
    memset(msg, 0, sizeof(msg));
    if (len > 0u) {
        const void *native = wasm_runtime_addr_app_to_native(module_inst, ptr);
        if (native == NULL) {
            return WDC_ERR_BAD_POINTER;
        }
        memcpy(msg, native, len);
    }
    msg[sizeof(msg) - 1u] = '\0';
    return wdc_diag_log(level, msg);
}

static uint64_t wdc_wamr_native_millis(wasm_exec_env_t exec_env)
{
    (void)exec_env;
    return (uint64_t)(esp_timer_get_time() / 1000LL);
}

static int32_t wdc_wamr_native_random(wasm_exec_env_t exec_env, uint32_t ptr, uint32_t len)
{
    wasm_module_inst_t module_inst = wasm_runtime_get_module_inst(exec_env);
    if (module_inst == NULL) {
        return WDC_ERR_INVALID_STATE;
    }
    if (len > WDC_MAX_RESPONSE_BYTES_DEFAULT) {
        return WDC_ERR_BAD_LENGTH;
    }
    if (len > 0u && !wasm_runtime_validate_app_addr(module_inst, ptr, len)) {
        return WDC_ERR_BAD_POINTER;
    }
    uint8_t *native = (uint8_t *)wasm_runtime_addr_app_to_native(module_inst, ptr);
    if (len > 0u && native == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    for (uint32_t i = 0u; i < len; ++i) {
        uint32_t value = esp_random();
        native[i] = (uint8_t)(value & 0xffu);
    }
    return WDC_OK;
}

static int32_t wdc_wamr_native_yield(wasm_exec_env_t exec_env)
{
    (void)exec_env;
    vTaskDelay(0);
    return WDC_OK;
}

static int32_t wdc_wamr_native_host_call(wasm_exec_env_t exec_env,
                                         uint32_t opcode,
                                         uint32_t req_ptr,
                                         uint32_t req_len,
                                         uint32_t rsp_ptr,
                                         uint32_t rsp_cap)
{
    wasm_module_inst_t module_inst = wasm_runtime_get_module_inst(exec_env);
    if (module_inst == NULL) {
        return WDC_ERR_INVALID_STATE;
    }
    if (req_len > WDC_MAX_REQUEST_BYTES_DEFAULT || rsp_cap > WDC_MAX_RESPONSE_BYTES_DEFAULT) {
        return WDC_ERR_BAD_LENGTH;
    }
    if (req_len > 0u && !wasm_runtime_validate_app_addr(module_inst, req_ptr, req_len)) {
        return WDC_ERR_BAD_POINTER;
    }
    if (rsp_cap > 0u && !wasm_runtime_validate_app_addr(module_inst, rsp_ptr, rsp_cap)) {
        return WDC_ERR_BAD_POINTER;
    }

    const uint8_t *req = req_len > 0u ? (const uint8_t *)wasm_runtime_addr_app_to_native(module_inst, req_ptr) : NULL;
    uint8_t *rsp = rsp_cap > 0u ? (uint8_t *)wasm_runtime_addr_app_to_native(module_inst, rsp_ptr) : NULL;
    if ((req_len > 0u && req == NULL) || (rsp_cap > 0u && rsp == NULL)) {
        return WDC_ERR_BAD_POINTER;
    }
    uint32_t rsp_len = 0u;
    return wdc_host_call_dispatch(opcode, req, req_len, rsp, rsp_cap, &rsp_len);
}

static NativeSymbol s_wdc_native_symbols[] = {
    { WDC_IMPORT_LOG,       wdc_wamr_native_log,       "(iii)i", NULL },
    { WDC_IMPORT_MILLIS,    wdc_wamr_native_millis,    "()I",    NULL },
    { WDC_IMPORT_RANDOM,    wdc_wamr_native_random,    "(ii)i",  NULL },
    { WDC_IMPORT_YIELD,     wdc_wamr_native_yield,     "()i",    NULL },
    { WDC_IMPORT_HOST_CALL, wdc_wamr_native_host_call, "(iiiii)i", NULL },
};
#endif

int32_t wdc_runtime_init(WdcRuntime *runtime, const WdcRuntimeConfig *config)
{
    if (runtime == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    memset(runtime, 0, sizeof(*runtime));
    runtime->config = config != NULL ? *config : wdc_runtime_default_config();
    wdc_runtime_apply_default_config(&runtime->config);
    runtime->report.outcome = WDC_RUNTIME_OUTCOME_NOT_STARTED;
    runtime->report.last_status = WDC_OK;
#ifdef ESP_PLATFORM
    runtime->report.backend = WDC_RUNTIME_BACKEND_WAMR;
    if (!s_wamr_runtime_initialized) {
        if (!wasm_runtime_init()) {
            wdc_runtime_set_error(runtime,
                                  WDC_RUNTIME_OUTCOME_RUNTIME_INIT_FAILED,
                                  WDC_ERR_NOT_AVAILABLE,
                                  "WAMR runtime init failed");
            return WDC_ERR_NOT_AVAILABLE;
        }
        if (!wasm_runtime_register_natives(WDC_IMPORT_MODULE,
                                           s_wdc_native_symbols,
                                           (uint32_t)(sizeof(s_wdc_native_symbols) / sizeof(s_wdc_native_symbols[0])))) {
            wasm_runtime_destroy();
            wdc_runtime_set_error(runtime,
                                  WDC_RUNTIME_OUTCOME_RUNTIME_INIT_FAILED,
                                  WDC_ERR_NOT_AVAILABLE,
                                  "WAMR native registration failed");
            return WDC_ERR_NOT_AVAILABLE;
        }
        s_wamr_runtime_initialized = true;
    }
#else
    runtime->report.backend = WDC_RUNTIME_BACKEND_HOST_STUB;
#endif
    runtime->report.runtime_initialized = true;
    runtime->report.outcome = WDC_RUNTIME_OUTCOME_OK;
    (void)wdc_diag_log(WDC_LOG_INFO, "runtime initialized");
    return WDC_OK;
}

int32_t wdc_runtime_load_static(WdcRuntime *runtime, const uint8_t *wasm_bytes, uint32_t wasm_len)
{
    if (runtime == NULL || wasm_bytes == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    if (!runtime->report.runtime_initialized) {
        wdc_runtime_set_error(runtime, WDC_RUNTIME_OUTCOME_INVALID_STATE, WDC_ERR_INVALID_STATE, "runtime load before init");
        return WDC_ERR_INVALID_STATE;
    }
    if (wasm_len == 0u || wasm_len > runtime->config.max_module_bytes) {
        wdc_runtime_set_error(runtime, WDC_RUNTIME_OUTCOME_INVALID_PAYLOAD, WDC_ERR_BAD_LENGTH, "invalid wasm payload length");
        return WDC_ERR_BAD_LENGTH;
    }
    if (!wdc_runtime_valid_wasm_magic(wasm_bytes, wasm_len)) {
        wdc_runtime_set_error(runtime, WDC_RUNTIME_OUTCOME_INVALID_PAYLOAD, WDC_ERR_BAD_ENCODING, "invalid wasm magic/version");
        return WDC_ERR_BAD_ENCODING;
    }

    runtime->wasm_bytes = wasm_bytes;
    runtime->wasm_len = wasm_len;
    runtime->report.module_size = wasm_len;

#ifdef ESP_PLATFORM
    char error_buf[WDC_RUNTIME_ERROR_MAX];
    memset(error_buf, 0, sizeof(error_buf));
    wasm_module_t module = wasm_runtime_load((uint8_t *)wasm_bytes, wasm_len, error_buf, sizeof(error_buf));
    if (module == NULL) {
        wdc_runtime_set_error(runtime, WDC_RUNTIME_OUTCOME_BUNDLE_LOAD_FAILED, WDC_ERR_BAD_ENCODING, error_buf);
        return WDC_ERR_BAD_ENCODING;
    }
    runtime->backend_module = (void *)module;

    wasm_module_inst_t module_inst = wasm_runtime_instantiate(module,
                                                              runtime->config.instance_stack_bytes,
                                                              runtime->config.host_heap_bytes,
                                                              error_buf,
                                                              sizeof(error_buf));
    if (module_inst == NULL) {
        wdc_runtime_set_error(runtime, WDC_RUNTIME_OUTCOME_INSTANTIATE_FAILED, WDC_ERR_NO_MEMORY, error_buf);
        return WDC_ERR_NO_MEMORY;
    }
    runtime->backend_module_inst = (void *)module_inst;
    runtime->report.module_instantiated = true;

    wasm_exec_env_t exec_env = wasm_runtime_create_exec_env(module_inst, runtime->config.exec_stack_bytes);
    if (exec_env == NULL) {
        wdc_runtime_set_error(runtime, WDC_RUNTIME_OUTCOME_EXEC_ENV_FAILED, WDC_ERR_NO_MEMORY, "WAMR exec_env allocation failed");
        return WDC_ERR_NO_MEMORY;
    }
    runtime->backend_exec_env = (void *)exec_env;
#else
    runtime->report.module_instantiated = true;
#endif

    runtime->report.module_loaded = true;
    runtime->report.outcome = WDC_RUNTIME_OUTCOME_OK;
    runtime->report.last_status = WDC_OK;
    (void)wdc_diag_log(WDC_LOG_INFO, "static wasm payload loaded");
    return WDC_OK;
}

int32_t wdc_runtime_lookup_exports(WdcRuntime *runtime)
{
    if (runtime == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    if (!runtime->report.module_loaded) {
        wdc_runtime_set_error(runtime, WDC_RUNTIME_OUTCOME_INVALID_STATE, WDC_ERR_INVALID_STATE, "export lookup before module load");
        return WDC_ERR_INVALID_STATE;
    }

#ifdef ESP_PLATFORM
    wasm_module_inst_t module_inst = (wasm_module_inst_t)runtime->backend_module_inst;
    runtime->backend_func_init = wasm_runtime_lookup_function(module_inst, WDC_EXPORT_INIT, NULL);
    runtime->backend_func_on_event = wasm_runtime_lookup_function(module_inst, WDC_EXPORT_ON_EVENT, NULL);
    runtime->backend_func_health = wasm_runtime_lookup_function(module_inst, WDC_EXPORT_HEALTH, NULL);
    runtime->backend_func_shutdown = wasm_runtime_lookup_function(module_inst, WDC_EXPORT_SHUTDOWN, NULL);
#else
    runtime->backend_func_init = wdc_bytes_contains(runtime->wasm_bytes, runtime->wasm_len, WDC_EXPORT_INIT) ? (void *)1 : NULL;
    runtime->backend_func_on_event = wdc_bytes_contains(runtime->wasm_bytes, runtime->wasm_len, WDC_EXPORT_ON_EVENT) ? (void *)1 : NULL;
    runtime->backend_func_health = wdc_bytes_contains(runtime->wasm_bytes, runtime->wasm_len, WDC_EXPORT_HEALTH) ? (void *)1 : NULL;
    runtime->backend_func_shutdown = wdc_bytes_contains(runtime->wasm_bytes, runtime->wasm_len, WDC_EXPORT_SHUTDOWN) ? (void *)1 : NULL;
#endif

    if (runtime->backend_func_init == NULL ||
        runtime->backend_func_on_event == NULL ||
        runtime->backend_func_health == NULL ||
        runtime->backend_func_shutdown == NULL) {
        wdc_runtime_set_error(runtime, WDC_RUNTIME_OUTCOME_EXPORT_MISSING, WDC_ERR_NOT_AVAILABLE, "required lifecycle export missing");
        return WDC_ERR_NOT_AVAILABLE;
    }

    runtime->report.exports_resolved = true;
    runtime->report.outcome = WDC_RUNTIME_OUTCOME_OK;
    runtime->report.last_status = WDC_OK;
    (void)wdc_diag_log(WDC_LOG_INFO, "lifecycle exports resolved");
    return WDC_OK;
}

#ifdef ESP_PLATFORM
static int32_t wdc_runtime_call_wamr_i32(WdcRuntime *runtime,
                                         void *function,
                                         uint32_t argc,
                                         uint32_t *argv,
                                         uint32_t *out_result)
{
    if (runtime == NULL || function == NULL || out_result == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    wasm_exec_env_t exec_env = (wasm_exec_env_t)runtime->backend_exec_env;
    wasm_module_inst_t module_inst = (wasm_module_inst_t)runtime->backend_module_inst;
    if (exec_env == NULL || module_inst == NULL) {
        wdc_runtime_set_error(runtime, WDC_RUNTIME_OUTCOME_INVALID_STATE, WDC_ERR_INVALID_STATE, "WAMR call without exec_env");
        return WDC_ERR_INVALID_STATE;
    }
    uint32_t local_argv[4] = {0u, 0u, 0u, 0u};
    if (argv != NULL) {
        for (uint32_t i = 0u; i < argc && i < 4u; ++i) {
            local_argv[i] = argv[i];
        }
    }
    if (!wasm_runtime_call_wasm(exec_env, (wasm_function_inst_t)function, argc, local_argv)) {
        const char *exception = wasm_runtime_get_exception(module_inst);
        wdc_runtime_set_error(runtime,
                              WDC_RUNTIME_OUTCOME_GUEST_TRAPPED,
                              WDC_ERR_CONTRACT_VIOLATION,
                              exception != NULL ? exception : "guest trapped");
        return WDC_ERR_CONTRACT_VIOLATION;
    }
    *out_result = local_argv[0];
    return WDC_OK;
}
#endif

static int32_t wdc_runtime_handle_guest_result(WdcRuntime *runtime,
                                               uint32_t result,
                                               const char *label)
{
    if (result != (uint32_t)WDC_OK) {
        char msg[WDC_RUNTIME_ERROR_MAX];
        (void)snprintf(msg, sizeof(msg), "%s returned non-OK status %lu",
                       label != NULL ? label : "guest",
                       (unsigned long)result);
        wdc_runtime_set_error(runtime,
                              WDC_RUNTIME_OUTCOME_GUEST_NON_OK_STATUS,
                              WDC_ERR_CONTRACT_VIOLATION,
                              msg);
        return WDC_ERR_CONTRACT_VIOLATION;
    }
    runtime->report.outcome = WDC_RUNTIME_OUTCOME_OK;
    runtime->report.last_status = WDC_OK;
    return WDC_OK;
}

int32_t wdc_runtime_call_init(WdcRuntime *runtime)
{
    if (runtime == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    if (!runtime->report.exports_resolved || runtime->backend_func_init == NULL) {
        wdc_runtime_set_error(runtime, WDC_RUNTIME_OUTCOME_INVALID_STATE, WDC_ERR_INVALID_STATE, "init before export lookup");
        return WDC_ERR_INVALID_STATE;
    }

    uint32_t result = 0u;
#ifdef ESP_PLATFORM
    int32_t status = wdc_runtime_call_wamr_i32(runtime, runtime->backend_func_init, 0u, NULL, &result);
    if (status != WDC_OK) {
        return status;
    }
#else
    if (wdc_host_meta_value(runtime->wasm_bytes, runtime->wasm_len, "trap_init", 0) != 0) {
        wdc_runtime_set_error(runtime,
                              WDC_RUNTIME_OUTCOME_GUEST_TRAPPED,
                              WDC_ERR_CONTRACT_VIOLATION,
                              "host-stub simulated init trap");
        runtime->report.init_called = true;
        return WDC_ERR_CONTRACT_VIOLATION;
    }
    result = (uint32_t)wdc_host_meta_value(runtime->wasm_bytes, runtime->wasm_len, "init_status", 0);
    (void)wdc_diag_log(WDC_LOG_INFO, "r2 hello from static wasm");
#endif
    runtime->report.init_called = true;
    runtime->report.init_result = result;
    return wdc_runtime_handle_guest_result(runtime, result, "wdc_module_init");
}

int32_t wdc_runtime_call_on_event(WdcRuntime *runtime, uint32_t event_ptr, uint32_t event_len)
{
    if (runtime == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    if (!runtime->report.exports_resolved || runtime->backend_func_on_event == NULL) {
        wdc_runtime_set_error(runtime, WDC_RUNTIME_OUTCOME_INVALID_STATE, WDC_ERR_INVALID_STATE, "on_event before export lookup");
        return WDC_ERR_INVALID_STATE;
    }

    uint32_t result = 0u;
#ifdef ESP_PLATFORM
    uint32_t argv[2] = {event_ptr, event_len};
    int32_t status = wdc_runtime_call_wamr_i32(runtime, runtime->backend_func_on_event, 2u, argv, &result);
    if (status != WDC_OK) {
        return status;
    }
#else
    (void)event_ptr;
    if (wdc_host_meta_value(runtime->wasm_bytes, runtime->wasm_len, "trap_event", 0) != 0) {
        wdc_runtime_set_error(runtime,
                              WDC_RUNTIME_OUTCOME_GUEST_TRAPPED,
                              WDC_ERR_CONTRACT_VIOLATION,
                              "host-stub simulated event trap");
        runtime->report.on_event_called = true;
        runtime->report.on_event_result = (uint32_t)WDC_ERR_CONTRACT_VIOLATION;
        return WDC_ERR_CONTRACT_VIOLATION;
    }
    (void)event_len;
    result = (uint32_t)wdc_host_meta_value(runtime->wasm_bytes, runtime->wasm_len, "event_status", 0);
#endif
    runtime->report.on_event_called = true;
    runtime->report.on_event_result = result;
    return wdc_runtime_handle_guest_result(runtime, result, "wdc_module_on_event");
}


int32_t wdc_runtime_call_event_cbor(WdcRuntime *runtime, const uint8_t *event_bytes, uint32_t event_len)
{
    if (runtime == NULL || (event_len != 0u && event_bytes == NULL)) {
        return WDC_ERR_BAD_POINTER;
    }
    if (event_len > runtime->config.max_event_bytes) {
        wdc_runtime_set_error(runtime, WDC_RUNTIME_OUTCOME_INVALID_PAYLOAD, WDC_ERR_BAD_LENGTH, "event exceeds manifest runtime limit");
        return WDC_ERR_BAD_LENGTH;
    }
#ifdef ESP_PLATFORM
    wasm_module_inst_t module_inst = (wasm_module_inst_t)runtime->backend_module_inst;
    if (module_inst == NULL) {
        wdc_runtime_set_error(runtime, WDC_RUNTIME_OUTCOME_INVALID_STATE, WDC_ERR_INVALID_STATE, "event dispatch without module instance");
        return WDC_ERR_INVALID_STATE;
    }
    void *native_ptr = NULL;
    uint32_t app_ptr = 0u;
    if (event_len != 0u) {
        app_ptr = wasm_runtime_module_malloc(module_inst, event_len, &native_ptr);
        if (app_ptr == 0u || native_ptr == NULL) {
            wdc_runtime_set_error(runtime, WDC_RUNTIME_OUTCOME_EXEC_ENV_FAILED, WDC_ERR_NO_MEMORY, "event guest-memory allocation failed");
            return WDC_ERR_NO_MEMORY;
        }
        memcpy(native_ptr, event_bytes, event_len);
    }
    int32_t status = wdc_runtime_call_on_event(runtime, app_ptr, event_len);
    if (app_ptr != 0u) {
        wasm_runtime_module_free(module_inst, app_ptr);
    }
    return status;
#else
    (void)event_bytes;
    return wdc_runtime_call_on_event(runtime, 0u, event_len);
#endif
}

int32_t wdc_runtime_dispatch_event(WdcRuntime *runtime, const WdcEvent *event)
{
    if (runtime == NULL || event == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    uint8_t encoded[WDC_MAX_EVENT_BYTES_DEFAULT];
    uint32_t encoded_len = 0u;
    int32_t status = wdc_event_encode_cbor(event, encoded, sizeof(encoded), &encoded_len);
    if (status != WDC_OK) {
        wdc_runtime_set_error(runtime, WDC_RUNTIME_OUTCOME_INVALID_PAYLOAD, status, "event envelope encode failed");
        return status;
    }
    return wdc_runtime_call_event_cbor(runtime, encoded, encoded_len);
}

int32_t wdc_runtime_call_health(WdcRuntime *runtime)
{
    if (runtime == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    if (!runtime->report.exports_resolved || runtime->backend_func_health == NULL) {
        wdc_runtime_set_error(runtime, WDC_RUNTIME_OUTCOME_INVALID_STATE, WDC_ERR_INVALID_STATE, "health before export lookup");
        return WDC_ERR_INVALID_STATE;
    }

    uint32_t result = 0u;
#ifdef ESP_PLATFORM
    int32_t status = wdc_runtime_call_wamr_i32(runtime, runtime->backend_func_health, 0u, NULL, &result);
    if (status != WDC_OK) {
        return status;
    }
#else
    result = (uint32_t)wdc_host_meta_value(runtime->wasm_bytes, runtime->wasm_len, "health_status", 0);
#endif
    runtime->report.health_called = true;
    runtime->report.health_result = result;
    return wdc_runtime_handle_guest_result(runtime, result, "wdc_module_health");
}

int32_t wdc_runtime_call_shutdown(WdcRuntime *runtime, int32_t reason)
{
    if (runtime == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    if (!runtime->report.exports_resolved || runtime->backend_func_shutdown == NULL) {
        wdc_runtime_set_error(runtime, WDC_RUNTIME_OUTCOME_INVALID_STATE, WDC_ERR_INVALID_STATE, "shutdown before export lookup");
        return WDC_ERR_INVALID_STATE;
    }

    uint32_t result = 0u;
#ifdef ESP_PLATFORM
    uint32_t argv[1] = {(uint32_t)reason};
    int32_t status = wdc_runtime_call_wamr_i32(runtime, runtime->backend_func_shutdown, 1u, argv, &result);
    if (status != WDC_OK) {
        return status;
    }
#else
    (void)reason;
    result = 0u;
#endif
    runtime->report.shutdown_called = true;
    runtime->report.shutdown_result = result;
    return wdc_runtime_handle_guest_result(runtime, result, "wdc_module_shutdown");
}

void wdc_runtime_teardown(WdcRuntime *runtime)
{
    if (runtime == NULL) {
        return;
    }
#ifdef ESP_PLATFORM
    if (runtime->backend_exec_env != NULL) {
        wasm_runtime_destroy_exec_env((wasm_exec_env_t)runtime->backend_exec_env);
        runtime->backend_exec_env = NULL;
    }
    if (runtime->backend_module_inst != NULL) {
        wasm_runtime_deinstantiate((wasm_module_inst_t)runtime->backend_module_inst);
        runtime->backend_module_inst = NULL;
    }
    if (runtime->backend_module != NULL) {
        wasm_runtime_unload((wasm_module_t)runtime->backend_module);
        runtime->backend_module = NULL;
    }
    if (s_wamr_runtime_initialized) {
        wasm_runtime_destroy();
        s_wamr_runtime_initialized = false;
    }
#else
    runtime->backend_exec_env = NULL;
    runtime->backend_module_inst = NULL;
    runtime->backend_module = NULL;
#endif
    (void)wdc_diag_log(WDC_LOG_INFO, "runtime torn down");
}

int32_t wdc_runtime_run_static_smoke(const WdcRuntimeConfig *config,
                                     const uint8_t *wasm_bytes,
                                     uint32_t wasm_len,
                                     WdcRuntimeReport *out_report)
{
    WdcRuntime runtime;
    int32_t status = wdc_runtime_init(&runtime, config);
    if (status == WDC_OK) {
        status = wdc_runtime_load_static(&runtime, wasm_bytes, wasm_len);
    }
    if (status == WDC_OK) {
        status = wdc_runtime_lookup_exports(&runtime);
    }
    if (status == WDC_OK) {
        status = wdc_runtime_call_init(&runtime);
    }
    if (status == WDC_OK) {
        status = wdc_runtime_call_on_event(&runtime, 0u, 0u);
    }
    if (status == WDC_OK) {
        status = wdc_runtime_call_health(&runtime);
    }
    if (status == WDC_OK) {
        status = wdc_runtime_call_shutdown(&runtime, WDC_SHUTDOWN_NORMAL);
    }
    if (out_report != NULL) {
        *out_report = runtime.report;
    }
    wdc_runtime_teardown(&runtime);
    return status;
}

const WdcRuntimeReport *wdc_runtime_get_report(const WdcRuntime *runtime)
{
    if (runtime == NULL) {
        return NULL;
    }
    return &runtime->report;
}

void wdc_runtime_copy_report(const WdcRuntime *runtime, WdcRuntimeReport *out_report)
{
    if (runtime == NULL || out_report == NULL) {
        return;
    }
    *out_report = runtime->report;
}
