#include "wdc_extension.h"

#include <stddef.h>
#include <stdint.h>
#include <string.h>

#include "wdc_extension_internal.h"

#define WDC_EXTENSION_FAILURE_QUIESCE_MS 1000u

#ifdef PULSE_EXTENSION_HOST_TEST
typedef struct WdcExtensionTestFaultState {
    WdcExtensionTestFaultPoint point;
    uint32_t occurrence;
    uint32_t matches;
    uint32_t fired;
} WdcExtensionTestFaultState;

static WdcExtensionTestFaultState s_test_fault;

int32_t wdc_extension_test_fault_arm(
    WdcExtensionTestFaultPoint point,
    uint32_t occurrence)
{
    if (point <= WDC_EXTENSION_TEST_FAULT_NONE ||
        point > WDC_EXTENSION_TEST_FAULT_UNLOAD_RETURN || occurrence == 0u) {
        return WDC_EXTENSION_ERR_ARGUMENT;
    }
    memset(&s_test_fault, 0, sizeof(s_test_fault));
    s_test_fault.point = point;
    s_test_fault.occurrence = occurrence;
    return WDC_EXTENSION_OK;
}

void wdc_extension_test_fault_clear(void)
{
    memset(&s_test_fault, 0, sizeof(s_test_fault));
}

uint32_t wdc_extension_test_fault_fired(void)
{
    return s_test_fault.fired;
}

static int test_fault_should_fail(WdcExtensionTestFaultPoint point)
{
    if (s_test_fault.point != point || s_test_fault.fired != 0u) {
        return 0;
    }
    s_test_fault.matches += 1u;
    if (s_test_fault.matches != s_test_fault.occurrence) {
        return 0;
    }
    s_test_fault.fired = 1u;
    return 1;
}

#define WDC_EXTENSION_TEST_SHOULD_FAIL(point) test_fault_should_fail(point)
#else
#define WDC_EXTENSION_TEST_SHOULD_FAIL(point) 0
#endif

static uint64_t parts_to_u64(pulse_u64_parts_v1 value)
{
    return ((uint64_t)value.hi << 32u) | value.lo;
}

static pulse_u64_parts_v1 parts_from_u64(uint64_t value)
{
    pulse_u64_parts_v1 result;
    result.lo = (uint32_t)value;
    result.hi = (uint32_t)(value >> 32u);
    return result;
}

static int bytes_zero(const void *value, size_t size)
{
    const uint8_t *bytes = (const uint8_t *)value;
    size_t index;
    for (index = 0u; index < size; ++index) {
        if (bytes[index] != 0u) {
            return 0;
        }
    }
    return 1;
}

static int operation_admitted(const WdcExtensionCandidate *candidate, uint32_t operation_id)
{
    uint32_t index;
    for (index = 0u; index < candidate->descriptor->operation_count; ++index) {
        if (candidate->descriptor->operation_ids[index] == operation_id) {
            return 1;
        }
    }
    return 0;
}

static void refresh_counts(WdcExtensionRegistry *registry)
{
    uint32_t initialized = 0u;
    uint32_t started = 0u;
    uint32_t index;
    for (index = 0u; index < registry->count; ++index) {
        WdcExtensionCandidate *candidate = registry->candidates[index];
        if (candidate == NULL) {
            continue;
        }
        if (candidate->state == WDC_EXTENSION_INITIALIZED ||
            candidate->state == WDC_EXTENSION_STARTING ||
            candidate->state == WDC_EXTENSION_STARTED ||
            candidate->state == WDC_EXTENSION_QUIESCING ||
            candidate->state == WDC_EXTENSION_QUIESCED ||
            candidate->state == WDC_EXTENSION_RESET_REQUIRED) {
            initialized += 1u;
        }
        if (candidate->start_entered != 0u &&
            candidate->state != WDC_EXTENSION_QUIESCED &&
            candidate->state != WDC_EXTENSION_DEINITIALIZED) {
            started += 1u;
        }
    }
    registry->initialized_count = initialized;
    registry->started_count = started;
}

static void mark_registry_reset(WdcExtensionCandidate *candidate)
{
    WdcExtensionRegistry *registry = wdc_extension_services_registry();
    uint32_t index;
    if (registry == NULL) {
        return;
    }
    for (index = 0u; index < registry->count; ++index) {
        if (registry->candidates[index] == candidate) {
            registry->reset_required = 1u;
            registry->lifecycle_failed = 1u;
            refresh_counts(registry);
            return;
        }
    }
}

static void latch_reset(WdcExtensionCandidate *candidate,
                        int32_t status,
                        uint32_t fault_code)
{
    if (candidate == NULL) {
        return;
    }
    candidate->last_extension_status = status;
    if (candidate->fault_code == 0u) {
        candidate->fault_code = fault_code;
    }
    candidate->reset_required = 1u;
    candidate->state = WDC_EXTENSION_RESET_REQUIRED;
    mark_registry_reset(candidate);
}

static int health_record_valid(const WdcExtensionCandidate *candidate,
                               const pulse_extension_health_v1 *health)
{
    if (candidate == NULL || health == NULL ||
        health->struct_size != sizeof(*health) || health->flags != 0u ||
        !bytes_zero(health->reserved, sizeof(health->reserved)) ||
        health->state < PULSE_EXT_HEALTH_INITIALIZED ||
        health->state > PULSE_EXT_HEALTH_FAULTED ||
        health->pending_count > candidate->inspection.metadata.queue_depth ||
        health->queue_high_water > candidate->inspection.metadata.queue_depth ||
        health->task_stack_high_water_bytes >
            candidate->inspection.metadata.task_stack_bytes) {
        return 0;
    }
    if ((health->state == PULSE_EXT_HEALTH_FAULTED) !=
        (health->fault_status != PULSE_EXT_OK)) {
        return 0;
    }
    return 1;
}

static int health_state_matches(const WdcExtensionCandidate *candidate,
                                const pulse_extension_health_v1 *health)
{
    switch (candidate->state) {
        case WDC_EXTENSION_INITIALIZED:
            return health->state == PULSE_EXT_HEALTH_INITIALIZED;
        case WDC_EXTENSION_STARTING:
        case WDC_EXTENSION_STARTED:
            return health->state == PULSE_EXT_HEALTH_RUNNING ||
                   health->state == PULSE_EXT_HEALTH_FAULTED;
        case WDC_EXTENSION_QUIESCING:
            return health->state == PULSE_EXT_HEALTH_QUIESCING ||
                   health->state == PULSE_EXT_HEALTH_QUIESCED ||
                   health->state == PULSE_EXT_HEALTH_FAULTED;
        case WDC_EXTENSION_QUIESCED:
            return health->state == PULSE_EXT_HEALTH_QUIESCED;
        case WDC_EXTENSION_RESET_REQUIRED:
            return health->state == PULSE_EXT_HEALTH_FAULTED ||
                   health->state == PULSE_EXT_HEALTH_QUIESCING ||
                   health->state == PULSE_EXT_HEALTH_QUIESCED;
        default:
            return 0;
    }
}

int32_t wdc_extension_record_service_health(
    WdcExtensionCandidate *candidate,
    const pulse_extension_health_v1 *health)
{
    if (!health_record_valid(candidate, health) ||
        !health_state_matches(candidate, health)) {
        latch_reset(candidate, PULSE_EXT_ERR_FAULT, WDC_EXTENSION_FAULT_HOST_SERVICE);
        return PULSE_EXT_ERR_FAULT;
    }
    memcpy(&candidate->observed_health, health, sizeof(*health));
    candidate->observed_health_valid = 1u;
    if (health->state == PULSE_EXT_HEALTH_FAULTED) {
        latch_reset(candidate, health->fault_status, WDC_EXTENSION_FAULT_HEALTH);
        return PULSE_EXT_ERR_FAULT;
    }
    return PULSE_EXT_OK;
}

void wdc_extension_record_service_fault(
    WdcExtensionCandidate *candidate,
    int32_t status,
    uint32_t fault_code)
{
    latch_reset(
        candidate,
        status == PULSE_EXT_OK ? PULSE_EXT_ERR_FAULT : status,
        fault_code == 0u ? WDC_EXTENSION_FAULT_HOST_SERVICE : fault_code);
}

static int init_template_valid(const pulse_extension_init_args_v1 *args)
{
    return args != NULL && args->struct_size == sizeof(*args) && args->flags == 0u &&
           args->host_event_queue_capacity != 0u &&
           args->host_max_event_payload_bytes != 0u &&
           args->host_max_effect_completion_bytes != 0u &&
           args->host_max_inflight_effects != 0u &&
           bytes_zero(args->extension_id, sizeof(args->extension_id)) &&
           bytes_zero(args->reserved, sizeof(args->reserved));
}

static int init_capacity_valid(const WdcExtensionCandidate *candidate,
                               const pulse_extension_init_args_v1 *args)
{
    return args->host_event_queue_capacity >= candidate->inspection.metadata.queue_depth &&
           args->host_max_event_payload_bytes >=
               candidate->inspection.metadata.max_event_payload_bytes &&
           args->host_max_effect_completion_bytes >=
               candidate->inspection.metadata.max_effect_completion_bytes;
}

static int32_t deinitialize_candidate(WdcExtensionCandidate *candidate)
{
    int32_t code;
    if (candidate == NULL || candidate->descriptor == NULL ||
        (candidate->state != WDC_EXTENSION_INITIALIZING &&
         candidate->state != WDC_EXTENSION_INITIALIZED &&
         candidate->state != WDC_EXTENSION_QUIESCED)) {
        return WDC_EXTENSION_ERR_STATE;
    }
    if (candidate->start_entered != 0u &&
        candidate->state != WDC_EXTENSION_QUIESCED) {
        latch_reset(candidate, PULSE_EXT_ERR_STATE, WDC_EXTENSION_FAULT_DEINIT);
        return WDC_EXTENSION_ERR_RESET_REQUIRED;
    }
    code = candidate->descriptor->deinit_fn();
    if (WDC_EXTENSION_TEST_SHOULD_FAIL(
            WDC_EXTENSION_TEST_FAULT_DEINIT_RETURN)) {
        code = PULSE_EXT_ERR_FAULT;
    }
    candidate->last_extension_status = code;
    if (code != PULSE_EXT_OK) {
        latch_reset(candidate, code, WDC_EXTENSION_FAULT_DEINIT);
        return WDC_EXTENSION_ERR_RESET_REQUIRED;
    }
    candidate->state = WDC_EXTENSION_DEINITIALIZED;
    candidate->observed_health_valid = 0u;
    return WDC_EXTENSION_OK;
}

static int32_t deinitialize_reverse(WdcExtensionRegistry *registry)
{
    int32_t first_error = WDC_EXTENSION_OK;
    uint32_t index = registry->count;
    while (index != 0u) {
        WdcExtensionCandidate *candidate = registry->candidates[--index];
        int32_t code;
        if (candidate == NULL || candidate->state == WDC_EXTENSION_REGISTRY_SEALED ||
            candidate->state == WDC_EXTENSION_DEINITIALIZED) {
            continue;
        }
        if (candidate->state == WDC_EXTENSION_RESET_REQUIRED) {
            if (first_error == WDC_EXTENSION_OK) {
                first_error = WDC_EXTENSION_ERR_RESET_REQUIRED;
            }
            continue;
        }
        code = deinitialize_candidate(candidate);
        if (code != WDC_EXTENSION_OK && first_error == WDC_EXTENSION_OK) {
            first_error = code;
        }
    }
    refresh_counts(registry);
    return first_error;
}

int32_t wdc_extension_registry_initialize(
    WdcExtensionRegistry *registry,
    const pulse_extension_init_args_v1 *template_args)
{
    uint32_t index;
    if (registry == NULL || registry->sealed == 0u || registry->count == 0u ||
        registry->lifecycle_failed != 0u || registry->reset_required != 0u ||
        !init_template_valid(template_args)) {
        return WDC_EXTENSION_ERR_STATE;
    }
    for (index = 0u; index < registry->count; ++index) {
        WdcExtensionCandidate *candidate = registry->candidates[index];
        if (candidate == NULL || candidate->state != WDC_EXTENSION_REGISTRY_SEALED) {
            return WDC_EXTENSION_ERR_STATE;
        }
        if (!init_capacity_valid(candidate, template_args)) {
            return WDC_EXTENSION_ERR_BUDGET;
        }
    }
    {
        int32_t bind_code = wdc_extension_services_bind(registry);
        if (bind_code == WDC_EXTENSION_OK &&
            WDC_EXTENSION_TEST_SHOULD_FAIL(
                WDC_EXTENSION_TEST_FAULT_SERVICES_BIND_RETURN)) {
            wdc_extension_services_unbind(registry);
            bind_code = WDC_EXTENSION_ERR_STATE;
        }
        if (bind_code != WDC_EXTENSION_OK) {
            return WDC_EXTENSION_ERR_STATE;
        }
    }
    for (index = 0u; index < registry->count; ++index) {
        WdcExtensionCandidate *candidate = registry->candidates[index];
        pulse_extension_init_args_v1 args = *template_args;
        int32_t code;
        memcpy(args.extension_id, candidate->descriptor->extension_id,
               sizeof(args.extension_id));
        candidate->state = WDC_EXTENSION_INITIALIZING;
        code = candidate->descriptor->init_fn(&args);
        if (WDC_EXTENSION_TEST_SHOULD_FAIL(
                WDC_EXTENSION_TEST_FAULT_INIT_RETURN)) {
            code = PULSE_EXT_ERR_FAULT;
        }
        candidate->last_extension_status = code;
        if (code != PULSE_EXT_OK) {
            int32_t cleanup;
            registry->lifecycle_failed = 1u;
            cleanup = deinitialize_reverse(registry);
            if (cleanup != WDC_EXTENSION_OK) {
                registry->reset_required = 1u;
                return WDC_EXTENSION_ERR_RESET_REQUIRED;
            }
            wdc_extension_services_unbind(registry);
            return WDC_EXTENSION_ERR_LIFECYCLE;
        }
        candidate->state = WDC_EXTENSION_INITIALIZED;
        refresh_counts(registry);
    }
    return WDC_EXTENSION_OK;
}

int32_t wdc_extension_candidate_health(
    WdcExtensionCandidate *candidate,
    pulse_extension_health_v1 *out_health)
{
    int32_t code;
    if (candidate == NULL || out_health == NULL || candidate->descriptor == NULL ||
        (candidate->state != WDC_EXTENSION_INITIALIZED &&
         candidate->state != WDC_EXTENSION_STARTING &&
         candidate->state != WDC_EXTENSION_STARTED &&
         candidate->state != WDC_EXTENSION_QUIESCING &&
         candidate->state != WDC_EXTENSION_QUIESCED &&
         candidate->state != WDC_EXTENSION_RESET_REQUIRED)) {
        return WDC_EXTENSION_ERR_STATE;
    }
    memset(out_health, 0, sizeof(*out_health));
    out_health->struct_size = sizeof(*out_health);
    code = candidate->descriptor->health_fn(out_health);
    if (WDC_EXTENSION_TEST_SHOULD_FAIL(
            WDC_EXTENSION_TEST_FAULT_HEALTH_RETURN)) {
        code = PULSE_EXT_ERR_FAULT;
    }
    candidate->last_extension_status = code;
    if (code != PULSE_EXT_OK || !health_record_valid(candidate, out_health) ||
        !health_state_matches(candidate, out_health)) {
        if (candidate->start_entered != 0u) {
            latch_reset(candidate,
                        code == PULSE_EXT_OK ? PULSE_EXT_ERR_FAULT : code,
                        WDC_EXTENSION_FAULT_HEALTH);
        }
        return WDC_EXTENSION_ERR_HEALTH;
    }
    memcpy(&candidate->observed_health, out_health, sizeof(*out_health));
    candidate->observed_health_valid = 1u;
    if (out_health->state == PULSE_EXT_HEALTH_FAULTED) {
        latch_reset(candidate, out_health->fault_status, WDC_EXTENSION_FAULT_HEALTH);
        return WDC_EXTENSION_ERR_HEALTH;
    }
    return WDC_EXTENSION_OK;
}

static int quiesce_request_shape_valid(const pulse_extension_quiesce_v1 *request)
{
    return request != NULL && request->struct_size == sizeof(*request) &&
           request->flags == 0u &&
           bytes_zero(request->reserved, sizeof(request->reserved));
}

static int quiesce_deadline_valid(const pulse_extension_quiesce_v1 *request)
{
    uint64_t deadline = parts_to_u64(request->deadline_ms);
    return deadline != 0u && wdc_extension_platform_monotonic_ms() < deadline;
}

static int32_t quiesce_candidate(WdcExtensionCandidate *candidate,
                                 const pulse_extension_quiesce_v1 *request)
{
    pulse_extension_health_v1 health;
    uint32_t preserve_reset;
    int32_t code;
    if (candidate == NULL || candidate->descriptor == NULL ||
        candidate->start_entered == 0u ||
        (candidate->state != WDC_EXTENSION_STARTING &&
         candidate->state != WDC_EXTENSION_STARTED &&
         candidate->state != WDC_EXTENSION_QUIESCING &&
         candidate->state != WDC_EXTENSION_RESET_REQUIRED)) {
        return WDC_EXTENSION_ERR_STATE;
    }
    if (!quiesce_request_shape_valid(request)) {
        return WDC_EXTENSION_ERR_STATE;
    }
    if (!quiesce_deadline_valid(request)) {
        latch_reset(candidate, PULSE_EXT_ERR_TIMEOUT, WDC_EXTENSION_FAULT_QUIESCE);
        return WDC_EXTENSION_ERR_TIMEOUT;
    }
    preserve_reset = candidate->reset_required;
    wdc_extension_services_cancel_candidate_effects(candidate);
    candidate->state = WDC_EXTENSION_QUIESCING;
    code = candidate->descriptor->quiesce_fn(request);
    if (WDC_EXTENSION_TEST_SHOULD_FAIL(
            WDC_EXTENSION_TEST_FAULT_QUIESCE_RETURN)) {
        code = PULSE_EXT_ERR_FAULT;
    }
    candidate->last_extension_status = code;
    if (code != PULSE_EXT_OK) {
        latch_reset(candidate, code, WDC_EXTENSION_FAULT_QUIESCE);
        return code == PULSE_EXT_ERR_TIMEOUT ? WDC_EXTENSION_ERR_TIMEOUT :
                                               WDC_EXTENSION_ERR_RESET_REQUIRED;
    }
    memset(&health, 0, sizeof(health));
    health.struct_size = sizeof(health);
    code = candidate->descriptor->health_fn(&health);
    if (WDC_EXTENSION_TEST_SHOULD_FAIL(
            WDC_EXTENSION_TEST_FAULT_QUIESCE_HEALTH_RETURN)) {
        code = PULSE_EXT_ERR_FAULT;
    }
    candidate->last_extension_status = code;
    if (code != PULSE_EXT_OK || !health_record_valid(candidate, &health) ||
        health.state != PULSE_EXT_HEALTH_QUIESCED ||
        health.pending_count != 0u) {
        latch_reset(candidate,
                    code == PULSE_EXT_OK ? PULSE_EXT_ERR_FAULT : code,
                    WDC_EXTENSION_FAULT_QUIESCE);
        return WDC_EXTENSION_ERR_RESET_REQUIRED;
    }
    memcpy(&candidate->observed_health, &health, sizeof(health));
    candidate->observed_health_valid = 1u;
    if (preserve_reset != 0u) {
        candidate->reset_required = 1u;
        candidate->state = WDC_EXTENSION_RESET_REQUIRED;
        mark_registry_reset(candidate);
        return WDC_EXTENSION_ERR_RESET_REQUIRED;
    }
    candidate->state = WDC_EXTENSION_QUIESCED;
    return WDC_EXTENSION_OK;
}

static pulse_extension_quiesce_v1 failure_quiesce_request(void)
{
    pulse_extension_quiesce_v1 request;
    uint64_t now = wdc_extension_platform_monotonic_ms();
    memset(&request, 0, sizeof(request));
    request.struct_size = sizeof(request);
    request.reason = WDC_EXTENSION_FAULT_START;
    request.deadline_ms = parts_from_u64(now + WDC_EXTENSION_FAILURE_QUIESCE_MS);
    return request;
}

static int32_t unwind_after_start(WdcExtensionRegistry *registry)
{
    pulse_extension_quiesce_v1 request = failure_quiesce_request();
    int32_t first_error = WDC_EXTENSION_OK;
    uint32_t index = registry->count;
    while (index != 0u) {
        WdcExtensionCandidate *candidate = registry->candidates[--index];
        int32_t code;
        if (candidate == NULL || candidate->start_entered == 0u ||
            candidate->state == WDC_EXTENSION_QUIESCED) {
            continue;
        }
        code = quiesce_candidate(candidate, &request);
        if (code != WDC_EXTENSION_OK && first_error == WDC_EXTENSION_OK) {
            first_error = code;
        }
    }
    if (deinitialize_reverse(registry) != WDC_EXTENSION_OK &&
        first_error == WDC_EXTENSION_OK) {
        first_error = WDC_EXTENSION_ERR_RESET_REQUIRED;
    }
    refresh_counts(registry);
    return first_error;
}

int32_t wdc_extension_registry_start(WdcExtensionRegistry *registry)
{
    uint32_t index;
    if (registry == NULL || registry->sealed == 0u || registry->count == 0u ||
        registry->lifecycle_failed != 0u || registry->reset_required != 0u) {
        return WDC_EXTENSION_ERR_STATE;
    }
    for (index = 0u; index < registry->count; ++index) {
        if (registry->candidates[index] == NULL ||
            registry->candidates[index]->state != WDC_EXTENSION_INITIALIZED) {
            return WDC_EXTENSION_ERR_STATE;
        }
    }
    for (index = 0u; index < registry->count; ++index) {
        WdcExtensionCandidate *candidate = registry->candidates[index];
        pulse_extension_health_v1 health;
        int32_t code;
        candidate->state = WDC_EXTENSION_STARTING;
        candidate->start_entered = 1u;
        code = candidate->descriptor->start_fn();
        if (WDC_EXTENSION_TEST_SHOULD_FAIL(
                WDC_EXTENSION_TEST_FAULT_START_RETURN)) {
            code = PULSE_EXT_ERR_FAULT;
        }
        candidate->last_extension_status = code;
        if (code != PULSE_EXT_OK || candidate->reset_required != 0u) {
            registry->lifecycle_failed = 1u;
            code = unwind_after_start(registry);
            return code == WDC_EXTENSION_OK ? WDC_EXTENSION_ERR_LIFECYCLE : code;
        }
        candidate->state = WDC_EXTENSION_STARTED;
        refresh_counts(registry);
        code = wdc_extension_candidate_health(candidate, &health);
        if (code != WDC_EXTENSION_OK) {
            registry->lifecycle_failed = 1u;
            code = unwind_after_start(registry);
            return code == WDC_EXTENSION_OK ? WDC_EXTENSION_ERR_HEALTH : code;
        }
    }
    return WDC_EXTENSION_OK;
}

int32_t wdc_extension_candidate_invoke(
    WdcExtensionCandidate *candidate,
    const pulse_extension_invoke_v1 *request)
{
    int32_t code;
    uint64_t correlation;
    uint64_t deadline;
    if (candidate == NULL || request == NULL || candidate->descriptor == NULL ||
        candidate->state != WDC_EXTENSION_STARTED) {
        return WDC_EXTENSION_ERR_STATE;
    }
    correlation = parts_to_u64(request->correlation_id);
    deadline = parts_to_u64(request->deadline_ms);
    if (request->struct_size != sizeof(*request) || request->flags != 0u ||
        !bytes_zero(request->reserved, sizeof(request->reserved)) ||
        !operation_admitted(candidate, request->operation_id) || correlation == 0u ||
        deadline == 0u ||
        ((request->payload_len == 0u) != (request->payload_ptr == NULL)) ||
        request->payload_len > candidate->inspection.metadata.max_effect_request_bytes) {
        return WDC_EXTENSION_ERR_ARGUMENT;
    }
    if (deadline <= wdc_extension_platform_monotonic_ms()) {
        return WDC_EXTENSION_ERR_TIMEOUT;
    }
    code = candidate->descriptor->invoke_fn(request);
    if (WDC_EXTENSION_TEST_SHOULD_FAIL(
            WDC_EXTENSION_TEST_FAULT_INVOKE_RETURN)) {
        code = PULSE_EXT_ERR_FAULT;
    }
    candidate->last_extension_status = code;
    if (code == PULSE_EXT_ERR_FAULT) {
        latch_reset(candidate, code, WDC_EXTENSION_FAULT_HOST_SERVICE);
        return WDC_EXTENSION_ERR_RESET_REQUIRED;
    }
    return code == PULSE_EXT_OK ? WDC_EXTENSION_OK : WDC_EXTENSION_ERR_LIFECYCLE;
}

int32_t wdc_extension_registry_quiesce(
    WdcExtensionRegistry *registry,
    const pulse_extension_quiesce_v1 *request)
{
    int32_t first_error = WDC_EXTENSION_OK;
    uint32_t index;
    if (registry == NULL || registry->sealed == 0u || registry->count == 0u ||
        !quiesce_request_shape_valid(request)) {
        return WDC_EXTENSION_ERR_STATE;
    }
    index = registry->count;
    while (index != 0u) {
        WdcExtensionCandidate *candidate = registry->candidates[--index];
        int32_t code;
        if (candidate == NULL || candidate->state != WDC_EXTENSION_STARTED) {
            if (first_error == WDC_EXTENSION_OK) {
                first_error = WDC_EXTENSION_ERR_STATE;
            }
            continue;
        }
        code = quiesce_candidate(candidate, request);
        if (code != WDC_EXTENSION_OK && first_error == WDC_EXTENSION_OK) {
            first_error = code;
        }
    }
    refresh_counts(registry);
    return first_error;
}

int32_t wdc_extension_registry_deinitialize(WdcExtensionRegistry *registry)
{
    int32_t code;
    uint32_t actionable = 0u;
    uint32_t index;
    if (registry == NULL || registry->sealed == 0u || registry->count == 0u ||
        registry->reset_required != 0u) {
        return registry != NULL && registry->reset_required != 0u ?
                   WDC_EXTENSION_ERR_RESET_REQUIRED : WDC_EXTENSION_ERR_STATE;
    }
    for (index = 0u; index < registry->count; ++index) {
        WdcExtensionCandidate *candidate = registry->candidates[index];
        if (candidate != NULL &&
            (candidate->state == WDC_EXTENSION_INITIALIZING ||
             candidate->state == WDC_EXTENSION_INITIALIZED ||
             candidate->state == WDC_EXTENSION_QUIESCED)) {
            actionable += 1u;
        }
    }
    if (actionable == 0u) {
        return WDC_EXTENSION_ERR_STATE;
    }
    code = deinitialize_reverse(registry);
    if (code == WDC_EXTENSION_OK) {
        wdc_extension_services_unbind(registry);
    }
    return code;
}

int32_t wdc_extension_registry_unload_clean(WdcExtensionRegistry *registry)
{
    uint32_t index;
    if (registry == NULL || registry->sealed == 0u || registry->reset_required != 0u) {
        return WDC_EXTENSION_ERR_STATE;
    }
    for (index = 0u; index < registry->count; ++index) {
        WdcExtensionCandidate *candidate = registry->candidates[index];
        if (candidate == NULL ||
            (candidate->state != WDC_EXTENSION_DEINITIALIZED &&
             candidate->state != WDC_EXTENSION_REGISTRY_SEALED)) {
            return WDC_EXTENSION_ERR_STATE;
        }
    }
    wdc_extension_services_unbind(registry);
    index = registry->count;
    while (index != 0u) {
        WdcExtensionCandidate *candidate = registry->candidates[--index];
        int32_t unload_code = wdc_elf_unload(&candidate->image);
        if (WDC_EXTENSION_TEST_SHOULD_FAIL(
                WDC_EXTENSION_TEST_FAULT_UNLOAD_RETURN)) {
            unload_code = WDC_ELF_ERR_LOADER;
        }
        if (unload_code != WDC_ELF_OK) {
            registry->lifecycle_failed = 1u;
            registry->reset_required = 1u;
            candidate->last_extension_status = PULSE_EXT_ERR_FAULT;
            if (candidate->fault_code == 0u) {
                candidate->fault_code = WDC_EXTENSION_FAULT_UNLOAD;
            }
            candidate->reset_required = 1u;
            candidate->state = WDC_EXTENSION_RESET_REQUIRED;
            refresh_counts(registry);
            return WDC_EXTENSION_ERR_RESET_REQUIRED;
        }
        memset(candidate, 0, sizeof(*candidate));
    }
    memset(registry, 0, sizeof(*registry));
    return WDC_EXTENSION_OK;
}

uint32_t wdc_extension_registry_requires_reset(const WdcExtensionRegistry *registry)
{
    uint32_t index;
    if (registry == NULL) {
        return 0u;
    }
    if (registry->reset_required != 0u) {
        return 1u;
    }
    for (index = 0u; index < registry->count; ++index) {
        if (registry->candidates[index] != NULL &&
            registry->candidates[index]->reset_required != 0u) {
            return 1u;
        }
    }
    return 0u;
}
