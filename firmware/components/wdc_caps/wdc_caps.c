#include "wdc_caps.h"

#include <stdio.h>
#include <string.h>

#ifdef ESP_PLATFORM
#include "esp_timer.h"
#endif

static const WdcCapability s_relay_limited_caps[] = {
    { 1u, WDC_RESOURCE_KIND_GPIO, WDC_R4_RESOURCE_RELAY_1, "relay_1", WDC_CAP_OP_READ | WDC_CAP_OP_WRITE, 0u, 0u },
    { 3u, WDC_RESOURCE_KIND_GPIO, WDC_R4_RESOURCE_BUTTON_1, "button_1", WDC_CAP_OP_READ | WDC_CAP_OP_SUBSCRIBE, 0u, 0u },
    { 20u, WDC_RESOURCE_KIND_NETWORK, WDC_R8_RESOURCE_MQTT_TELEMETRY, "mqtt_telemetry", WDC_CAP_OP_PUBLISH, 0u, 0u },
    { 30u, WDC_RESOURCE_KIND_CONFIG, 0u, "app.*", WDC_CAP_OP_READ | WDC_CAP_OP_WRITE, 0u, 0u },
};

static const WdcCapabilitySet s_relay_limited = {
    .bundle_id = "com.example.relay-controller-r4-limited",
    .bundle_version = 4u,
    .capabilities = s_relay_limited_caps,
    .capability_count = sizeof(s_relay_limited_caps) / sizeof(s_relay_limited_caps[0]),
};

static const WdcCapability s_relay_full_caps[] = {
    { 1u, WDC_RESOURCE_KIND_GPIO, WDC_R4_RESOURCE_RELAY_1, "relay_1", WDC_CAP_OP_READ | WDC_CAP_OP_WRITE, 0u, 0u },
    { 2u, WDC_RESOURCE_KIND_GPIO, WDC_R4_RESOURCE_STATUS_LED, "status_led", WDC_CAP_OP_READ | WDC_CAP_OP_WRITE, 0u, 0u },
    { 3u, WDC_RESOURCE_KIND_GPIO, WDC_R4_RESOURCE_BUTTON_1, "button_1", WDC_CAP_OP_READ | WDC_CAP_OP_SUBSCRIBE, 0u, 0u },
    { 20u, WDC_RESOURCE_KIND_NETWORK, WDC_R8_RESOURCE_MQTT_TELEMETRY, "mqtt_telemetry", WDC_CAP_OP_PUBLISH, 0u, 0u },
    { 21u, WDC_RESOURCE_KIND_NETWORK, WDC_R8_RESOURCE_MQTT_COMMANDS, "mqtt_commands", WDC_CAP_OP_SUBSCRIBE, 0u, 0u },
    { 22u, WDC_RESOURCE_KIND_NETWORK, WDC_R8_RESOURCE_HTTP_API, "http_api", WDC_CAP_OP_REQUEST, 0u, 0u },
    { 30u, WDC_RESOURCE_KIND_CONFIG, 0u, "app.*", WDC_CAP_OP_READ | WDC_CAP_OP_WRITE, 0u, 0u },
};

static const WdcCapabilitySet s_relay_full = {
    .bundle_id = "com.example.relay-controller-r4-full",
    .bundle_version = 4u,
    .capabilities = s_relay_full_caps,
    .capability_count = sizeof(s_relay_full_caps) / sizeof(s_relay_full_caps[0]),
};

static WdcCapabilityAuthorizer s_authorizer_ctx;
static WdcCapabilityAuditRecord s_last_audit;
static WdcCapsClockFn s_clock_fn;
static void *s_clock_ctx;
static bool s_test_time_set;
static uint64_t s_test_now_ms;

static uint64_t caps_now_ms(void)
{
    if (s_clock_fn != NULL) {
        return s_clock_fn(s_clock_ctx);
    }
    if (s_test_time_set) {
        return s_test_now_ms;
    }
#ifdef ESP_PLATFORM
    return (uint64_t)(esp_timer_get_time() / 1000LL);
#else
    static uint64_t host_stub_now_ms;
    return host_stub_now_ms++;
#endif
}

void wdc_caps_set_clock(WdcCapsClockFn fn, void *ctx)
{
    s_clock_fn = fn;
    s_clock_ctx = ctx;
    s_test_time_set = false;
}

void wdc_caps_clear_clock(void)
{
    s_clock_fn = NULL;
    s_clock_ctx = NULL;
    s_test_time_set = false;
    s_test_now_ms = 0u;
}

void wdc_caps_set_time_ms_for_test(uint64_t now_ms)
{
    s_clock_fn = NULL;
    s_clock_ctx = NULL;
    s_test_time_set = true;
    s_test_now_ms = now_ms;
}

const char *wdc_resource_kind_name(WdcResourceKind kind)
{
    switch (kind) {
    case WDC_RESOURCE_KIND_GPIO: return "gpio";
    case WDC_RESOURCE_KIND_SENSOR: return "sensor";
    case WDC_RESOURCE_KIND_I2C: return "i2c";
    case WDC_RESOURCE_KIND_NETWORK: return "network";
    case WDC_RESOURCE_KIND_BLE: return "ble";
    case WDC_RESOURCE_KIND_CONFIG: return "config";
    case WDC_RESOURCE_KIND_STORAGE: return "storage";
    case WDC_RESOURCE_KIND_DIAGNOSTICS: return "diagnostics";
    case WDC_RESOURCE_KIND_CLOCK: return "clock";
    default: return "none";
    }
}

const char *wdc_cap_op_name(uint32_t op)
{
    switch (op) {
    case WDC_CAP_OP_READ: return "read";
    case WDC_CAP_OP_WRITE: return "write";
    case WDC_CAP_OP_SUBSCRIBE: return "subscribe";
    case WDC_CAP_OP_PUBLISH: return "publish";
    case WDC_CAP_OP_REQUEST: return "request";
    case WDC_CAP_OP_NOTIFY: return "notify";
    default: return "op";
    }
}

static bool slice_eq(const char *text, size_t text_len, const char *literal)
{
    const size_t literal_len = strlen(literal);
    return text != NULL && text_len == literal_len && memcmp(text, literal, literal_len) == 0;
}

WdcResourceKind wdc_resource_kind_from_string(const char *text, size_t len)
{
    if (slice_eq(text, len, "gpio")) { return WDC_RESOURCE_KIND_GPIO; }
    if (slice_eq(text, len, "sensor")) { return WDC_RESOURCE_KIND_SENSOR; }
    if (slice_eq(text, len, "i2c")) { return WDC_RESOURCE_KIND_I2C; }
    if (slice_eq(text, len, "network")) { return WDC_RESOURCE_KIND_NETWORK; }
    if (slice_eq(text, len, "ble")) { return WDC_RESOURCE_KIND_BLE; }
    if (slice_eq(text, len, "config")) { return WDC_RESOURCE_KIND_CONFIG; }
    if (slice_eq(text, len, "storage")) { return WDC_RESOURCE_KIND_STORAGE; }
    if (slice_eq(text, len, "diagnostics")) { return WDC_RESOURCE_KIND_DIAGNOSTICS; }
    if (slice_eq(text, len, "clock")) { return WDC_RESOURCE_KIND_CLOCK; }
    return WDC_RESOURCE_KIND_NONE;
}

uint32_t wdc_cap_op_from_string(const char *text, size_t len)
{
    if (slice_eq(text, len, "read")) { return WDC_CAP_OP_READ; }
    if (slice_eq(text, len, "write")) { return WDC_CAP_OP_WRITE; }
    if (slice_eq(text, len, "subscribe")) { return WDC_CAP_OP_SUBSCRIBE; }
    if (slice_eq(text, len, "publish")) { return WDC_CAP_OP_PUBLISH; }
    if (slice_eq(text, len, "request")) { return WDC_CAP_OP_REQUEST; }
    if (slice_eq(text, len, "notify")) { return WDC_CAP_OP_NOTIFY; }
    return WDC_CAP_OP_NONE;
}

const WdcCapabilitySet *wdc_caps_builtin_relay_limited(void)
{
    return &s_relay_limited;
}

const WdcCapabilitySet *wdc_caps_builtin_relay_full(void)
{
    return &s_relay_full;
}

static void audit_reset(WdcCapabilityAuditRecord *audit,
                        const WdcCapabilitySet *set,
                        uint32_t opcode,
                        WdcResourceKind kind,
                        uint32_t op,
                        uint32_t resource_id,
                        const char *resource_name)
{
    if (audit == NULL) {
        return;
    }
    memset(audit, 0, sizeof(*audit));
    if (set != NULL && set->bundle_id != NULL) {
        (void)snprintf(audit->bundle, sizeof(audit->bundle), "%s@%lu", set->bundle_id, (unsigned long)set->bundle_version);
        audit->bundle_version = set->bundle_version;
    }
    audit->opcode = opcode;
    (void)snprintf(audit->opcode_name, sizeof(audit->opcode_name), "%s", wdc_opcode_name(opcode));
    audit->resource_id = resource_id;
    if (resource_name != NULL) {
        (void)snprintf(audit->resource_name, sizeof(audit->resource_name), "%s", resource_name);
    }
    (void)snprintf(audit->capability, sizeof(audit->capability), "%s.%s:%s",
                   wdc_resource_kind_name(kind), wdc_cap_op_name(op), resource_name != NULL ? resource_name : "");
}

static void audit_decision(WdcCapabilityAuditRecord *audit, int32_t result)
{
    if (audit == NULL) {
        return;
    }
    audit->result = result;
    (void)snprintf(audit->decision, sizeof(audit->decision), "%s", result == WDC_OK ? "allowed" : "denied");
}

static bool config_name_matches(const char *pattern, const char *key, size_t key_len)
{
    if (pattern == NULL || key == NULL) {
        return false;
    }
    const size_t pattern_len = strlen(pattern);
    if (pattern_len >= 2u && pattern[pattern_len - 1u] == '*' && pattern[pattern_len - 2u] == '.') {
        const size_t prefix_len = pattern_len - 1u;
        return key_len >= prefix_len && memcmp(key, pattern, prefix_len) == 0;
    }
    return key_len == pattern_len && memcmp(key, pattern, pattern_len) == 0;
}

int32_t wdc_caps_check_resource(const WdcCapabilitySet *set,
                                const WdcDeviceProfile *profile,
                                uint32_t opcode,
                                WdcResourceKind kind,
                                uint32_t op,
                                uint32_t resource_id,
                                WdcCapabilityAuditRecord *out_audit)
{
    const WdcProfileResource *resource = wdc_profile_find_resource_by_id(profile, resource_id);
    const char *name = resource != NULL ? resource->name : "";
    audit_reset(out_audit, set, opcode, kind, op, resource_id, name);
    if (resource == NULL || resource->kind != kind) {
        audit_decision(out_audit, WDC_ERR_INVALID_RESOURCE);
        return WDC_ERR_INVALID_RESOURCE;
    }
    if (set == NULL || set->capabilities == NULL) {
        audit_decision(out_audit, WDC_ERR_CAPABILITY_DENIED);
        return WDC_ERR_CAPABILITY_DENIED;
    }
    for (size_t i = 0; i < set->capability_count; ++i) {
        const WdcCapability *cap = &set->capabilities[i];
        if (cap->kind == kind && cap->resource_id == resource_id && (cap->ops & op) != 0u) {
            if (out_audit != NULL) {
                out_audit->payload_limit = cap->max_payload_bytes;
                out_audit->rate_limit_hz = cap->max_rate_hz;
            }
            audit_decision(out_audit, WDC_OK);
            return WDC_OK;
        }
    }
    audit_decision(out_audit, WDC_ERR_CAPABILITY_DENIED);
    return WDC_ERR_CAPABILITY_DENIED;
}

int32_t wdc_caps_check_config_key(const WdcCapabilitySet *set,
                                  uint32_t opcode,
                                  uint32_t op,
                                  const char *key,
                                  size_t key_len,
                                  WdcCapabilityAuditRecord *out_audit)
{
    char local_name[WDC_CAPS_AUDIT_TEXT_MAX];
    memset(local_name, 0, sizeof(local_name));
    if (key != NULL && key_len < sizeof(local_name)) {
        memcpy(local_name, key, key_len);
    } else if (key != NULL) {
        memcpy(local_name, key, sizeof(local_name) - 1u);
    }
    audit_reset(out_audit, set, opcode, WDC_RESOURCE_KIND_CONFIG, op, 0u, local_name);
    if (key == NULL || key_len == 0u) {
        audit_decision(out_audit, WDC_ERR_BAD_ENCODING);
        return WDC_ERR_BAD_ENCODING;
    }
    if (set == NULL || set->capabilities == NULL) {
        audit_decision(out_audit, WDC_ERR_CAPABILITY_DENIED);
        return WDC_ERR_CAPABILITY_DENIED;
    }
    for (size_t i = 0; i < set->capability_count; ++i) {
        const WdcCapability *cap = &set->capabilities[i];
        if (cap->kind == WDC_RESOURCE_KIND_CONFIG && (cap->ops & op) != 0u && config_name_matches(cap->resource_name, key, key_len)) {
            if (out_audit != NULL) {
                out_audit->payload_limit = cap->max_payload_bytes;
                out_audit->rate_limit_hz = cap->max_rate_hz;
            }
            audit_decision(out_audit, WDC_OK);
            return WDC_OK;
        }
    }
    audit_decision(out_audit, WDC_ERR_CAPABILITY_DENIED);
    return WDC_ERR_CAPABILITY_DENIED;
}

static const char *skip_ws(const char *p, const char *end)
{
    while (p < end && (*p == ' ' || *p == '\n' || *p == '\r' || *p == '\t')) {
        p++;
    }
    return p;
}

static const char *find_key(const char *start, const char *end, const char *key)
{
    const size_t key_len = strlen(key);
    for (const char *p = start; p + key_len + 2u < end; ++p) {
        if (*p == '"' && (size_t)(end - p) >= key_len + 2u && memcmp(p + 1, key, key_len) == 0 && p[1 + key_len] == '"') {
            const char *colon = p + key_len + 2u;
            colon = skip_ws(colon, end);
            if (colon < end && *colon == ':') {
                return skip_ws(colon + 1, end);
            }
        }
    }
    return NULL;
}

static int32_t extract_string_value(const char *start, const char *end, const char **out_ptr, size_t *out_len)
{
    start = skip_ws(start, end);
    if (start >= end || *start != '"' || out_ptr == NULL || out_len == NULL) {
        return WDC_ERR_BAD_ENCODING;
    }
    start++;
    const char *p = start;
    while (p < end && *p != '"') {
        if (*p == '\\') {
            return WDC_ERR_BAD_ENCODING;
        }
        p++;
    }
    if (p >= end) {
        return WDC_ERR_BAD_ENCODING;
    }
    *out_ptr = start;
    *out_len = (size_t)(p - start);
    return WDC_OK;
}

static int32_t extract_uint_value(const char *start, const char *end, uint32_t *out_value)
{
    if (out_value == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    start = skip_ws(start, end);
    if (start >= end || *start < '0' || *start > '9') {
        return WDC_ERR_BAD_ENCODING;
    }
    uint32_t value = 0u;
    const char *p = start;
    while (p < end && *p >= '0' && *p <= '9') {
        value = value * 10u + (uint32_t)(*p - '0');
        p++;
    }
    *out_value = value;
    return WDC_OK;
}

static const char *find_matching(const char *open, const char *end, char left, char right)
{
    int depth = 0;
    bool in_string = false;
    for (const char *p = open; p < end; ++p) {
        if (*p == '"' && (p == open || p[-1] != '\\')) {
            in_string = !in_string;
        }
        if (in_string) {
            continue;
        }
        if (*p == left) {
            depth++;
        } else if (*p == right) {
            depth--;
            if (depth == 0) {
                return p;
            }
        }
    }
    return NULL;
}

static char *arena_copy(WdcCapabilityParseArena *arena, const char *src, size_t src_len)
{
    if (arena == NULL || src == NULL || src_len + 1u > sizeof(arena->strings) - arena->string_len) {
        return NULL;
    }
    char *out = &arena->strings[arena->string_len];
    memcpy(out, src, src_len);
    out[src_len] = '\0';
    arena->string_len += src_len + 1u;
    return out;
}

static uint32_t parse_ops_array(const char *object_start, const char *object_end)
{
    const char *ops_value = find_key(object_start, object_end, "ops");
    if (ops_value == NULL || *ops_value != '[') {
        return WDC_CAP_OP_NONE;
    }
    const char *ops_end = find_matching(ops_value, object_end, '[', ']');
    if (ops_end == NULL) {
        return WDC_CAP_OP_NONE;
    }
    uint32_t ops = WDC_CAP_OP_NONE;
    const char *p = ops_value + 1;
    while (p < ops_end) {
        p = skip_ws(p, ops_end);
        if (p >= ops_end) {
            break;
        }
        if (*p == ',') {
            p++;
            continue;
        }
        const char *op_text = NULL;
        size_t op_len = 0u;
        if (extract_string_value(p, ops_end, &op_text, &op_len) != WDC_OK) {
            break;
        }
        ops |= wdc_cap_op_from_string(op_text, op_len);
        p = op_text + op_len + 1u;
    }
    return ops;
}

static uint32_t parse_optional_u32(const char *object_start, const char *object_end, const char *key)
{
    uint32_t value = 0u;
    const char *value_text = find_key(object_start, object_end, key);
    if (value_text != NULL && extract_uint_value(value_text, object_end, &value) == WDC_OK) {
        return value;
    }
    return 0u;
}

static int32_t request_payload_len(uint32_t opcode, const uint8_t *request, uint32_t request_len, uint32_t *out_len)
{
    if (out_len == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    *out_len = 0u;
    switch (opcode) {
    case WDC_OP_CONFIG_SET:
    case WDC_OP_MQTT_PUBLISH:
    case WDC_OP_HTTP_REQUEST: {
        WdcCborBytes bytes = {0};
        int32_t status = wdc_cbor_map_find_bytes(request, request_len, WDC_CBOR_KEY_DATA, &bytes);
        if (status == WDC_ERR_NOT_AVAILABLE) {
            return WDC_OK;
        }
        if (status != WDC_OK) {
            return WDC_ERR_BAD_ENCODING;
        }
        *out_len = bytes.len;
        return WDC_OK;
    }
    default:
        return WDC_OK;
    }
}

static int32_t enforce_payload_limit(uint32_t opcode,
                                     const uint8_t *request,
                                     uint32_t request_len,
                                     WdcCapabilityAuditRecord *audit)
{
    if (audit == NULL || audit->payload_limit == 0u) {
        return WDC_OK;
    }
    uint32_t payload_len = 0u;
    int32_t status = request_payload_len(opcode, request, request_len, &payload_len);
    if (status != WDC_OK) {
        audit_decision(audit, status);
        return status;
    }
    audit->payload_len = payload_len;
    if (payload_len > audit->payload_limit) {
        audit_decision(audit, WDC_ERR_BAD_LENGTH);
        return WDC_ERR_BAD_LENGTH;
    }
    return WDC_OK;
}

static int32_t find_resource_capability_index(const WdcCapabilitySet *set,
                                              WdcResourceKind kind,
                                              uint32_t op,
                                              uint32_t resource_id)
{
    if (set == NULL || set->capabilities == NULL) {
        return -1;
    }
    for (size_t i = 0u; i < set->capability_count && i < WDC_CAPS_MAX_CAPABILITIES; ++i) {
        const WdcCapability *cap = &set->capabilities[i];
        if (cap->kind == kind && cap->resource_id == resource_id && (cap->ops & op) != 0u) {
            return (int32_t)i;
        }
    }
    return -1;
}

static int32_t find_config_capability_index(const WdcCapabilitySet *set,
                                            uint32_t op,
                                            const char *key,
                                            size_t key_len)
{
    if (set == NULL || set->capabilities == NULL) {
        return -1;
    }
    for (size_t i = 0u; i < set->capability_count && i < WDC_CAPS_MAX_CAPABILITIES; ++i) {
        const WdcCapability *cap = &set->capabilities[i];
        if (cap->kind == WDC_RESOURCE_KIND_CONFIG && (cap->ops & op) != 0u && config_name_matches(cap->resource_name, key, key_len)) {
            return (int32_t)i;
        }
    }
    return -1;
}

static int32_t enforce_rate_limit(WdcCapabilityAuthorizer *authorizer,
                                  int32_t cap_index,
                                  WdcCapabilityAuditRecord *audit)
{
    if (authorizer == NULL || authorizer->capability_set == NULL || cap_index < 0) {
        return WDC_OK;
    }
    if ((uint32_t)cap_index >= WDC_CAPS_MAX_CAPABILITIES || (size_t)cap_index >= authorizer->capability_set->capability_count) {
        return WDC_OK;
    }
    const WdcCapability *cap = &authorizer->capability_set->capabilities[cap_index];
    if (cap->max_rate_hz == 0u) {
        return WDC_OK;
    }
    uint64_t interval_ms = 1000u / cap->max_rate_hz;
    if (interval_ms == 0u) {
        interval_ms = 1u;
    }
    uint64_t now = caps_now_ms();
    uint64_t next_allowed = authorizer->last_allowed_ms[cap_index] + interval_ms;
    if (audit != NULL) {
        audit->rate_limit_hz = cap->max_rate_hz;
        audit->now_ms = now;
        audit->next_allowed_ms = authorizer->rate_seen[cap_index] ? next_allowed : now;
    }
    if (authorizer->rate_seen[cap_index] && now < next_allowed) {
        if (audit != NULL) {
            audit->next_allowed_ms = next_allowed;
        }
        audit_decision(audit, WDC_ERR_RATE_LIMITED);
        return WDC_ERR_RATE_LIMITED;
    }
    authorizer->last_allowed_ms[cap_index] = now;
    authorizer->rate_seen[cap_index] = true;
    return WDC_OK;
}

int32_t wdc_caps_parse_manifest_json(const char *json,
                                     size_t json_len,
                                     const WdcDeviceProfile *profile,
                                     WdcCapabilityParseArena *arena,
                                     WdcCapabilitySet *out_set)
{
    if (json == NULL || arena == NULL || out_set == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    memset(arena, 0, sizeof(*arena));
    memset(out_set, 0, sizeof(*out_set));
    const char *end = json + json_len;

    const char *bundle_value = find_key(json, end, "bundle_id");
    if (bundle_value == NULL) {
        return WDC_ERR_BAD_ENCODING;
    }
    const char *bundle_text = NULL;
    size_t bundle_len = 0u;
    int32_t status = extract_string_value(bundle_value, end, &bundle_text, &bundle_len);
    if (status != WDC_OK || bundle_len >= sizeof(arena->bundle_id)) {
        return WDC_ERR_BAD_ENCODING;
    }
    memcpy(arena->bundle_id, bundle_text, bundle_len);
    arena->bundle_id[bundle_len] = '\0';

    uint32_t bundle_version = 0u;
    const char *version_value = find_key(json, end, "bundle_version");
    if (version_value == NULL || extract_uint_value(version_value, end, &bundle_version) != WDC_OK) {
        return WDC_ERR_BAD_ENCODING;
    }

    const char *caps_value = find_key(json, end, "capabilities");
    if (caps_value == NULL || *caps_value != '[') {
        return WDC_ERR_BAD_ENCODING;
    }
    const char *caps_end = find_matching(caps_value, end, '[', ']');
    if (caps_end == NULL) {
        return WDC_ERR_BAD_ENCODING;
    }

    size_t count = 0u;
    const char *p = caps_value + 1;
    while (p < caps_end) {
        p = skip_ws(p, caps_end);
        if (p >= caps_end) {
            break;
        }
        if (*p == ',') {
            p++;
            continue;
        }
        if (*p != '{') {
            return WDC_ERR_BAD_ENCODING;
        }
        const char *object_end = find_matching(p, caps_end, '{', '}');
        if (object_end == NULL) {
            return WDC_ERR_BAD_ENCODING;
        }
        if (count >= WDC_CAPS_MAX_CAPABILITIES) {
            return WDC_ERR_NO_MEMORY;
        }

        uint32_t capability_id = 0u;
        const char *id_value = find_key(p, object_end, "id");
        if (id_value == NULL || extract_uint_value(id_value, object_end, &capability_id) != WDC_OK) {
            return WDC_ERR_BAD_ENCODING;
        }

        const char *kind_text = NULL;
        size_t kind_len = 0u;
        const char *kind_value = find_key(p, object_end, "kind");
        if (kind_value == NULL || extract_string_value(kind_value, object_end, &kind_text, &kind_len) != WDC_OK) {
            return WDC_ERR_BAD_ENCODING;
        }
        WdcResourceKind kind = wdc_resource_kind_from_string(kind_text, kind_len);
        if (kind == WDC_RESOURCE_KIND_NONE) {
            return WDC_ERR_BAD_ENCODING;
        }

        const char *resource_text = NULL;
        size_t resource_len = 0u;
        const char *resource_value = find_key(p, object_end, "resource");
        if (resource_value == NULL || extract_string_value(resource_value, object_end, &resource_text, &resource_len) != WDC_OK) {
            return WDC_ERR_BAD_ENCODING;
        }

        uint32_t ops = parse_ops_array(p, object_end);
        if (ops == WDC_CAP_OP_NONE) {
            return WDC_ERR_BAD_ENCODING;
        }
        uint32_t max_payload_bytes = parse_optional_u32(p, object_end, "max_payload_bytes");
        uint32_t max_rate_hz = parse_optional_u32(p, object_end, "max_rate_hz");

        char *resource_copy = arena_copy(arena, resource_text, resource_len);
        if (resource_copy == NULL) {
            return WDC_ERR_NO_MEMORY;
        }

        uint32_t resource_id = 0u;
        if (kind != WDC_RESOURCE_KIND_CONFIG && kind != WDC_RESOURCE_KIND_STORAGE && kind != WDC_RESOURCE_KIND_DIAGNOSTICS && kind != WDC_RESOURCE_KIND_CLOCK) {
            const WdcProfileResource *resource = wdc_profile_find_resource_by_name(profile, kind, resource_copy);
            if (resource == NULL) {
                return WDC_ERR_INVALID_RESOURCE;
            }
            resource_id = resource->resource_id;
        }

        arena->capabilities[count].capability_id = capability_id;
        arena->capabilities[count].kind = kind;
        arena->capabilities[count].resource_id = resource_id;
        arena->capabilities[count].resource_name = resource_copy;
        arena->capabilities[count].ops = ops;
        arena->capabilities[count].max_payload_bytes = max_payload_bytes;
        arena->capabilities[count].max_rate_hz = max_rate_hz;
        count++;
        p = object_end + 1;
    }

    out_set->bundle_id = arena->bundle_id;
    out_set->bundle_version = bundle_version;
    out_set->capabilities = arena->capabilities;
    out_set->capability_count = count;
    return count > 0u ? WDC_OK : WDC_ERR_BAD_ENCODING;
}

int32_t wdc_caps_authorize_host_call(void *ctx,
                                     uint32_t opcode,
                                     const uint8_t *request,
                                     uint32_t request_len,
                                     int32_t *out_decision_status)
{
    if (out_decision_status == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    *out_decision_status = WDC_OK;
    WdcCapabilityAuthorizer *authorizer = (WdcCapabilityAuthorizer *)ctx;
    if (authorizer == NULL) {
        *out_decision_status = WDC_ERR_CAPABILITY_DENIED;
        return WDC_OK;
    }

    int32_t decision = WDC_OK;
    switch (opcode) {
    case WDC_OP_SYS_GET_INFO:
    case WDC_OP_NET_STATUS:
    case WDC_OP_TIMER_SET:
    case WDC_OP_TIMER_CANCEL:
        decision = WDC_OK;
        break;
    case WDC_OP_GPIO_GET:
    case WDC_OP_GPIO_SET:
    case WDC_OP_GPIO_SUBSCRIBE: {
        uint32_t resource_id = 0u;
        int32_t status = wdc_cbor_map_find_u32(request, request_len, WDC_CBOR_KEY_RESOURCE_ID, &resource_id);
        if (status != WDC_OK) {
            decision = WDC_ERR_BAD_ENCODING;
            break;
        }
        uint32_t op = WDC_CAP_OP_READ;
        if (opcode == WDC_OP_GPIO_SET) {
            op = WDC_CAP_OP_WRITE;
        } else if (opcode == WDC_OP_GPIO_SUBSCRIBE) {
            op = WDC_CAP_OP_SUBSCRIBE;
        }
        decision = wdc_caps_check_resource(authorizer->capability_set,
                                           authorizer->profile,
                                           opcode,
                                           WDC_RESOURCE_KIND_GPIO,
                                           op,
                                           resource_id,
                                           &s_last_audit);
        if (decision == WDC_OK) {
            int32_t cap_index = find_resource_capability_index(authorizer->capability_set, WDC_RESOURCE_KIND_GPIO, op, resource_id);
            decision = enforce_rate_limit(authorizer, cap_index, &s_last_audit);
        }
        break;
    }
    case WDC_OP_CONFIG_GET:
    case WDC_OP_CONFIG_SET:
    case WDC_OP_CONFIG_DELETE: {
        WdcCborText key;
        int32_t status = wdc_cbor_map_find_text(request, request_len, WDC_CBOR_KEY_KEY, &key);
        if (status != WDC_OK) {
            decision = WDC_ERR_BAD_ENCODING;
            break;
        }
        decision = wdc_caps_check_config_key(authorizer->capability_set,
                                             opcode,
                                             opcode == WDC_OP_CONFIG_GET ? WDC_CAP_OP_READ : WDC_CAP_OP_WRITE,
                                             key.ptr,
                                             key.len,
                                             &s_last_audit);
        if (decision == WDC_OK) {
            decision = enforce_payload_limit(opcode, request, request_len, &s_last_audit);
        }
        if (decision == WDC_OK) {
            int32_t cap_index = find_config_capability_index(authorizer->capability_set,
                                                             opcode == WDC_OP_CONFIG_GET ? WDC_CAP_OP_READ : WDC_CAP_OP_WRITE,
                                                             key.ptr,
                                                             key.len);
            decision = enforce_rate_limit(authorizer, cap_index, &s_last_audit);
        }
        break;
    }
    case WDC_OP_MQTT_PUBLISH:
    case WDC_OP_MQTT_SUBSCRIBE:
    case WDC_OP_HTTP_REQUEST: {
        uint32_t resource_id = 0u;
        int32_t status = wdc_cbor_map_find_u32(request, request_len, WDC_CBOR_KEY_RESOURCE_ID, &resource_id);
        if (status != WDC_OK) {
            decision = WDC_ERR_BAD_ENCODING;
            break;
        }
        uint32_t op = WDC_CAP_OP_REQUEST;
        if (opcode == WDC_OP_MQTT_PUBLISH) {
            op = WDC_CAP_OP_PUBLISH;
        } else if (opcode == WDC_OP_MQTT_SUBSCRIBE) {
            op = WDC_CAP_OP_SUBSCRIBE;
        }
        decision = wdc_caps_check_resource(authorizer->capability_set,
                                           authorizer->profile,
                                           opcode,
                                           WDC_RESOURCE_KIND_NETWORK,
                                           op,
                                           resource_id,
                                           &s_last_audit);
        if (decision == WDC_OK) {
            decision = enforce_payload_limit(opcode, request, request_len, &s_last_audit);
        }
        if (decision == WDC_OK) {
            int32_t cap_index = find_resource_capability_index(authorizer->capability_set, WDC_RESOURCE_KIND_NETWORK, op, resource_id);
            decision = enforce_rate_limit(authorizer, cap_index, &s_last_audit);
        }
        break;
    }
    default:
        decision = WDC_ERR_UNSUPPORTED_OPCODE;
        break;
    }
    *out_decision_status = decision;
    return WDC_OK;
}

int32_t wdc_caps_install_host_authorizer(const WdcDeviceProfile *profile,
                                         const WdcCapabilitySet *set)
{
    if (profile == NULL || set == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    memset(&s_authorizer_ctx, 0, sizeof(s_authorizer_ctx));
    s_authorizer_ctx.profile = profile;
    s_authorizer_ctx.capability_set = set;
    memset(&s_last_audit, 0, sizeof(s_last_audit));
    wdc_host_call_set_authorizer(wdc_caps_authorize_host_call, &s_authorizer_ctx);
    return WDC_OK;
}

void wdc_caps_clear_host_authorizer(void)
{
    memset(&s_authorizer_ctx, 0, sizeof(s_authorizer_ctx));
    memset(&s_last_audit, 0, sizeof(s_last_audit));
    wdc_host_call_clear_authorizer();
}

void wdc_caps_last_audit(WdcCapabilityAuditRecord *out_audit)
{
    if (out_audit != NULL) {
        *out_audit = s_last_audit;
    }
}
