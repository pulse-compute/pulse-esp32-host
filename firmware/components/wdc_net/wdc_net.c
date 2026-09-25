#include "wdc_net.h"

#include <string.h>

static const WdcDeviceProfile *s_profile;
static WdcNetStatus s_status;
static WdcNetHttpResponseHookFn s_http_response_hook;
static void *s_http_response_context;

const char *wdc_net_state_name(WdcNetState state)
{
    switch (state) {
    case WDC_NET_STATE_UNINITIALIZED: return "uninitialized";
    case WDC_NET_STATE_DISCONNECTED: return "disconnected";
    case WDC_NET_STATE_CONNECTED: return "connected";
    case WDC_NET_STATE_DEGRADED: return "degraded";
    default: return "unknown";
    }
}

static int32_t finish_response(WdcCborBuilder *builder, uint32_t *out_len)
{
    if (out_len != NULL) {
        *out_len = wdc_cbor_len(builder);
    }
    return WDC_OK;
}

static int32_t write_status_response(uint8_t *response, uint32_t response_cap, uint32_t *out_len, int32_t code)
{
    WdcCborBuilder builder;
    wdc_cbor_builder_init(&builder, response, response_cap);
    int32_t status = wdc_cbor_begin_map(&builder, 1u);
    if (status == WDC_OK) { status = wdc_cbor_put_key_i32(&builder, WDC_CBOR_KEY_STATUS, code); }
    return status == WDC_OK ? finish_response(&builder, out_len) : status;
}

static int32_t write_net_status_response(uint8_t *response, uint32_t response_cap, uint32_t *out_len)
{
    WdcCborBuilder builder;
    wdc_cbor_builder_init(&builder, response, response_cap);
    int32_t status = wdc_cbor_begin_map(&builder, 5u);
    if (status == WDC_OK) { status = wdc_cbor_put_key_i32(&builder, WDC_CBOR_KEY_STATUS, WDC_OK); }
    if (status == WDC_OK) { status = wdc_cbor_put_key_bool(&builder, WDC_CBOR_KEY_CONNECTED, s_status.connected); }
    if (status == WDC_OK) { status = wdc_cbor_put_key_u32(&builder, WDC_CBOR_KEY_NETWORK_STATE, (uint32_t)s_status.state); }
    if (status == WDC_OK) { status = wdc_cbor_put_key_u32(&builder, WDC_CBOR_KEY_PENDING_COUNT, s_status.http_request_count + s_status.subscribe_count); }
    if (status == WDC_OK) { status = wdc_cbor_put_key_u32(&builder, WDC_CBOR_KEY_REQUEST_ID, s_status.last_request_id); }
    return status == WDC_OK ? finish_response(&builder, out_len) : status;
}

static int32_t copy_text(WdcCborText text, char *out, uint32_t out_cap)
{
    if (out == NULL || out_cap == 0u) {
        return WDC_ERR_BAD_POINTER;
    }
    if (text.ptr == NULL || text.len == 0u || text.len >= out_cap) {
        return WDC_ERR_BAD_LENGTH;
    }
    memcpy(out, text.ptr, text.len);
    out[text.len] = '\0';
    return WDC_OK;
}

static bool resource_is_network(uint32_t resource_id)
{
    const WdcProfileResource *resource = wdc_profile_find_resource_by_id(s_profile, resource_id);
    return resource != NULL && resource->kind == WDC_RESOURCE_KIND_NETWORK;
}

static int32_t parse_network_resource(const uint8_t *request, uint32_t request_len, uint32_t *out_resource_id)
{
    if (out_resource_id == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    uint32_t resource_id = 0u;
    int32_t status = wdc_cbor_map_find_u32(request, request_len, WDC_CBOR_KEY_RESOURCE_ID, &resource_id);
    if (status != WDC_OK) {
        return WDC_ERR_BAD_ENCODING;
    }
    if (!resource_is_network(resource_id)) {
        return WDC_ERR_INVALID_RESOURCE;
    }
    *out_resource_id = resource_id;
    return WDC_OK;
}

static int32_t require_connected(void)
{
    if (!s_status.initialized) {
        return WDC_ERR_INVALID_STATE;
    }
    if (!s_status.connected) {
        s_status.denied_disconnected_count++;
        s_status.last_status = WDC_ERR_NOT_SYNCHRONIZED;
        return WDC_ERR_NOT_SYNCHRONIZED;
    }
    return WDC_OK;
}

static uint32_t next_request_id(void)
{
    uint32_t request_id = s_status.next_request_id;
    if (request_id == 0u) {
        request_id = 1u;
    }
    s_status.next_request_id = request_id + 1u;
    s_status.last_request_id = request_id;
    return request_id;
}

static bool text_has_prefix(WdcCborText text, const char *prefix)
{
    if (prefix == NULL || prefix[0] == '\0') {
        return false;
    }
    size_t n = strlen(prefix);
    return text.len >= n && memcmp(text.ptr, prefix, n) == 0;
}

static bool method_allowed(WdcCborText method, const char *allowed_csv)
{
    if (allowed_csv == NULL || allowed_csv[0] == '\0' || method.len == 0u) {
        return false;
    }
    const char *p = allowed_csv;
    while (*p != '\0') {
        while (*p == ',' || *p == ' ') { p++; }
        const char *start = p;
        while (*p != '\0' && *p != ',') { p++; }
        size_t len = (size_t)(p - start);
        while (len > 0u && start[len - 1u] == ' ') { len--; }
        if (len == method.len && memcmp(method.ptr, start, len) == 0) {
            return true;
        }
    }
    return false;
}

static int32_t network_policy_for(uint32_t resource_id, const WdcNetworkResource **out_policy)
{
    if (out_policy != NULL) { *out_policy = NULL; }
    if (s_profile == NULL) {
        return WDC_ERR_INVALID_STATE;
    }
    const WdcNetworkResource *policy = wdc_profile_find_network_by_id(s_profile, resource_id);
    if (policy == NULL) {
        return WDC_ERR_INVALID_RESOURCE;
    }
    if (out_policy != NULL) { *out_policy = policy; }
    return WDC_OK;
}

static int32_t reject_policy(uint8_t *response, uint32_t response_cap, uint32_t *out_response_len, int32_t code)
{
    s_status.rejected_count++;
    s_status.last_status = code;
    return write_status_response(response, response_cap, out_response_len, code);
}

static int32_t mqtt_publish(const uint8_t *request,
                            uint32_t request_len,
                            uint8_t *response,
                            uint32_t response_cap,
                            uint32_t *out_response_len)
{
    uint32_t resource_id = 0u;
    int32_t status = parse_network_resource(request, request_len, &resource_id);
    if (status != WDC_OK) {
        s_status.rejected_count++;
        s_status.last_status = status;
        return write_status_response(response, response_cap, out_response_len, status);
    }
    status = require_connected();
    if (status != WDC_OK) {
        return write_status_response(response, response_cap, out_response_len, status);
    }

    WdcCborText topic = {0};
    status = wdc_cbor_map_find_text(request, request_len, WDC_CBOR_KEY_TOPIC, &topic);
    if (status != WDC_OK) {
        s_status.rejected_count++;
        s_status.last_status = WDC_ERR_BAD_ENCODING;
        return write_status_response(response, response_cap, out_response_len, WDC_ERR_BAD_ENCODING);
    }
    WdcCborBytes payload = {0};
    status = wdc_cbor_map_find_bytes(request, request_len, WDC_CBOR_KEY_DATA, &payload);
    if (status != WDC_OK && status != WDC_ERR_NOT_AVAILABLE) {
        s_status.rejected_count++;
        s_status.last_status = WDC_ERR_BAD_ENCODING;
        return write_status_response(response, response_cap, out_response_len, WDC_ERR_BAD_ENCODING);
    }
    if (payload.len > WDC_NET_PAYLOAD_MAX_BYTES) {
        s_status.rejected_count++;
        s_status.last_status = WDC_ERR_BAD_LENGTH;
        return write_status_response(response, response_cap, out_response_len, WDC_ERR_BAD_LENGTH);
    }
    const WdcNetworkResource *policy = NULL;
    status = network_policy_for(resource_id, &policy);
    if (status != WDC_OK) {
        return reject_policy(response, response_cap, out_response_len, status);
    }
    if (policy->mqtt_topic_prefix == NULL || !text_has_prefix(topic, policy->mqtt_topic_prefix)) {
        return reject_policy(response, response_cap, out_response_len, WDC_ERR_CAPABILITY_DENIED);
    }
    if (payload.len > policy->max_payload_bytes) {
        return reject_policy(response, response_cap, out_response_len, WDC_ERR_BAD_LENGTH);
    }
    uint32_t qos = 0u;
    status = wdc_cbor_map_find_u32(request, request_len, WDC_CBOR_KEY_QOS, &qos);
    if (status != WDC_OK && status != WDC_ERR_NOT_AVAILABLE) {
        s_status.rejected_count++;
        s_status.last_status = WDC_ERR_BAD_ENCODING;
        return write_status_response(response, response_cap, out_response_len, WDC_ERR_BAD_ENCODING);
    }
    if (qos > 2u) {
        s_status.rejected_count++;
        s_status.last_status = WDC_ERR_BAD_ENCODING;
        return write_status_response(response, response_cap, out_response_len, WDC_ERR_BAD_ENCODING);
    }

    status = copy_text(topic, s_status.last_publish.topic, sizeof(s_status.last_publish.topic));
    if (status != WDC_OK) {
        s_status.rejected_count++;
        s_status.last_status = status;
        return write_status_response(response, response_cap, out_response_len, status);
    }
    s_status.last_publish.resource_id = resource_id;
    s_status.last_publish.request_id = next_request_id();
    s_status.last_publish.payload_len = payload.len;
    s_status.last_publish.qos = qos;
    s_status.publish_count++;
    s_status.last_status = WDC_OK;

    WdcCborBuilder builder;
    wdc_cbor_builder_init(&builder, response, response_cap);
    status = wdc_cbor_begin_map(&builder, 2u);
    if (status == WDC_OK) { status = wdc_cbor_put_key_i32(&builder, WDC_CBOR_KEY_STATUS, WDC_OK); }
    if (status == WDC_OK) { status = wdc_cbor_put_key_u32(&builder, WDC_CBOR_KEY_REQUEST_ID, s_status.last_publish.request_id); }
    return status == WDC_OK ? finish_response(&builder, out_response_len) : status;
}

static int32_t mqtt_subscribe(const uint8_t *request,
                              uint32_t request_len,
                              uint8_t *response,
                              uint32_t response_cap,
                              uint32_t *out_response_len)
{
    uint32_t resource_id = 0u;
    int32_t status = parse_network_resource(request, request_len, &resource_id);
    if (status != WDC_OK) {
        s_status.rejected_count++;
        s_status.last_status = status;
        return write_status_response(response, response_cap, out_response_len, status);
    }
    status = require_connected();
    if (status != WDC_OK) {
        return write_status_response(response, response_cap, out_response_len, status);
    }

    WdcCborText topic = {0};
    status = wdc_cbor_map_find_text(request, request_len, WDC_CBOR_KEY_TOPIC, &topic);
    if (status != WDC_OK) {
        s_status.rejected_count++;
        s_status.last_status = WDC_ERR_BAD_ENCODING;
        return write_status_response(response, response_cap, out_response_len, WDC_ERR_BAD_ENCODING);
    }
    const WdcNetworkResource *policy = NULL;
    status = network_policy_for(resource_id, &policy);
    if (status != WDC_OK) {
        return reject_policy(response, response_cap, out_response_len, status);
    }
    if (policy->mqtt_subscribe_prefix == NULL || !text_has_prefix(topic, policy->mqtt_subscribe_prefix)) {
        return reject_policy(response, response_cap, out_response_len, WDC_ERR_CAPABILITY_DENIED);
    }

    status = copy_text(topic, s_status.last_subscribe.topic, sizeof(s_status.last_subscribe.topic));
    if (status != WDC_OK) {
        s_status.rejected_count++;
        s_status.last_status = status;
        return write_status_response(response, response_cap, out_response_len, status);
    }
    s_status.last_subscribe.resource_id = resource_id;
    s_status.last_subscribe.request_id = next_request_id();
    s_status.subscribe_count++;
    s_status.last_status = WDC_OK;

    WdcCborBuilder builder;
    wdc_cbor_builder_init(&builder, response, response_cap);
    status = wdc_cbor_begin_map(&builder, 2u);
    if (status == WDC_OK) { status = wdc_cbor_put_key_i32(&builder, WDC_CBOR_KEY_STATUS, WDC_OK); }
    if (status == WDC_OK) { status = wdc_cbor_put_key_u32(&builder, WDC_CBOR_KEY_REQUEST_ID, s_status.last_subscribe.request_id); }
    return status == WDC_OK ? finish_response(&builder, out_response_len) : status;
}

static int32_t http_request(const uint8_t *request,
                            uint32_t request_len,
                            uint8_t *response,
                            uint32_t response_cap,
                            uint32_t *out_response_len)
{
    uint32_t resource_id = 0u;
    int32_t status = parse_network_resource(request, request_len, &resource_id);
    if (status != WDC_OK) {
        s_status.rejected_count++;
        s_status.last_status = status;
        return write_status_response(response, response_cap, out_response_len, status);
    }
    status = require_connected();
    if (status != WDC_OK) {
        return write_status_response(response, response_cap, out_response_len, status);
    }

    WdcCborText method = {0};
    WdcCborText url = {0};
    status = wdc_cbor_map_find_text(request, request_len, WDC_CBOR_KEY_METHOD, &method);
    if (status != WDC_OK) {
        s_status.rejected_count++;
        s_status.last_status = WDC_ERR_BAD_ENCODING;
        return write_status_response(response, response_cap, out_response_len, WDC_ERR_BAD_ENCODING);
    }
    status = wdc_cbor_map_find_text(request, request_len, WDC_CBOR_KEY_URL, &url);
    if (status != WDC_OK) {
        s_status.rejected_count++;
        s_status.last_status = WDC_ERR_BAD_ENCODING;
        return write_status_response(response, response_cap, out_response_len, WDC_ERR_BAD_ENCODING);
    }
    WdcCborBytes body = {0};
    status = wdc_cbor_map_find_bytes(request, request_len, WDC_CBOR_KEY_DATA, &body);
    if (status != WDC_OK && status != WDC_ERR_NOT_AVAILABLE) {
        s_status.rejected_count++;
        s_status.last_status = WDC_ERR_BAD_ENCODING;
        return write_status_response(response, response_cap, out_response_len, WDC_ERR_BAD_ENCODING);
    }
    if (body.len > WDC_NET_PAYLOAD_MAX_BYTES) {
        s_status.rejected_count++;
        s_status.last_status = WDC_ERR_BAD_LENGTH;
        return write_status_response(response, response_cap, out_response_len, WDC_ERR_BAD_LENGTH);
    }
    const WdcNetworkResource *policy = NULL;
    status = network_policy_for(resource_id, &policy);
    if (status != WDC_OK) {
        return reject_policy(response, response_cap, out_response_len, status);
    }
    if (policy->http_url_prefix == NULL || !text_has_prefix(url, policy->http_url_prefix) || !method_allowed(method, policy->http_methods_csv)) {
        return reject_policy(response, response_cap, out_response_len, WDC_ERR_CAPABILITY_DENIED);
    }
    if (body.len > policy->max_payload_bytes) {
        return reject_policy(response, response_cap, out_response_len, WDC_ERR_BAD_LENGTH);
    }

    status = copy_text(method, s_status.last_http_request.method, sizeof(s_status.last_http_request.method));
    if (status == WDC_OK) { status = copy_text(url, s_status.last_http_request.url, sizeof(s_status.last_http_request.url)); }
    if (status != WDC_OK) {
        s_status.rejected_count++;
        s_status.last_status = status;
        return write_status_response(response, response_cap, out_response_len, status);
    }

    s_status.last_http_request.resource_id = resource_id;
    s_status.last_http_request.request_id = next_request_id();
    s_status.last_http_request.payload_len = body.len;
    s_status.http_request_count++;
    s_status.last_status = WDC_OK;

    WdcCborBuilder builder;
    wdc_cbor_builder_init(&builder, response, response_cap);
    status = wdc_cbor_begin_map(&builder, 3u);
    if (status == WDC_OK) { status = wdc_cbor_put_key_i32(&builder, WDC_CBOR_KEY_STATUS, WDC_OK); }
    if (status == WDC_OK) { status = wdc_cbor_put_key_u32(&builder, WDC_CBOR_KEY_REQUEST_ID, s_status.last_http_request.request_id); }
    if (status == WDC_OK) { status = wdc_cbor_put_key_u32(&builder, WDC_CBOR_KEY_HTTP_STATUS, 202u); }
    return status == WDC_OK ? finish_response(&builder, out_response_len) : status;
}

int32_t wdc_net_host_call(void *ctx,
                          uint32_t opcode,
                          const uint8_t *request,
                          uint32_t request_len,
                          uint8_t *response,
                          uint32_t response_cap,
                          uint32_t *out_response_len)
{
    (void)ctx;
    if (response == NULL || response_cap == 0u) {
        return WDC_ERR_RESPONSE_TOO_SMALL;
    }
    switch (opcode) {
    case WDC_OP_NET_STATUS: return write_net_status_response(response, response_cap, out_response_len);
    case WDC_OP_MQTT_PUBLISH: return mqtt_publish(request, request_len, response, response_cap, out_response_len);
    case WDC_OP_MQTT_SUBSCRIBE: return mqtt_subscribe(request, request_len, response, response_cap, out_response_len);
    case WDC_OP_HTTP_REQUEST: return http_request(request, request_len, response, response_cap, out_response_len);
    case WDC_OP_HTTP_RESPOND:
        if (s_http_response_hook == NULL) {
            return write_status_response(response, response_cap,
                                         out_response_len,
                                         WDC_ERR_INVALID_STATE);
        }
        return s_http_response_hook(s_http_response_context, request,
                                    request_len, response, response_cap,
                                    out_response_len);
    default: return WDC_ERR_UNSUPPORTED_OPCODE;
    }
}

int32_t wdc_net_handle_host_call(void *ctx,
                                 uint32_t opcode,
                                 const uint8_t *request,
                                 uint32_t request_len,
                                 uint8_t *response,
                                 uint32_t response_cap,
                                 uint32_t *out_response_len)
{
    return wdc_net_host_call(ctx, opcode, request, request_len, response, response_cap, out_response_len);
}

int32_t wdc_net_init(const WdcDeviceProfile *profile)
{
    if (profile == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    s_profile = profile;
    memset(&s_status, 0, sizeof(s_status));
    s_status.state = WDC_NET_STATE_DISCONNECTED;
    s_status.initialized = true;
    s_status.connected = false;
    s_status.next_request_id = 1u;
    s_status.last_status = WDC_OK;
    return wdc_net_install_host_bridge(profile);
}

void wdc_net_reset_for_test(void)
{
    memset(&s_status, 0, sizeof(s_status));
    s_profile = NULL;
    s_http_response_hook = NULL;
    s_http_response_context = NULL;
    wdc_host_call_clear_net_hook();
}

int32_t wdc_net_set_http_response_hook(WdcNetHttpResponseHookFn hook,
                                       void *context)
{
    if (hook == NULL || context == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    if (s_http_response_hook != NULL &&
        (s_http_response_hook != hook || s_http_response_context != context)) {
        return WDC_ERR_INVALID_STATE;
    }
    s_http_response_hook = hook;
    s_http_response_context = context;
    return WDC_OK;
}

void wdc_net_clear_http_response_hook(WdcNetHttpResponseHookFn hook,
                                      void *context)
{
    if (s_http_response_hook == hook && s_http_response_context == context) {
        s_http_response_hook = NULL;
        s_http_response_context = NULL;
    }
}

void wdc_net_get_status(WdcNetStatus *out_status)
{
    if (out_status != NULL) {
        *out_status = s_status;
    }
}

WdcNetState wdc_net_get_state(void)
{
    return s_status.state;
}

static void post_network_state_event(uint32_t event_type, const char *reason)
{
    uint8_t payload[WDC_EVENT_PAYLOAD_MAX];
    uint16_t payload_len = 0u;
    if (reason != NULL) {
        size_t n = strlen(reason);
        if (n > sizeof(payload)) {
            n = sizeof(payload);
        }
        memcpy(payload, reason, n);
        payload_len = (uint16_t)n;
    }
    WdcEvent event;
    if (wdc_event_make(&event,
                       event_type,
                       WDC_EVENT_RESOURCE_NONE,
                       0u,
                       payload_len != 0u ? payload : NULL,
                       payload_len) == WDC_OK) {
        (void)wdc_events_post(&event);
    }
}

int32_t wdc_net_set_state(WdcNetState state, const char *reason)
{
    if (!s_status.initialized) {
        return WDC_ERR_INVALID_STATE;
    }
    bool old_connected = s_status.connected;
    s_status.state = state;
    s_status.connected = (state == WDC_NET_STATE_CONNECTED);
    s_status.last_status = WDC_OK;
    if (old_connected != s_status.connected) {
        post_network_state_event(s_status.connected ? WDC_EVENT_NET_CONNECTED : WDC_EVENT_NET_DISCONNECTED, reason);
    }
    return WDC_OK;
}

int32_t wdc_net_set_connected(bool connected, const char *reason)
{
    return wdc_net_set_state(connected ? WDC_NET_STATE_CONNECTED : WDC_NET_STATE_DISCONNECTED, reason);
}

int32_t wdc_net_install_host_bridge(const WdcDeviceProfile *profile)
{
    if (profile != NULL) {
        s_profile = profile;
    }
    if (s_profile == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    wdc_host_call_set_net_hook(wdc_net_host_call, NULL);
    return WDC_OK;
}

int32_t wdc_net_install_host_hook(void)
{
    return wdc_net_install_host_bridge(s_profile);
}

void wdc_net_clear_host_bridge(void)
{
    wdc_host_call_clear_net_hook();
}

void wdc_net_clear_host_hook(void)
{
    wdc_net_clear_host_bridge();
}
