#include "wdc_extension_bridge.h"

#include <limits.h>
#include <stddef.h>
#include <string.h>

#include "wdc_extension_internal.h"

#ifdef ESP_PLATFORM
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#endif

static WdcExtensionCandidate *resolve_operation(WdcExtensionRegistry *registry,
                                                uint32_t operation_id)
{
    WdcExtensionCandidate *resolved = NULL;
    uint32_t candidate_index;
    if (registry == NULL || registry->sealed == 0u || operation_id == 0u) {
        return NULL;
    }
    for (candidate_index = 0u; candidate_index < registry->count; ++candidate_index) {
        WdcExtensionCandidate *candidate = registry->candidates[candidate_index];
        uint32_t operation_index;
        if (candidate == NULL || candidate->descriptor == NULL ||
            candidate->state != WDC_EXTENSION_STARTED) {
            continue;
        }
        for (operation_index = 0u;
             operation_index < candidate->descriptor->operation_count;
             ++operation_index) {
            if (candidate->descriptor->operation_ids[operation_index] == operation_id) {
                if (resolved != NULL) {
                    return NULL;
                }
                resolved = candidate;
            }
        }
    }
    return resolved;
}

static pulse_u64_parts_v1 parts_from_u64(uint64_t value)
{
    pulse_u64_parts_v1 parts;
    parts.lo = (uint32_t)value;
    parts.hi = (uint32_t)(value >> 32u);
    return parts;
}

static uint64_t next_correlation(WdcExtensionBridge *bridge)
{
    uint64_t result = bridge->next_correlation_id++;
    if (result == 0u) {
        result = bridge->next_correlation_id++;
    }
    if (bridge->next_correlation_id == 0u) {
        bridge->next_correlation_id = 1u;
    }
    return result;
}

static int32_t write_effect_response(const WdcExtensionCompletionResult *completion,
                                     uint32_t operation_id,
                                     uint64_t deadline_ms,
                                     uint8_t *response,
                                     uint32_t response_cap,
                                     uint32_t *out_response_len)
{
    WdcCborBuilder builder;
    int32_t status;
    uint32_t latency = completion->completed_ms >= completion->started_ms ?
                           (uint32_t)(completion->completed_ms - completion->started_ms) :
                           0u;
    wdc_cbor_builder_init(&builder, response, response_cap);
    status = wdc_cbor_begin_map(&builder, 7u);
    if (status == WDC_OK) {
        status = wdc_cbor_put_key_i32(
            &builder, WDC_CBOR_KEY_STATUS, completion->status);
    }
    if (status == WDC_OK) {
        status = wdc_cbor_put_key_u32(
            &builder, WDC_CBOR_KEY_OPERATION_ID, operation_id);
    }
    if (status == WDC_OK) {
        status = wdc_cbor_put_key_u64(
            &builder, WDC_CBOR_KEY_CORRELATION_ID, completion->correlation_id);
    }
    if (status == WDC_OK) {
        status = wdc_cbor_put_key_u64(
            &builder, WDC_CBOR_KEY_DEADLINE_MS, deadline_ms);
    }
    if (status == WDC_OK) {
        status = wdc_cbor_put_key_u32(
            &builder, WDC_CBOR_KEY_ENCODING, WDC_EXTENSION_BRIDGE_ENCODING_CBOR);
    }
    if (status == WDC_OK) {
        status = wdc_cbor_put_key_u32(
            &builder, WDC_CBOR_KEY_COMPLETION_LATENCY_MS, latency);
    }
    if (status == WDC_OK) {
        status = wdc_cbor_put_key_bytes(
            &builder,
            WDC_CBOR_KEY_DATA,
            completion->payload,
            completion->payload_len);
    }
    if (status == WDC_OK && out_response_len != NULL) {
        *out_response_len = wdc_cbor_len(&builder);
    }
    return status;
}

static int32_t bridge_effect_call(void *ctx,
                                  const uint8_t *request,
                                  uint32_t request_len,
                                  uint8_t *response,
                                  uint32_t response_cap,
                                  uint32_t *out_response_len)
{
    WdcExtensionBridge *bridge = (WdcExtensionBridge *)ctx;
    WdcExtensionCandidate *candidate;
    WdcCborBytes payload = {NULL, 0u};
    pulse_extension_invoke_v1 invoke;
    WdcExtensionCompletionResult completion;
    uint32_t operation_id = 0u;
    uint64_t correlation;
    uint64_t now;
    uint64_t deadline;
    int32_t status;
    if (out_response_len != NULL) {
        *out_response_len = 0u;
    }
    if (bridge == NULL || bridge->initialized == 0u ||
        bridge->current_event_active == 0u || response == NULL || response_cap == 0u ||
        (request_len != 0u && request == NULL)) {
        return WDC_ERR_INVALID_STATE;
    }
    status = wdc_cbor_map_find_u32(
        request, request_len, WDC_CBOR_KEY_OPERATION_ID, &operation_id);
    if (status != WDC_OK) {
        return WDC_ERR_BAD_ENCODING;
    }
    status = wdc_cbor_map_find_bytes(
        request, request_len, WDC_CBOR_KEY_DATA, &payload);
    if (status == WDC_ERR_NOT_AVAILABLE) {
        payload.ptr = NULL;
        payload.len = 0u;
    } else if (status != WDC_OK) {
        return WDC_ERR_BAD_ENCODING;
    }
    if (payload.len > bridge->config.max_effect_request_bytes ||
        (bridge->config.expected_operation_id != 0u &&
         operation_id != bridge->config.expected_operation_id)) {
        return payload.len > bridge->config.max_effect_request_bytes ?
                   WDC_ERR_BAD_LENGTH : WDC_ERR_UNSUPPORTED_OPCODE;
    }
    candidate = resolve_operation(bridge->registry, operation_id);
    if (candidate == NULL) {
        return WDC_ERR_UNSUPPORTED_OPCODE;
    }
    now = wdc_extension_platform_monotonic_ms();
    if (bridge->config.effect_timeout_ms > UINT64_MAX - now) {
        return WDC_ERR_BAD_LENGTH;
    }
    deadline = now + bridge->config.effect_timeout_ms;
    correlation = next_correlation(bridge);
    status = wdc_extension_services_begin_effect(candidate, correlation, deadline);
    if (status != WDC_EXTENSION_OK) {
        return status == WDC_EXTENSION_ERR_BUDGET ? WDC_ERR_BUSY :
                                                    WDC_ERR_INVALID_STATE;
    }
    memset(&invoke, 0, sizeof(invoke));
    invoke.struct_size = sizeof(invoke);
    invoke.operation_id = operation_id;
    invoke.correlation_id = parts_from_u64(correlation);
    invoke.deadline_ms = parts_from_u64(deadline);
    invoke.payload_ptr = payload.ptr;
    invoke.payload_len = payload.len;
    bridge->report.effect_invoked = 1u;
    bridge->report.operation_id = operation_id;
    bridge->report.correlation_id = correlation;
    bridge->report.deadline_ms = deadline;
    bridge->report.effect_request_len = payload.len;
    status = wdc_extension_candidate_invoke(candidate, &invoke);
    if (status != WDC_EXTENSION_OK) {
        (void)wdc_extension_services_timeout_effect(candidate, correlation);
        (void)wdc_extension_services_release_effect(candidate, correlation);
        if (status == WDC_EXTENSION_ERR_ARGUMENT) {
            return WDC_ERR_BAD_ENCODING;
        }
        return status == WDC_EXTENSION_ERR_TIMEOUT ? WDC_ERR_TIMEOUT : WDC_ERR_IO;
    }
    for (;;) {
        status = wdc_extension_services_take_effect(
            candidate, correlation, &completion);
        if (status == WDC_EXTENSION_OK) {
            break;
        }
        if (status != WDC_EXTENSION_ERR_NOT_READY) {
            (void)wdc_extension_services_release_effect(candidate, correlation);
            return status == WDC_EXTENSION_ERR_TIMEOUT ? WDC_ERR_TIMEOUT :
                                                         WDC_ERR_INVALID_STATE;
        }
        now = wdc_extension_platform_monotonic_ms();
        if (now >= deadline) {
            (void)wdc_extension_services_timeout_effect(candidate, correlation);
            (void)wdc_extension_services_release_effect(candidate, correlation);
            return WDC_ERR_TIMEOUT;
        }
#ifdef ESP_PLATFORM
        vTaskDelay(1u);
#else
        (void)wdc_extension_services_timeout_effect(candidate, correlation);
        (void)wdc_extension_services_release_effect(candidate, correlation);
        return WDC_ERR_TIMEOUT;
#endif
    }
    if (completion.payload_len > bridge->config.max_effect_completion_bytes) {
        (void)wdc_extension_services_release_effect(candidate, correlation);
        return WDC_ERR_BAD_LENGTH;
    }
    status = write_effect_response(
        &completion, operation_id, deadline, response, response_cap, out_response_len);
    if (status == WDC_OK) {
        bridge->report.completion_status = completion.status;
        bridge->report.completion_payload_len = completion.payload_len;
        bridge->report.completion_latency_ms =
            completion.completed_ms >= completion.started_ms ?
                (uint32_t)(completion.completed_ms - completion.started_ms) :
                0u;
        bridge->report.completion_accepted = 1u;
        if (completion.payload_len != 0u) {
            memcpy(bridge->report.completion_payload,
                   completion.payload,
                   completion.payload_len);
        }
    }
    (void)wdc_extension_services_release_effect(candidate, correlation);
    return status;
}

WdcExtensionBridgeConfig wdc_extension_bridge_default_config(void)
{
    WdcExtensionBridgeConfig config = {
        .effect_timeout_ms = WDC_EXTENSION_BRIDGE_DEFAULT_EFFECT_TIMEOUT_MS,
        .max_effect_request_bytes = WDC_EXTENSION_EFFECT_PAYLOAD_MAX,
        .max_effect_completion_bytes = WDC_EXTENSION_EFFECT_PAYLOAD_MAX,
        .expected_event_id = 0u,
        .expected_operation_id = 0u,
    };
    return config;
}

int32_t wdc_extension_bridge_init(WdcExtensionBridge *bridge,
                                  WdcExtensionRegistry *registry,
                                  WdcRuntime *runtime,
                                  const WdcExtensionBridgeConfig *config)
{
    WdcExtensionBridgeConfig selected;
    int32_t status;
    if (bridge == NULL || registry == NULL || runtime == NULL ||
        registry->sealed == 0u || registry->count == 0u ||
        wdc_extension_services_registry() != registry ||
        !runtime->report.runtime_initialized || !runtime->report.exports_resolved) {
        return WDC_ERR_INVALID_STATE;
    }
    selected = config != NULL ? *config : wdc_extension_bridge_default_config();
    if (selected.effect_timeout_ms == 0u ||
        selected.max_effect_request_bytes == 0u ||
        selected.max_effect_request_bytes > WDC_EXTENSION_EFFECT_PAYLOAD_MAX ||
        selected.max_effect_completion_bytes == 0u ||
        selected.max_effect_completion_bytes > WDC_EXTENSION_EFFECT_PAYLOAD_MAX) {
        return WDC_ERR_BAD_LENGTH;
    }
    memset(bridge, 0, sizeof(*bridge));
    bridge->registry = registry;
    bridge->runtime = runtime;
    bridge->config = selected;
    bridge->next_correlation_id = 1u;
    status = wdc_host_call_set_effect_hook(bridge_effect_call, bridge);
    if (status != WDC_OK) {
        memset(bridge, 0, sizeof(*bridge));
        return status;
    }
    bridge->initialized = 1u;
    return WDC_OK;
}

int32_t wdc_extension_bridge_process_next(WdcExtensionBridge *bridge)
{
    WdcEventQueueStats queue_stats;
    uint8_t encoded[WDC_MAX_EVENT_BYTES_DEFAULT];
    uint32_t encoded_len = 0u;
    int32_t status;
    if (bridge == NULL || bridge->initialized == 0u ||
        bridge->current_event_active != 0u) {
        return WDC_ERR_INVALID_STATE;
    }
    memset(&bridge->report, 0, sizeof(bridge->report));
    wdc_events_get_stats(&queue_stats);
    bridge->report.event_queue_depth_before = (uint32_t)queue_stats.pending;
    status = wdc_events_next(&bridge->current_event);
    if (status != WDC_OK) {
        bridge->report.status = status;
        return status;
    }
    wdc_events_get_stats(&queue_stats);
    bridge->report.event_queue_depth_after = (uint32_t)queue_stats.pending;
    bridge->report.event_type = bridge->current_event.event_type;
    bridge->report.event_id = bridge->current_event.event_id;
    bridge->report.causation_id = bridge->current_event.causation_id;
    bridge->report.event_payload_len = bridge->current_event.payload_len;
    bridge->report.encoding = WDC_EXTENSION_BRIDGE_ENCODING_CBOR;
    if (bridge->config.expected_event_id != 0u &&
        bridge->current_event.event_type != bridge->config.expected_event_id) {
        bridge->report.status = WDC_ERR_UNSUPPORTED_OPCODE;
        return WDC_ERR_UNSUPPORTED_OPCODE;
    }
    status = wdc_event_encode_cbor(
        &bridge->current_event, encoded, sizeof(encoded), &encoded_len);
    if (status != WDC_OK) {
        bridge->report.status = status;
        return status;
    }
    bridge->report.event_encoded_len = encoded_len;
    bridge->current_event_active = 1u;
    status = wdc_runtime_dispatch_event(bridge->runtime, &bridge->current_event);
    bridge->current_event_active = 0u;
    bridge->report.runtime_status = status;
    if (status == WDC_OK && bridge->config.expected_operation_id != 0u &&
        (bridge->report.effect_invoked == 0u ||
         bridge->report.completion_accepted == 0u)) {
        status = WDC_ERR_CONTRACT_VIOLATION;
    }
    bridge->report.status = status;
    return status;
}

void wdc_extension_bridge_deinit(WdcExtensionBridge *bridge)
{
    if (bridge == NULL) {
        return;
    }
    if (bridge->initialized != 0u) {
        wdc_host_call_clear_effect_hook();
    }
    memset(bridge, 0, sizeof(*bridge));
}

const WdcExtensionBridgeReport *wdc_extension_bridge_get_report(
    const WdcExtensionBridge *bridge)
{
    return bridge != NULL ? &bridge->report : NULL;
}
