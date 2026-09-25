#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "wdc_abi.h"

#ifdef __cplusplus
extern "C" {
#endif

#define WDC_CONTROL_PRIORITY_CLASS_COUNT 5u
#define WDC_CONTROL_QUEUE_CAPACITY_MAX 16u
#define WDC_CONTROL_ISR_CAPACITY 8u
#define WDC_CONTROL_ISR_STORAGE_SLOTS (WDC_CONTROL_ISR_CAPACITY + 1u)
#define WDC_CONTROL_KERNEL_STATIC_BUDGET_BYTES 8192u

typedef enum WdcControlPriorityClass {
    WDC_CONTROL_PRIORITY_NONE = 0,
    WDC_CONTROL_PRIORITY_APPLICATION = 1,
    WDC_CONTROL_PRIORITY_CAPABILITY = 2,
    WDC_CONTROL_PRIORITY_NETWORK = 3,
    WDC_CONTROL_PRIORITY_ADMINISTRATION = 4,
    WDC_CONTROL_PRIORITY_SAFETY_RECOVERY = 5,
} WdcControlPriorityClass;

typedef enum WdcControlSource {
    WDC_CONTROL_SOURCE_NONE = 0,
    WDC_CONTROL_SOURCE_SAFETY = 1,
    WDC_CONTROL_SOURCE_WATCHDOG = 2,
    WDC_CONTROL_SOURCE_RECOVERY = 3,
    WDC_CONTROL_SOURCE_ADMINISTRATION = 4,
    WDC_CONTROL_SOURCE_UPDATE = 5,
    WDC_CONTROL_SOURCE_NETWORK_MAINTENANCE = 6,
    WDC_CONTROL_SOURCE_CAPABILITY = 7,
    WDC_CONTROL_SOURCE_APPLICATION = 8,
} WdcControlSource;

typedef enum WdcControlOverflowPolicy {
    WDC_CONTROL_OVERFLOW_NONE = 0,
    WDC_CONTROL_OVERFLOW_TERMINAL_REJECT_NEWEST = 1,
    WDC_CONTROL_OVERFLOW_LATCH_RECOVERY_REJECT_NEWEST = 2,
} WdcControlOverflowPolicy;

typedef enum WdcControlTerminalDisposition {
    WDC_CONTROL_TERMINAL_NONE = 0,
    WDC_CONTROL_TERMINAL_SUCCEEDED = 1,
    WDC_CONTROL_TERMINAL_FAILED = 2,
    WDC_CONTROL_TERMINAL_TIMED_OUT = 3,
    WDC_CONTROL_TERMINAL_CANCELLED = 4,
    WDC_CONTROL_TERMINAL_REJECTED_OVERFLOW = 5,
} WdcControlTerminalDisposition;

typedef enum WdcControlSlotState {
    WDC_CONTROL_SLOT_FREE = 0,
    WDC_CONTROL_SLOT_QUEUED = 1,
    WDC_CONTROL_SLOT_IN_FLIGHT = 2,
    WDC_CONTROL_SLOT_COMPLETED = 3,
} WdcControlSlotState;

typedef enum WdcControlAdmissionOutcome {
    WDC_CONTROL_ADMISSION_NOT_EVALUATED = 0,
    WDC_CONTROL_ADMISSION_ACCEPTED_PORTABLE = 1,
    WDC_CONTROL_ADMISSION_ACCEPTED_TARGET_OPTIMIZED = 2,
    WDC_CONTROL_ADMISSION_DENIED_BAD_REQUEST = 3,
    WDC_CONTROL_ADMISSION_DENIED_APPLICATION_PRIORITY = 4,
    WDC_CONTROL_ADMISSION_DENIED_UNBOUNDED_ALLOCATION = 5,
    WDC_CONTROL_ADMISSION_DENIED_PSRAM_REQUIRED = 6,
    WDC_CONTROL_ADMISSION_DENIED_APPLICATION_BUDGET = 7,
    WDC_CONTROL_ADMISSION_DENIED_INTERNAL_FREE = 8,
    WDC_CONTROL_ADMISSION_DENIED_LARGEST_BLOCK = 9,
    WDC_CONTROL_ADMISSION_DENIED_PSRAM_FREE = 10,
    WDC_CONTROL_ADMISSION_DENIED_ARITHMETIC = 11,
} WdcControlAdmissionOutcome;

typedef struct WdcControlTaskPolicy {
    WdcControlPriorityClass priority_class;
    uint32_t freertos_priority;
    uint32_t stack_bytes;
    uint32_t queue_capacity;
    WdcControlOverflowPolicy overflow_policy;
} WdcControlTaskPolicy;

typedef struct WdcControlReservePlan {
    uint32_t kernel_static_bytes;
    uint32_t control_metadata_bytes;
    uint32_t administration_bytes;
    uint32_t verification_bytes;
    uint32_t recovery_bytes;
    uint32_t fixed_control_reserve_bytes;
    uint32_t exclusive_update_working_bytes;
    uint32_t update_largest_allocation_bytes;
    uint32_t largest_block_floor_bytes;
    uint32_t maximum_application_internal_bytes;
    uint32_t maximum_transition_scratch_bytes;
    uint32_t maximum_application_psram_bytes;
    uint32_t psram_floor_bytes;
} WdcControlReservePlan;

typedef struct WdcControlResourceProfile {
    const char *profile_id;
    const char *target;
    bool psram_supported;
    WdcControlTaskPolicy policies[WDC_CONTROL_PRIORITY_CLASS_COUNT];
    WdcControlReservePlan reserve;
} WdcControlResourceProfile;

typedef struct WdcControlWorkRequest {
    WdcControlSource source;
    uint32_t operation_id;
    uint32_t correlation_id;
    uint32_t value;
} WdcControlWorkRequest;

typedef struct WdcControlWorkItem {
    uint32_t ticket;
    WdcControlPriorityClass priority_class;
    WdcControlWorkRequest request;
} WdcControlWorkItem;

typedef struct WdcControlCompletion {
    uint32_t ticket;
    WdcControlPriorityClass priority_class;
    WdcControlSource source;
    uint32_t correlation_id;
    WdcControlTerminalDisposition disposition;
    int32_t result;
} WdcControlCompletion;

typedef struct WdcControlSlot {
    uint32_t generation;
    WdcControlSlotState state;
    WdcControlWorkItem item;
    WdcControlCompletion completion;
} WdcControlSlot;

typedef struct WdcControlLane {
    WdcControlSlot slots[WDC_CONTROL_QUEUE_CAPACITY_MAX];
    uint8_t queue[WDC_CONTROL_QUEUE_CAPACITY_MAX];
    uint32_t head;
    uint32_t count;
    uint32_t high_water;
    uint32_t accepted;
    uint32_t terminal_rejections;
} WdcControlLane;

typedef struct WdcControlIsrCapture {
    uint32_t source_id;
    uint32_t signal;
    uint32_t value;
    uint32_t sequence;
} WdcControlIsrCapture;

typedef struct WdcControlHeapSnapshot {
    uint32_t internal_free_bytes;
    uint32_t internal_largest_block_bytes;
    uint32_t psram_free_bytes;
} WdcControlHeapSnapshot;

typedef struct WdcControlAdmissionRequest {
    WdcControlHeapSnapshot heap;
    uint32_t guest_linear_memory_bytes;
    uint32_t runtime_stack_bytes;
    uint32_t network_working_bytes;
    uint32_t capability_working_bytes;
    uint32_t native_extension_bytes;
    uint32_t transition_scratch_bytes;
    uint32_t largest_application_allocation_bytes;
    uint32_t external_application_bytes;
    uint32_t requested_task_priority;
    bool requests_unbounded_allocation;
} WdcControlAdmissionRequest;

typedef struct WdcControlAdmissionDecision {
    WdcControlAdmissionOutcome outcome;
    int32_t status;
    bool portable;
    uint32_t fixed_control_reserve_bytes;
    uint32_t application_internal_bytes;
    uint32_t normal_required_bytes;
    uint32_t transition_required_bytes;
    uint32_t exclusive_update_required_bytes;
    uint32_t required_internal_free_bytes;
    uint32_t required_largest_block_bytes;
    uint32_t required_psram_free_bytes;
    uint32_t remaining_internal_free_bytes;
    uint32_t remaining_largest_block_bytes;
} WdcControlAdmissionDecision;

typedef struct WdcControlKernel {
    const WdcControlResourceProfile *profile;
    WdcControlLane lanes[WDC_CONTROL_PRIORITY_CLASS_COUNT];
    WdcControlIsrCapture isr_records[WDC_CONTROL_ISR_STORAGE_SLOTS];
    volatile uint32_t isr_write_index;
    volatile uint32_t isr_read_index;
    volatile uint32_t isr_notification_count;
    volatile uint32_t isr_overflow_count;
    volatile uint32_t recovery_required;
} WdcControlKernel;

const WdcControlResourceProfile *wdc_control_profile_c6_minimum(void);
const WdcControlResourceProfile *wdc_control_profile_s3_psram(void);
int32_t wdc_control_validate_profile(const WdcControlResourceProfile *profile);
uint32_t wdc_control_fixed_reserve_bytes(const WdcControlResourceProfile *profile);
WdcControlPriorityClass wdc_control_priority_class_for_source(WdcControlSource source);
int32_t wdc_control_task_priority_for_source(const WdcControlResourceProfile *profile,
                                             WdcControlSource source,
                                             uint32_t *out_priority);

int32_t wdc_control_kernel_init(WdcControlKernel *kernel,
                                const WdcControlResourceProfile *profile);
int32_t wdc_control_submit(WdcControlKernel *kernel,
                           const WdcControlWorkRequest *request,
                           uint32_t *out_ticket,
                           WdcControlCompletion *out_rejection);
int32_t wdc_control_next(WdcControlKernel *kernel, WdcControlWorkItem *out_item);
int32_t wdc_control_complete(WdcControlKernel *kernel,
                             uint32_t ticket,
                             WdcControlTerminalDisposition disposition,
                             int32_t result);
int32_t wdc_control_take_completion(WdcControlKernel *kernel,
                                    uint32_t ticket,
                                    WdcControlCompletion *out_completion);
uint32_t wdc_control_lane_pending(const WdcControlKernel *kernel,
                                  WdcControlPriorityClass priority_class);
uint32_t wdc_control_lane_outstanding(const WdcControlKernel *kernel,
                                      WdcControlPriorityClass priority_class);
uint32_t wdc_control_recovery_required(const WdcControlKernel *kernel);

/* ISR-safe: fixed-field capture and atomic index publication only. */
int32_t wdc_control_capture_isr(WdcControlKernel *kernel,
                                const WdcControlIsrCapture *capture);
int32_t wdc_control_take_isr_capture(WdcControlKernel *kernel,
                                     WdcControlIsrCapture *out_capture);
uint32_t wdc_control_isr_pending(const WdcControlKernel *kernel);
uint32_t wdc_control_isr_notifications(const WdcControlKernel *kernel);
uint32_t wdc_control_isr_overflows(const WdcControlKernel *kernel);

int32_t wdc_control_admit(const WdcControlResourceProfile *profile,
                          const WdcControlAdmissionRequest *request,
                          WdcControlAdmissionDecision *out_decision);

/*
 * HP4.2 reuses HP1's sealed reserve arithmetic after the application and
 * native refinements have been positively unloaded.  This gate admits only
 * the fixed control reserve plus the exclusive update working set; it does
 * not accept application-controlled sizes or priorities.
 */
int32_t wdc_control_admit_exclusive_update(
    const WdcControlResourceProfile *profile,
    const WdcControlHeapSnapshot *heap,
    WdcControlAdmissionDecision *out_decision);

/* ESP-IDF-only platform adapter; opaque task handle avoids FreeRTOS leakage. */
int32_t wdc_control_platform_bind_notification_task(void *host_task_handle);
void wdc_control_platform_unbind_notification_task(void);
int32_t wdc_control_platform_capture_from_isr(WdcControlKernel *kernel,
                                              const WdcControlIsrCapture *capture,
                                              int32_t *out_higher_priority_woken);
int32_t wdc_control_platform_heap_snapshot(WdcControlHeapSnapshot *out_snapshot);

/* Side-effect-free boot link anchor. */
uint32_t wdc_control_link_anchor(void);

#ifdef __cplusplus
}
#endif
