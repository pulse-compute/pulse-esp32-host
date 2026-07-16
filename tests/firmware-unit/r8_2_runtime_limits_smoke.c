#include <assert.h>
#include <stdint.h>
#include <string.h>
#include "wdc_abi.h"
#include "wdc_caps.h"
#include "wdc_profile.h"
#include "wdc_runtime.h"

static int32_t rsp_status(const uint8_t *rsp, uint32_t len) {
    int32_t status = WDC_ERR_UNKNOWN;
    assert(wdc_cbor_map_find_i32(rsp, len, WDC_CBOR_KEY_STATUS, &status) == WDC_OK);
    return status;
}

static uint32_t publish_req(uint8_t *req, uint32_t cap, uint32_t payload_len) {
    uint8_t payload[16];
    for (uint32_t i = 0u; i < sizeof(payload); ++i) { payload[i] = (uint8_t)i; }
    WdcCborBuilder b;
    wdc_cbor_builder_init(&b, req, cap);
    assert(wdc_cbor_begin_map(&b, 4u) == WDC_OK);
    assert(wdc_cbor_put_key_u32(&b, WDC_CBOR_KEY_RESOURCE_ID, WDC_R8_RESOURCE_MQTT_TELEMETRY) == WDC_OK);
    assert(wdc_cbor_put_key_text(&b, WDC_CBOR_KEY_TOPIC, "devices/demo/telemetry/state") == WDC_OK);
    assert(wdc_cbor_put_key_bytes(&b, WDC_CBOR_KEY_DATA, payload, payload_len) == WDC_OK);
    assert(wdc_cbor_put_key_u32(&b, WDC_CBOR_KEY_QOS, 0u) == WDC_OK);
    return wdc_cbor_len(&b);
}

static void check_host_call_limits(void) {
    uint8_t rsp[256];
    uint32_t rsp_len = 123u;
    wdc_host_call_reset_for_test();
    WdcHostCallLimits defaults = wdc_host_call_get_limits();
    assert(defaults.max_request_bytes == WDC_MAX_REQUEST_BYTES_DEFAULT);
    assert(defaults.max_response_bytes == WDC_MAX_RESPONSE_BYTES_DEFAULT);
    WdcHostCallLimits tight = { .max_request_bytes = 16u, .max_response_bytes = 32u };
    wdc_host_call_set_limits(&tight);
    WdcHostCallLimits active = wdc_host_call_get_limits();
    assert(active.max_request_bytes == 16u);
    assert(active.max_response_bytes == 32u);
    assert(wdc_host_call_dispatch(WDC_OP_SYS_GET_INFO, NULL, 0u, rsp, sizeof(rsp), &rsp_len) == WDC_ERR_BAD_LENGTH);
    assert(rsp_len == 0u);
    wdc_host_call_reset_limits();
    assert(wdc_host_call_dispatch(WDC_OP_SYS_GET_INFO, NULL, 0u, rsp, sizeof(rsp), &rsp_len) == WDC_OK);
    assert(rsp_status(rsp, rsp_len) == WDC_OK);
}

static void check_capability_payload_limit(void) {
    const char manifest[] =
        "{\"bundle_id\":\"com.example.r8_2-limits\","
        "\"bundle_version\":82,"
        "\"capabilities\":[{"
        "\"id\":20,\"kind\":\"network\",\"resource\":\"mqtt_telemetry\","
        "\"ops\":[\"publish\"],\"max_payload_bytes\":4,\"max_rate_hz\":10}]}";
    WdcCapabilityParseArena arena;
    WdcCapabilitySet set;
    assert(wdc_caps_parse_manifest_json(manifest, (uint32_t)strlen(manifest), wdc_profile_builtin(), &arena, &set) == WDC_OK);
    assert(set.capability_count == 1u);
    assert(set.capabilities[0].max_payload_bytes == 4u);
    assert(set.capabilities[0].max_rate_hz == 10u);
    assert(wdc_caps_install_host_authorizer(wdc_profile_builtin(), &set) == WDC_OK);
    uint8_t req[256];
    uint8_t rsp[128];
    uint32_t rsp_len = 0u;
    uint32_t req_len = publish_req(req, sizeof(req), 8u);
    assert(wdc_host_call_dispatch(WDC_OP_MQTT_PUBLISH, req, req_len, rsp, sizeof(rsp), &rsp_len) == WDC_OK);
    assert(rsp_status(rsp, rsp_len) == WDC_ERR_BAD_LENGTH);
    WdcCapabilityAuditRecord audit;
    wdc_caps_last_audit(&audit);
    assert(audit.payload_len == 8u);
    assert(audit.payload_limit == 4u);
    assert(audit.result == WDC_ERR_BAD_LENGTH);
    req_len = publish_req(req, sizeof(req), 4u);
    assert(wdc_host_call_dispatch(WDC_OP_MQTT_PUBLISH, req, req_len, rsp, sizeof(rsp), &rsp_len) == WDC_OK);
    assert(rsp_status(rsp, rsp_len) == WDC_ERR_NOT_AVAILABLE);

    req_len = publish_req(req, sizeof(req), 4u);
    assert(wdc_host_call_dispatch(WDC_OP_MQTT_PUBLISH, req, req_len, rsp, sizeof(rsp), &rsp_len) == WDC_OK);
    assert(rsp_status(rsp, rsp_len) == WDC_ERR_RATE_LIMITED);
    wdc_caps_last_audit(&audit);
    assert(audit.rate_limit_hz == 10u);
    assert(audit.result == WDC_ERR_RATE_LIMITED);
    assert(audit.next_allowed_ms > audit.now_ms);

    wdc_caps_set_time_ms_for_test(audit.next_allowed_ms);
    req_len = publish_req(req, sizeof(req), 4u);
    assert(wdc_host_call_dispatch(WDC_OP_MQTT_PUBLISH, req, req_len, rsp, sizeof(rsp), &rsp_len) == WDC_OK);
    assert(rsp_status(rsp, rsp_len) == WDC_ERR_NOT_AVAILABLE);
    wdc_caps_clear_clock();
    wdc_caps_clear_host_authorizer();
}

static void check_runtime_event_limit(void) {
    static const uint8_t wasm[] =
        "\0asm\1\0\0\0"
        "wdc_module_init wdc_module_on_event wdc_module_health wdc_module_shutdown";
    WdcRuntime runtime;
    WdcRuntimeConfig cfg = wdc_runtime_default_config();
    cfg.max_event_bytes = 4u;
    assert(wdc_runtime_init(&runtime, &cfg) == WDC_OK);
    assert(wdc_runtime_load_static(&runtime, wasm, (uint32_t)sizeof(wasm)) == WDC_OK);
    assert(wdc_runtime_lookup_exports(&runtime) == WDC_OK);
    uint8_t event[5] = {0, 1, 2, 3, 4};
    assert(wdc_runtime_call_event_cbor(&runtime, event, sizeof(event)) == WDC_ERR_BAD_LENGTH);
    const WdcRuntimeReport *report = wdc_runtime_get_report(&runtime);
    assert(report != NULL);
    assert(report->outcome == WDC_RUNTIME_OUTCOME_INVALID_PAYLOAD);
    assert(report->last_status == WDC_ERR_BAD_LENGTH);
    wdc_runtime_teardown(&runtime);
}

int main(void) {
    check_runtime_event_limit();
    check_host_call_limits();
    check_capability_payload_limit();
    return 0;
}
