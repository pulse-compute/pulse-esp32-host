#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "wdc_control.h"

#define HP1_CASE_COUNT 9u
#define HP1_PRESSURE_ROUNDS 64u

typedef struct CaseRecord {
    const char *name;
    uint32_t passed;
} CaseRecord;

static uint32_t s_failures;
static CaseRecord s_cases[HP1_CASE_COUNT];
static uint32_t s_case_count;
static uint32_t s_correlation = 1u;

#define CHECK(condition) \
    do { \
        if (!(condition)) { \
            s_failures += 1u; \
        } \
    } while (0)

static void record_case(const char *name, uint32_t failures_before)
{
    CHECK(s_case_count < HP1_CASE_COUNT);
    if (s_case_count < HP1_CASE_COUNT) {
        s_cases[s_case_count].name = name;
        s_cases[s_case_count].passed = s_failures == failures_before ? 1u : 0u;
        s_case_count += 1u;
    }
}

static WdcControlWorkRequest request_for(WdcControlSource source,
                                         uint32_t operation,
                                         uint32_t value)
{
    WdcControlWorkRequest request;
    memset(&request, 0, sizeof(request));
    request.source = source;
    request.operation_id = operation;
    request.correlation_id = s_correlation++;
    if (s_correlation == 0u) {
        s_correlation = 1u;
    }
    request.value = value;
    return request;
}

static uint32_t submit_ok(WdcControlKernel *kernel,
                          WdcControlSource source,
                          uint32_t operation,
                          uint32_t value)
{
    WdcControlWorkRequest request = request_for(source, operation, value);
    WdcControlCompletion rejection;
    uint32_t ticket = 0u;
    CHECK(wdc_control_submit(kernel, &request, &ticket, &rejection) == WDC_OK);
    CHECK(ticket != 0u);
    CHECK(rejection.disposition == WDC_CONTROL_TERMINAL_NONE);
    return ticket;
}

static void finish_next(WdcControlKernel *kernel,
                        WdcControlPriorityClass expected_class,
                        uint32_t *terminal_count)
{
    WdcControlWorkItem item;
    WdcControlCompletion completion;
    memset(&item, 0, sizeof(item));
    CHECK(wdc_control_next(kernel, &item) == WDC_OK);
    CHECK(item.priority_class == expected_class);
    CHECK(wdc_control_complete(kernel,
                               item.ticket,
                               WDC_CONTROL_TERMINAL_SUCCEEDED,
                               WDC_OK) == WDC_OK);
    memset(&completion, 0, sizeof(completion));
    CHECK(wdc_control_take_completion(kernel, item.ticket, &completion) == WDC_OK);
    CHECK(completion.ticket == item.ticket);
    CHECK(completion.priority_class == expected_class);
    CHECK(completion.disposition == WDC_CONTROL_TERMINAL_SUCCEEDED);
    CHECK(completion.result == WDC_OK);
    if (terminal_count != NULL) {
        *terminal_count += 1u;
    }
}

static WdcControlAdmissionRequest portable_request(void)
{
    WdcControlAdmissionRequest request;
    memset(&request, 0, sizeof(request));
    request.heap.internal_free_bytes = 255032u;
    request.heap.internal_largest_block_bytes = 221184u;
    request.guest_linear_memory_bytes = 49152u;
    request.runtime_stack_bytes = 16384u;
    request.network_working_bytes = 8192u;
    request.capability_working_bytes = 4096u;
    request.native_extension_bytes = 8192u;
    request.transition_scratch_bytes = 8192u;
    request.largest_application_allocation_bytes = 49152u;
    return request;
}

static void run_profile_authority(uint32_t priorities[WDC_CONTROL_PRIORITY_CLASS_COUNT])
{
    const WdcControlResourceProfile *c6 = wdc_control_profile_c6_minimum();
    const WdcControlResourceProfile *s3 = wdc_control_profile_s3_psram();
    WdcControlSource sources[WDC_CONTROL_PRIORITY_CLASS_COUNT] = {
        WDC_CONTROL_SOURCE_APPLICATION,
        WDC_CONTROL_SOURCE_CAPABILITY,
        WDC_CONTROL_SOURCE_NETWORK_MAINTENANCE,
        WDC_CONTROL_SOURCE_ADMINISTRATION,
        WDC_CONTROL_SOURCE_SAFETY,
    };
    uint32_t expected[WDC_CONTROL_PRIORITY_CLASS_COUNT] = { 5u, 7u, 9u, 11u, 13u };
    uint32_t index;
    uint32_t before = s_failures;
    CHECK(wdc_control_validate_profile(c6) == WDC_OK);
    CHECK(wdc_control_validate_profile(s3) == WDC_OK);
    CHECK(!c6->psram_supported);
    CHECK(s3->psram_supported);
    CHECK(wdc_control_fixed_reserve_bytes(c6) == 98304u);
    CHECK(wdc_control_fixed_reserve_bytes(s3) == 98304u);
    CHECK(c6->reserve.exclusive_update_working_bytes == 65536u);
    CHECK(c6->reserve.largest_block_floor_bytes == 32768u);
    CHECK(c6->reserve.maximum_application_internal_bytes == 131072u);
    CHECK(sizeof(WdcControlKernel) <= WDC_CONTROL_KERNEL_STATIC_BUDGET_BYTES);
    for (index = 0u; index < WDC_CONTROL_PRIORITY_CLASS_COUNT; ++index) {
        priorities[index] = 0u;
        CHECK(wdc_control_task_priority_for_source(c6, sources[index],
                                                   &priorities[index]) == WDC_OK);
        CHECK(priorities[index] == expected[index]);
    }
    CHECK(wdc_control_priority_class_for_source(WDC_CONTROL_SOURCE_WATCHDOG) ==
          WDC_CONTROL_PRIORITY_SAFETY_RECOVERY);
    CHECK(wdc_control_priority_class_for_source(WDC_CONTROL_SOURCE_UPDATE) ==
          WDC_CONTROL_PRIORITY_ADMINISTRATION);
    record_case("fixed-priority-and-reserve-authority", before);
}

static void run_isr_contract(uint32_t *captures,
                             uint32_t *overflows,
                             uint32_t *notifications)
{
    WdcControlKernel kernel;
    uint32_t sequence;
    uint32_t before = s_failures;
    *captures = 0u;
    *overflows = 0u;
    *notifications = 0u;
    CHECK(wdc_control_kernel_init(&kernel,
                                  wdc_control_profile_c6_minimum()) == WDC_OK);
    for (sequence = 1u; sequence <= WDC_CONTROL_ISR_CAPACITY; ++sequence) {
        WdcControlIsrCapture capture = { 17u, 0x495352u, sequence * 3u, sequence };
        CHECK(wdc_control_capture_isr(&kernel, &capture) == WDC_OK);
        *captures += 1u;
    }
    {
        WdcControlIsrCapture overflow = { 17u, 0x495352u, 99u, 9u };
        CHECK(wdc_control_capture_isr(&kernel, &overflow) == WDC_ERR_BUSY);
        *overflows += 1u;
    }
    CHECK(wdc_control_isr_pending(&kernel) == WDC_CONTROL_ISR_CAPACITY);
    CHECK(wdc_control_isr_notifications(&kernel) == WDC_CONTROL_ISR_CAPACITY);
    CHECK(wdc_control_isr_overflows(&kernel) == 1u);
    CHECK(wdc_control_recovery_required(&kernel) == 1u);
    *notifications = wdc_control_isr_notifications(&kernel);
    for (sequence = 1u; sequence <= WDC_CONTROL_ISR_CAPACITY; ++sequence) {
        WdcControlIsrCapture observed;
        memset(&observed, 0, sizeof(observed));
        CHECK(wdc_control_take_isr_capture(&kernel, &observed) == WDC_OK);
        CHECK(observed.source_id == 17u);
        CHECK(observed.signal == 0x495352u);
        CHECK(observed.value == sequence * 3u);
        CHECK(observed.sequence == sequence);
    }
    CHECK(wdc_control_take_isr_capture(&kernel, &(WdcControlIsrCapture){0}) ==
          WDC_ERR_NOT_AVAILABLE);
    CHECK(wdc_control_isr_pending(&kernel) == 0u);
    record_case("isr-fixed-capture-notification", before);
}

static void run_priority_pressure(uint32_t *application_high_water,
                                  uint32_t *overflow_rejections)
{
    WdcControlKernel kernel;
    WdcControlCompletion rejection;
    WdcControlWorkRequest overflow;
    WdcControlWorkItem item;
    uint32_t ticket;
    uint32_t index;
    uint32_t before = s_failures;
    CHECK(wdc_control_kernel_init(&kernel,
                                  wdc_control_profile_c6_minimum()) == WDC_OK);
    for (index = 0u; index < 16u; ++index) {
        (void)submit_ok(&kernel, WDC_CONTROL_SOURCE_APPLICATION,
                        0x415050u, index);
    }
    overflow = request_for(WDC_CONTROL_SOURCE_APPLICATION, 0x415050u, 17u);
    ticket = 99u;
    memset(&rejection, 0, sizeof(rejection));
    CHECK(wdc_control_submit(&kernel, &overflow, &ticket, &rejection) ==
          WDC_ERR_BUSY);
    CHECK(ticket == 0u);
    CHECK(rejection.ticket == 0u);
    CHECK(rejection.source == WDC_CONTROL_SOURCE_APPLICATION);
    CHECK(rejection.correlation_id == overflow.correlation_id);
    CHECK(rejection.disposition == WDC_CONTROL_TERMINAL_REJECTED_OVERFLOW);
    CHECK(rejection.result == WDC_ERR_BUSY);
    *overflow_rejections = 1u;
    (void)submit_ok(&kernel, WDC_CONTROL_SOURCE_ADMINISTRATION,
                    0x41444du, 1u);
    (void)submit_ok(&kernel, WDC_CONTROL_SOURCE_SAFETY,
                    0x534146u, 1u);
    memset(&item, 0, sizeof(item));
    CHECK(wdc_control_next(&kernel, &item) == WDC_OK);
    CHECK(item.priority_class == WDC_CONTROL_PRIORITY_SAFETY_RECOVERY);
    CHECK(item.request.source == WDC_CONTROL_SOURCE_SAFETY);
    CHECK(wdc_control_complete(&kernel, item.ticket,
                               WDC_CONTROL_TERMINAL_SUCCEEDED, WDC_OK) == WDC_OK);
    CHECK(wdc_control_take_completion(&kernel, item.ticket, &rejection) == WDC_OK);
    memset(&item, 0, sizeof(item));
    CHECK(wdc_control_next(&kernel, &item) == WDC_OK);
    CHECK(item.priority_class == WDC_CONTROL_PRIORITY_ADMINISTRATION);
    CHECK(wdc_control_complete(&kernel, item.ticket,
                               WDC_CONTROL_TERMINAL_SUCCEEDED, WDC_OK) == WDC_OK);
    CHECK(wdc_control_take_completion(&kernel, item.ticket, &rejection) == WDC_OK);
    memset(&item, 0, sizeof(item));
    CHECK(wdc_control_next(&kernel, &item) == WDC_OK);
    CHECK(item.priority_class == WDC_CONTROL_PRIORITY_APPLICATION);
    *application_high_water =
        kernel.lanes[WDC_CONTROL_PRIORITY_APPLICATION - 1u].high_water;
    CHECK(*application_high_water == 16u);
    record_case("priority-preemption-under-application-pressure", before);
}

static void run_terminal_completion(void)
{
    WdcControlKernel kernel;
    WdcControlWorkItem item;
    WdcControlCompletion completion;
    uint32_t before = s_failures;
    CHECK(wdc_control_kernel_init(&kernel,
                                  wdc_control_profile_c6_minimum()) == WDC_OK);
    (void)submit_ok(&kernel, WDC_CONTROL_SOURCE_APPLICATION, 0x444f4eu, 1u);
    CHECK(wdc_control_next(&kernel, &item) == WDC_OK);
    CHECK(wdc_control_complete(&kernel, item.ticket,
                               WDC_CONTROL_TERMINAL_SUCCEEDED,
                               WDC_ERR_UNKNOWN) == WDC_ERR_BAD_ENCODING);
    CHECK(wdc_control_complete(&kernel, item.ticket,
                               WDC_CONTROL_TERMINAL_SUCCEEDED, WDC_OK) == WDC_OK);
    CHECK(wdc_control_complete(&kernel, item.ticket,
                               WDC_CONTROL_TERMINAL_SUCCEEDED, WDC_OK) ==
          WDC_ERR_INVALID_STATE);
    CHECK(wdc_control_take_completion(&kernel, item.ticket, &completion) == WDC_OK);
    CHECK(completion.disposition == WDC_CONTROL_TERMINAL_SUCCEEDED);
    CHECK(wdc_control_take_completion(&kernel, item.ticket, &completion) ==
          WDC_ERR_NOT_AVAILABLE);
    CHECK(wdc_control_lane_outstanding(&kernel,
                                       WDC_CONTROL_PRIORITY_APPLICATION) == 0u);
    record_case("terminal-completion-exactly-once", before);
}

static void run_partitioned_capacity(void)
{
    WdcControlKernel kernel;
    WdcControlSource sources[] = {
        WDC_CONTROL_SOURCE_APPLICATION,
        WDC_CONTROL_SOURCE_CAPABILITY,
        WDC_CONTROL_SOURCE_NETWORK_MAINTENANCE,
        WDC_CONTROL_SOURCE_ADMINISTRATION,
    };
    uint32_t capacities[] = { 16u, 16u, 8u, 8u };
    uint32_t source_index;
    uint32_t index;
    uint32_t before = s_failures;
    CHECK(wdc_control_kernel_init(&kernel,
                                  wdc_control_profile_c6_minimum()) == WDC_OK);
    for (source_index = 0u; source_index < 4u; ++source_index) {
        for (index = 0u; index < capacities[source_index]; ++index) {
            (void)submit_ok(&kernel, sources[source_index],
                            0x504152u + source_index, index);
        }
    }
    for (index = 0u; index < 8u; ++index) {
        (void)submit_ok(&kernel, WDC_CONTROL_SOURCE_RECOVERY, 0x524543u, index);
    }
    CHECK(wdc_control_lane_outstanding(&kernel,
                                       WDC_CONTROL_PRIORITY_APPLICATION) == 16u);
    CHECK(wdc_control_lane_outstanding(&kernel,
                                       WDC_CONTROL_PRIORITY_CAPABILITY) == 16u);
    CHECK(wdc_control_lane_outstanding(&kernel,
                                       WDC_CONTROL_PRIORITY_NETWORK) == 8u);
    CHECK(wdc_control_lane_outstanding(&kernel,
                                       WDC_CONTROL_PRIORITY_ADMINISTRATION) == 8u);
    CHECK(wdc_control_lane_outstanding(&kernel,
                                       WDC_CONTROL_PRIORITY_SAFETY_RECOVERY) == 8u);
    {
        WdcControlWorkRequest request =
            request_for(WDC_CONTROL_SOURCE_RECOVERY, 0x524543u, 9u);
        WdcControlCompletion rejection;
        uint32_t ticket = 0u;
        CHECK(wdc_control_submit(&kernel, &request, &ticket, &rejection) ==
              WDC_ERR_BUSY);
        CHECK(rejection.disposition == WDC_CONTROL_TERMINAL_REJECTED_OVERFLOW);
        CHECK(wdc_control_recovery_required(&kernel) == 1u);
    }
    record_case("per-class-capacity-reservation", before);
}

static void run_c6_admission(uint32_t *required_free,
                             uint32_t *required_largest,
                             uint32_t *free_margin,
                             uint32_t *largest_margin)
{
    WdcControlAdmissionRequest request = portable_request();
    WdcControlAdmissionDecision decision;
    uint32_t before = s_failures;
    CHECK(wdc_control_admit(wdc_control_profile_c6_minimum(), &request,
                            &decision) == WDC_OK);
    CHECK(decision.outcome == WDC_CONTROL_ADMISSION_ACCEPTED_PORTABLE);
    CHECK(decision.portable);
    CHECK(decision.fixed_control_reserve_bytes == 98304u);
    CHECK(decision.application_internal_bytes == 86016u);
    CHECK(decision.normal_required_bytes == 184320u);
    CHECK(decision.transition_required_bytes == 192512u);
    CHECK(decision.exclusive_update_required_bytes == 163840u);
    CHECK(decision.required_internal_free_bytes == 192512u);
    CHECK(decision.required_largest_block_bytes == 98304u);
    CHECK(decision.remaining_internal_free_bytes == 62520u);
    CHECK(decision.remaining_largest_block_bytes == 122880u);
    *required_free = decision.required_internal_free_bytes;
    *required_largest = decision.required_largest_block_bytes;
    *free_margin = decision.remaining_internal_free_bytes;
    *largest_margin = decision.remaining_largest_block_bytes;
    record_case("c6-portable-admission", before);
}

static void run_admission_denials(uint32_t *denial_count)
{
    const WdcControlResourceProfile *c6 = wdc_control_profile_c6_minimum();
    WdcControlAdmissionRequest request;
    WdcControlAdmissionDecision decision;
    uint32_t before = s_failures;
    *denial_count = 0u;

    request = portable_request();
    request.requested_task_priority = 6u;
    CHECK(wdc_control_admit(c6, &request, &decision) == WDC_ERR_CAPABILITY_DENIED);
    CHECK(decision.outcome == WDC_CONTROL_ADMISSION_DENIED_APPLICATION_PRIORITY);
    *denial_count += 1u;

    request = portable_request();
    request.requests_unbounded_allocation = true;
    CHECK(wdc_control_admit(c6, &request, &decision) == WDC_ERR_CAPABILITY_DENIED);
    CHECK(decision.outcome == WDC_CONTROL_ADMISSION_DENIED_UNBOUNDED_ALLOCATION);
    *denial_count += 1u;

    request = portable_request();
    request.external_application_bytes = 1u;
    CHECK(wdc_control_admit(c6, &request, &decision) == WDC_ERR_CAPABILITY_DENIED);
    CHECK(decision.outcome == WDC_CONTROL_ADMISSION_DENIED_PSRAM_REQUIRED);
    *denial_count += 1u;

    request = portable_request();
    request.guest_linear_memory_bytes = 131072u;
    request.largest_application_allocation_bytes = 131072u;
    CHECK(wdc_control_admit(c6, &request, &decision) == WDC_ERR_NO_MEMORY);
    CHECK(decision.outcome == WDC_CONTROL_ADMISSION_DENIED_APPLICATION_BUDGET);
    *denial_count += 1u;

    request = portable_request();
    request.heap.internal_free_bytes = 192511u;
    request.heap.internal_largest_block_bytes = 192511u;
    CHECK(wdc_control_admit(c6, &request, &decision) == WDC_ERR_NO_MEMORY);
    CHECK(decision.outcome == WDC_CONTROL_ADMISSION_DENIED_INTERNAL_FREE);
    *denial_count += 1u;

    request = portable_request();
    request.heap.internal_largest_block_bytes = 98303u;
    CHECK(wdc_control_admit(c6, &request, &decision) == WDC_ERR_NO_MEMORY);
    CHECK(decision.outcome == WDC_CONTROL_ADMISSION_DENIED_LARGEST_BLOCK);
    *denial_count += 1u;

    request = portable_request();
    request.guest_linear_memory_bytes = UINT32_MAX;
    request.largest_application_allocation_bytes = UINT32_MAX;
    CHECK(wdc_control_admit(c6, &request, &decision) == WDC_ERR_BAD_LENGTH);
    CHECK(decision.outcome == WDC_CONTROL_ADMISSION_DENIED_ARITHMETIC);
    *denial_count += 1u;

    request = portable_request();
    request.runtime_stack_bytes = 0u;
    CHECK(wdc_control_admit(c6, &request, &decision) == WDC_ERR_BAD_ENCODING);
    CHECK(decision.outcome == WDC_CONTROL_ADMISSION_DENIED_BAD_REQUEST);
    *denial_count += 1u;

    CHECK(*denial_count == 8u);
    record_case("admission-denials-fail-closed", before);
}

static void run_s3_explicit_psram(uint32_t *required_psram)
{
    WdcControlAdmissionRequest request = portable_request();
    WdcControlAdmissionDecision decision;
    uint32_t before = s_failures;
    request.external_application_bytes = 262144u;
    request.heap.psram_free_bytes = 2097152u;
    CHECK(wdc_control_admit(wdc_control_profile_s3_psram(), &request,
                            &decision) == WDC_OK);
    CHECK(decision.outcome ==
          WDC_CONTROL_ADMISSION_ACCEPTED_TARGET_OPTIMIZED);
    CHECK(!decision.portable);
    CHECK(decision.required_psram_free_bytes == 393216u);
    CHECK(decision.fixed_control_reserve_bytes == 98304u);
    *required_psram = decision.required_psram_free_bytes;
    request.heap.psram_free_bytes = 393215u;
    CHECK(wdc_control_admit(wdc_control_profile_s3_psram(), &request,
                            &decision) == WDC_ERR_NO_MEMORY);
    CHECK(decision.outcome == WDC_CONTROL_ADMISSION_DENIED_PSRAM_FREE);
    record_case("s3-psram-explicit-nonportable", before);
}

static void run_synthetic_pressure(uint32_t *accepted,
                                   uint32_t *terminal,
                                   uint32_t *retained)
{
    WdcControlKernel kernel;
    uint32_t round;
    uint32_t before = s_failures;
    *accepted = 0u;
    *terminal = 0u;
    *retained = 0u;
    CHECK(wdc_control_kernel_init(&kernel,
                                  wdc_control_profile_c6_minimum()) == WDC_OK);
    for (round = 0u; round < HP1_PRESSURE_ROUNDS; ++round) {
        (void)submit_ok(&kernel, WDC_CONTROL_SOURCE_APPLICATION, 0x505245u, round);
        (void)submit_ok(&kernel, WDC_CONTROL_SOURCE_CAPABILITY, 0x505245u, round);
        (void)submit_ok(&kernel, WDC_CONTROL_SOURCE_NETWORK_MAINTENANCE,
                        0x505245u, round);
        (void)submit_ok(&kernel, WDC_CONTROL_SOURCE_ADMINISTRATION,
                        0x505245u, round);
        (void)submit_ok(&kernel, WDC_CONTROL_SOURCE_SAFETY, 0x505245u, round);
        *accepted += 5u;
        finish_next(&kernel, WDC_CONTROL_PRIORITY_SAFETY_RECOVERY, terminal);
        finish_next(&kernel, WDC_CONTROL_PRIORITY_ADMINISTRATION, terminal);
        finish_next(&kernel, WDC_CONTROL_PRIORITY_NETWORK, terminal);
        finish_next(&kernel, WDC_CONTROL_PRIORITY_CAPABILITY, terminal);
        finish_next(&kernel, WDC_CONTROL_PRIORITY_APPLICATION, terminal);
    }
    for (round = WDC_CONTROL_PRIORITY_APPLICATION;
         round <= WDC_CONTROL_PRIORITY_SAFETY_RECOVERY;
         ++round) {
        *retained += wdc_control_lane_outstanding(
            &kernel, (WdcControlPriorityClass)round);
        CHECK(wdc_control_lane_pending(&kernel,
                                       (WdcControlPriorityClass)round) == 0u);
    }
    CHECK(*accepted == HP1_PRESSURE_ROUNDS * 5u);
    CHECK(*terminal == *accepted);
    CHECK(*retained == 0u);
    CHECK(wdc_control_recovery_required(&kernel) == 0u);
    record_case("synthetic-pressure-no-retention", before);
}

int main(void)
{
    uint32_t priorities[WDC_CONTROL_PRIORITY_CLASS_COUNT];
    uint32_t isr_captures;
    uint32_t isr_overflows;
    uint32_t isr_notifications;
    uint32_t application_high_water;
    uint32_t overflow_rejections;
    uint32_t required_free;
    uint32_t required_largest;
    uint32_t free_margin;
    uint32_t largest_margin;
    uint32_t denial_count;
    uint32_t required_psram;
    uint32_t pressure_accepted;
    uint32_t pressure_terminal;
    uint32_t pressure_retained;
    uint32_t index;

    run_profile_authority(priorities);
    run_isr_contract(&isr_captures, &isr_overflows, &isr_notifications);
    run_priority_pressure(&application_high_water, &overflow_rejections);
    run_terminal_completion();
    run_partitioned_capacity();
    run_c6_admission(&required_free, &required_largest,
                     &free_margin, &largest_margin);
    run_admission_denials(&denial_count);
    run_s3_explicit_psram(&required_psram);
    run_synthetic_pressure(&pressure_accepted, &pressure_terminal,
                           &pressure_retained);

    CHECK(s_case_count == HP1_CASE_COUNT);
    for (index = 0u; index < s_case_count; ++index) {
        CHECK(s_cases[index].passed == 1u);
    }

    printf("{\"schema\":\"pulse.esp32.hp1-control-kernel-smoke.v1\","
           "\"status\":\"%s\",\"failures\":%" PRIu32
           ",\"case_count\":%" PRIu32 ",\"cases\":[",
           s_failures == 0u ? "PASS" : "FAIL",
           s_failures,
           s_case_count);
    for (index = 0u; index < s_case_count; ++index) {
        printf("%s{\"name\":\"%s\",\"status\":\"%s\"}",
               index == 0u ? "" : ",",
               s_cases[index].name,
               s_cases[index].passed != 0u ? "PASS" : "FAIL");
    }
    printf("],\"priorities\":{\"application\":%" PRIu32
           ",\"capability\":%" PRIu32 ",\"network\":%" PRIu32
           ",\"administration\":%" PRIu32
           ",\"safety_recovery\":%" PRIu32 "},"
           "\"isr\":{\"capacity\":%u,\"captures\":%" PRIu32
           ",\"notifications\":%" PRIu32 ",\"overflows\":%" PRIu32 "},"
           "\"queues\":{\"application_high_water\":%" PRIu32
           ",\"terminal_overflow_rejections\":%" PRIu32 "},"
           "\"c6_admission\":{\"fixed_reserve_bytes\":98304,"
           "\"required_internal_free_bytes\":%" PRIu32
           ",\"required_largest_block_bytes\":%" PRIu32
           ",\"remaining_internal_free_bytes\":%" PRIu32
           ",\"remaining_largest_block_bytes\":%" PRIu32
           ",\"denial_count\":%" PRIu32 "},"
           "\"s3_optimization\":{\"required_psram_free_bytes\":%" PRIu32
           ",\"portable\":false},"
           "\"pressure\":{\"rounds\":%u,\"accepted\":%" PRIu32
           ",\"terminal\":%" PRIu32 ",\"retained\":%" PRIu32 "}}\n",
           priorities[0], priorities[1], priorities[2], priorities[3],
           priorities[4],
           (unsigned)WDC_CONTROL_ISR_CAPACITY, isr_captures,
           isr_notifications, isr_overflows,
           application_high_water, overflow_rejections,
           required_free, required_largest, free_margin, largest_margin,
           denial_count, required_psram,
           (unsigned)HP1_PRESSURE_ROUNDS, pressure_accepted,
           pressure_terminal, pressure_retained);
    return s_failures == 0u ? 0 : 1;
}
