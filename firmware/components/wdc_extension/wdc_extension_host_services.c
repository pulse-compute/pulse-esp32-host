#include "pulse_extension.h"

#include <stdint.h>
#include <string.h>

#include "wdc_extension_internal.h"
#include "wdc_events.h"

#ifdef ESP_PLATFORM
#include "freertos/FreeRTOS.h"
#include "freertos/portmacro.h"
#endif

typedef enum WdcEffectSlotState {
    WDC_EFFECT_SLOT_EMPTY = 0,
    WDC_EFFECT_SLOT_ACTIVE = 1,
    WDC_EFFECT_SLOT_COMPLETED = 2,
    WDC_EFFECT_SLOT_TIMED_OUT = 3,
    WDC_EFFECT_SLOT_CANCELED = 4,
} WdcEffectSlotState;

typedef struct WdcEffectSlot {
    WdcEffectSlotState state;
    WdcExtensionCandidate *candidate;
    uint64_t correlation_id;
    uint64_t deadline_ms;
    uint64_t started_ms;
    uint64_t completed_ms;
    int32_t completion_status;
    uint32_t payload_len;
    uint8_t payload[WDC_EXTENSION_EFFECT_PAYLOAD_MAX];
    uint64_t last_correlation_id;
    WdcEffectSlotState last_terminal_state;
} WdcEffectSlot;

static WdcExtensionRegistry *s_service_registry;
static WdcEffectSlot s_effect_slot;
#ifdef ESP_PLATFORM
static portMUX_TYPE s_effect_lock = portMUX_INITIALIZER_UNLOCKED;
#define EFFECT_LOCK() portENTER_CRITICAL(&s_effect_lock)
#define EFFECT_UNLOCK() portEXIT_CRITICAL(&s_effect_lock)
#else
#define EFFECT_LOCK() ((void)0)
#define EFFECT_UNLOCK() ((void)0)
#endif

#ifdef PULSE_EXTENSION_HOST_TEST
static WdcExtensionCandidate *s_test_caller;
#endif

static int range_contains(uint32_t start, uint32_t size, const void *pointer, uint32_t required)
{
    uint32_t address = (uint32_t)(uintptr_t)pointer;
    return required <= size && address >= start && address - start <= size - required;
}

static WdcExtensionCandidate *candidate_for_caller(uint32_t caller)
{
    uint32_t index;
#ifdef PULSE_EXTENSION_HOST_TEST
    if (s_test_caller != NULL) {
        return s_test_caller;
    }
#endif
    if (s_service_registry == NULL) {
        return NULL;
    }
    for (index = 0u; index < s_service_registry->count; ++index) {
        WdcExtensionCandidate *candidate = s_service_registry->candidates[index];
        if (candidate != NULL &&
            range_contains(candidate->memory.executable_address,
                           candidate->memory.executable_size,
                           (const void *)(uintptr_t)caller,
                           1u)) {
            return candidate;
        }
    }
    return NULL;
}

static int readable_bytes(const WdcExtensionCandidate *candidate,
                          const void *bytes,
                          uint32_t size)
{
    if (size == 0u) {
        return bytes == NULL;
    }
#ifdef PULSE_EXTENSION_HOST_TEST
    if (candidate != NULL && bytes != NULL) {
        return 1;
    }
#endif
    return candidate != NULL && bytes != NULL &&
           (range_contains(candidate->memory.executable_address,
                           candidate->memory.executable_size,
                           bytes,
                           size) ||
            range_contains(candidate->memory.writable_address,
                           candidate->memory.writable_size,
                           bytes,
                           size));
}

static int writable_record(const WdcExtensionCandidate *candidate,
                           const void *record,
                           uint32_t size)
{
#ifdef PULSE_EXTENSION_HOST_TEST
    if (candidate != NULL && record != NULL) {
        return 1;
    }
#endif
    return candidate != NULL && record != NULL &&
           range_contains(candidate->memory.writable_address,
                          candidate->memory.writable_size,
                          record,
                          size);
}

static uint64_t parts_to_u64(pulse_u64_parts_v1 value)
{
    return ((uint64_t)value.hi << 32u) | value.lo;
}

static int event_admitted(const WdcExtensionCandidate *candidate, uint32_t event_id)
{
    uint32_t index;
    if (candidate == NULL || candidate->descriptor == NULL) {
        return 0;
    }
    for (index = 0u; index < candidate->descriptor->event_count; ++index) {
        if (candidate->descriptor->event_ids[index] == event_id) {
            return 1;
        }
    }
    return 0;
}

static int words_zero(const uint32_t *words, uint32_t count)
{
    uint32_t index;
    for (index = 0u; index < count; ++index) {
        if (words[index] != 0u) {
            return 0;
        }
    }
    return 1;
}

int32_t wdc_extension_services_bind(WdcExtensionRegistry *registry)
{
    if (registry == NULL || registry->sealed == 0u || s_service_registry != NULL) {
        return WDC_EXTENSION_ERR_STATE;
    }
    memset(&s_effect_slot, 0, sizeof(s_effect_slot));
    s_service_registry = registry;
    return WDC_EXTENSION_OK;
}

void wdc_extension_services_unbind(WdcExtensionRegistry *registry)
{
    if (s_service_registry == registry) {
        memset(&s_effect_slot, 0, sizeof(s_effect_slot));
        s_service_registry = NULL;
#ifdef PULSE_EXTENSION_HOST_TEST
        s_test_caller = NULL;
#endif
    }
}

#ifdef PULSE_EXTENSION_HOST_TEST
void wdc_extension_services_set_test_caller(WdcExtensionCandidate *candidate)
{
    s_test_caller = candidate;
}
#endif

int32_t wdc_extension_services_begin_effect(
    WdcExtensionCandidate *candidate,
    uint64_t correlation_id,
    uint64_t deadline_ms)
{
    uint64_t now = wdc_extension_platform_monotonic_ms();
    int32_t result = WDC_EXTENSION_OK;
    if (candidate == NULL || candidate->state != WDC_EXTENSION_STARTED ||
        correlation_id == 0u || deadline_ms == 0u || now >= deadline_ms) {
        return WDC_EXTENSION_ERR_ARGUMENT;
    }
    EFFECT_LOCK();
    if (s_effect_slot.state != WDC_EFFECT_SLOT_EMPTY) {
        result = WDC_EXTENSION_ERR_BUDGET;
    } else if (s_effect_slot.last_correlation_id == correlation_id) {
        result = WDC_EXTENSION_ERR_DUPLICATE;
    } else {
        s_effect_slot.state = WDC_EFFECT_SLOT_ACTIVE;
        s_effect_slot.candidate = candidate;
        s_effect_slot.correlation_id = correlation_id;
        s_effect_slot.deadline_ms = deadline_ms;
        s_effect_slot.started_ms = now;
        s_effect_slot.completed_ms = 0u;
        s_effect_slot.completion_status = PULSE_EXT_ERR_STATE;
        s_effect_slot.payload_len = 0u;
    }
    EFFECT_UNLOCK();
    return result;
}

int32_t wdc_extension_services_take_effect(
    WdcExtensionCandidate *candidate,
    uint64_t correlation_id,
    WdcExtensionCompletionResult *out_result)
{
    int32_t result = WDC_EXTENSION_ERR_STATE;
    if (candidate == NULL || correlation_id == 0u || out_result == NULL) {
        return WDC_EXTENSION_ERR_ARGUMENT;
    }
    EFFECT_LOCK();
    if (s_effect_slot.candidate != candidate ||
        s_effect_slot.correlation_id != correlation_id) {
        result = WDC_EXTENSION_ERR_STATE;
    } else if (s_effect_slot.state == WDC_EFFECT_SLOT_ACTIVE) {
        result = WDC_EXTENSION_ERR_NOT_READY;
    } else if (s_effect_slot.state == WDC_EFFECT_SLOT_COMPLETED) {
        memset(out_result, 0, sizeof(*out_result));
        out_result->status = s_effect_slot.completion_status;
        out_result->correlation_id = correlation_id;
        out_result->started_ms = s_effect_slot.started_ms;
        out_result->completed_ms = s_effect_slot.completed_ms;
        out_result->payload_len = s_effect_slot.payload_len;
        if (out_result->payload_len != 0u) {
            memcpy(out_result->payload,
                   s_effect_slot.payload,
                   out_result->payload_len);
        }
        result = WDC_EXTENSION_OK;
    } else if (s_effect_slot.state == WDC_EFFECT_SLOT_TIMED_OUT) {
        result = WDC_EXTENSION_ERR_TIMEOUT;
    } else {
        result = WDC_EXTENSION_ERR_STATE;
    }
    EFFECT_UNLOCK();
    return result;
}

int32_t wdc_extension_services_timeout_effect(
    WdcExtensionCandidate *candidate,
    uint64_t correlation_id)
{
    int32_t result = WDC_EXTENSION_ERR_STATE;
    EFFECT_LOCK();
    if (candidate != NULL && s_effect_slot.candidate == candidate &&
        s_effect_slot.correlation_id == correlation_id &&
        s_effect_slot.state == WDC_EFFECT_SLOT_ACTIVE) {
        s_effect_slot.state = WDC_EFFECT_SLOT_TIMED_OUT;
        result = WDC_EXTENSION_OK;
    }
    EFFECT_UNLOCK();
    return result;
}

int32_t wdc_extension_services_release_effect(
    WdcExtensionCandidate *candidate,
    uint64_t correlation_id)
{
    int32_t result = WDC_EXTENSION_ERR_STATE;
    EFFECT_LOCK();
    if (candidate != NULL && s_effect_slot.candidate == candidate &&
        s_effect_slot.correlation_id == correlation_id &&
        s_effect_slot.state != WDC_EFFECT_SLOT_ACTIVE &&
        s_effect_slot.state != WDC_EFFECT_SLOT_EMPTY) {
        s_effect_slot.last_correlation_id = correlation_id;
        s_effect_slot.last_terminal_state = s_effect_slot.state;
        s_effect_slot.state = WDC_EFFECT_SLOT_EMPTY;
        s_effect_slot.candidate = NULL;
        s_effect_slot.correlation_id = 0u;
        s_effect_slot.deadline_ms = 0u;
        s_effect_slot.started_ms = 0u;
        s_effect_slot.completed_ms = 0u;
        s_effect_slot.completion_status = PULSE_EXT_ERR_STATE;
        s_effect_slot.payload_len = 0u;
        result = WDC_EXTENSION_OK;
    }
    EFFECT_UNLOCK();
    return result;
}

void wdc_extension_services_cancel_candidate_effects(
    WdcExtensionCandidate *candidate)
{
    EFFECT_LOCK();
    if (candidate != NULL && s_effect_slot.candidate == candidate &&
        s_effect_slot.state == WDC_EFFECT_SLOT_ACTIVE) {
        s_effect_slot.state = WDC_EFFECT_SLOT_CANCELED;
    }
    EFFECT_UNLOCK();
}

WdcExtensionRegistry *wdc_extension_services_registry(void)
{
    return s_service_registry;
}

int32_t pulse_host_monotonic_ms_v1(pulse_u64_parts_v1 *out_time)
{
    uint32_t caller = (uint32_t)(uintptr_t)__builtin_return_address(0);
    WdcExtensionCandidate *candidate = candidate_for_caller(caller);
    uint64_t now;
    if (!writable_record(candidate, out_time, sizeof(*out_time))) {
        return PULSE_EXT_ERR_ARGUMENT;
    }
    now = wdc_extension_platform_monotonic_ms();
    out_time->lo = (uint32_t)now;
    out_time->hi = (uint32_t)(now >> 32u);
    return PULSE_EXT_OK;
}

int32_t pulse_host_report_health_v1(const pulse_extension_health_v1 *health)
{
    uint32_t caller = (uint32_t)(uintptr_t)__builtin_return_address(0);
    WdcExtensionCandidate *candidate = candidate_for_caller(caller);
    if (!writable_record(candidate, health, sizeof(*health))) {
        return PULSE_EXT_ERR_ARGUMENT;
    }
    return wdc_extension_record_service_health(candidate, health);
}

int32_t pulse_host_report_fault_v1(const pulse_extension_fault_v1 *fault)
{
    uint32_t caller = (uint32_t)(uintptr_t)__builtin_return_address(0);
    WdcExtensionCandidate *candidate = candidate_for_caller(caller);
    if (!writable_record(candidate, fault, sizeof(*fault)) ||
        fault->struct_size != sizeof(*fault) || fault->status == PULSE_EXT_OK ||
        fault->fault_code == 0u || fault->flags != 0u ||
        !words_zero(fault->reserved, 2u)) {
        return PULSE_EXT_ERR_ARGUMENT;
    }
    wdc_extension_record_service_fault(candidate, fault->status, fault->fault_code);
    return PULSE_EXT_OK;
}

int32_t pulse_host_emit_event_v1(const pulse_extension_event_v1 *event)
{
    uint32_t caller = (uint32_t)(uintptr_t)__builtin_return_address(0);
    WdcExtensionCandidate *candidate = candidate_for_caller(caller);
    WdcEvent queued;
    int32_t status;
    if (!writable_record(candidate, event, sizeof(*event)) ||
        event->struct_size != sizeof(*event) || event->flags != 0u ||
        !words_zero(event->reserved, 3u) || !event_admitted(candidate, event->event_id) ||
        (candidate->state != WDC_EXTENSION_STARTING &&
         candidate->state != WDC_EXTENSION_STARTED) ||
        event->payload_len > candidate->inspection.metadata.max_event_payload_bytes ||
        !readable_bytes(candidate, event->payload_ptr, event->payload_len)) {
        return event != NULL && candidate != NULL &&
                       event->payload_len > candidate->inspection.metadata.max_event_payload_bytes ?
                   PULSE_EXT_ERR_BOUNDS : PULSE_EXT_ERR_ARGUMENT;
    }
    status = wdc_event_make(&queued,
                            event->event_id,
                            WDC_EVENT_RESOURCE_NONE,
                            wdc_extension_platform_monotonic_ms(),
                            event->payload_ptr,
                            (uint16_t)event->payload_len);
    if (status != WDC_OK) {
        return status == WDC_ERR_BAD_LENGTH ? PULSE_EXT_ERR_BOUNDS :
                                              PULSE_EXT_ERR_ARGUMENT;
    }
    queued.causation_id = parts_to_u64(event->causation_id);
    status = wdc_events_post(&queued);
    if (status == WDC_ERR_BUSY) {
        return PULSE_EXT_ERR_BUSY;
    }
    return status == WDC_OK ? PULSE_EXT_OK : PULSE_EXT_ERR_FAULT;
}

int32_t pulse_host_complete_effect_v1(const pulse_extension_completion_v1 *completion)
{
    uint32_t caller = (uint32_t)(uintptr_t)__builtin_return_address(0);
    WdcExtensionCandidate *candidate = candidate_for_caller(caller);
    uint64_t correlation;
    uint64_t now;
    int32_t result = PULSE_EXT_ERR_STALE;
    if (!writable_record(candidate, completion, sizeof(*completion)) ||
        completion->struct_size != sizeof(*completion) || completion->flags != 0u ||
        !words_zero(completion->reserved, 3u) ||
        completion->payload_len > candidate->inspection.metadata.max_effect_completion_bytes ||
        completion->payload_len > WDC_EXTENSION_EFFECT_PAYLOAD_MAX ||
        !readable_bytes(candidate, completion->payload_ptr, completion->payload_len)) {
        return completion != NULL && candidate != NULL &&
                       completion->payload_len >
                           candidate->inspection.metadata.max_effect_completion_bytes ?
                   PULSE_EXT_ERR_BOUNDS : PULSE_EXT_ERR_ARGUMENT;
    }
    correlation = parts_to_u64(completion->correlation_id);
    now = wdc_extension_platform_monotonic_ms();
    EFFECT_LOCK();
    if (s_effect_slot.candidate == candidate &&
        s_effect_slot.correlation_id == correlation) {
        if (s_effect_slot.state == WDC_EFFECT_SLOT_COMPLETED) {
            result = PULSE_EXT_ERR_DUPLICATE;
        } else if (s_effect_slot.state != WDC_EFFECT_SLOT_ACTIVE ||
                   candidate->state != WDC_EXTENSION_STARTED ||
                   now >= s_effect_slot.deadline_ms) {
            if (s_effect_slot.state == WDC_EFFECT_SLOT_ACTIVE) {
                s_effect_slot.state = WDC_EFFECT_SLOT_TIMED_OUT;
            }
            result = PULSE_EXT_ERR_STALE;
        } else {
            s_effect_slot.completion_status = completion->status;
            s_effect_slot.completed_ms = now;
            s_effect_slot.payload_len = completion->payload_len;
            if (completion->payload_len != 0u) {
                memcpy(s_effect_slot.payload,
                       completion->payload_ptr,
                       completion->payload_len);
            }
            s_effect_slot.state = WDC_EFFECT_SLOT_COMPLETED;
            result = PULSE_EXT_OK;
        }
    } else if (s_effect_slot.last_correlation_id == correlation &&
               s_effect_slot.last_terminal_state == WDC_EFFECT_SLOT_COMPLETED) {
        result = PULSE_EXT_ERR_DUPLICATE;
    }
    EFFECT_UNLOCK();
    return result;
}

int32_t pulse_host_log_v1(const pulse_extension_log_v1 *record)
{
    (void)record;
    return PULSE_EXT_ERR_UNSUPPORTED;
}
