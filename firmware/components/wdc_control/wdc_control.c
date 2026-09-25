#include "wdc_control.h"

#include <limits.h>
#include <stddef.h>
#include <string.h>

#ifdef ESP_PLATFORM
#include "esp_attr.h"
#define WDC_CONTROL_ISR_ATTR IRAM_ATTR
#else
#define WDC_CONTROL_ISR_ATTR
#endif

#define WDC_CONTROL_TICKET_SLOT_MASK 0x0fu
#define WDC_CONTROL_TICKET_CLASS_SHIFT 4u
#define WDC_CONTROL_TICKET_CLASS_MASK 0x0fu
#define WDC_CONTROL_TICKET_GENERATION_SHIFT 8u
#define WDC_CONTROL_TICKET_GENERATION_MASK 0x00ffffffu

_Static_assert(sizeof(WdcControlKernel) <= WDC_CONTROL_KERNEL_STATIC_BUDGET_BYTES,
               "HP1 control kernel exceeds its fixed static reserve");
_Static_assert(WDC_CONTROL_QUEUE_CAPACITY_MAX <= 16u,
               "HP1 ticket encoding reserves four slot bits");

static const WdcControlResourceProfile s_c6_profile = {
    .profile_id = "esp32c6-no-psram-minimum-v1",
    .target = "esp32c6",
    .psram_supported = false,
    .policies = {
        { WDC_CONTROL_PRIORITY_APPLICATION, 5u, 8192u, 16u, WDC_CONTROL_OVERFLOW_TERMINAL_REJECT_NEWEST },
        { WDC_CONTROL_PRIORITY_CAPABILITY, 7u, 4096u, 16u, WDC_CONTROL_OVERFLOW_TERMINAL_REJECT_NEWEST },
        { WDC_CONTROL_PRIORITY_NETWORK, 9u, 6144u, 8u, WDC_CONTROL_OVERFLOW_TERMINAL_REJECT_NEWEST },
        { WDC_CONTROL_PRIORITY_ADMINISTRATION, 11u, 6144u, 8u, WDC_CONTROL_OVERFLOW_TERMINAL_REJECT_NEWEST },
        { WDC_CONTROL_PRIORITY_SAFETY_RECOVERY, 13u, 4096u, 8u, WDC_CONTROL_OVERFLOW_LATCH_RECOVERY_REJECT_NEWEST },
    },
    .reserve = {
        .kernel_static_bytes = 8192u,
        .control_metadata_bytes = 8192u,
        .administration_bytes = 12288u,
        .verification_bytes = 24576u,
        .recovery_bytes = 16384u,
        .fixed_control_reserve_bytes = 98304u,
        .exclusive_update_working_bytes = 65536u,
        .update_largest_allocation_bytes = 65536u,
        .largest_block_floor_bytes = 32768u,
        .maximum_application_internal_bytes = 131072u,
        .maximum_transition_scratch_bytes = 16384u,
        .maximum_application_psram_bytes = 0u,
        .psram_floor_bytes = 0u,
    },
};

static const WdcControlResourceProfile s_s3_profile = {
    .profile_id = "esp32s3-psram-optimization-v1",
    .target = "esp32s3",
    .psram_supported = true,
    .policies = {
        { WDC_CONTROL_PRIORITY_APPLICATION, 5u, 8192u, 16u, WDC_CONTROL_OVERFLOW_TERMINAL_REJECT_NEWEST },
        { WDC_CONTROL_PRIORITY_CAPABILITY, 7u, 4096u, 16u, WDC_CONTROL_OVERFLOW_TERMINAL_REJECT_NEWEST },
        { WDC_CONTROL_PRIORITY_NETWORK, 9u, 6144u, 8u, WDC_CONTROL_OVERFLOW_TERMINAL_REJECT_NEWEST },
        { WDC_CONTROL_PRIORITY_ADMINISTRATION, 11u, 6144u, 8u, WDC_CONTROL_OVERFLOW_TERMINAL_REJECT_NEWEST },
        { WDC_CONTROL_PRIORITY_SAFETY_RECOVERY, 13u, 4096u, 8u, WDC_CONTROL_OVERFLOW_LATCH_RECOVERY_REJECT_NEWEST },
    },
    .reserve = {
        .kernel_static_bytes = 8192u,
        .control_metadata_bytes = 8192u,
        .administration_bytes = 12288u,
        .verification_bytes = 24576u,
        .recovery_bytes = 16384u,
        .fixed_control_reserve_bytes = 98304u,
        .exclusive_update_working_bytes = 65536u,
        .update_largest_allocation_bytes = 65536u,
        .largest_block_floor_bytes = 32768u,
        .maximum_application_internal_bytes = 131072u,
        .maximum_transition_scratch_bytes = 16384u,
        .maximum_application_psram_bytes = 1048576u,
        .psram_floor_bytes = 131072u,
    },
};

static int checked_add(uint32_t left, uint32_t right, uint32_t *out)
{
    if (out == NULL || left > UINT32_MAX - right) {
        return 0;
    }
    *out = left + right;
    return 1;
}

static uint32_t maximum(uint32_t left, uint32_t right)
{
    return left > right ? left : right;
}

static const WdcControlTaskPolicy *policy_for_class(
    const WdcControlResourceProfile *profile,
    WdcControlPriorityClass priority_class)
{
    uint32_t index;
    if (profile == NULL || priority_class < WDC_CONTROL_PRIORITY_APPLICATION ||
        priority_class > WDC_CONTROL_PRIORITY_SAFETY_RECOVERY) {
        return NULL;
    }
    for (index = 0u; index < WDC_CONTROL_PRIORITY_CLASS_COUNT; ++index) {
        if (profile->policies[index].priority_class == priority_class) {
            return &profile->policies[index];
        }
    }
    return NULL;
}

static WdcControlLane *lane_for_class(WdcControlKernel *kernel,
                                      WdcControlPriorityClass priority_class)
{
    if (kernel == NULL || priority_class < WDC_CONTROL_PRIORITY_APPLICATION ||
        priority_class > WDC_CONTROL_PRIORITY_SAFETY_RECOVERY) {
        return NULL;
    }
    return &kernel->lanes[(uint32_t)priority_class - 1u];
}

static const WdcControlLane *const_lane_for_class(
    const WdcControlKernel *kernel,
    WdcControlPriorityClass priority_class)
{
    if (kernel == NULL || priority_class < WDC_CONTROL_PRIORITY_APPLICATION ||
        priority_class > WDC_CONTROL_PRIORITY_SAFETY_RECOVERY) {
        return NULL;
    }
    return &kernel->lanes[(uint32_t)priority_class - 1u];
}

static uint32_t task_stack_bytes(const WdcControlResourceProfile *profile)
{
    uint32_t total = 0u;
    uint32_t index;
    if (profile == NULL) {
        return 0u;
    }
    for (index = 0u; index < WDC_CONTROL_PRIORITY_CLASS_COUNT; ++index) {
        if (!checked_add(total, profile->policies[index].stack_bytes, &total)) {
            return 0u;
        }
    }
    return total;
}

const WdcControlResourceProfile *wdc_control_profile_c6_minimum(void)
{
    return &s_c6_profile;
}

const WdcControlResourceProfile *wdc_control_profile_s3_psram(void)
{
    return &s_s3_profile;
}

uint32_t wdc_control_fixed_reserve_bytes(const WdcControlResourceProfile *profile)
{
    uint32_t total;
    if (profile == NULL) {
        return 0u;
    }
    total = task_stack_bytes(profile);
    if (total == 0u ||
        !checked_add(total, profile->reserve.kernel_static_bytes, &total) ||
        !checked_add(total, profile->reserve.control_metadata_bytes, &total) ||
        !checked_add(total, profile->reserve.administration_bytes, &total) ||
        !checked_add(total, profile->reserve.verification_bytes, &total) ||
        !checked_add(total, profile->reserve.recovery_bytes, &total)) {
        return 0u;
    }
    return total;
}

int32_t wdc_control_validate_profile(const WdcControlResourceProfile *profile)
{
    uint32_t index;
    uint32_t previous_priority = 0u;
    if (profile == NULL || profile->profile_id == NULL || profile->target == NULL ||
        profile->profile_id[0] == '\0' || profile->target[0] == '\0') {
        return WDC_ERR_BAD_POINTER;
    }
    for (index = 0u; index < WDC_CONTROL_PRIORITY_CLASS_COUNT; ++index) {
        const WdcControlTaskPolicy *policy = &profile->policies[index];
        if (policy->priority_class != (WdcControlPriorityClass)(index + 1u) ||
            policy->freertos_priority <= previous_priority ||
            policy->stack_bytes == 0u ||
            policy->queue_capacity == 0u ||
            policy->queue_capacity > WDC_CONTROL_QUEUE_CAPACITY_MAX ||
            policy->overflow_policy == WDC_CONTROL_OVERFLOW_NONE) {
            return WDC_ERR_BAD_ENCODING;
        }
        if (policy->priority_class == WDC_CONTROL_PRIORITY_SAFETY_RECOVERY) {
            if (policy->overflow_policy !=
                WDC_CONTROL_OVERFLOW_LATCH_RECOVERY_REJECT_NEWEST) {
                return WDC_ERR_BAD_ENCODING;
            }
        } else if (policy->overflow_policy !=
                   WDC_CONTROL_OVERFLOW_TERMINAL_REJECT_NEWEST) {
            return WDC_ERR_BAD_ENCODING;
        }
        previous_priority = policy->freertos_priority;
    }
    if (profile->reserve.kernel_static_bytes < sizeof(WdcControlKernel) ||
        profile->reserve.fixed_control_reserve_bytes == 0u ||
        wdc_control_fixed_reserve_bytes(profile) !=
            profile->reserve.fixed_control_reserve_bytes ||
        profile->reserve.exclusive_update_working_bytes == 0u ||
        profile->reserve.update_largest_allocation_bytes == 0u ||
        profile->reserve.update_largest_allocation_bytes >
            profile->reserve.exclusive_update_working_bytes ||
        profile->reserve.largest_block_floor_bytes == 0u ||
        profile->reserve.maximum_application_internal_bytes == 0u ||
        profile->reserve.maximum_transition_scratch_bytes == 0u) {
        return WDC_ERR_BAD_ENCODING;
    }
    if ((!profile->psram_supported &&
         (profile->reserve.maximum_application_psram_bytes != 0u ||
          profile->reserve.psram_floor_bytes != 0u)) ||
        (profile->psram_supported &&
         (profile->reserve.maximum_application_psram_bytes == 0u ||
          profile->reserve.psram_floor_bytes == 0u))) {
        return WDC_ERR_BAD_ENCODING;
    }
    return WDC_OK;
}

WdcControlPriorityClass wdc_control_priority_class_for_source(WdcControlSource source)
{
    switch (source) {
    case WDC_CONTROL_SOURCE_SAFETY:
    case WDC_CONTROL_SOURCE_WATCHDOG:
    case WDC_CONTROL_SOURCE_RECOVERY:
        return WDC_CONTROL_PRIORITY_SAFETY_RECOVERY;
    case WDC_CONTROL_SOURCE_ADMINISTRATION:
    case WDC_CONTROL_SOURCE_UPDATE:
        return WDC_CONTROL_PRIORITY_ADMINISTRATION;
    case WDC_CONTROL_SOURCE_NETWORK_MAINTENANCE:
        return WDC_CONTROL_PRIORITY_NETWORK;
    case WDC_CONTROL_SOURCE_CAPABILITY:
        return WDC_CONTROL_PRIORITY_CAPABILITY;
    case WDC_CONTROL_SOURCE_APPLICATION:
        return WDC_CONTROL_PRIORITY_APPLICATION;
    default:
        return WDC_CONTROL_PRIORITY_NONE;
    }
}

int32_t wdc_control_task_priority_for_source(const WdcControlResourceProfile *profile,
                                             WdcControlSource source,
                                             uint32_t *out_priority)
{
    WdcControlPriorityClass priority_class;
    const WdcControlTaskPolicy *policy;
    if (out_priority == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    priority_class = wdc_control_priority_class_for_source(source);
    policy = policy_for_class(profile, priority_class);
    if (policy == NULL) {
        return WDC_ERR_INVALID_RESOURCE;
    }
    *out_priority = policy->freertos_priority;
    return WDC_OK;
}

int32_t wdc_control_kernel_init(WdcControlKernel *kernel,
                                const WdcControlResourceProfile *profile)
{
    int32_t status;
    if (kernel == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    status = wdc_control_validate_profile(profile);
    if (status != WDC_OK) {
        return status;
    }
    memset(kernel, 0, sizeof(*kernel));
    kernel->profile = profile;
    return WDC_OK;
}

static uint32_t next_generation(uint32_t generation)
{
    generation = (generation + 1u) & WDC_CONTROL_TICKET_GENERATION_MASK;
    return generation == 0u ? 1u : generation;
}

static uint32_t make_ticket(WdcControlPriorityClass priority_class,
                            uint32_t slot_index,
                            uint32_t generation)
{
    return (generation << WDC_CONTROL_TICKET_GENERATION_SHIFT) |
           ((uint32_t)priority_class << WDC_CONTROL_TICKET_CLASS_SHIFT) |
           slot_index;
}

static int decode_ticket(uint32_t ticket,
                         WdcControlPriorityClass *out_class,
                         uint32_t *out_slot)
{
    uint32_t class_value;
    uint32_t slot;
    if (ticket == 0u || out_class == NULL || out_slot == NULL) {
        return 0;
    }
    class_value = (ticket >> WDC_CONTROL_TICKET_CLASS_SHIFT) &
                  WDC_CONTROL_TICKET_CLASS_MASK;
    slot = ticket & WDC_CONTROL_TICKET_SLOT_MASK;
    if (class_value < WDC_CONTROL_PRIORITY_APPLICATION ||
        class_value > WDC_CONTROL_PRIORITY_SAFETY_RECOVERY ||
        slot >= WDC_CONTROL_QUEUE_CAPACITY_MAX) {
        return 0;
    }
    *out_class = (WdcControlPriorityClass)class_value;
    *out_slot = slot;
    return 1;
}

static void overflow_completion(const WdcControlWorkRequest *request,
                                WdcControlPriorityClass priority_class,
                                WdcControlCompletion *out)
{
    if (out == NULL) {
        return;
    }
    memset(out, 0, sizeof(*out));
    out->priority_class = priority_class;
    out->source = request != NULL ? request->source : WDC_CONTROL_SOURCE_NONE;
    out->correlation_id = request != NULL ? request->correlation_id : 0u;
    out->disposition = WDC_CONTROL_TERMINAL_REJECTED_OVERFLOW;
    out->result = WDC_ERR_BUSY;
}

int32_t wdc_control_submit(WdcControlKernel *kernel,
                           const WdcControlWorkRequest *request,
                           uint32_t *out_ticket,
                           WdcControlCompletion *out_rejection)
{
    WdcControlPriorityClass priority_class;
    const WdcControlTaskPolicy *policy;
    WdcControlLane *lane;
    WdcControlSlot *slot = NULL;
    uint32_t slot_index = 0u;
    uint32_t index;
    uint32_t tail;
    if (kernel == NULL || request == NULL || out_ticket == NULL ||
        out_rejection == NULL || kernel->profile == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    *out_ticket = 0u;
    memset(out_rejection, 0, sizeof(*out_rejection));
    if (request->operation_id == 0u || request->correlation_id == 0u) {
        return WDC_ERR_BAD_ENCODING;
    }
    priority_class = wdc_control_priority_class_for_source(request->source);
    policy = policy_for_class(kernel->profile, priority_class);
    lane = lane_for_class(kernel, priority_class);
    if (policy == NULL || lane == NULL) {
        return WDC_ERR_INVALID_RESOURCE;
    }
    if (lane->count >= policy->queue_capacity) {
        lane->terminal_rejections += 1u;
        if (policy->overflow_policy ==
            WDC_CONTROL_OVERFLOW_LATCH_RECOVERY_REJECT_NEWEST) {
            __atomic_store_n(&kernel->recovery_required, 1u, __ATOMIC_RELEASE);
        }
        overflow_completion(request, priority_class, out_rejection);
        return WDC_ERR_BUSY;
    }
    for (index = 0u; index < policy->queue_capacity; ++index) {
        if (lane->slots[index].state == WDC_CONTROL_SLOT_FREE) {
            slot = &lane->slots[index];
            slot_index = index;
            break;
        }
    }
    if (slot == NULL) {
        lane->terminal_rejections += 1u;
        if (policy->overflow_policy ==
            WDC_CONTROL_OVERFLOW_LATCH_RECOVERY_REJECT_NEWEST) {
            __atomic_store_n(&kernel->recovery_required, 1u, __ATOMIC_RELEASE);
        }
        overflow_completion(request, priority_class, out_rejection);
        return WDC_ERR_BUSY;
    }
    slot->generation = next_generation(slot->generation);
    memset(&slot->item, 0, sizeof(slot->item));
    memset(&slot->completion, 0, sizeof(slot->completion));
    slot->item.ticket = make_ticket(priority_class, slot_index, slot->generation);
    slot->item.priority_class = priority_class;
    slot->item.request = *request;
    slot->state = WDC_CONTROL_SLOT_QUEUED;
    tail = (lane->head + lane->count) % policy->queue_capacity;
    lane->queue[tail] = (uint8_t)slot_index;
    lane->count += 1u;
    lane->accepted += 1u;
    if (lane->count > lane->high_water) {
        lane->high_water = lane->count;
    }
    *out_ticket = slot->item.ticket;
    return WDC_OK;
}

int32_t wdc_control_next(WdcControlKernel *kernel, WdcControlWorkItem *out_item)
{
    int32_t class_value;
    if (kernel == NULL || out_item == NULL || kernel->profile == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    for (class_value = (int32_t)WDC_CONTROL_PRIORITY_SAFETY_RECOVERY;
         class_value >= (int32_t)WDC_CONTROL_PRIORITY_APPLICATION;
         --class_value) {
        WdcControlPriorityClass priority_class =
            (WdcControlPriorityClass)class_value;
        const WdcControlTaskPolicy *policy =
            policy_for_class(kernel->profile, priority_class);
        WdcControlLane *lane = lane_for_class(kernel, priority_class);
        uint32_t slot_index;
        WdcControlSlot *slot;
        if (policy == NULL || lane == NULL || lane->count == 0u) {
            continue;
        }
        slot_index = lane->queue[lane->head];
        lane->head = (lane->head + 1u) % policy->queue_capacity;
        lane->count -= 1u;
        if (slot_index >= policy->queue_capacity) {
            __atomic_store_n(&kernel->recovery_required, 1u, __ATOMIC_RELEASE);
            return WDC_ERR_CONTRACT_VIOLATION;
        }
        slot = &lane->slots[slot_index];
        if (slot->state != WDC_CONTROL_SLOT_QUEUED) {
            __atomic_store_n(&kernel->recovery_required, 1u, __ATOMIC_RELEASE);
            return WDC_ERR_CONTRACT_VIOLATION;
        }
        slot->state = WDC_CONTROL_SLOT_IN_FLIGHT;
        *out_item = slot->item;
        return WDC_OK;
    }
    return WDC_ERR_NOT_AVAILABLE;
}

static WdcControlSlot *slot_for_ticket(WdcControlKernel *kernel,
                                       uint32_t ticket,
                                       WdcControlPriorityClass *out_class)
{
    WdcControlPriorityClass priority_class;
    const WdcControlTaskPolicy *policy;
    WdcControlLane *lane;
    uint32_t slot_index;
    WdcControlSlot *slot;
    if (!decode_ticket(ticket, &priority_class, &slot_index)) {
        return NULL;
    }
    lane = lane_for_class(kernel, priority_class);
    if (lane == NULL || kernel->profile == NULL) {
        return NULL;
    }
    policy = policy_for_class(kernel->profile, priority_class);
    if (policy == NULL || slot_index >= policy->queue_capacity) {
        return NULL;
    }
    slot = &lane->slots[slot_index];
    if (slot->item.ticket != ticket) {
        return NULL;
    }
    if (out_class != NULL) {
        *out_class = priority_class;
    }
    return slot;
}

static int terminal_pair_valid(WdcControlTerminalDisposition disposition,
                               int32_t result)
{
    if (disposition == WDC_CONTROL_TERMINAL_SUCCEEDED) {
        return result == WDC_OK;
    }
    return (disposition == WDC_CONTROL_TERMINAL_FAILED ||
            disposition == WDC_CONTROL_TERMINAL_TIMED_OUT ||
            disposition == WDC_CONTROL_TERMINAL_CANCELLED) &&
           result != WDC_OK;
}

int32_t wdc_control_complete(WdcControlKernel *kernel,
                             uint32_t ticket,
                             WdcControlTerminalDisposition disposition,
                             int32_t result)
{
    WdcControlPriorityClass priority_class;
    WdcControlSlot *slot;
    if (kernel == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    if (!terminal_pair_valid(disposition, result)) {
        return WDC_ERR_BAD_ENCODING;
    }
    slot = slot_for_ticket(kernel, ticket, &priority_class);
    if (slot == NULL) {
        return WDC_ERR_NOT_AVAILABLE;
    }
    if (slot->state != WDC_CONTROL_SLOT_IN_FLIGHT) {
        return WDC_ERR_INVALID_STATE;
    }
    memset(&slot->completion, 0, sizeof(slot->completion));
    slot->completion.ticket = ticket;
    slot->completion.priority_class = priority_class;
    slot->completion.source = slot->item.request.source;
    slot->completion.correlation_id = slot->item.request.correlation_id;
    slot->completion.disposition = disposition;
    slot->completion.result = result;
    slot->state = WDC_CONTROL_SLOT_COMPLETED;
    return WDC_OK;
}

int32_t wdc_control_take_completion(WdcControlKernel *kernel,
                                    uint32_t ticket,
                                    WdcControlCompletion *out_completion)
{
    WdcControlSlot *slot;
    if (kernel == NULL || out_completion == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    slot = slot_for_ticket(kernel, ticket, NULL);
    if (slot == NULL) {
        return WDC_ERR_NOT_AVAILABLE;
    }
    if (slot->state != WDC_CONTROL_SLOT_COMPLETED) {
        return WDC_ERR_INVALID_STATE;
    }
    *out_completion = slot->completion;
    slot->state = WDC_CONTROL_SLOT_FREE;
    slot->item.ticket = 0u;
    memset(&slot->completion, 0, sizeof(slot->completion));
    return WDC_OK;
}

uint32_t wdc_control_lane_pending(const WdcControlKernel *kernel,
                                  WdcControlPriorityClass priority_class)
{
    const WdcControlLane *lane = const_lane_for_class(kernel, priority_class);
    return lane == NULL ? 0u : lane->count;
}

uint32_t wdc_control_lane_outstanding(const WdcControlKernel *kernel,
                                      WdcControlPriorityClass priority_class)
{
    const WdcControlLane *lane = const_lane_for_class(kernel, priority_class);
    const WdcControlTaskPolicy *policy;
    uint32_t outstanding = 0u;
    uint32_t index;
    if (lane == NULL || kernel->profile == NULL) {
        return 0u;
    }
    policy = policy_for_class(kernel->profile, priority_class);
    if (policy == NULL) {
        return 0u;
    }
    for (index = 0u; index < policy->queue_capacity; ++index) {
        if (lane->slots[index].state != WDC_CONTROL_SLOT_FREE) {
            outstanding += 1u;
        }
    }
    return outstanding;
}

uint32_t wdc_control_recovery_required(const WdcControlKernel *kernel)
{
    return kernel == NULL
               ? 0u
               : __atomic_load_n(&kernel->recovery_required, __ATOMIC_ACQUIRE);
}

int32_t WDC_CONTROL_ISR_ATTR wdc_control_capture_isr(
    WdcControlKernel *kernel,
    const WdcControlIsrCapture *capture)
{
    uint32_t write_index;
    uint32_t read_index;
    uint32_t next_index;
    WdcControlIsrCapture *record;
    if (kernel == NULL || capture == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    if (capture->source_id == 0u || capture->signal == 0u ||
        capture->sequence == 0u) {
        return WDC_ERR_BAD_ENCODING;
    }
    write_index = __atomic_load_n(&kernel->isr_write_index, __ATOMIC_RELAXED);
    read_index = __atomic_load_n(&kernel->isr_read_index, __ATOMIC_ACQUIRE);
    next_index = (write_index + 1u) % WDC_CONTROL_ISR_STORAGE_SLOTS;
    if (next_index == read_index) {
        (void)__atomic_fetch_add(&kernel->isr_overflow_count, 1u,
                                 __ATOMIC_RELAXED);
        __atomic_store_n(&kernel->recovery_required, 1u, __ATOMIC_RELEASE);
        return WDC_ERR_BUSY;
    }
    record = &kernel->isr_records[write_index];
    record->source_id = capture->source_id;
    record->signal = capture->signal;
    record->value = capture->value;
    record->sequence = capture->sequence;
    __atomic_store_n(&kernel->isr_write_index, next_index, __ATOMIC_RELEASE);
    (void)__atomic_fetch_add(&kernel->isr_notification_count, 1u,
                             __ATOMIC_RELAXED);
    return WDC_OK;
}

int32_t wdc_control_take_isr_capture(WdcControlKernel *kernel,
                                     WdcControlIsrCapture *out_capture)
{
    uint32_t read_index;
    uint32_t write_index;
    if (kernel == NULL || out_capture == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    read_index = __atomic_load_n(&kernel->isr_read_index, __ATOMIC_RELAXED);
    write_index = __atomic_load_n(&kernel->isr_write_index, __ATOMIC_ACQUIRE);
    if (read_index == write_index) {
        return WDC_ERR_NOT_AVAILABLE;
    }
    *out_capture = kernel->isr_records[read_index];
    __atomic_store_n(&kernel->isr_read_index,
                     (read_index + 1u) % WDC_CONTROL_ISR_STORAGE_SLOTS,
                     __ATOMIC_RELEASE);
    return WDC_OK;
}

uint32_t wdc_control_isr_pending(const WdcControlKernel *kernel)
{
    uint32_t read_index;
    uint32_t write_index;
    if (kernel == NULL) {
        return 0u;
    }
    read_index = __atomic_load_n(&kernel->isr_read_index, __ATOMIC_ACQUIRE);
    write_index = __atomic_load_n(&kernel->isr_write_index, __ATOMIC_ACQUIRE);
    return write_index >= read_index
               ? write_index - read_index
               : WDC_CONTROL_ISR_STORAGE_SLOTS - read_index + write_index;
}

uint32_t wdc_control_isr_notifications(const WdcControlKernel *kernel)
{
    return kernel == NULL
               ? 0u
               : __atomic_load_n(&kernel->isr_notification_count,
                                 __ATOMIC_ACQUIRE);
}

uint32_t wdc_control_isr_overflows(const WdcControlKernel *kernel)
{
    return kernel == NULL
               ? 0u
               : __atomic_load_n(&kernel->isr_overflow_count, __ATOMIC_ACQUIRE);
}

static int admission_arithmetic(const WdcControlResourceProfile *profile,
                                const WdcControlAdmissionRequest *request,
                                WdcControlAdmissionDecision *decision)
{
    uint32_t application = 0u;
    uint32_t largest_application;
    uint32_t largest_update;
    if (!checked_add(application, request->guest_linear_memory_bytes, &application) ||
        !checked_add(application, request->runtime_stack_bytes, &application) ||
        !checked_add(application, request->network_working_bytes, &application) ||
        !checked_add(application, request->capability_working_bytes, &application) ||
        !checked_add(application, request->native_extension_bytes, &application) ||
        !checked_add(profile->reserve.fixed_control_reserve_bytes, application,
                     &decision->normal_required_bytes) ||
        !checked_add(decision->normal_required_bytes,
                     request->transition_scratch_bytes,
                     &decision->transition_required_bytes) ||
        !checked_add(profile->reserve.fixed_control_reserve_bytes,
                     profile->reserve.exclusive_update_working_bytes,
                     &decision->exclusive_update_required_bytes) ||
        !checked_add(request->largest_application_allocation_bytes,
                     profile->reserve.largest_block_floor_bytes,
                     &largest_application) ||
        !checked_add(profile->reserve.update_largest_allocation_bytes,
                     profile->reserve.largest_block_floor_bytes,
                     &largest_update)) {
        return 0;
    }
    decision->application_internal_bytes = application;
    decision->required_internal_free_bytes =
        maximum(decision->transition_required_bytes,
                decision->exclusive_update_required_bytes);
    decision->required_largest_block_bytes =
        maximum(largest_application, largest_update);
    if (request->external_application_bytes != 0u &&
        !checked_add(request->external_application_bytes,
                     profile->reserve.psram_floor_bytes,
                     &decision->required_psram_free_bytes)) {
        return 0;
    }
    return 1;
}

static int32_t deny(WdcControlAdmissionDecision *decision,
                    WdcControlAdmissionOutcome outcome,
                    int32_t status)
{
    decision->outcome = outcome;
    decision->status = status;
    return status;
}

int32_t wdc_control_admit(const WdcControlResourceProfile *profile,
                          const WdcControlAdmissionRequest *request,
                          WdcControlAdmissionDecision *out_decision)
{
    int32_t profile_status;
    if (out_decision == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    memset(out_decision, 0, sizeof(*out_decision));
    out_decision->status = WDC_ERR_UNKNOWN;
    if (profile == NULL || request == NULL) {
        return deny(out_decision, WDC_CONTROL_ADMISSION_DENIED_BAD_REQUEST,
                    WDC_ERR_BAD_POINTER);
    }
    profile_status = wdc_control_validate_profile(profile);
    if (profile_status != WDC_OK || request->heap.internal_free_bytes == 0u ||
        request->heap.internal_largest_block_bytes == 0u ||
        request->heap.internal_largest_block_bytes >
            request->heap.internal_free_bytes ||
        request->guest_linear_memory_bytes == 0u ||
        request->runtime_stack_bytes == 0u ||
        request->largest_application_allocation_bytes == 0u) {
        return deny(out_decision, WDC_CONTROL_ADMISSION_DENIED_BAD_REQUEST,
                    profile_status != WDC_OK ? profile_status : WDC_ERR_BAD_ENCODING);
    }
    out_decision->fixed_control_reserve_bytes =
        profile->reserve.fixed_control_reserve_bytes;
    if (request->requested_task_priority != 0u) {
        return deny(out_decision,
                    WDC_CONTROL_ADMISSION_DENIED_APPLICATION_PRIORITY,
                    WDC_ERR_CAPABILITY_DENIED);
    }
    if (request->requests_unbounded_allocation) {
        return deny(out_decision,
                    WDC_CONTROL_ADMISSION_DENIED_UNBOUNDED_ALLOCATION,
                    WDC_ERR_CAPABILITY_DENIED);
    }
    if (!profile->psram_supported && request->external_application_bytes != 0u) {
        return deny(out_decision,
                    WDC_CONTROL_ADMISSION_DENIED_PSRAM_REQUIRED,
                    WDC_ERR_CAPABILITY_DENIED);
    }
    if (!admission_arithmetic(profile, request, out_decision)) {
        return deny(out_decision, WDC_CONTROL_ADMISSION_DENIED_ARITHMETIC,
                    WDC_ERR_BAD_LENGTH);
    }
    if (out_decision->application_internal_bytes >
            profile->reserve.maximum_application_internal_bytes ||
        request->transition_scratch_bytes >
            profile->reserve.maximum_transition_scratch_bytes ||
        request->largest_application_allocation_bytes >
            out_decision->application_internal_bytes ||
        request->external_application_bytes >
            profile->reserve.maximum_application_psram_bytes) {
        return deny(out_decision,
                    WDC_CONTROL_ADMISSION_DENIED_APPLICATION_BUDGET,
                    WDC_ERR_NO_MEMORY);
    }
    if (request->heap.internal_free_bytes <
        out_decision->required_internal_free_bytes) {
        return deny(out_decision, WDC_CONTROL_ADMISSION_DENIED_INTERNAL_FREE,
                    WDC_ERR_NO_MEMORY);
    }
    if (request->heap.internal_largest_block_bytes <
        out_decision->required_largest_block_bytes) {
        return deny(out_decision, WDC_CONTROL_ADMISSION_DENIED_LARGEST_BLOCK,
                    WDC_ERR_NO_MEMORY);
    }
    if (request->external_application_bytes != 0u &&
        request->heap.psram_free_bytes < out_decision->required_psram_free_bytes) {
        return deny(out_decision, WDC_CONTROL_ADMISSION_DENIED_PSRAM_FREE,
                    WDC_ERR_NO_MEMORY);
    }
    out_decision->portable = request->external_application_bytes == 0u;
    out_decision->outcome = out_decision->portable
                                ? WDC_CONTROL_ADMISSION_ACCEPTED_PORTABLE
                                : WDC_CONTROL_ADMISSION_ACCEPTED_TARGET_OPTIMIZED;
    out_decision->status = WDC_OK;
    out_decision->remaining_internal_free_bytes =
        request->heap.internal_free_bytes -
        out_decision->required_internal_free_bytes;
    out_decision->remaining_largest_block_bytes =
        request->heap.internal_largest_block_bytes -
        out_decision->required_largest_block_bytes;
    return WDC_OK;
}

int32_t wdc_control_admit_exclusive_update(
    const WdcControlResourceProfile *profile,
    const WdcControlHeapSnapshot *heap,
    WdcControlAdmissionDecision *out_decision)
{
    uint32_t required_internal;
    uint32_t required_largest;
    int32_t profile_status;
    if (out_decision == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    memset(out_decision, 0, sizeof(*out_decision));
    out_decision->status = WDC_ERR_UNKNOWN;
    if (profile == NULL || heap == NULL) {
        return deny(out_decision, WDC_CONTROL_ADMISSION_DENIED_BAD_REQUEST,
                    WDC_ERR_BAD_POINTER);
    }
    profile_status = wdc_control_validate_profile(profile);
    if (profile_status != WDC_OK || heap->internal_free_bytes == 0u ||
        heap->internal_largest_block_bytes == 0u ||
        heap->internal_largest_block_bytes > heap->internal_free_bytes) {
        return deny(out_decision, WDC_CONTROL_ADMISSION_DENIED_BAD_REQUEST,
                    profile_status != WDC_OK ? profile_status
                                             : WDC_ERR_BAD_ENCODING);
    }
    if (!checked_add(profile->reserve.fixed_control_reserve_bytes,
                     profile->reserve.exclusive_update_working_bytes,
                     &required_internal) ||
        !checked_add(profile->reserve.update_largest_allocation_bytes,
                     profile->reserve.largest_block_floor_bytes,
                     &required_largest)) {
        return deny(out_decision, WDC_CONTROL_ADMISSION_DENIED_ARITHMETIC,
                    WDC_ERR_BAD_LENGTH);
    }
    out_decision->fixed_control_reserve_bytes =
        profile->reserve.fixed_control_reserve_bytes;
    out_decision->exclusive_update_required_bytes = required_internal;
    out_decision->required_internal_free_bytes = required_internal;
    out_decision->required_largest_block_bytes = required_largest;
    if (heap->internal_free_bytes < required_internal) {
        return deny(out_decision, WDC_CONTROL_ADMISSION_DENIED_INTERNAL_FREE,
                    WDC_ERR_NO_MEMORY);
    }
    if (heap->internal_largest_block_bytes < required_largest) {
        return deny(out_decision, WDC_CONTROL_ADMISSION_DENIED_LARGEST_BLOCK,
                    WDC_ERR_NO_MEMORY);
    }
    out_decision->portable = true;
    out_decision->outcome = WDC_CONTROL_ADMISSION_ACCEPTED_PORTABLE;
    out_decision->status = WDC_OK;
    out_decision->remaining_internal_free_bytes =
        heap->internal_free_bytes - required_internal;
    out_decision->remaining_largest_block_bytes =
        heap->internal_largest_block_bytes - required_largest;
    return WDC_OK;
}

uint32_t wdc_control_link_anchor(void)
{
    return 0x48503101u;
}
