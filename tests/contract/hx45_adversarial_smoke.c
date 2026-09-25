#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "wdc_extension_bridge.h"
#include "wdc_extension_internal.h"
#include "wdc_static_wasm.h"

#define SYNTHETIC_EVENT_TICK 0x5449434bu
#define SYNTHETIC_EVENT_UNKNOWN 0x554e4b4eu
#define SYNTHETIC_OPERATION_ECHO 0x4543484fu
#define SYNTHETIC_OPERATION_UNKNOWN 0x554e4b4eu
#define ADVERSARIAL_CASE_COUNT 11u

typedef enum HandlerMode {
    HANDLER_NORMAL = 0,
    HANDLER_UNKNOWN_OPERATION = 1,
    HANDLER_OVERSIZED_EFFECT = 2,
    HANDLER_EXPIRED_DEADLINE = 3,
} HandlerMode;

typedef enum InvokeMode {
    INVOKE_COMPLETE = 0,
    INVOKE_DEFER_TO_TIMEOUT = 1,
    INVOKE_QUIESCE_THEN_COMPLETE = 2,
    INVOKE_FAULT = 3,
} InvokeMode;

typedef struct CaseRecord {
    const char *name;
    int32_t observed;
    int32_t expected;
    uint32_t passed;
} CaseRecord;

static uint64_t s_now_ms;
static uint32_t s_failures;
static uint32_t s_handler_calls;
static uint32_t s_invoke_calls;
static uint32_t s_expire_time_reads;
static uint32_t s_expire_during_invoke;
static int32_t s_host_call_status;
static int32_t s_quiesce_completion_status;
static HandlerMode s_handler_mode;
static InvokeMode s_invoke_mode;
static uint32_t s_health_state;
static pulse_u64_parts_v1 s_saved_correlation;
static uint32_t s_saved_payload_len;
static uint8_t s_saved_payload[WDC_EXTENSION_EFFECT_PAYLOAD_MAX];
static WdcExtensionCandidate s_candidate;
static WdcExtensionRegistry s_registry;
static pulse_extension_descriptor_v1 s_descriptor;
static WdcRuntime s_runtime;
static WdcExtensionBridge s_bridge;
static CaseRecord s_cases[ADVERSARIAL_CASE_COUNT];
static uint32_t s_case_count;

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

static uint64_t value_of(pulse_u64_parts_v1 value)
{
    return ((uint64_t)value.hi << 32u) | value.lo;
}

uint64_t wdc_extension_platform_monotonic_ms(void)
{
    if (s_expire_during_invoke != 0u) {
        s_expire_time_reads += 1u;
        return s_expire_time_reads >= 3u ? 2000u : 1000u;
    }
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

static void save_request(const pulse_extension_invoke_v1 *request)
{
    s_saved_correlation = request->correlation_id;
    s_saved_payload_len = request->payload_len;
    if (s_saved_payload_len != 0u) {
        memcpy(s_saved_payload, request->payload_ptr, s_saved_payload_len);
    }
}

static int32_t complete_saved(void)
{
    pulse_extension_completion_v1 completion;
    memset(&completion, 0, sizeof(completion));
    completion.struct_size = sizeof(completion);
    completion.status = PULSE_EXT_OK;
    completion.correlation_id = s_saved_correlation;
    completion.payload_ptr = s_saved_payload_len != 0u ? s_saved_payload : NULL;
    completion.payload_len = s_saved_payload_len;
    return pulse_host_complete_effect_v1(&completion);
}

static int32_t mock_quiesce(const pulse_extension_quiesce_v1 *request)
{
    if (request == NULL || request->struct_size != sizeof(*request)) {
        return PULSE_EXT_ERR_ARGUMENT;
    }
    s_health_state = PULSE_EXT_HEALTH_QUIESCED;
    return PULSE_EXT_OK;
}

static int32_t mock_health(pulse_extension_health_v1 *out_health)
{
    if (out_health == NULL || out_health->struct_size != sizeof(*out_health)) {
        return PULSE_EXT_ERR_ARGUMENT;
    }
    memset(out_health, 0, sizeof(*out_health));
    out_health->struct_size = sizeof(*out_health);
    out_health->state = s_health_state;
    out_health->fault_status = PULSE_EXT_OK;
    return PULSE_EXT_OK;
}

static int32_t mock_invoke(const pulse_extension_invoke_v1 *request)
{
    pulse_extension_quiesce_v1 quiesce;
    int32_t status;
    s_invoke_calls += 1u;
    if (request == NULL || request->struct_size != sizeof(*request) ||
        request->operation_id != SYNTHETIC_OPERATION_ECHO ||
        request->payload_len > sizeof(s_saved_payload)) {
        return PULSE_EXT_ERR_ARGUMENT;
    }
    save_request(request);
    if (s_invoke_mode == INVOKE_FAULT) {
        return PULSE_EXT_ERR_FAULT;
    }
    if (s_invoke_mode == INVOKE_DEFER_TO_TIMEOUT) {
        s_now_ms = value_of(request->deadline_ms);
        return PULSE_EXT_OK;
    }
    if (s_invoke_mode == INVOKE_QUIESCE_THEN_COMPLETE) {
        memset(&quiesce, 0, sizeof(quiesce));
        quiesce.struct_size = sizeof(quiesce);
        quiesce.reason = 0x48583435u;
        quiesce.deadline_ms = parts(s_now_ms + 1000u);
        status = wdc_extension_registry_quiesce(&s_registry, &quiesce);
        if (status != WDC_EXTENSION_OK) {
            return PULSE_EXT_ERR_FAULT;
        }
        s_quiesce_completion_status = complete_saved();
        return PULSE_EXT_OK;
    }
    return complete_saved();
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

static int32_t adversarial_wasm_handler(void *ctx,
                                        const uint8_t *event_cbor,
                                        uint32_t event_len)
{
    static const uint8_t echo[] = {'h', 'x', '4', '-', 'e', 'c', 'h', 'o'};
    uint8_t oversized[33];
    uint8_t request[128];
    uint8_t response[128];
    const uint8_t *payload = echo;
    uint32_t payload_len = sizeof(echo);
    uint32_t operation_id = SYNTHETIC_OPERATION_ECHO;
    uint32_t response_len = 0u;
    WdcCborBuilder builder;
    WdcEvent event;
    int32_t status;
    (void)ctx;
    s_handler_calls += 1u;
    status = wdc_event_decode_cbor(event_cbor, event_len, &event);
    if (status != WDC_OK || event.event_type != SYNTHETIC_EVENT_TICK) {
        return WDC_ERR_BAD_ENCODING;
    }
    if (s_handler_mode == HANDLER_UNKNOWN_OPERATION) {
        operation_id = SYNTHETIC_OPERATION_UNKNOWN;
    } else if (s_handler_mode == HANDLER_OVERSIZED_EFFECT) {
        memset(oversized, 0xa5, sizeof(oversized));
        payload = oversized;
        payload_len = sizeof(oversized);
    } else if (s_handler_mode == HANDLER_EXPIRED_DEADLINE) {
        s_expire_time_reads = 0u;
        s_expire_during_invoke = 1u;
    }
    wdc_cbor_builder_init(&builder, request, sizeof(request));
    status = wdc_cbor_begin_map(&builder, 2u);
    if (status == WDC_OK) {
        status = wdc_cbor_put_key_u32(
            &builder, WDC_CBOR_KEY_OPERATION_ID, operation_id);
    }
    if (status == WDC_OK) {
        status = wdc_cbor_put_key_bytes(
            &builder, WDC_CBOR_KEY_DATA, payload, payload_len);
    }
    if (status != WDC_OK) {
        return status;
    }
    status = wdc_host_call_dispatch(WDC_OP_EFFECT_INVOKE,
                                    request,
                                    wdc_cbor_len(&builder),
                                    response,
                                    sizeof(response),
                                    &response_len);
    s_host_call_status = status;
    return status;
}

static void reset_fixture_state(void)
{
    s_now_ms = 1000u;
    s_handler_calls = 0u;
    s_invoke_calls = 0u;
    s_expire_time_reads = 0u;
    s_expire_during_invoke = 0u;
    s_host_call_status = WDC_ERR_UNKNOWN;
    s_quiesce_completion_status = WDC_ERR_UNKNOWN;
    s_handler_mode = HANDLER_NORMAL;
    s_invoke_mode = INVOKE_COMPLETE;
    s_health_state = PULSE_EXT_HEALTH_RUNNING;
    memset(&s_saved_correlation, 0, sizeof(s_saved_correlation));
    memset(s_saved_payload, 0, sizeof(s_saved_payload));
    s_saved_payload_len = 0u;
    memset(&s_candidate, 0, sizeof(s_candidate));
    memset(&s_registry, 0, sizeof(s_registry));
    memset(&s_descriptor, 0, sizeof(s_descriptor));
    memset(&s_runtime, 0, sizeof(s_runtime));
    memset(&s_bridge, 0, sizeof(s_bridge));
    wdc_host_call_reset_for_test();
}

static void fixture(uint32_t trap_runtime)
{
    WdcRuntimeConfig runtime_config;
    WdcExtensionBridgeConfig bridge_config;
    reset_fixture_state();
    s_descriptor.event_count = 1u;
    s_descriptor.operation_count = 1u;
    s_descriptor.event_ids[0] = SYNTHETIC_EVENT_TICK;
    s_descriptor.operation_ids[0] = SYNTHETIC_OPERATION_ECHO;
    s_descriptor.invoke_fn = mock_invoke;
    s_descriptor.health_fn = mock_health;
    s_descriptor.quiesce_fn = mock_quiesce;
    s_candidate.state = WDC_EXTENSION_STARTED;
    s_candidate.start_entered = 1u;
    s_candidate.descriptor = &s_descriptor;
    s_candidate.inspection.metadata.queue_depth = 4u;
    s_candidate.inspection.metadata.task_stack_bytes = 4096u;
    s_candidate.inspection.metadata.max_event_payload_bytes = 64u;
    s_candidate.inspection.metadata.max_effect_request_bytes = 32u;
    s_candidate.inspection.metadata.max_effect_completion_bytes = 32u;
    s_registry.sealed = 1u;
    s_registry.count = 1u;
    s_registry.started_count = 1u;
    s_registry.candidates[0] = &s_candidate;
    CHECK(wdc_extension_services_bind(&s_registry) == WDC_EXTENSION_OK);
    wdc_extension_services_set_test_caller(&s_candidate);
    CHECK(wdc_events_init() == WDC_OK);
    runtime_config = wdc_runtime_default_config();
    CHECK(wdc_runtime_init(&s_runtime, &runtime_config) == WDC_OK);
    if (trap_runtime != 0u) {
        CHECK(wdc_runtime_load_static(&s_runtime,
                                      wdc_static_event_trap_wasm,
                                      wdc_static_event_trap_wasm_len) == WDC_OK);
    } else {
        CHECK(wdc_runtime_load_static(&s_runtime,
                                      wdc_hx4_event_effect_wasm,
                                      wdc_hx4_event_effect_wasm_len) == WDC_OK);
    }
    CHECK(wdc_runtime_lookup_exports(&s_runtime) == WDC_OK);
    CHECK(wdc_runtime_call_init(&s_runtime) == WDC_OK);
    if (trap_runtime == 0u) {
        wdc_runtime_set_host_stub_event_hook(
            &s_runtime, adversarial_wasm_handler, NULL);
    }
    wdc_host_call_set_authorizer(allow_effect_authorizer, NULL);
    bridge_config = wdc_extension_bridge_default_config();
    bridge_config.effect_timeout_ms = 1000u;
    bridge_config.max_effect_request_bytes = 32u;
    bridge_config.max_effect_completion_bytes = 32u;
    bridge_config.expected_event_id = SYNTHETIC_EVENT_TICK;
    bridge_config.expected_operation_id = SYNTHETIC_OPERATION_ECHO;
    CHECK(wdc_extension_bridge_init(
              &s_bridge, &s_registry, &s_runtime, &bridge_config) == WDC_OK);
}

static void teardown_fixture(void)
{
    wdc_extension_bridge_deinit(&s_bridge);
    wdc_runtime_teardown(&s_runtime);
    wdc_extension_services_unbind(&s_registry);
    wdc_host_call_reset_for_test();
}

static int32_t emit_event(uint32_t event_id,
                          const uint8_t *payload,
                          uint32_t payload_len)
{
    pulse_extension_event_v1 event;
    memset(&event, 0, sizeof(event));
    event.struct_size = sizeof(event);
    event.event_id = event_id;
    event.causation_id = parts(42u);
    event.payload_ptr = payload;
    event.payload_len = payload_len;
    return pulse_host_emit_event_v1(&event);
}

static void record_case(const char *name,
                        int32_t observed,
                        int32_t expected,
                        uint32_t failures_before)
{
    CaseRecord *record;
    if (observed != expected) {
        s_failures += 1u;
    }
    CHECK(s_case_count < ADVERSARIAL_CASE_COUNT);
    if (s_case_count >= ADVERSARIAL_CASE_COUNT) {
        return;
    }
    record = &s_cases[s_case_count++];
    record->name = name;
    record->observed = observed;
    record->expected = expected;
    record->passed = s_failures == failures_before ? 1u : 0u;
}

static void case_unknown_event(void)
{
    static const uint8_t tick[] = {'h', 'x', '4', '-', 't', 'i', 'c', 'k'};
    WdcEvent forged;
    uint32_t before = s_failures;
    int32_t status;
    fixture(0u);
    status = emit_event(SYNTHETIC_EVENT_UNKNOWN, tick, sizeof(tick));
    CHECK(status == PULSE_EXT_ERR_ARGUMENT);
    CHECK(wdc_events_pending() == 0u);
    CHECK(wdc_event_make(&forged,
                         SYNTHETIC_EVENT_UNKNOWN,
                         WDC_EVENT_RESOURCE_NONE,
                         s_now_ms,
                         tick,
                         sizeof(tick)) == WDC_OK);
    CHECK(wdc_events_post(&forged) == WDC_OK);
    status = wdc_extension_bridge_process_next(&s_bridge);
    CHECK(s_handler_calls == 0u);
    CHECK(wdc_events_pending() == 0u);
    record_case("unknown-event-identity", status, WDC_ERR_UNSUPPORTED_OPCODE, before);
    teardown_fixture();
}

static void case_unknown_operation(void)
{
    static const uint8_t tick[] = {'h', 'x', '4', '-', 't', 'i', 'c', 'k'};
    uint32_t before = s_failures;
    int32_t status;
    fixture(0u);
    s_handler_mode = HANDLER_UNKNOWN_OPERATION;
    CHECK(emit_event(SYNTHETIC_EVENT_TICK, tick, sizeof(tick)) == PULSE_EXT_OK);
    status = wdc_extension_bridge_process_next(&s_bridge);
    CHECK(status == WDC_ERR_CONTRACT_VIOLATION);
    CHECK(s_invoke_calls == 0u);
    record_case("unknown-operation-identity",
                s_host_call_status,
                WDC_ERR_UNSUPPORTED_OPCODE,
                before);
    teardown_fixture();
}

static void case_event_queue_full(void)
{
    static const uint8_t tick[] = {'h', 'x', '4', '-', 't', 'i', 'c', 'k'};
    WdcEventQueueStats stats;
    uint32_t before = s_failures;
    uint32_t index;
    int32_t status = PULSE_EXT_OK;
    fixture(0u);
    for (index = 0u; index <= WDC_EVENT_QUEUE_CAPACITY_DEFAULT; ++index) {
        status = emit_event(SYNTHETIC_EVENT_TICK, tick, sizeof(tick));
        if (index < WDC_EVENT_QUEUE_CAPACITY_DEFAULT) {
            CHECK(status == PULSE_EXT_OK);
        }
    }
    wdc_events_get_stats(&stats);
    CHECK(stats.pending == WDC_EVENT_QUEUE_CAPACITY_DEFAULT);
    CHECK(stats.dropped == 1u);
    CHECK(stats.overflow_policy == WDC_EVENT_OVERFLOW_DROP_NEWEST);
    record_case("event-queue-full", status, PULSE_EXT_ERR_BUSY, before);
    teardown_fixture();
}

static void case_oversized_event(void)
{
    uint8_t oversized[65];
    uint32_t before = s_failures;
    int32_t status;
    memset(oversized, 0xa5, sizeof(oversized));
    fixture(0u);
    status = emit_event(SYNTHETIC_EVENT_TICK, oversized, sizeof(oversized));
    CHECK(wdc_events_pending() == 0u);
    record_case("oversized-event-frame", status, PULSE_EXT_ERR_BOUNDS, before);
    teardown_fixture();
}

static void case_oversized_effect(void)
{
    static const uint8_t tick[] = {'h', 'x', '4', '-', 't', 'i', 'c', 'k'};
    uint32_t before = s_failures;
    int32_t status;
    fixture(0u);
    s_handler_mode = HANDLER_OVERSIZED_EFFECT;
    CHECK(emit_event(SYNTHETIC_EVENT_TICK, tick, sizeof(tick)) == PULSE_EXT_OK);
    status = wdc_extension_bridge_process_next(&s_bridge);
    CHECK(status == WDC_ERR_CONTRACT_VIOLATION);
    CHECK(s_invoke_calls == 0u);
    record_case("oversized-effect-frame", s_host_call_status, WDC_ERR_BAD_LENGTH, before);
    teardown_fixture();
}

static void case_expired_deadline(void)
{
    static const uint8_t tick[] = {'h', 'x', '4', '-', 't', 'i', 'c', 'k'};
    uint32_t before = s_failures;
    int32_t status;
    fixture(0u);
    s_handler_mode = HANDLER_EXPIRED_DEADLINE;
    CHECK(emit_event(SYNTHETIC_EVENT_TICK, tick, sizeof(tick)) == PULSE_EXT_OK);
    status = wdc_extension_bridge_process_next(&s_bridge);
    CHECK(status == WDC_ERR_CONTRACT_VIOLATION);
    CHECK(s_invoke_calls == 0u);
    CHECK(s_candidate.state == WDC_EXTENSION_STARTED);
    record_case("expired-deadline", s_host_call_status, WDC_ERR_TIMEOUT, before);
    teardown_fixture();
}

static void case_completion_after_timeout(void)
{
    static const uint8_t tick[] = {'h', 'x', '4', '-', 't', 'i', 'c', 'k'};
    uint32_t before = s_failures;
    int32_t status;
    int32_t late_status;
    fixture(0u);
    s_invoke_mode = INVOKE_DEFER_TO_TIMEOUT;
    CHECK(emit_event(SYNTHETIC_EVENT_TICK, tick, sizeof(tick)) == PULSE_EXT_OK);
    status = wdc_extension_bridge_process_next(&s_bridge);
    CHECK(status == WDC_ERR_CONTRACT_VIOLATION);
    CHECK(s_host_call_status == WDC_ERR_TIMEOUT);
    late_status = complete_saved();
    record_case("completion-after-timeout", late_status, PULSE_EXT_ERR_STALE, before);
    teardown_fixture();
}

static void case_duplicate_completion(void)
{
    static const uint8_t tick[] = {'h', 'x', '4', '-', 't', 'i', 'c', 'k'};
    uint32_t before = s_failures;
    int32_t status;
    int32_t duplicate_status;
    fixture(0u);
    s_invoke_mode = INVOKE_COMPLETE;
    CHECK(emit_event(SYNTHETIC_EVENT_TICK, tick, sizeof(tick)) == PULSE_EXT_OK);
    status = wdc_extension_bridge_process_next(&s_bridge);
    CHECK(status == WDC_OK);
    duplicate_status = complete_saved();
    record_case("duplicate-completion",
                duplicate_status,
                PULSE_EXT_ERR_DUPLICATE,
                before);
    teardown_fixture();
}

static void case_completion_after_quiescence(void)
{
    static const uint8_t tick[] = {'h', 'x', '4', '-', 't', 'i', 'c', 'k'};
    uint32_t before = s_failures;
    int32_t status;
    fixture(0u);
    s_invoke_mode = INVOKE_QUIESCE_THEN_COMPLETE;
    CHECK(emit_event(SYNTHETIC_EVENT_TICK, tick, sizeof(tick)) == PULSE_EXT_OK);
    status = wdc_extension_bridge_process_next(&s_bridge);
    CHECK(status == WDC_ERR_CONTRACT_VIOLATION);
    CHECK(s_host_call_status == WDC_ERR_INVALID_STATE);
    CHECK(s_candidate.state == WDC_EXTENSION_QUIESCED);
    CHECK(wdc_extension_registry_requires_reset(&s_registry) == 0u);
    record_case("completion-after-quiescence",
                s_quiesce_completion_status,
                PULSE_EXT_ERR_STALE,
                before);
    teardown_fixture();
}

static void case_wasm_trap(void)
{
    static const uint8_t tick[] = {'h', 'x', '4', '-', 't', 'i', 'c', 'k'};
    const WdcRuntimeReport *runtime_report;
    uint32_t before = s_failures;
    int32_t status;
    fixture(1u);
    CHECK(emit_event(SYNTHETIC_EVENT_TICK, tick, sizeof(tick)) == PULSE_EXT_OK);
    status = wdc_extension_bridge_process_next(&s_bridge);
    runtime_report = wdc_runtime_get_report(&s_runtime);
    CHECK(runtime_report != NULL);
    CHECK(runtime_report != NULL &&
          runtime_report->outcome == WDC_RUNTIME_OUTCOME_GUEST_TRAPPED);
    CHECK(s_invoke_calls == 0u);
    record_case("wasm-trap-during-event",
                status,
                WDC_ERR_CONTRACT_VIOLATION,
                before);
    teardown_fixture();
}

static void case_extension_fault(void)
{
    static const uint8_t tick[] = {'h', 'x', '4', '-', 't', 'i', 'c', 'k'};
    uint32_t before = s_failures;
    int32_t status;
    fixture(0u);
    s_invoke_mode = INVOKE_FAULT;
    CHECK(emit_event(SYNTHETIC_EVENT_TICK, tick, sizeof(tick)) == PULSE_EXT_OK);
    status = wdc_extension_bridge_process_next(&s_bridge);
    CHECK(status == WDC_ERR_CONTRACT_VIOLATION);
    CHECK(s_candidate.state == WDC_EXTENSION_RESET_REQUIRED);
    CHECK(wdc_extension_registry_requires_reset(&s_registry) == 1u);
    record_case("extension-fault-during-operation",
                s_host_call_status,
                WDC_ERR_IO,
                before);
    teardown_fixture();
}

int main(void)
{
    uint32_t index;
    memset(s_cases, 0, sizeof(s_cases));
    case_unknown_event();
    case_unknown_operation();
    case_event_queue_full();
    case_oversized_event();
    case_oversized_effect();
    case_expired_deadline();
    case_completion_after_timeout();
    case_duplicate_completion();
    case_completion_after_quiescence();
    case_wasm_trap();
    case_extension_fault();
    CHECK(s_case_count == ADVERSARIAL_CASE_COUNT);
    printf("{\"status\":\"%s\",\"failures\":%u,\"case_count\":%u,"
           "\"queue_capacity\":%u,\"cases\":[",
           s_failures == 0u ? "PASS" : "FAIL",
           s_failures,
           s_case_count,
           WDC_EVENT_QUEUE_CAPACITY_DEFAULT);
    for (index = 0u; index < s_case_count; ++index) {
        const CaseRecord *record = &s_cases[index];
        printf("%s{\"name\":\"%s\",\"status\":\"%s\","
               "\"observed\":%d,\"expected\":%d}",
               index == 0u ? "" : ",",
               record->name,
               record->passed != 0u ? "PASS" : "FAIL",
               (int)record->observed,
               (int)record->expected);
    }
    printf("]}\n");
    return s_failures == 0u ? 0 : 1;
}
