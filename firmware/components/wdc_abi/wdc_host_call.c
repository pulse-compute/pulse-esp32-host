#include "wdc_abi.h"

#include <stddef.h>
#include <string.h>

#define CONFIG_SLOTS 4u
#define CONFIG_KEY_MAX 31u
#define CONFIG_VALUE_MAX 96u
#define TIMER_SLOTS 4u

typedef struct ConfigSlot { bool used; char key[CONFIG_KEY_MAX + 1u]; uint8_t value[CONFIG_VALUE_MAX]; uint32_t value_len; } ConfigSlot;
typedef struct TimerSlot { bool used; uint32_t timer_id; uint32_t delay_ms; bool repeat; } TimerSlot;

static int s_gpio_levels[4] = {0, 0, 1, 1};
static ConfigSlot s_config[CONFIG_SLOTS];
static TimerSlot s_timers[TIMER_SLOTS];
static WdcHostAuthorizeFn s_authorizer;
static void *s_authorizer_ctx;
static WdcHostGpioWriteFn s_gpio_write_hook;
static WdcHostGpioReadFn s_gpio_read_hook;
static void *s_gpio_hook_ctx;
static WdcHostNetCallFn s_net_hook;
static void *s_net_hook_ctx;
static WdcHostEffectCallFn s_effect_hook;
static void *s_effect_hook_ctx;
static WdcHostCallLimits s_limits = { WDC_MAX_REQUEST_BYTES_DEFAULT, WDC_MAX_RESPONSE_BYTES_DEFAULT };

void wdc_host_call_set_authorizer(WdcHostAuthorizeFn fn, void *ctx)
{
    s_authorizer = fn;
    s_authorizer_ctx = ctx;
}

void wdc_host_call_clear_authorizer(void)
{
    s_authorizer = NULL;
    s_authorizer_ctx = NULL;
}

WdcHostCallLimits wdc_host_call_default_limits(void)
{
    WdcHostCallLimits limits = { WDC_MAX_REQUEST_BYTES_DEFAULT, WDC_MAX_RESPONSE_BYTES_DEFAULT };
    return limits;
}

WdcHostCallLimits wdc_host_call_get_limits(void)
{
    return s_limits;
}

void wdc_host_call_set_limits(const WdcHostCallLimits *limits)
{
    WdcHostCallLimits defaults = wdc_host_call_default_limits();
    if (limits == NULL) {
        s_limits = defaults;
        return;
    }
    s_limits.max_request_bytes = limits->max_request_bytes != 0u ? limits->max_request_bytes : defaults.max_request_bytes;
    s_limits.max_response_bytes = limits->max_response_bytes != 0u ? limits->max_response_bytes : defaults.max_response_bytes;
    if (s_limits.max_request_bytes > defaults.max_request_bytes) {
        s_limits.max_request_bytes = defaults.max_request_bytes;
    }
    if (s_limits.max_response_bytes > defaults.max_response_bytes) {
        s_limits.max_response_bytes = defaults.max_response_bytes;
    }
}

void wdc_host_call_reset_limits(void)
{
    s_limits = wdc_host_call_default_limits();
}

void wdc_host_call_set_gpio_hooks(WdcHostGpioWriteFn write_fn, WdcHostGpioReadFn read_fn, void *ctx)
{
    s_gpio_write_hook = write_fn;
    s_gpio_read_hook = read_fn;
    s_gpio_hook_ctx = ctx;
}

void wdc_host_call_clear_gpio_hooks(void)
{
    s_gpio_write_hook = NULL;
    s_gpio_read_hook = NULL;
    s_gpio_hook_ctx = NULL;
}

void wdc_host_call_set_net_hook(WdcHostNetCallFn net_fn, void *ctx)
{
    s_net_hook = net_fn;
    s_net_hook_ctx = ctx;
}

void wdc_host_call_clear_net_hook(void)
{
    s_net_hook = NULL;
    s_net_hook_ctx = NULL;
}

int32_t wdc_host_call_set_effect_hook(WdcHostEffectCallFn effect_fn, void *ctx)
{
    if (effect_fn == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    if (s_effect_hook != NULL &&
        (s_effect_hook != effect_fn || s_effect_hook_ctx != ctx)) {
        return WDC_ERR_BUSY;
    }
    s_effect_hook = effect_fn;
    s_effect_hook_ctx = ctx;
    return WDC_OK;
}

void wdc_host_call_clear_effect_hook(void)
{
    s_effect_hook = NULL;
    s_effect_hook_ctx = NULL;
}

void wdc_host_call_reset_for_test(void)
{
    s_gpio_levels[0] = 0;
    s_gpio_levels[WDC_R3_RESOURCE_RELAY_1] = 0;
    s_gpio_levels[WDC_R3_RESOURCE_STATUS_LED] = 1;
    s_gpio_levels[WDC_R3_RESOURCE_BUTTON_1] = 1;
    memset(s_config, 0, sizeof(s_config));
    memset(s_timers, 0, sizeof(s_timers));
    wdc_host_call_clear_authorizer();
    wdc_host_call_reset_limits();
    wdc_host_call_clear_gpio_hooks();
    wdc_host_call_clear_net_hook();
    wdc_host_call_clear_effect_hook();
}

const char *wdc_opcode_name(uint32_t opcode)
{
    switch (opcode) {
    case WDC_OP_SYS_GET_INFO: return "WDC_OP_SYS_GET_INFO";
    case WDC_OP_SYS_GET_METRIC: return "WDC_OP_SYS_GET_METRIC";
    case WDC_OP_TIME_GET: return "WDC_OP_TIME_GET";
    case WDC_OP_TIMER_SET: return "WDC_OP_TIMER_SET";
    case WDC_OP_TIMER_CANCEL: return "WDC_OP_TIMER_CANCEL";
    case WDC_OP_CONFIG_GET: return "WDC_OP_CONFIG_GET";
    case WDC_OP_CONFIG_SET: return "WDC_OP_CONFIG_SET";
    case WDC_OP_CONFIG_DELETE: return "WDC_OP_CONFIG_DELETE";
    case WDC_OP_GPIO_GET: return "WDC_OP_GPIO_GET";
    case WDC_OP_GPIO_SET: return "WDC_OP_GPIO_SET";
    case WDC_OP_GPIO_SUBSCRIBE: return "WDC_OP_GPIO_SUBSCRIBE";
    case WDC_OP_SENSOR_READ: return "WDC_OP_SENSOR_READ";
    case WDC_OP_SENSOR_SUBSCRIBE: return "WDC_OP_SENSOR_SUBSCRIBE";
    case WDC_OP_I2C_TRANSFER: return "WDC_OP_I2C_TRANSFER";
    case WDC_OP_NET_STATUS: return "WDC_OP_NET_STATUS";
    case WDC_OP_MQTT_PUBLISH: return "WDC_OP_MQTT_PUBLISH";
    case WDC_OP_MQTT_SUBSCRIBE: return "WDC_OP_MQTT_SUBSCRIBE";
    case WDC_OP_HTTP_REQUEST: return "WDC_OP_HTTP_REQUEST";
    case WDC_OP_HTTP_RESPOND: return "WDC_OP_HTTP_RESPOND";
    case WDC_OP_BLE_SET_VALUE: return "WDC_OP_BLE_SET_VALUE";
    case WDC_OP_BLE_NOTIFY: return "WDC_OP_BLE_NOTIFY";
    case WDC_OP_BLE_ADVERTISE_SET: return "WDC_OP_BLE_ADVERTISE_SET";
    case WDC_OP_KV_GET: return "WDC_OP_KV_GET";
    case WDC_OP_KV_SET: return "WDC_OP_KV_SET";
    case WDC_OP_KV_DELETE: return "WDC_OP_KV_DELETE";
    case WDC_OP_EFFECT_INVOKE: return "WDC_OP_EFFECT_INVOKE";
    default: return "WDC_OP_UNKNOWN";
    }
}

bool wdc_opcode_known(uint32_t opcode)
{
    switch (opcode) {
    case WDC_OP_SYS_GET_INFO: case WDC_OP_SYS_GET_METRIC: case WDC_OP_TIME_GET:
    case WDC_OP_TIMER_SET: case WDC_OP_TIMER_CANCEL:
    case WDC_OP_CONFIG_GET: case WDC_OP_CONFIG_SET: case WDC_OP_CONFIG_DELETE:
    case WDC_OP_GPIO_GET: case WDC_OP_GPIO_SET: case WDC_OP_GPIO_SUBSCRIBE:
    case WDC_OP_SENSOR_READ: case WDC_OP_SENSOR_SUBSCRIBE: case WDC_OP_I2C_TRANSFER:
    case WDC_OP_NET_STATUS: case WDC_OP_MQTT_PUBLISH: case WDC_OP_MQTT_SUBSCRIBE: case WDC_OP_HTTP_REQUEST: case WDC_OP_HTTP_RESPOND:
    case WDC_OP_BLE_SET_VALUE: case WDC_OP_BLE_NOTIFY: case WDC_OP_BLE_ADVERTISE_SET:
    case WDC_OP_KV_GET: case WDC_OP_KV_SET: case WDC_OP_KV_DELETE:
    case WDC_OP_EFFECT_INVOKE:
        return true;
    default:
        return false;
    }
}

bool wdc_opcode_supported_r3(uint32_t opcode)
{
    switch (opcode) {
    case WDC_OP_SYS_GET_INFO:
    case WDC_OP_TIMER_SET:
    case WDC_OP_TIMER_CANCEL:
    case WDC_OP_CONFIG_GET:
    case WDC_OP_CONFIG_SET:
    case WDC_OP_GPIO_GET:
    case WDC_OP_GPIO_SET:
        return true;
    default:
        return false;
    }
}

bool wdc_opcode_supported_r4(uint32_t opcode)
{
    return wdc_opcode_supported_r3(opcode) || opcode == WDC_OP_CONFIG_DELETE || opcode == WDC_OP_GPIO_SUBSCRIBE;
}

bool wdc_opcode_supported_r8(uint32_t opcode)
{
    return wdc_opcode_supported_r4(opcode) ||
           opcode == WDC_OP_NET_STATUS ||
           opcode == WDC_OP_MQTT_PUBLISH ||
           opcode == WDC_OP_MQTT_SUBSCRIBE ||
           opcode == WDC_OP_HTTP_REQUEST ||
           opcode == WDC_OP_HTTP_RESPOND ||
           opcode == WDC_OP_EFFECT_INVOKE;
}

bool wdc_opcode_requires_resource(uint32_t opcode)
{
    switch (opcode) {
    case WDC_OP_GPIO_GET: case WDC_OP_GPIO_SET: case WDC_OP_GPIO_SUBSCRIBE:
    case WDC_OP_SENSOR_READ: case WDC_OP_SENSOR_SUBSCRIBE: case WDC_OP_I2C_TRANSFER:
    case WDC_OP_MQTT_PUBLISH: case WDC_OP_MQTT_SUBSCRIBE: case WDC_OP_HTTP_REQUEST: case WDC_OP_HTTP_RESPOND:
    case WDC_OP_BLE_SET_VALUE: case WDC_OP_BLE_NOTIFY: case WDC_OP_BLE_ADVERTISE_SET:
    case WDC_OP_KV_GET: case WDC_OP_KV_SET: case WDC_OP_KV_DELETE:
        return true;
    default:
        return false;
    }
}

static int32_t finish(WdcCborBuilder *b, uint32_t *out_len)
{
    if (out_len != NULL) { *out_len = wdc_cbor_len(b); }
    return WDC_OK;
}

static int32_t response_status(uint8_t *rsp, uint32_t cap, uint32_t *out_len, int32_t code)
{
    WdcCborBuilder b; wdc_cbor_builder_init(&b, rsp, cap);
    int32_t status = wdc_cbor_begin_map(&b, 1u);
    if (status == WDC_OK) { status = wdc_cbor_put_key_i32(&b, WDC_CBOR_KEY_STATUS, code); }
    return status == WDC_OK ? finish(&b, out_len) : status;
}

static int32_t response_status_value(uint8_t *rsp, uint32_t cap, uint32_t *out_len, int32_t code, uint32_t value)
{
    WdcCborBuilder b; wdc_cbor_builder_init(&b, rsp, cap);
    int32_t status = wdc_cbor_begin_map(&b, 2u);
    if (status == WDC_OK) { status = wdc_cbor_put_key_i32(&b, WDC_CBOR_KEY_STATUS, code); }
    if (status == WDC_OK) { status = wdc_cbor_put_key_u32(&b, WDC_CBOR_KEY_VALUE, value); }
    return status == WDC_OK ? finish(&b, out_len) : status;
}

static int32_t sys_info(uint8_t *rsp, uint32_t cap, uint32_t *out_len)
{
    WdcCborBuilder b; wdc_cbor_builder_init(&b, rsp, cap);
    int32_t status = wdc_cbor_begin_map(&b, 5u);
    if (status == WDC_OK) { status = wdc_cbor_put_key_i32(&b, WDC_CBOR_KEY_STATUS, WDC_OK); }
    if (status == WDC_OK) { status = wdc_cbor_put_key_u32(&b, WDC_CBOR_KEY_ABI_MAJOR, WDC_ABI_MAJOR); }
    if (status == WDC_OK) { status = wdc_cbor_put_key_u32(&b, WDC_CBOR_KEY_ABI_MINOR, WDC_ABI_MINOR); }
    if (status == WDC_OK) { status = wdc_cbor_put_key_text(&b, WDC_CBOR_KEY_BUILD_STAGE, WDC_CURRENT_BUILD_STAGE); }
    if (status == WDC_OK) { status = wdc_cbor_put_key_text(&b, WDC_CBOR_KEY_SHELL_VERSION, WDC_CURRENT_SHELL_VERSION); }
    return status == WDC_OK ? finish(&b, out_len) : status;
}

static int32_t valid_resource(uint32_t id)
{
    return (id == WDC_R3_RESOURCE_RELAY_1 || id == WDC_R3_RESOURCE_STATUS_LED || id == WDC_R3_RESOURCE_BUTTON_1) ? WDC_OK : WDC_ERR_INVALID_RESOURCE;
}

static bool writable_resource(uint32_t id)
{
    return id == WDC_R3_RESOURCE_RELAY_1 || id == WDC_R3_RESOURCE_STATUS_LED;
}

static int32_t gpio_set(const uint8_t *req, uint32_t req_len, uint8_t *rsp, uint32_t cap, uint32_t *out_len)
{
    uint32_t id = 0u, value = 0u;
    int32_t status = wdc_cbor_map_find_u32(req, req_len, WDC_CBOR_KEY_RESOURCE_ID, &id);
    if (status != WDC_OK) { return WDC_ERR_BAD_ENCODING; }
    status = wdc_cbor_map_find_u32(req, req_len, WDC_CBOR_KEY_VALUE, &value);
    if (status != WDC_OK) {
        bool b = false;
        status = wdc_cbor_map_find_bool(req, req_len, WDC_CBOR_KEY_VALUE, &b);
        if (status != WDC_OK) { return WDC_ERR_BAD_ENCODING; }
        value = b ? 1u : 0u;
    }
    status = valid_resource(id);
    if (status != WDC_OK) { return response_status(rsp, cap, out_len, status); }
    if (!writable_resource(id)) { return response_status(rsp, cap, out_len, WDC_ERR_INVALID_RESOURCE); }
    if (value > 1u) { return WDC_ERR_BAD_ENCODING; }
    if (s_gpio_write_hook != NULL) {
        status = s_gpio_write_hook(s_gpio_hook_ctx, id, value ? 1u : 0u);
        if (status != WDC_OK) {
            return response_status(rsp, cap, out_len, status);
        }
    }
    s_gpio_levels[id] = value ? 1 : 0;
    return response_status(rsp, cap, out_len, WDC_OK);
}

static int32_t gpio_get(const uint8_t *req, uint32_t req_len, uint8_t *rsp, uint32_t cap, uint32_t *out_len)
{
    uint32_t id = 0u;
    int32_t status = wdc_cbor_map_find_u32(req, req_len, WDC_CBOR_KEY_RESOURCE_ID, &id);
    if (status != WDC_OK) { return WDC_ERR_BAD_ENCODING; }
    status = valid_resource(id);
    if (status != WDC_OK) { return response_status(rsp, cap, out_len, status); }
    if (s_gpio_read_hook != NULL) {
        uint32_t level = 0u;
        status = s_gpio_read_hook(s_gpio_hook_ctx, id, &level);
        if (status == WDC_OK) {
            return response_status_value(rsp, cap, out_len, WDC_OK, level != 0u ? 1u : 0u);
        }
        if (status != WDC_ERR_NOT_AVAILABLE) {
            return response_status(rsp, cap, out_len, status);
        }
    }
    return response_status_value(rsp, cap, out_len, WDC_OK, (uint32_t)s_gpio_levels[id]);
}

static int32_t gpio_subscribe(const uint8_t *req, uint32_t req_len, uint8_t *rsp, uint32_t cap, uint32_t *out_len)
{
    uint32_t id = 0u;
    int32_t status = wdc_cbor_map_find_u32(req, req_len, WDC_CBOR_KEY_RESOURCE_ID, &id);
    if (status != WDC_OK) { return WDC_ERR_BAD_ENCODING; }
    status = valid_resource(id);
    if (status != WDC_OK) { return response_status(rsp, cap, out_len, status); }
    return response_status(rsp, cap, out_len, WDC_OK);
}

static int32_t find_timer(uint32_t timer_id)
{
    for (uint32_t i = 0u; i < TIMER_SLOTS; ++i) { if (s_timers[i].used && s_timers[i].timer_id == timer_id) { return (int32_t)i; } }
    return -1;
}

static int32_t timer_set(const uint8_t *req, uint32_t req_len, uint8_t *rsp, uint32_t cap, uint32_t *out_len)
{
    uint32_t id = 0u, delay = 0u; bool repeat = false;
    int32_t status = wdc_cbor_map_find_u32(req, req_len, WDC_CBOR_KEY_TIMER_ID, &id);
    if (status != WDC_OK) { return WDC_ERR_BAD_ENCODING; }
    status = wdc_cbor_map_find_u32(req, req_len, WDC_CBOR_KEY_DELAY_MS, &delay);
    if (status != WDC_OK || id == 0u || delay == 0u) { return WDC_ERR_BAD_ENCODING; }
    status = wdc_cbor_map_find_bool(req, req_len, WDC_CBOR_KEY_REPEAT, &repeat);
    if (status != WDC_OK && status != WDC_ERR_NOT_AVAILABLE) { return WDC_ERR_BAD_ENCODING; }
    int32_t index = find_timer(id);
    if (index < 0) { for (uint32_t i = 0u; i < TIMER_SLOTS; ++i) { if (!s_timers[i].used) { index = (int32_t)i; break; } } }
    if (index < 0) { return response_status(rsp, cap, out_len, WDC_ERR_NO_MEMORY); }
    s_timers[index].used = true; s_timers[index].timer_id = id; s_timers[index].delay_ms = delay; s_timers[index].repeat = repeat;
    return response_status(rsp, cap, out_len, WDC_OK);
}

static int32_t timer_cancel(const uint8_t *req, uint32_t req_len, uint8_t *rsp, uint32_t cap, uint32_t *out_len)
{
    uint32_t id = 0u;
    int32_t status = wdc_cbor_map_find_u32(req, req_len, WDC_CBOR_KEY_TIMER_ID, &id);
    if (status != WDC_OK || id == 0u) { return WDC_ERR_BAD_ENCODING; }
    int32_t index = find_timer(id);
    if (index >= 0) { memset(&s_timers[index], 0, sizeof(s_timers[index])); }
    return response_status(rsp, cap, out_len, WDC_OK);
}

static int32_t find_config(const char *key, uint32_t key_len)
{
    for (uint32_t i = 0u; i < CONFIG_SLOTS; ++i) {
        if (s_config[i].used && strlen(s_config[i].key) == key_len && memcmp(s_config[i].key, key, key_len) == 0) { return (int32_t)i; }
    }
    return -1;
}

static int32_t config_set(const uint8_t *req, uint32_t req_len, uint8_t *rsp, uint32_t cap, uint32_t *out_len)
{
    WdcCborText key; WdcCborBytes value;
    int32_t status = wdc_cbor_map_find_text(req, req_len, WDC_CBOR_KEY_KEY, &key);
    if (status != WDC_OK) { return WDC_ERR_BAD_ENCODING; }
    status = wdc_cbor_map_find_bytes(req, req_len, WDC_CBOR_KEY_DATA, &value);
    if (status != WDC_OK) { return WDC_ERR_BAD_ENCODING; }
    if (key.len == 0u || key.len > CONFIG_KEY_MAX || value.len > CONFIG_VALUE_MAX) { return WDC_ERR_BAD_LENGTH; }
    int32_t index = find_config(key.ptr, key.len);
    if (index < 0) { for (uint32_t i = 0u; i < CONFIG_SLOTS; ++i) { if (!s_config[i].used) { index = (int32_t)i; break; } } }
    if (index < 0) { return response_status(rsp, cap, out_len, WDC_ERR_NO_MEMORY); }
    s_config[index].used = true; memcpy(s_config[index].key, key.ptr, key.len); s_config[index].key[key.len] = '\0';
    if (value.len != 0u) { memcpy(s_config[index].value, value.ptr, value.len); }
    s_config[index].value_len = value.len;
    return response_status(rsp, cap, out_len, WDC_OK);
}

static int32_t config_get(const uint8_t *req, uint32_t req_len, uint8_t *rsp, uint32_t cap, uint32_t *out_len)
{
    WdcCborText key;
    int32_t status = wdc_cbor_map_find_text(req, req_len, WDC_CBOR_KEY_KEY, &key);
    if (status != WDC_OK) { return WDC_ERR_BAD_ENCODING; }
    int32_t index = find_config(key.ptr, key.len);
    if (index < 0) { return response_status(rsp, cap, out_len, WDC_ERR_NOT_AVAILABLE); }
    WdcCborBuilder b; wdc_cbor_builder_init(&b, rsp, cap);
    status = wdc_cbor_begin_map(&b, 2u);
    if (status == WDC_OK) { status = wdc_cbor_put_key_i32(&b, WDC_CBOR_KEY_STATUS, WDC_OK); }
    if (status == WDC_OK) { status = wdc_cbor_put_key_bytes(&b, WDC_CBOR_KEY_DATA, s_config[index].value, s_config[index].value_len); }
    return status == WDC_OK ? finish(&b, out_len) : status;
}

static int32_t config_delete(const uint8_t *req, uint32_t req_len, uint8_t *rsp, uint32_t cap, uint32_t *out_len)
{
    WdcCborText key;
    int32_t status = wdc_cbor_map_find_text(req, req_len, WDC_CBOR_KEY_KEY, &key);
    if (status != WDC_OK) { return WDC_ERR_BAD_ENCODING; }
    int32_t index = find_config(key.ptr, key.len);
    if (index >= 0) { memset(&s_config[index], 0, sizeof(s_config[index])); }
    return response_status(rsp, cap, out_len, WDC_OK);
}


static int32_t network_call(uint32_t opcode,
                            const uint8_t *req,
                            uint32_t req_len,
                            uint8_t *rsp,
                            uint32_t cap,
                            uint32_t *out_len)
{
    if (s_net_hook == NULL) {
        return response_status(rsp, cap, out_len, WDC_ERR_NOT_AVAILABLE);
    }
    return s_net_hook(s_net_hook_ctx, opcode, req, req_len, rsp, cap, out_len);
}

static bool opcode_safe_without_authorizer(uint32_t opcode)
{
    switch (opcode) {
    case WDC_OP_SYS_GET_INFO:
    case WDC_OP_NET_STATUS:
        return true;
    default:
        return false;
    }
}

static int32_t maybe_authorize(uint32_t opcode,
                                 const uint8_t *request,
                                 uint32_t request_len,
                                 uint8_t *response,
                                 uint32_t response_cap,
                                 uint32_t *out_response_len,
                                 bool *out_response_written)
{
    if (out_response_written != NULL) {
        *out_response_written = false;
    }
    if (s_authorizer == NULL) {
        if (opcode_safe_without_authorizer(opcode)) {
            return WDC_OK;
        }
        int32_t status = response_status(response, response_cap, out_response_len, WDC_ERR_CAPABILITY_DENIED);
        if (status == WDC_OK && out_response_written != NULL) {
            *out_response_written = true;
        }
        return status;
    }
    int32_t decision = WDC_OK;
    int32_t status = s_authorizer(s_authorizer_ctx, opcode, request, request_len, &decision);
    if (status != WDC_OK) {
        return status;
    }
    if (decision != WDC_OK) {
        status = response_status(response, response_cap, out_response_len, decision);
        if (status == WDC_OK && out_response_written != NULL) {
            *out_response_written = true;
        }
        return status;
    }
    return WDC_OK;
}

int32_t wdc_guest_memory_validate_range(const WdcGuestMemory *memory, uint32_t ptr, uint32_t len, bool write, uint8_t **out_native)
{
    (void)write;
    if (out_native != NULL) { *out_native = NULL; }
    if (memory == NULL || memory->base == NULL) { return WDC_ERR_BAD_POINTER; }
    if (len == 0u) {
        if (ptr > memory->len) { return WDC_ERR_BAD_POINTER; }
        if (out_native != NULL) { *out_native = &memory->base[ptr]; }
        return WDC_OK;
    }
    if (ptr >= memory->len || len > memory->len - ptr) { return WDC_ERR_BAD_POINTER; }
    if (out_native != NULL) { *out_native = &memory->base[ptr]; }
    return WDC_OK;
}

int32_t wdc_host_call_dispatch(uint32_t opcode, const uint8_t *request, uint32_t request_len, uint8_t *response, uint32_t response_cap, uint32_t *out_response_len)
{
    if (out_response_len != NULL) { *out_response_len = 0u; }
    if (!wdc_opcode_known(opcode) || !wdc_opcode_supported_r8(opcode)) { return WDC_ERR_UNSUPPORTED_OPCODE; }
    if (request_len > s_limits.max_request_bytes || response_cap > s_limits.max_response_bytes) { return WDC_ERR_BAD_LENGTH; }
    if (request_len != 0u && request == NULL) { return WDC_ERR_BAD_POINTER; }
    if (response == NULL && response_cap != 0u) { return WDC_ERR_BAD_POINTER; }
    if (response_cap == 0u) { return WDC_ERR_RESPONSE_TOO_SMALL; }
    if (!wdc_cbor_is_empty_or_map(request, request_len)) { return WDC_ERR_BAD_ENCODING; }

    bool auth_response_written = false;
    int32_t status = maybe_authorize(opcode, request, request_len, response, response_cap, out_response_len, &auth_response_written);
    if (status != WDC_OK) { return status; }
    if (auth_response_written) { return WDC_OK; }

    switch (opcode) {
    case WDC_OP_SYS_GET_INFO: return sys_info(response, response_cap, out_response_len);
    case WDC_OP_TIMER_SET: return timer_set(request, request_len, response, response_cap, out_response_len);
    case WDC_OP_TIMER_CANCEL: return timer_cancel(request, request_len, response, response_cap, out_response_len);
    case WDC_OP_CONFIG_GET: return config_get(request, request_len, response, response_cap, out_response_len);
    case WDC_OP_CONFIG_SET: return config_set(request, request_len, response, response_cap, out_response_len);
    case WDC_OP_CONFIG_DELETE: return config_delete(request, request_len, response, response_cap, out_response_len);
    case WDC_OP_GPIO_GET: return gpio_get(request, request_len, response, response_cap, out_response_len);
    case WDC_OP_GPIO_SET: return gpio_set(request, request_len, response, response_cap, out_response_len);
    case WDC_OP_GPIO_SUBSCRIBE: return gpio_subscribe(request, request_len, response, response_cap, out_response_len);
    case WDC_OP_NET_STATUS:
    case WDC_OP_MQTT_PUBLISH:
    case WDC_OP_MQTT_SUBSCRIBE:
    case WDC_OP_HTTP_REQUEST:
    case WDC_OP_HTTP_RESPOND:
        return network_call(opcode, request, request_len, response, response_cap, out_response_len);
    case WDC_OP_EFFECT_INVOKE:
        return s_effect_hook != NULL ?
                   s_effect_hook(s_effect_hook_ctx,
                                 request,
                                 request_len,
                                 response,
                                 response_cap,
                                 out_response_len) :
                   WDC_ERR_NOT_AVAILABLE;
    default: return WDC_ERR_UNSUPPORTED_OPCODE;
    }
}

int32_t wdc_host_call_from_guest_memory(const WdcGuestMemory *memory, uint32_t opcode, uint32_t req_ptr, uint32_t req_len, uint32_t rsp_ptr, uint32_t rsp_cap, uint32_t *out_response_len)
{
    if (req_len > s_limits.max_request_bytes || rsp_cap > s_limits.max_response_bytes) { return WDC_ERR_BAD_LENGTH; }
    if (memory != NULL && memory->max_request_bytes != 0u && req_len > memory->max_request_bytes) { return WDC_ERR_BAD_LENGTH; }
    if (memory != NULL && memory->max_response_bytes != 0u && rsp_cap > memory->max_response_bytes) { return WDC_ERR_BAD_LENGTH; }
    uint8_t *req = NULL; uint8_t *rsp = NULL;
    int32_t status = wdc_guest_memory_validate_range(memory, req_ptr, req_len, false, &req);
    if (status != WDC_OK) { return status; }
    status = wdc_guest_memory_validate_range(memory, rsp_ptr, rsp_cap, true, &rsp);
    if (status != WDC_OK) { return status; }
    return wdc_host_call_dispatch(opcode, req, req_len, rsp, rsp_cap, out_response_len);
}

int32_t wdc_host_call_dispatch_stub(uint32_t opcode, const uint8_t *request, uint32_t request_len, uint8_t *response, uint32_t response_cap)
{
    return wdc_host_call_dispatch(opcode, request, request_len, response, response_cap, NULL);
}
