#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "wdc_extension_bridge.h"
#include "wdc_extension_internal.h"
#include "wdc_static_wasm.h"

#define SYNTHETIC_EVENT_TICK 0x5449434bu
#define SYNTHETIC_OPERATION_ECHO 0x4543484fu

static uint64_t s_now_ms = 1000u;
static uint32_t s_failures;
static uint32_t s_handler_calls;
static uint32_t s_invoke_calls;
static uint32_t s_response_len;
static int32_t s_duplicate_status;
static int32_t s_host_call_status;
static uint32_t s_handler_stage;
static WdcExtensionCandidate s_candidate;
static WdcExtensionRegistry s_registry;
static pulse_extension_descriptor_v1 s_descriptor;
static WdcRuntime s_runtime;
static WdcExtensionBridge s_bridge;

#define CHECK(condition) \
    do { \
        if (!(condition)) { \
            s_failures += 1u; \
        } \
    } while (0)

static pulse_u64_parts_v1 parts(uint64_t value)
{
    pulse_u64_parts_v1 result;
    result.lo = (uint32_t)value;
    result.hi = (uint32_t)(value >> 32u);
    return result;
}

uint64_t wdc_extension_platform_monotonic_ms(void)
{
    return s_now_ms;
}

int32_t wdc_diag_log(int32_t level, const char *message)
{
    (void)level;
    (void)message;
    return WDC_OK;
}

int32_t wdc_elf_unload(WdcElfImage **image)
{
    if (image != NULL) {
        *image = NULL;
    }
    return WDC_ELF_OK;
}

static int32_t mock_invoke(const pulse_extension_invoke_v1 *request)
{
    pulse_extension_completion_v1 completion;
    s_invoke_calls += 1u;
    if (request == NULL || request->struct_size != sizeof(*request) ||
        request->operation_id != SYNTHETIC_OPERATION_ECHO ||
        request->payload_len != 8u ||
        memcmp(request->payload_ptr, "hx4-echo", 8u) != 0) {
        return PULSE_EXT_ERR_ARGUMENT;
    }
    memset(&completion, 0, sizeof(completion));
    completion.struct_size = sizeof(completion);
    completion.status = PULSE_EXT_OK;
    completion.correlation_id = request->correlation_id;
    completion.payload_ptr = request->payload_ptr;
    completion.payload_len = request->payload_len;
    return pulse_host_complete_effect_v1(&completion);
}

static int32_t allow_effect_authorizer(void *ctx,
                                       uint32_t opcode,
                                       const uint8_t *request,
                                       uint32_t request_len,
                                       int32_t *decision)
{
    (void)ctx;
    (void)request;
    (void)request_len;
    if (decision == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    *decision = opcode == WDC_OP_EFFECT_INVOKE ? WDC_OK :
                                                    WDC_ERR_CAPABILITY_DENIED;
    return WDC_OK;
}

static int32_t host_stub_wasm_handler(void *ctx,
                                      const uint8_t *event_cbor,
                                      uint32_t event_len)
{
    static const uint8_t echo[] = {'h', 'x', '4', '-', 'e', 'c', 'h', 'o'};
    WdcEvent event;
    WdcCborBuilder request_builder;
    WdcCborBytes completion_payload;
    uint8_t request[64];
    uint8_t response[128];
    uint32_t response_len = 0u;
    uint32_t operation_id = 0u;
    uint64_t correlation_id = 0u;
    int32_t completion_status = WDC_ERR_UNKNOWN;
    int32_t status;
    (void)ctx;
    s_handler_calls += 1u;
    s_handler_stage = 1u;
    status = wdc_event_decode_cbor(event_cbor, event_len, &event);
    if (status != WDC_OK || event.event_type != SYNTHETIC_EVENT_TICK ||
        event.causation_id != 42u || event.payload_len != 8u ||
        memcmp(event.payload, "hx4-tick", 8u) != 0) {
        return WDC_ERR_BAD_ENCODING;
    }
    s_handler_stage = 2u;
    wdc_cbor_builder_init(&request_builder, request, sizeof(request));
    status = wdc_cbor_begin_map(&request_builder, 2u);
    if (status == WDC_OK) {
        status = wdc_cbor_put_key_u32(
            &request_builder, WDC_CBOR_KEY_OPERATION_ID, SYNTHETIC_OPERATION_ECHO);
    }
    if (status == WDC_OK) {
        status = wdc_cbor_put_key_bytes(
            &request_builder, WDC_CBOR_KEY_DATA, echo, sizeof(echo));
    }
    if (status != WDC_OK) {
        return status;
    }
    s_handler_stage = 3u;
    status = wdc_host_call_dispatch(WDC_OP_EFFECT_INVOKE,
                                    request,
                                    wdc_cbor_len(&request_builder),
                                    response,
                                    sizeof(response),
                                    &response_len);
    s_host_call_status = status;
    s_handler_stage = 4u;
    if (status != WDC_OK) {
        return status;
    }
    s_response_len = response_len;
    if (wdc_cbor_map_find_i32(
            response, response_len, WDC_CBOR_KEY_STATUS, &completion_status) != WDC_OK ||
        wdc_cbor_map_find_u32(
            response, response_len, WDC_CBOR_KEY_OPERATION_ID, &operation_id) != WDC_OK ||
        wdc_cbor_map_find_u64(
            response, response_len, WDC_CBOR_KEY_CORRELATION_ID, &correlation_id) != WDC_OK ||
        wdc_cbor_map_find_bytes(
            response, response_len, WDC_CBOR_KEY_DATA, &completion_payload) != WDC_OK ||
        completion_status != PULSE_EXT_OK ||
        operation_id != SYNTHETIC_OPERATION_ECHO || correlation_id != 1u ||
        completion_payload.len != sizeof(echo) ||
        memcmp(completion_payload.ptr, echo, sizeof(echo)) != 0) {
        return WDC_ERR_CONTRACT_VIOLATION;
    }
    s_handler_stage = 5u;
    return WDC_OK;
}

static void fixture(void)
{
    WdcRuntimeConfig runtime_config = wdc_runtime_default_config();
    WdcExtensionBridgeConfig bridge_config = wdc_extension_bridge_default_config();
    memset(&s_candidate, 0, sizeof(s_candidate));
    memset(&s_registry, 0, sizeof(s_registry));
    memset(&s_descriptor, 0, sizeof(s_descriptor));
    s_descriptor.event_count = 1u;
    s_descriptor.operation_count = 1u;
    s_descriptor.event_ids[0] = SYNTHETIC_EVENT_TICK;
    s_descriptor.operation_ids[0] = SYNTHETIC_OPERATION_ECHO;
    s_descriptor.invoke_fn = mock_invoke;
    s_candidate.state = WDC_EXTENSION_STARTED;
    s_candidate.descriptor = &s_descriptor;
    s_candidate.inspection.metadata.max_event_payload_bytes = 64u;
    s_candidate.inspection.metadata.max_effect_request_bytes = 32u;
    s_candidate.inspection.metadata.max_effect_completion_bytes = 32u;
    s_registry.sealed = 1u;
    s_registry.count = 1u;
    s_registry.candidates[0] = &s_candidate;
    CHECK(wdc_extension_services_bind(&s_registry) == WDC_EXTENSION_OK);
    wdc_extension_services_set_test_caller(&s_candidate);
    CHECK(wdc_events_init() == WDC_OK);
    CHECK(wdc_runtime_init(&s_runtime, &runtime_config) == WDC_OK);
    CHECK(wdc_runtime_load_static(&s_runtime,
                                  wdc_hx4_event_effect_wasm,
                                  wdc_hx4_event_effect_wasm_len) == WDC_OK);
    CHECK(wdc_runtime_lookup_exports(&s_runtime) == WDC_OK);
    CHECK(wdc_runtime_call_init(&s_runtime) == WDC_OK);
    wdc_runtime_set_host_stub_event_hook(
        &s_runtime, host_stub_wasm_handler, NULL);
    wdc_host_call_set_authorizer(allow_effect_authorizer, NULL);
    bridge_config.effect_timeout_ms = 1000u;
    bridge_config.max_effect_request_bytes = 32u;
    bridge_config.max_effect_completion_bytes = 32u;
    bridge_config.expected_event_id = SYNTHETIC_EVENT_TICK;
    bridge_config.expected_operation_id = SYNTHETIC_OPERATION_ECHO;
    CHECK(wdc_extension_bridge_init(
              &s_bridge, &s_registry, &s_runtime, &bridge_config) == WDC_OK);
}

static void emit_tick(void)
{
    static const uint8_t tick[] = {'h', 'x', '4', '-', 't', 'i', 'c', 'k'};
    pulse_extension_event_v1 event;
    memset(&event, 0, sizeof(event));
    event.struct_size = sizeof(event);
    event.event_id = SYNTHETIC_EVENT_TICK;
    event.causation_id = parts(42u);
    event.payload_ptr = tick;
    event.payload_len = sizeof(tick);
    CHECK(pulse_host_emit_event_v1(&event) == PULSE_EXT_OK);
}

static void verify_duplicate_completion(void)
{
    static const uint8_t echo[] = {'h', 'x', '4', '-', 'e', 'c', 'h', 'o'};
    pulse_extension_completion_v1 completion;
    memset(&completion, 0, sizeof(completion));
    completion.struct_size = sizeof(completion);
    completion.status = PULSE_EXT_OK;
    completion.correlation_id = parts(1u);
    completion.payload_ptr = echo;
    completion.payload_len = sizeof(echo);
    s_duplicate_status = pulse_host_complete_effect_v1(&completion);
    CHECK(s_duplicate_status == PULSE_EXT_ERR_DUPLICATE);
}

int main(void)
{
    const WdcExtensionBridgeReport *report;
    fixture();
    emit_tick();
    CHECK(wdc_events_pending() == 1u);
    CHECK(wdc_extension_bridge_process_next(&s_bridge) == WDC_OK);
    report = wdc_extension_bridge_get_report(&s_bridge);
    CHECK(report != NULL);
    if (report != NULL) {
        CHECK(report->status == WDC_OK);
        CHECK(report->runtime_status == WDC_OK);
        CHECK(report->event_queue_depth_before == 1u);
        CHECK(report->event_queue_depth_after == 0u);
        CHECK(report->event_type == SYNTHETIC_EVENT_TICK);
        CHECK(report->event_id == 1u);
        CHECK(report->causation_id == 42u);
        CHECK(report->event_payload_len == 8u);
        CHECK(report->event_encoded_len != 0u);
        CHECK(report->operation_id == SYNTHETIC_OPERATION_ECHO);
        CHECK(report->correlation_id == 1u);
        CHECK(report->deadline_ms == 2000u);
        CHECK(report->effect_request_len == 8u);
        CHECK(report->completion_payload_len == 8u);
        CHECK(report->completion_latency_ms == 0u);
        CHECK(report->encoding == WDC_EXTENSION_BRIDGE_ENCODING_CBOR);
        CHECK(report->effect_invoked == 1u);
        CHECK(report->completion_accepted == 1u);
        CHECK(memcmp(report->completion_payload, "hx4-echo", 8u) == 0);
    }
    verify_duplicate_completion();
    CHECK(s_handler_calls == 1u);
    CHECK(s_invoke_calls == 1u);
    CHECK(s_response_len != 0u);
    printf("{\"status\":\"%s\",\"failures\":%u,"
           "\"handler_calls\":%u,\"invoke_calls\":%u,"
           "\"queue_before\":%u,\"queue_after\":%u,"
           "\"event_id\":%u,\"causation_id\":%llu,"
           "\"operation_id\":%u,\"correlation_id\":%llu,"
           "\"deadline_ms\":%llu,\"event_payload_len\":%u,"
           "\"effect_payload_len\":%u,\"completion_payload_len\":%u,"
           "\"completion_latency_ms\":%u,\"encoding\":\"cbor\","
           "\"duplicate_completion_status\":%d,"
           "\"host_call_status\":%d,\"bridge_status\":%d,"
           "\"runtime_status\":%d,\"handler_stage\":%u}\n",
           s_failures == 0u ? "PASS" : "FAIL",
           s_failures,
           s_handler_calls,
           s_invoke_calls,
           report != NULL ? report->event_queue_depth_before : 0u,
           report != NULL ? report->event_queue_depth_after : 0u,
           report != NULL ? report->event_id : 0u,
           (unsigned long long)(report != NULL ? report->causation_id : 0u),
           report != NULL ? report->operation_id : 0u,
           (unsigned long long)(report != NULL ? report->correlation_id : 0u),
           (unsigned long long)(report != NULL ? report->deadline_ms : 0u),
           report != NULL ? report->event_payload_len : 0u,
           report != NULL ? report->effect_request_len : 0u,
           report != NULL ? report->completion_payload_len : 0u,
           report != NULL ? report->completion_latency_ms : 0u,
           s_duplicate_status,
           s_host_call_status,
           report != NULL ? report->status : WDC_ERR_UNKNOWN,
           report != NULL ? report->runtime_status : WDC_ERR_UNKNOWN,
           s_handler_stage);
    wdc_extension_bridge_deinit(&s_bridge);
    wdc_runtime_teardown(&s_runtime);
    wdc_extension_services_unbind(&s_registry);
    return s_failures == 0u ? 0 : 1;
}
