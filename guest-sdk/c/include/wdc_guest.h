#pragma once

#include <stdbool.h>
#include <stdint.h>
#include <string.h>

#ifdef __cplusplus
extern "C" {
#endif

#define WDC_ABI_MAJOR 1u
#define WDC_ABI_MINOR 0u

#define WDC_OK 0
#define WDC_ERR_UNKNOWN -1
#define WDC_ERR_UNSUPPORTED_ABI -2
#define WDC_ERR_BAD_POINTER -3
#define WDC_ERR_BAD_LENGTH -4
#define WDC_ERR_BAD_ENCODING -5
#define WDC_ERR_UNSUPPORTED_OPCODE -6
#define WDC_ERR_CAPABILITY_DENIED -7
#define WDC_ERR_INVALID_RESOURCE -8
#define WDC_ERR_INVALID_STATE -9
#define WDC_ERR_BUSY -10
#define WDC_ERR_TIMEOUT -11
#define WDC_ERR_NO_MEMORY -12
#define WDC_ERR_RESPONSE_TOO_SMALL -13
#define WDC_ERR_RATE_LIMITED -14
#define WDC_ERR_CONTRACT_VIOLATION -15
#define WDC_ERR_IO -16
#define WDC_ERR_NOT_AVAILABLE -17
#define WDC_ERR_NOT_SYNCHRONIZED -18

#define WDC_OP_SYS_GET_INFO 0x0001u
#define WDC_OP_TIMER_SET    0x0101u
#define WDC_OP_TIMER_CANCEL 0x0102u
#define WDC_OP_CONFIG_GET   0x0201u
#define WDC_OP_CONFIG_SET   0x0202u
#define WDC_OP_CONFIG_DELETE 0x0203u
#define WDC_OP_GPIO_GET     0x0301u
#define WDC_OP_GPIO_SET     0x0302u
#define WDC_OP_GPIO_SUBSCRIBE 0x0303u
#define WDC_OP_NET_STATUS 0x0501u
#define WDC_OP_MQTT_PUBLISH 0x0502u
#define WDC_OP_MQTT_SUBSCRIBE 0x0503u
#define WDC_OP_HTTP_REQUEST 0x0504u

#define WDC_CBOR_KEY_STATUS        0u
#define WDC_CBOR_KEY_ABI_MAJOR     1u
#define WDC_CBOR_KEY_ABI_MINOR     2u
#define WDC_CBOR_KEY_RESOURCE_ID   3u
#define WDC_CBOR_KEY_VALUE         4u
#define WDC_CBOR_KEY_TIMER_ID      5u
#define WDC_CBOR_KEY_DELAY_MS      6u
#define WDC_CBOR_KEY_REPEAT        7u
#define WDC_CBOR_KEY_KEY           8u
#define WDC_CBOR_KEY_DATA          9u
#define WDC_CBOR_KEY_BUILD_STAGE   10u
#define WDC_CBOR_KEY_SHELL_VERSION 11u
#define WDC_CBOR_KEY_ABI_VERSION   12u
#define WDC_CBOR_KEY_EVENT_TYPE    13u
#define WDC_CBOR_KEY_EVENT_ID      14u
#define WDC_CBOR_KEY_TIMESTAMP_MS  15u
#define WDC_CBOR_KEY_PAYLOAD       16u
#define WDC_CBOR_KEY_EVENT_PAYLOAD WDC_CBOR_KEY_PAYLOAD
#define WDC_CBOR_KEY_CAPABILITY    17u
#define WDC_CBOR_KEY_DECISION      18u
#define WDC_CBOR_KEY_RESULT        19u
#define WDC_CBOR_KEY_RESOURCE_NAME 20u
#define WDC_CBOR_KEY_BUNDLE_NAME   21u
#define WDC_CBOR_KEY_BUNDLE_VERSION 22u
#define WDC_CBOR_KEY_QUEUE_DROPPED 23u
#define WDC_CBOR_KEY_CONNECTED 24u
#define WDC_CBOR_KEY_TOPIC 25u
#define WDC_CBOR_KEY_QOS 26u
#define WDC_CBOR_KEY_RETAIN 27u
#define WDC_CBOR_KEY_REQUEST_ID 28u
#define WDC_CBOR_KEY_METHOD 29u
#define WDC_CBOR_KEY_URL 30u
#define WDC_CBOR_KEY_HTTP_STATUS 31u
#define WDC_CBOR_KEY_NETWORK_STATE 32u
#define WDC_CBOR_KEY_SLOT 33u
#define WDC_CBOR_KEY_SECURITY_COUNTER 34u
#define WDC_CBOR_KEY_PENDING_COUNT 35u
#define WDC_CBOR_KEY_PAYLOAD_LEN 36u

#define WDC_R3_RESOURCE_RELAY_1    1u
#define WDC_R3_RESOURCE_STATUS_LED 2u
#define WDC_R3_RESOURCE_BUTTON_1   3u
#define WDC_R4_RESOURCE_RELAY_1     WDC_R3_RESOURCE_RELAY_1
#define WDC_R4_RESOURCE_STATUS_LED  WDC_R3_RESOURCE_STATUS_LED
#define WDC_R4_RESOURCE_BUTTON_1    WDC_R3_RESOURCE_BUTTON_1
#define WDC_R4_RESOURCE_MQTT_TELEMETRY 20u
#define WDC_R8_RESOURCE_MQTT_TELEMETRY WDC_R4_RESOURCE_MQTT_TELEMETRY
#define WDC_R8_RESOURCE_MQTT_COMMANDS 21u
#define WDC_R8_RESOURCE_HTTP_API 22u
#define WDC_R4_EVENT_ABI_VERSION    ((WDC_ABI_MAJOR << 16u) | WDC_ABI_MINOR)

#define WDC_EVENT_BOOT 0x0001u
#define WDC_EVENT_SHUTDOWN_REQUEST 0x0002u
#define WDC_EVENT_CONFIG_CHANGED 0x0003u
#define WDC_EVENT_MODULE_PROBATION_STARTED 0x0004u
#define WDC_EVENT_MODULE_PROBATION_ENDING 0x0005u
#define WDC_EVENT_TIMER_FIRED 0x0101u
#define WDC_EVENT_GPIO_CHANGED 0x0201u
#define WDC_EVENT_FAULT 0x0701u
#define WDC_EVENT_SAFETY_STATE_CHANGED 0x0702u
#define WDC_EVENT_PHYSICAL_ACTION 0x0703u
#define WDC_EVENT_NET_STATE_CHANGED 0x0801u
#define WDC_EVENT_NETWORK_STATUS_CHANGED WDC_EVENT_NET_STATE_CHANGED
#define WDC_EVENT_NET_CONNECTED WDC_EVENT_NET_STATE_CHANGED
#define WDC_EVENT_NET_DISCONNECTED 0x0802u
#define WDC_EVENT_MQTT_MESSAGE 0x0803u
#define WDC_EVENT_HTTP_RESPONSE 0x0804u

typedef struct WdcGuestEventEnvelope {
    uint32_t abi_version;
    uint32_t event_type;
    uint32_t event_id;
    uint64_t timestamp_ms;
    uint32_t resource_id;
} WdcGuestEventEnvelope;

/* Imported by guest from module "wdc". */
int32_t wdc_log(int32_t level, uint32_t ptr, uint32_t len);
uint64_t wdc_millis(void);
int32_t wdc_random(uint32_t ptr, uint32_t len);
int32_t wdc_yield(void);
int32_t wdc_host_call(uint32_t opcode, uint32_t req_ptr, uint32_t req_len, uint32_t rsp_ptr, uint32_t rsp_cap);

/* Exported by guest. */
int32_t wdc_module_init(void);
int32_t wdc_module_on_event(uint32_t event_ptr, uint32_t event_len);
int32_t wdc_module_health(void);
int32_t wdc_module_shutdown(int32_t reason);

typedef struct WdcGuestCborBuilder {
    uint8_t *buf;
    uint32_t cap;
    uint32_t len;
} WdcGuestCborBuilder;

static inline void wdc_guest_cbor_init(WdcGuestCborBuilder *b, uint8_t *buf, uint32_t cap)
{
    if (b != 0) { b->buf = buf; b->cap = cap; b->len = 0u; }
}

static inline int32_t wdc_guest_cbor_put_u8(WdcGuestCborBuilder *b, uint8_t value)
{
    if (b == 0 || b->buf == 0) { return WDC_ERR_BAD_POINTER; }
    if (b->len >= b->cap) { return WDC_ERR_RESPONSE_TOO_SMALL; }
    b->buf[b->len++] = value;
    return WDC_OK;
}

static inline int32_t wdc_guest_cbor_put_raw(WdcGuestCborBuilder *b, const uint8_t *value, uint32_t len)
{
    if (b == 0 || b->buf == 0 || (len != 0u && value == 0)) { return WDC_ERR_BAD_POINTER; }
    if (len > b->cap || b->len > b->cap - len) { return WDC_ERR_RESPONSE_TOO_SMALL; }
    for (uint32_t i = 0u; i < len; ++i) { b->buf[b->len + i] = value[i]; }
    b->len += len;
    return WDC_OK;
}

static inline int32_t wdc_guest_cbor_put_type_value(WdcGuestCborBuilder *b, uint8_t major, uint64_t value)
{
    const uint8_t prefix = (uint8_t)(major << 5u);
    if (value <= 23u) { return wdc_guest_cbor_put_u8(b, (uint8_t)(prefix | (uint8_t)value)); }
    if (value <= 0xffu) {
        int32_t st = wdc_guest_cbor_put_u8(b, (uint8_t)(prefix | 24u));
        return st == WDC_OK ? wdc_guest_cbor_put_u8(b, (uint8_t)value) : st;
    }
    if (value <= 0xffffu) {
        int32_t st = wdc_guest_cbor_put_u8(b, (uint8_t)(prefix | 25u));
        if (st != WDC_OK) { return st; }
        st = wdc_guest_cbor_put_u8(b, (uint8_t)((value >> 8u) & 0xffu));
        return st == WDC_OK ? wdc_guest_cbor_put_u8(b, (uint8_t)(value & 0xffu)) : st;
    }
    int32_t st = wdc_guest_cbor_put_u8(b, (uint8_t)(prefix | 26u));
    if (st != WDC_OK) { return st; }
    for (int shift = 24; shift >= 0; shift -= 8) {
        st = wdc_guest_cbor_put_u8(b, (uint8_t)((value >> (unsigned)shift) & 0xffu));
        if (st != WDC_OK) { return st; }
    }
    return WDC_OK;
}

static inline int32_t wdc_guest_cbor_begin_map(WdcGuestCborBuilder *b, uint32_t pairs)
{
    return wdc_guest_cbor_put_type_value(b, 5u, pairs);
}

static inline int32_t wdc_guest_cbor_put_key(WdcGuestCborBuilder *b, uint32_t key)
{
    return wdc_guest_cbor_put_type_value(b, 0u, key);
}

static inline int32_t wdc_guest_cbor_put_key_u32(WdcGuestCborBuilder *b, uint32_t key, uint32_t value)
{
    int32_t st = wdc_guest_cbor_put_key(b, key);
    return st == WDC_OK ? wdc_guest_cbor_put_type_value(b, 0u, value) : st;
}

static inline int32_t wdc_guest_cbor_put_key_bool(WdcGuestCborBuilder *b, uint32_t key, bool value)
{
    int32_t st = wdc_guest_cbor_put_key(b, key);
    return st == WDC_OK ? wdc_guest_cbor_put_u8(b, value ? 0xf5u : 0xf4u) : st;
}

static inline int32_t wdc_guest_cbor_put_key_text(WdcGuestCborBuilder *b, uint32_t key, const char *value)
{
    if (value == 0) { return WDC_ERR_BAD_POINTER; }
    uint32_t len = (uint32_t)strlen(value);
    int32_t st = wdc_guest_cbor_put_key(b, key);
    if (st != WDC_OK) { return st; }
    st = wdc_guest_cbor_put_type_value(b, 3u, len);
    return st == WDC_OK ? wdc_guest_cbor_put_raw(b, (const uint8_t *)value, len) : st;
}

static inline int32_t wdc_guest_cbor_put_key_bytes(WdcGuestCborBuilder *b, uint32_t key, const uint8_t *value, uint32_t len)
{
    int32_t st = wdc_guest_cbor_put_key(b, key);
    if (st != WDC_OK) { return st; }
    st = wdc_guest_cbor_put_type_value(b, 2u, len);
    return st == WDC_OK ? wdc_guest_cbor_put_raw(b, value, len) : st;
}

static inline int32_t wdc_guest_cbor_read_type_value(const uint8_t *buf, uint32_t len, uint32_t *offset, uint8_t *major, uint64_t *value)
{
    if (buf == 0 || offset == 0 || major == 0 || value == 0) { return WDC_ERR_BAD_POINTER; }
    if (*offset >= len) { return WDC_ERR_BAD_ENCODING; }
    uint8_t initial = buf[(*offset)++];
    *major = (uint8_t)(initial >> 5u);
    uint8_t addl = (uint8_t)(initial & 0x1fu);
    if (addl <= 23u) { *value = addl; return WDC_OK; }
    if (addl == 24u) {
        if (*offset >= len) { return WDC_ERR_BAD_ENCODING; }
        *value = buf[(*offset)++]; return WDC_OK;
    }
    if (addl == 25u) {
        if (len - *offset < 2u) { return WDC_ERR_BAD_ENCODING; }
        *value = ((uint64_t)buf[*offset] << 8u) | (uint64_t)buf[*offset + 1u];
        *offset += 2u; return WDC_OK;
    }
    if (addl == 26u) {
        if (len - *offset < 4u) { return WDC_ERR_BAD_ENCODING; }
        *value = ((uint64_t)buf[*offset] << 24u) | ((uint64_t)buf[*offset + 1u] << 16u) | ((uint64_t)buf[*offset + 2u] << 8u) | (uint64_t)buf[*offset + 3u];
        *offset += 4u; return WDC_OK;
    }
    return WDC_ERR_BAD_ENCODING;
}

static inline int32_t wdc_guest_cbor_skip_value(const uint8_t *buf, uint32_t len, uint32_t *offset)
{
    if (buf == 0 || offset == 0 || *offset >= len) { return WDC_ERR_BAD_POINTER; }
    if (buf[*offset] == 0xf4u || buf[*offset] == 0xf5u) { *offset += 1u; return WDC_OK; }
    uint8_t major = 0u; uint64_t value = 0u;
    int32_t st = wdc_guest_cbor_read_type_value(buf, len, offset, &major, &value);
    if (st != WDC_OK) { return st; }
    if (major == 2u || major == 3u) {
        if (value > len - *offset) { return WDC_ERR_BAD_ENCODING; }
        *offset += (uint32_t)value;
    }
    return WDC_OK;
}

static inline int32_t wdc_guest_cbor_find_item(const uint8_t *buf, uint32_t len, uint32_t wanted_key, uint32_t *value_offset)
{
    if (buf == 0 || value_offset == 0) { return WDC_ERR_BAD_POINTER; }
    uint32_t off = 0u; uint8_t major = 0u; uint64_t pairs = 0u;
    int32_t st = wdc_guest_cbor_read_type_value(buf, len, &off, &major, &pairs);
    if (st != WDC_OK) { return st; }
    if (major != 5u || pairs > 32u) { return WDC_ERR_BAD_ENCODING; }
    for (uint64_t i = 0u; i < pairs; ++i) {
        uint8_t key_major = 0u; uint64_t key = 0u;
        st = wdc_guest_cbor_read_type_value(buf, len, &off, &key_major, &key);
        if (st != WDC_OK) { return st; }
        if (key_major != 0u) { return WDC_ERR_BAD_ENCODING; }
        if (key == wanted_key) { *value_offset = off; return WDC_OK; }
        st = wdc_guest_cbor_skip_value(buf, len, &off);
        if (st != WDC_OK) { return st; }
    }
    return WDC_ERR_NOT_AVAILABLE;
}

static inline int32_t wdc_guest_cbor_find_i32(const uint8_t *buf, uint32_t len, uint32_t key, int32_t *out)
{
    uint32_t off = 0u; uint8_t major = 0u; uint64_t value = 0u;
    int32_t st = wdc_guest_cbor_find_item(buf, len, key, &off);
    if (st != WDC_OK) { return st; }
    st = wdc_guest_cbor_read_type_value(buf, len, &off, &major, &value);
    if (st != WDC_OK) { return st; }
    if (major == 0u && value <= 0x7fffffffu) { *out = (int32_t)value; return WDC_OK; }
    if (major == 1u && value <= 0x7fffffffu) { *out = -1 - (int32_t)value; return WDC_OK; }
    return WDC_ERR_BAD_ENCODING;
}

static inline int32_t wdc_guest_cbor_find_u32(const uint8_t *buf, uint32_t len, uint32_t key, uint32_t *out)
{
    uint32_t off = 0u; uint8_t major = 0u; uint64_t value = 0u;
    int32_t st = wdc_guest_cbor_find_item(buf, len, key, &off);
    if (st != WDC_OK) { return st; }
    st = wdc_guest_cbor_read_type_value(buf, len, &off, &major, &value);
    if (st != WDC_OK) { return st; }
    if (major != 0u || value > 0xffffffffu) { return WDC_ERR_BAD_ENCODING; }
    *out = (uint32_t)value;
    return WDC_OK;
}

static inline int32_t wdc_guest_cbor_find_u64(const uint8_t *buf, uint32_t len, uint32_t key, uint64_t *out)
{
    uint32_t off = 0u; uint8_t major = 0u; uint64_t value = 0u;
    int32_t st = wdc_guest_cbor_find_item(buf, len, key, &off);
    if (st != WDC_OK) { return st; }
    st = wdc_guest_cbor_read_type_value(buf, len, &off, &major, &value);
    if (st != WDC_OK) { return st; }
    if (major != 0u) { return WDC_ERR_BAD_ENCODING; }
    *out = value;
    return WDC_OK;
}

static inline int32_t wdc_guest_cbor_find_bool(const uint8_t *buf, uint32_t len, uint32_t key, bool *out)
{
    if (buf == 0 || out == 0) { return WDC_ERR_BAD_POINTER; }
    uint32_t off = 0u;
    int32_t st = wdc_guest_cbor_find_item(buf, len, key, &off);
    if (st != WDC_OK) { return st; }
    if (off >= len) { return WDC_ERR_BAD_ENCODING; }
    if (buf[off] == 0xf4u) { *out = false; return WDC_OK; }
    if (buf[off] == 0xf5u) { *out = true; return WDC_OK; }
    return WDC_ERR_BAD_ENCODING;
}

static inline int32_t wdc_guest_response_status(const uint8_t *rsp, uint32_t rsp_len)
{
    int32_t status = WDC_ERR_UNKNOWN;
    int32_t st = wdc_guest_cbor_find_i32(rsp, rsp_len, WDC_CBOR_KEY_STATUS, &status);
    return st == WDC_OK ? status : st;
}

static inline int32_t wdc_guest_call_status(uint32_t opcode, uint8_t *req, uint32_t req_len, uint8_t *rsp, uint32_t rsp_cap)
{
    int32_t st = wdc_host_call(opcode, (uint32_t)(uintptr_t)req, req_len, (uint32_t)(uintptr_t)rsp, rsp_cap);
    if (st != WDC_OK) { return st; }
    return wdc_guest_response_status(rsp, rsp_cap);
}

static inline int32_t wdc_guest_timer_set(uint32_t timer_id, uint32_t delay_ms, bool repeat)
{
    uint8_t req[32]; uint8_t rsp[32]; WdcGuestCborBuilder b;
    wdc_guest_cbor_init(&b, req, sizeof(req));
    int32_t st = wdc_guest_cbor_begin_map(&b, 3u);
    if (st == WDC_OK) { st = wdc_guest_cbor_put_key_u32(&b, WDC_CBOR_KEY_TIMER_ID, timer_id); }
    if (st == WDC_OK) { st = wdc_guest_cbor_put_key_u32(&b, WDC_CBOR_KEY_DELAY_MS, delay_ms); }
    if (st == WDC_OK) { st = wdc_guest_cbor_put_key_bool(&b, WDC_CBOR_KEY_REPEAT, repeat); }
    return st == WDC_OK ? wdc_guest_call_status(WDC_OP_TIMER_SET, req, b.len, rsp, sizeof(rsp)) : st;
}

static inline int32_t wdc_guest_timer_cancel(uint32_t timer_id)
{
    uint8_t req[16]; uint8_t rsp[32]; WdcGuestCborBuilder b;
    wdc_guest_cbor_init(&b, req, sizeof(req));
    int32_t st = wdc_guest_cbor_begin_map(&b, 1u);
    if (st == WDC_OK) { st = wdc_guest_cbor_put_key_u32(&b, WDC_CBOR_KEY_TIMER_ID, timer_id); }
    return st == WDC_OK ? wdc_guest_call_status(WDC_OP_TIMER_CANCEL, req, b.len, rsp, sizeof(rsp)) : st;
}

static inline int32_t wdc_guest_gpio_set(uint32_t resource_id, bool value)
{
    uint8_t req[16]; uint8_t rsp[32]; WdcGuestCborBuilder b;
    wdc_guest_cbor_init(&b, req, sizeof(req));
    int32_t st = wdc_guest_cbor_begin_map(&b, 2u);
    if (st == WDC_OK) { st = wdc_guest_cbor_put_key_u32(&b, WDC_CBOR_KEY_RESOURCE_ID, resource_id); }
    if (st == WDC_OK) { st = wdc_guest_cbor_put_key_bool(&b, WDC_CBOR_KEY_VALUE, value); }
    return st == WDC_OK ? wdc_guest_call_status(WDC_OP_GPIO_SET, req, b.len, rsp, sizeof(rsp)) : st;
}

static inline int32_t wdc_guest_gpio_get(uint32_t resource_id, bool *out_value)
{
    if (out_value == 0) { return WDC_ERR_BAD_POINTER; }
    uint8_t req[16]; uint8_t rsp[40]; WdcGuestCborBuilder b;
    wdc_guest_cbor_init(&b, req, sizeof(req));
    int32_t st = wdc_guest_cbor_begin_map(&b, 1u);
    if (st == WDC_OK) { st = wdc_guest_cbor_put_key_u32(&b, WDC_CBOR_KEY_RESOURCE_ID, resource_id); }
    if (st != WDC_OK) { return st; }
    st = wdc_host_call(WDC_OP_GPIO_GET, (uint32_t)(uintptr_t)req, b.len, (uint32_t)(uintptr_t)rsp, sizeof(rsp));
    if (st != WDC_OK) { return st; }
    st = wdc_guest_response_status(rsp, sizeof(rsp));
    if (st != WDC_OK) { return st; }
    uint32_t value = 0u;
    st = wdc_guest_cbor_find_u32(rsp, sizeof(rsp), WDC_CBOR_KEY_VALUE, &value);
    if (st == WDC_OK) { *out_value = value != 0u; }
    return st;
}

static inline int32_t wdc_guest_config_set(const char *key, const uint8_t *value, uint32_t value_len, uint8_t *req, uint32_t req_cap, uint8_t *rsp, uint32_t rsp_cap)
{
    WdcGuestCborBuilder b;
    wdc_guest_cbor_init(&b, req, req_cap);
    int32_t st = wdc_guest_cbor_begin_map(&b, 2u);
    if (st == WDC_OK) { st = wdc_guest_cbor_put_key_text(&b, WDC_CBOR_KEY_KEY, key); }
    if (st == WDC_OK) { st = wdc_guest_cbor_put_key_bytes(&b, WDC_CBOR_KEY_DATA, value, value_len); }
    return st == WDC_OK ? wdc_guest_call_status(WDC_OP_CONFIG_SET, req, b.len, rsp, rsp_cap) : st;
}

static inline int32_t wdc_guest_net_status(bool *out_connected, uint32_t *out_state, uint8_t *rsp, uint32_t rsp_cap)
{
    uint8_t req[1] = {0xa0u};
    int32_t st = wdc_host_call(WDC_OP_NET_STATUS, (uint32_t)(uintptr_t)req, sizeof(req), (uint32_t)(uintptr_t)rsp, rsp_cap);
    if (st != WDC_OK) { return st; }
    st = wdc_guest_response_status(rsp, rsp_cap);
    if (st != WDC_OK) { return st; }
    if (out_connected != 0) { st = wdc_guest_cbor_find_bool(rsp, rsp_cap, WDC_CBOR_KEY_CONNECTED, out_connected); if (st != WDC_OK) { return st; } }
    if (out_state != 0) { st = wdc_guest_cbor_find_u32(rsp, rsp_cap, WDC_CBOR_KEY_NETWORK_STATE, out_state); if (st != WDC_OK) { return st; } }
    return WDC_OK;
}

static inline int32_t wdc_guest_mqtt_publish(uint32_t resource_id, const char *topic, const uint8_t *payload, uint32_t payload_len, uint32_t qos, uint8_t *req, uint32_t req_cap, uint8_t *rsp, uint32_t rsp_cap)
{
    WdcGuestCborBuilder b;
    wdc_guest_cbor_init(&b, req, req_cap);
    int32_t st = wdc_guest_cbor_begin_map(&b, 4u);
    if (st == WDC_OK) { st = wdc_guest_cbor_put_key_u32(&b, WDC_CBOR_KEY_RESOURCE_ID, resource_id); }
    if (st == WDC_OK) { st = wdc_guest_cbor_put_key_text(&b, WDC_CBOR_KEY_TOPIC, topic); }
    if (st == WDC_OK) { st = wdc_guest_cbor_put_key_bytes(&b, WDC_CBOR_KEY_DATA, payload, payload_len); }
    if (st == WDC_OK) { st = wdc_guest_cbor_put_key_u32(&b, WDC_CBOR_KEY_QOS, qos); }
    return st == WDC_OK ? wdc_guest_call_status(WDC_OP_MQTT_PUBLISH, req, b.len, rsp, rsp_cap) : st;
}

static inline int32_t wdc_guest_mqtt_subscribe(uint32_t resource_id, const char *topic, uint8_t *req, uint32_t req_cap, uint8_t *rsp, uint32_t rsp_cap)
{
    WdcGuestCborBuilder b;
    wdc_guest_cbor_init(&b, req, req_cap);
    int32_t st = wdc_guest_cbor_begin_map(&b, 2u);
    if (st == WDC_OK) { st = wdc_guest_cbor_put_key_u32(&b, WDC_CBOR_KEY_RESOURCE_ID, resource_id); }
    if (st == WDC_OK) { st = wdc_guest_cbor_put_key_text(&b, WDC_CBOR_KEY_TOPIC, topic); }
    return st == WDC_OK ? wdc_guest_call_status(WDC_OP_MQTT_SUBSCRIBE, req, b.len, rsp, rsp_cap) : st;
}

static inline int32_t wdc_guest_http_request(uint32_t resource_id, const char *method, const char *url, const uint8_t *body, uint32_t body_len, uint8_t *req, uint32_t req_cap, uint8_t *rsp, uint32_t rsp_cap)
{
    WdcGuestCborBuilder b;
    wdc_guest_cbor_init(&b, req, req_cap);
    int32_t st = wdc_guest_cbor_begin_map(&b, 4u);
    if (st == WDC_OK) { st = wdc_guest_cbor_put_key_u32(&b, WDC_CBOR_KEY_RESOURCE_ID, resource_id); }
    if (st == WDC_OK) { st = wdc_guest_cbor_put_key_text(&b, WDC_CBOR_KEY_METHOD, method); }
    if (st == WDC_OK) { st = wdc_guest_cbor_put_key_text(&b, WDC_CBOR_KEY_URL, url); }
    if (st == WDC_OK) { st = wdc_guest_cbor_put_key_bytes(&b, WDC_CBOR_KEY_DATA, body, body_len); }
    return st == WDC_OK ? wdc_guest_call_status(WDC_OP_HTTP_REQUEST, req, b.len, rsp, rsp_cap) : st;
}

#ifdef __cplusplus
}
#endif
