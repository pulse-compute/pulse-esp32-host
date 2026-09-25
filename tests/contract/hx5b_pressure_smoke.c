#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "wdc_events.h"
#include "wdc_extension_internal.h"

#define HX5B_QUEUE_ROUNDS 64u
#define HX5B_COMPLETION_ITERATIONS 128u
#define HX5B_NATIVE_FAULT_CYCLES 64u
#define HX5B_PRESSURE_BYTES (256u * 1024u)
#define HX5B_OPERATION_ECHO 0x4543484fu
#define HX5B_CASE_COUNT 7u

typedef struct CaseRecord {
    const char *name;
    uint32_t passed;
} CaseRecord;

static uint64_t s_now_ms = 1000u;
static uint32_t s_failures;
static CaseRecord s_cases[HX5B_CASE_COUNT];
static uint32_t s_case_count;
static pulse_extension_descriptor_v1 s_descriptor;
static WdcExtensionCandidate s_candidate;
static WdcExtensionRegistry s_registry;

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

int32_t wdc_elf_unload(WdcElfImage **image)
{
    if (image != NULL) {
        *image = NULL;
    }
    return WDC_ELF_OK;
}

static int32_t faulting_invoke(const pulse_extension_invoke_v1 *request)
{
    return request == NULL ? PULSE_EXT_ERR_ARGUMENT : PULSE_EXT_ERR_FAULT;
}

static void record_case(const char *name, uint32_t failures_before)
{
    CHECK(s_case_count < HX5B_CASE_COUNT);
    if (s_case_count < HX5B_CASE_COUNT) {
        s_cases[s_case_count].name = name;
        s_cases[s_case_count].passed = s_failures == failures_before ? 1u : 0u;
        s_case_count += 1u;
    }
}

static void service_fixture(void)
{
    memset(&s_descriptor, 0, sizeof(s_descriptor));
    memset(&s_candidate, 0, sizeof(s_candidate));
    memset(&s_registry, 0, sizeof(s_registry));
    s_descriptor.operation_count = 1u;
    s_descriptor.operation_ids[0] = HX5B_OPERATION_ECHO;
    s_descriptor.invoke_fn = faulting_invoke;
    s_candidate.state = WDC_EXTENSION_STARTED;
    s_candidate.descriptor = &s_descriptor;
    s_candidate.inspection.metadata.max_effect_completion_bytes = 32u;
    s_candidate.inspection.metadata.max_effect_request_bytes = 32u;
    s_candidate.inspection.metadata.queue_depth = 4u;
    s_candidate.inspection.metadata.task_stack_bytes = 4096u;
    s_registry.sealed = 1u;
    s_registry.count = 1u;
    s_registry.started_count = 1u;
    s_registry.candidates[0] = &s_candidate;
    CHECK(wdc_extension_services_bind(&s_registry) == WDC_EXTENSION_OK);
    wdc_extension_services_set_test_caller(&s_candidate);
}

static void service_reset(void)
{
    wdc_extension_services_unbind(&s_registry);
    memset(&s_descriptor, 0, sizeof(s_descriptor));
    memset(&s_candidate, 0, sizeof(s_candidate));
    memset(&s_registry, 0, sizeof(s_registry));
}

static void completion_for(uint64_t correlation,
                           const uint8_t *payload,
                           uint32_t payload_len,
                           pulse_extension_completion_v1 *out)
{
    memset(out, 0, sizeof(*out));
    out->struct_size = sizeof(*out);
    out->status = PULSE_EXT_OK;
    out->correlation_id = parts(correlation);
    out->payload_ptr = payload_len == 0u ? NULL : payload;
    out->payload_len = payload_len;
}

static int compare_u32(const void *left, const void *right)
{
    uint32_t a = *(const uint32_t *)left;
    uint32_t b = *(const uint32_t *)right;
    return a < b ? -1 : (a > b ? 1 : 0);
}

static void run_queue_pressure(uint32_t *accepted,
                               uint32_t *rejected,
                               uint32_t *recovered,
                               uint32_t *high_water)
{
    WdcEventQueue queue;
    uint32_t round;
    uint32_t next_sequence = 1u;
    uint32_t before = s_failures;
    *accepted = 0u;
    *rejected = 0u;
    *recovered = 0u;
    *high_water = 0u;
    CHECK(wdc_event_queue_init(&queue) == WDC_OK);
    for (round = 0u; round < HX5B_QUEUE_ROUNDS; ++round) {
        uint32_t index;
        for (index = 0u; index < WDC_EVENT_QUEUE_CAPACITY_DEFAULT; ++index) {
            WdcEvent event;
            uint32_t sequence = next_sequence++;
            CHECK(wdc_event_make(&event,
                                 0x5449434bu,
                                 WDC_EVENT_RESOURCE_NONE,
                                 sequence,
                                 (const uint8_t *)&sequence,
                                 (uint16_t)sizeof(sequence)) == WDC_OK);
            CHECK(wdc_event_queue_push(&queue, &event) == WDC_OK);
            *accepted += 1u;
        }
        if (wdc_event_queue_count(&queue) > *high_water) {
            *high_water = (uint32_t)wdc_event_queue_count(&queue);
        }
        {
            WdcEvent overflow;
            uint32_t sequence = next_sequence;
            CHECK(wdc_event_make(&overflow,
                                 0x5449434bu,
                                 WDC_EVENT_RESOURCE_NONE,
                                 sequence,
                                 (const uint8_t *)&sequence,
                                 (uint16_t)sizeof(sequence)) == WDC_OK);
            CHECK(wdc_event_queue_push(&queue, &overflow) == WDC_ERR_BUSY);
            *rejected += 1u;
        }
        for (index = 0u; index < WDC_EVENT_QUEUE_CAPACITY_DEFAULT; ++index) {
            WdcEvent event;
            uint32_t observed = 0u;
            uint32_t expected = next_sequence - WDC_EVENT_QUEUE_CAPACITY_DEFAULT + index;
            CHECK(wdc_event_queue_pop(&queue, &event) == WDC_OK);
            CHECK(event.payload_len == sizeof(observed));
            memcpy(&observed, event.payload, sizeof(observed));
            CHECK(observed == expected);
        }
        CHECK(wdc_event_queue_count(&queue) == 0u);
        *recovered += 1u;
    }
    CHECK(wdc_event_queue_dropped(&queue) == HX5B_QUEUE_ROUNDS);
    CHECK(*accepted == HX5B_QUEUE_ROUNDS * WDC_EVENT_QUEUE_CAPACITY_DEFAULT);
    CHECK(*rejected == HX5B_QUEUE_ROUNDS);
    CHECK(*recovered == HX5B_QUEUE_ROUNDS);
    CHECK(*high_water == WDC_EVENT_QUEUE_CAPACITY_DEFAULT);
    record_case("queue-saturation-recovery", before);
}

static void run_completion_pressure(uint32_t *late,
                                    uint32_t *duplicates,
                                    uint32_t *successful,
                                    uint32_t *latency_min,
                                    uint32_t *latency_p50,
                                    uint32_t *latency_p95,
                                    uint32_t *latency_max)
{
    static const uint8_t echo[] = {'h', 'x', '5', 'b'};
    uint32_t latencies[HX5B_COMPLETION_ITERATIONS];
    uint32_t iteration;
    uint32_t late_before = s_failures;
    *late = 0u;
    *duplicates = 0u;
    *successful = 0u;
    service_fixture();
    for (iteration = 0u; iteration < HX5B_COMPLETION_ITERATIONS; ++iteration) {
        pulse_extension_completion_v1 completion;
        WdcExtensionCompletionResult result;
        uint64_t late_correlation = (uint64_t)iteration * 2u + 1u;
        uint64_t success_correlation = late_correlation + 1u;
        uint64_t started = 10000u + (uint64_t)iteration * 100u;
        uint32_t latency = iteration % 8u;

        s_now_ms = started;
        CHECK(wdc_extension_services_begin_effect(
                  &s_candidate, late_correlation, started + 10u) == WDC_EXTENSION_OK);
        CHECK(wdc_extension_services_timeout_effect(
                  &s_candidate, late_correlation) == WDC_EXTENSION_OK);
        s_now_ms = started + 10u;
        completion_for(late_correlation, echo, sizeof(echo), &completion);
        CHECK(pulse_host_complete_effect_v1(&completion) == PULSE_EXT_ERR_STALE);
        *late += 1u;
        CHECK(wdc_extension_services_release_effect(
                  &s_candidate, late_correlation) == WDC_EXTENSION_OK);

        s_now_ms = started + 20u;
        CHECK(wdc_extension_services_begin_effect(
                  &s_candidate, success_correlation, started + 120u) ==
              WDC_EXTENSION_OK);
        s_now_ms += latency;
        completion_for(success_correlation, echo, sizeof(echo), &completion);
        CHECK(pulse_host_complete_effect_v1(&completion) == PULSE_EXT_OK);
        CHECK(pulse_host_complete_effect_v1(&completion) == PULSE_EXT_ERR_DUPLICATE);
        *duplicates += 1u;
        memset(&result, 0, sizeof(result));
        CHECK(wdc_extension_services_take_effect(
                  &s_candidate, success_correlation, &result) == WDC_EXTENSION_OK);
        CHECK(result.completed_ms >= result.started_ms);
        CHECK(result.payload_len == sizeof(echo));
        CHECK(memcmp(result.payload, echo, sizeof(echo)) == 0);
        latencies[iteration] = (uint32_t)(result.completed_ms - result.started_ms);
        *successful += 1u;
        CHECK(wdc_extension_services_release_effect(
                  &s_candidate, success_correlation) == WDC_EXTENSION_OK);
    }
    CHECK(wdc_extension_registry_requires_reset(&s_registry) == 0u);
    service_reset();
    CHECK(*late == HX5B_COMPLETION_ITERATIONS);
    record_case("deadline-late-completion-storm", late_before);

    {
        uint32_t duplicate_before = s_failures;
        CHECK(*duplicates == HX5B_COMPLETION_ITERATIONS);
        CHECK(*successful == HX5B_COMPLETION_ITERATIONS);
        record_case("duplicate-completion-recovery-storm", duplicate_before);
    }
    qsort(latencies,
          HX5B_COMPLETION_ITERATIONS,
          sizeof(latencies[0]),
          compare_u32);
    *latency_min = latencies[0];
    *latency_p50 = latencies[63];
    *latency_p95 = latencies[121];
    *latency_max = latencies[HX5B_COMPLETION_ITERATIONS - 1u];
    {
        uint32_t latency_before = s_failures;
        CHECK(*latency_min == 0u);
        CHECK(*latency_p50 == 3u);
        CHECK(*latency_p95 == 7u);
        CHECK(*latency_max == 7u);
        record_case("bounded-latency-distribution", latency_before);
    }
}

static void run_native_fault_pressure(uint32_t *faults, uint32_t *resets)
{
    uint32_t cycle;
    uint32_t before = s_failures;
    *faults = 0u;
    *resets = 0u;
    for (cycle = 0u; cycle < HX5B_NATIVE_FAULT_CYCLES; ++cycle) {
        pulse_extension_invoke_v1 request;
        service_fixture();
        memset(&request, 0, sizeof(request));
        request.struct_size = sizeof(request);
        request.operation_id = HX5B_OPERATION_ECHO;
        request.correlation_id = parts((uint64_t)cycle + 1u);
        request.deadline_ms = parts(s_now_ms + 1000u);
        CHECK(wdc_extension_candidate_invoke(&s_candidate, &request) ==
              WDC_EXTENSION_ERR_RESET_REQUIRED);
        CHECK(s_candidate.state == WDC_EXTENSION_RESET_REQUIRED);
        CHECK(wdc_extension_registry_requires_reset(&s_registry) == 1u);
        *faults += 1u;
        service_reset();
        CHECK(s_candidate.state == WDC_EXTENSION_EMPTY);
        CHECK(wdc_extension_registry_requires_reset(&s_registry) == 0u);
        *resets += 1u;
    }
    CHECK(*faults == HX5B_NATIVE_FAULT_CYCLES);
    CHECK(*resets == HX5B_NATIVE_FAULT_CYCLES);
    record_case("repeated-native-fault-reset-cycles", before);
}

int main(void)
{
    uint8_t *pressure;
    uint32_t accepted;
    uint32_t rejected;
    uint32_t recovered;
    uint32_t high_water;
    uint32_t late;
    uint32_t duplicates;
    uint32_t successful;
    uint32_t latency_min;
    uint32_t latency_p50;
    uint32_t latency_p95;
    uint32_t latency_max;
    uint32_t native_faults;
    uint32_t simulated_resets;
    uint32_t checksum = 0u;
    uint32_t index;
    uint32_t retained_bytes = 0u;
    uint32_t pressure_before = s_failures;

    memset(s_cases, 0, sizeof(s_cases));
    pressure = (uint8_t *)malloc(HX5B_PRESSURE_BYTES);
    CHECK(pressure != NULL);
    if (pressure != NULL) {
        for (index = 0u; index < HX5B_PRESSURE_BYTES; ++index) {
            pressure[index] = (uint8_t)(index * 33u + 17u);
            checksum += pressure[index];
        }
    }
    CHECK(checksum != 0u);
    record_case("pressure-reservation-held", pressure_before);

    run_queue_pressure(&accepted, &rejected, &recovered, &high_water);
    run_completion_pressure(&late,
                            &duplicates,
                            &successful,
                            &latency_min,
                            &latency_p50,
                            &latency_p95,
                            &latency_max);
    run_native_fault_pressure(&native_faults, &simulated_resets);
    free(pressure);
    pressure = NULL;
    {
        uint32_t release_before = s_failures;
        CHECK(pressure == NULL);
        CHECK(retained_bytes == 0u);
        record_case("pressure-reservation-released", release_before);
    }
    CHECK(s_case_count == HX5B_CASE_COUNT);

    printf("{\"schema\":\"pulse.esp32.hx5b-pressure-smoke.v1\","
           "\"status\":\"%s\",\"failures\":%u,\"case_count\":%u,"
           "\"queue\":{\"rounds\":%u,\"capacity\":%u,\"accepted\":%u,"
           "\"rejected\":%u,\"recovered_rounds\":%u,\"high_water\":%u},"
           "\"completions\":{\"iterations\":%u,\"late\":%u,"
           "\"duplicates\":%u,\"successful_recoveries\":%u},"
           "\"latency_ticks\":{\"sample_count\":%u,\"minimum\":%u,"
           "\"p50\":%u,\"p95\":%u,\"maximum\":%u},"
           "\"native_faults\":{\"cycles\":%u,\"faults\":%u,"
           "\"simulated_resets\":%u},"
           "\"memory_pressure\":{\"reserved_bytes\":%u,"
           "\"retained_bytes\":%u,\"checksum\":%u},\"cases\":[",
           s_failures == 0u ? "PASS" : "FAIL",
           s_failures,
           s_case_count,
           HX5B_QUEUE_ROUNDS,
           WDC_EVENT_QUEUE_CAPACITY_DEFAULT,
           accepted,
           rejected,
           recovered,
           high_water,
           HX5B_COMPLETION_ITERATIONS,
           late,
           duplicates,
           successful,
           HX5B_COMPLETION_ITERATIONS,
           latency_min,
           latency_p50,
           latency_p95,
           latency_max,
           HX5B_NATIVE_FAULT_CYCLES,
           native_faults,
           simulated_resets,
           HX5B_PRESSURE_BYTES,
           retained_bytes,
           checksum);
    for (index = 0u; index < s_case_count; ++index) {
        printf("%s{\"name\":\"%s\",\"status\":\"%s\"}",
               index == 0u ? "" : ",",
               s_cases[index].name,
               s_cases[index].passed != 0u ? "PASS" : "FAIL");
    }
    printf("]}\n");
    return s_failures == 0u ? 0 : 1;
}
