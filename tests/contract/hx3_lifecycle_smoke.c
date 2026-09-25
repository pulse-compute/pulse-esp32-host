#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "wdc_extension.h"
#include "wdc_extension_internal.h"

#define MOCK_CAPACITY 3u
#define CASE_CAPACITY 12u
#define REPEATED_CYCLES 32u

typedef struct MockExtension {
    int32_t init_result;
    int32_t start_result;
    int32_t quiesce_result;
    int32_t deinit_result;
    uint32_t partial_task_on_start_failure;
    uint32_t health_state;
    int32_t health_fault;
    uint32_t initialized;
    uint32_t live_task;
    uint32_t init_calls;
    uint32_t start_calls;
    uint32_t invoke_calls;
    uint32_t health_calls;
    uint32_t quiesce_calls;
    uint32_t deinit_calls;
} MockExtension;

typedef struct CaseResult {
    const char *name;
    uint32_t passed;
} CaseResult;

static MockExtension s_mocks[MOCK_CAPACITY];
static pulse_extension_descriptor_v1 s_descriptors[MOCK_CAPACITY];
static WdcExtensionCandidate s_candidates[MOCK_CAPACITY];
static WdcExtensionRegistry s_registry;
static WdcExtensionRegistry *s_bound_registry;
static uint64_t s_now_ms = 1000u;
static char s_sequence[256];
static uint32_t s_sequence_size;
static uint32_t s_failures;
static CaseResult s_cases[CASE_CAPACITY];
static uint32_t s_case_count;
static uint32_t s_simulated_resets;
static uint32_t s_init_unwind_reverse;
static uint32_t s_start_unwind_reverse;
static uint32_t s_repeated_retained_bytes;

#define CHECK(condition) \
    do { \
        if (!(condition)) { \
            s_failures += 1u; \
        } \
    } while (0)

static void sequence(char operation, uint32_t index)
{
    if (s_sequence_size + 2u < sizeof(s_sequence)) {
        s_sequence[s_sequence_size++] = operation;
        s_sequence[s_sequence_size++] = (char)('0' + index);
        s_sequence[s_sequence_size] = '\0';
    }
}

static pulse_u64_parts_v1 parts(uint64_t value)
{
    pulse_u64_parts_v1 result;
    result.lo = (uint32_t)value;
    result.hi = (uint32_t)(value >> 32u);
    return result;
}

static int32_t mock_init(uint32_t index, const pulse_extension_init_args_v1 *args)
{
    MockExtension *mock = &s_mocks[index];
    mock->init_calls += 1u;
    mock->initialized = 1u;
    sequence('I', index);
    if (args == NULL || args->struct_size != sizeof(*args) ||
        memcmp(args->extension_id, s_descriptors[index].extension_id, 16u) != 0) {
        return PULSE_EXT_ERR_ARGUMENT;
    }
    return mock->init_result;
}

static int32_t mock_start(uint32_t index)
{
    MockExtension *mock = &s_mocks[index];
    mock->start_calls += 1u;
    sequence('S', index);
    if (mock->start_result == PULSE_EXT_OK ||
        mock->partial_task_on_start_failure != 0u) {
        mock->live_task = 1u;
    }
    if (mock->start_result == PULSE_EXT_OK) {
        mock->health_state = PULSE_EXT_HEALTH_RUNNING;
    }
    return mock->start_result;
}

static int32_t mock_invoke(uint32_t index, const pulse_extension_invoke_v1 *request)
{
    s_mocks[index].invoke_calls += 1u;
    sequence('V', index);
    return request == NULL ? PULSE_EXT_ERR_ARGUMENT : PULSE_EXT_OK;
}

static int32_t mock_health(uint32_t index, pulse_extension_health_v1 *health)
{
    MockExtension *mock = &s_mocks[index];
    mock->health_calls += 1u;
    if (health == NULL || health->struct_size != sizeof(*health)) {
        return PULSE_EXT_ERR_ARGUMENT;
    }
    health->state = mock->health_state == 0u ? PULSE_EXT_HEALTH_INITIALIZED :
                                               mock->health_state;
    health->fault_status = mock->health_fault;
    health->pending_count = 0u;
    health->queue_high_water = mock->live_task != 0u ? 1u : 0u;
    health->task_stack_high_water_bytes = mock->live_task != 0u ? 512u : 0u;
    health->last_progress_ms = parts(s_now_ms);
    health->flags = 0u;
    memset(health->reserved, 0, sizeof(health->reserved));
    return PULSE_EXT_OK;
}

static int32_t mock_quiesce(uint32_t index,
                            const pulse_extension_quiesce_v1 *request)
{
    MockExtension *mock = &s_mocks[index];
    mock->quiesce_calls += 1u;
    sequence('Q', index);
    if (request == NULL || request->struct_size != sizeof(*request)) {
        return PULSE_EXT_ERR_ARGUMENT;
    }
    if (mock->quiesce_result == PULSE_EXT_OK) {
        mock->live_task = 0u;
        mock->health_state = PULSE_EXT_HEALTH_QUIESCED;
        mock->health_fault = PULSE_EXT_OK;
    }
    return mock->quiesce_result;
}

static int32_t mock_deinit(uint32_t index)
{
    MockExtension *mock = &s_mocks[index];
    mock->deinit_calls += 1u;
    sequence('D', index);
    if (mock->live_task != 0u) {
        return PULSE_EXT_ERR_STATE;
    }
    if (mock->deinit_result == PULSE_EXT_OK) {
        mock->initialized = 0u;
    }
    return mock->deinit_result;
}

#define DEFINE_SLOT(slot) \
    static int32_t init_##slot(const pulse_extension_init_args_v1 *args) \
    { \
        return mock_init(slot, args); \
    } \
    static int32_t start_##slot(void) \
    { \
        return mock_start(slot); \
    } \
    static int32_t invoke_##slot(const pulse_extension_invoke_v1 *request) \
    { \
        return mock_invoke(slot, request); \
    } \
    static int32_t health_##slot(pulse_extension_health_v1 *health) \
    { \
        return mock_health(slot, health); \
    } \
    static int32_t quiesce_##slot(const pulse_extension_quiesce_v1 *request) \
    { \
        return mock_quiesce(slot, request); \
    } \
    static int32_t deinit_##slot(void) \
    { \
        return mock_deinit(slot); \
    }

DEFINE_SLOT(0)
DEFINE_SLOT(1)
DEFINE_SLOT(2)

static pulse_extension_init_fn_v1 const s_init_functions[MOCK_CAPACITY] = {
    init_0, init_1, init_2,
};
static pulse_extension_start_fn_v1 const s_start_functions[MOCK_CAPACITY] = {
    start_0, start_1, start_2,
};
static pulse_extension_invoke_fn_v1 const s_invoke_functions[MOCK_CAPACITY] = {
    invoke_0, invoke_1, invoke_2,
};
static pulse_extension_health_fn_v1 const s_health_functions[MOCK_CAPACITY] = {
    health_0, health_1, health_2,
};
static pulse_extension_quiesce_fn_v1 const s_quiesce_functions[MOCK_CAPACITY] = {
    quiesce_0, quiesce_1, quiesce_2,
};
static pulse_extension_deinit_fn_v1 const s_deinit_functions[MOCK_CAPACITY] = {
    deinit_0, deinit_1, deinit_2,
};

static void fixture(uint32_t count)
{
    uint32_t index;
    memset(s_mocks, 0, sizeof(s_mocks));
    memset(s_descriptors, 0, sizeof(s_descriptors));
    memset(s_candidates, 0, sizeof(s_candidates));
    memset(&s_registry, 0, sizeof(s_registry));
    s_bound_registry = NULL;
    s_sequence_size = 0u;
    s_sequence[0] = '\0';
    s_registry.count = count;
    s_registry.sealed = 1u;
    for (index = 0u; index < count; ++index) {
        pulse_extension_descriptor_v1 *descriptor = &s_descriptors[index];
        WdcExtensionCandidate *candidate = &s_candidates[index];
        descriptor->extension_id[0] = (uint8_t)('A' + index);
        descriptor->event_count = 1u;
        descriptor->operation_count = 1u;
        descriptor->event_ids[0] = 0x100u + index;
        descriptor->operation_ids[0] = 0x200u + index;
        descriptor->init_fn = s_init_functions[index];
        descriptor->start_fn = s_start_functions[index];
        descriptor->invoke_fn = s_invoke_functions[index];
        descriptor->health_fn = s_health_functions[index];
        descriptor->quiesce_fn = s_quiesce_functions[index];
        descriptor->deinit_fn = s_deinit_functions[index];
        candidate->state = WDC_EXTENSION_REGISTRY_SEALED;
        candidate->descriptor = descriptor;
        candidate->image = (WdcElfImage *)(uintptr_t)(index + 1u);
        memcpy(candidate->inspection.metadata.extension_id,
               descriptor->extension_id,
               sizeof(descriptor->extension_id));
        candidate->inspection.metadata.queue_depth = 4u;
        candidate->inspection.metadata.task_stack_bytes = 4096u;
        candidate->inspection.metadata.max_event_payload_bytes = 64u;
        candidate->inspection.metadata.max_effect_request_bytes = 128u;
        candidate->inspection.metadata.max_effect_completion_bytes = 128u;
        s_registry.candidates[index] = candidate;
    }
}

static pulse_extension_init_args_v1 init_args(void)
{
    pulse_extension_init_args_v1 args;
    memset(&args, 0, sizeof(args));
    args.struct_size = sizeof(args);
    args.activation_epoch = parts(1u);
    args.boot_monotonic_ms = parts(s_now_ms);
    args.host_event_queue_capacity = 4u;
    args.host_max_event_payload_bytes = 64u;
    args.host_max_effect_completion_bytes = 128u;
    args.host_max_inflight_effects = 1u;
    return args;
}

static pulse_extension_quiesce_v1 quiesce_args(void)
{
    pulse_extension_quiesce_v1 args;
    memset(&args, 0, sizeof(args));
    args.struct_size = sizeof(args);
    args.reason = 1u;
    args.deadline_ms = parts(s_now_ms + 1000u);
    return args;
}

static pulse_extension_invoke_v1 invoke_args(void)
{
    pulse_extension_invoke_v1 args;
    memset(&args, 0, sizeof(args));
    args.struct_size = sizeof(args);
    args.operation_id = 0x200u;
    args.correlation_id = parts(1u);
    args.deadline_ms = parts(s_now_ms + 1000u);
    return args;
}

static uint32_t all_zero(const void *value, uint32_t size)
{
    const uint8_t *bytes = (const uint8_t *)value;
    uint32_t index;
    for (index = 0u; index < size; ++index) {
        if (bytes[index] != 0u) {
            return 0u;
        }
    }
    return 1u;
}

static void simulate_reset(void)
{
    memset(s_mocks, 0, sizeof(s_mocks));
    memset(s_candidates, 0, sizeof(s_candidates));
    memset(&s_registry, 0, sizeof(s_registry));
    s_bound_registry = NULL;
    s_simulated_resets += 1u;
}

static void case_happy_lifecycle(void)
{
    pulse_extension_init_args_v1 init = init_args();
    pulse_extension_quiesce_v1 quiesce = quiesce_args();
    pulse_extension_invoke_v1 invoke = invoke_args();
    pulse_extension_health_v1 health;
    fixture(1u);
    CHECK(wdc_extension_registry_initialize(&s_registry, &init) == WDC_EXTENSION_OK);
    CHECK(wdc_extension_registry_start(&s_registry) == WDC_EXTENSION_OK);
    CHECK(wdc_extension_candidate_invoke(&s_candidates[0], &invoke) == WDC_EXTENSION_OK);
    CHECK(wdc_extension_candidate_health(&s_candidates[0], &health) == WDC_EXTENSION_OK);
    CHECK(wdc_extension_registry_quiesce(&s_registry, &quiesce) == WDC_EXTENSION_OK);
    CHECK(wdc_extension_registry_deinitialize(&s_registry) == WDC_EXTENSION_OK);
    CHECK(wdc_extension_registry_unload_clean(&s_registry) == WDC_EXTENSION_OK);
    CHECK(strcmp(s_sequence, "I0S0V0Q0D0") == 0);
}

static void case_init_failure(void)
{
    pulse_extension_init_args_v1 init = init_args();
    fixture(3u);
    s_mocks[1].init_result = PULSE_EXT_ERR_FAULT;
    CHECK(wdc_extension_registry_initialize(&s_registry, &init) ==
          WDC_EXTENSION_ERR_LIFECYCLE);
    CHECK(strcmp(s_sequence, "I0I1D1D0") == 0);
    s_init_unwind_reverse = strcmp(s_sequence, "I0I1D1D0") == 0;
    CHECK(s_mocks[2].init_calls == 0u);
    CHECK(wdc_extension_registry_requires_reset(&s_registry) == 0u);
    CHECK(wdc_extension_registry_unload_clean(&s_registry) == WDC_EXTENSION_OK);
}

static void case_start_failure_before_task(void)
{
    pulse_extension_init_args_v1 init = init_args();
    fixture(3u);
    s_mocks[1].start_result = PULSE_EXT_ERR_FAULT;
    CHECK(wdc_extension_registry_initialize(&s_registry, &init) == WDC_EXTENSION_OK);
    CHECK(wdc_extension_registry_start(&s_registry) == WDC_EXTENSION_ERR_LIFECYCLE);
    CHECK(strcmp(s_sequence, "I0I1I2S0S1Q1Q0D2D1D0") == 0);
    s_start_unwind_reverse =
        strcmp(s_sequence, "I0I1I2S0S1Q1Q0D2D1D0") == 0;
    CHECK(wdc_extension_registry_requires_reset(&s_registry) == 0u);
    CHECK(wdc_extension_registry_unload_clean(&s_registry) == WDC_EXTENSION_OK);
}

static void case_start_failure_partial_task(void)
{
    pulse_extension_init_args_v1 init = init_args();
    fixture(1u);
    s_mocks[0].start_result = PULSE_EXT_ERR_FAULT;
    s_mocks[0].partial_task_on_start_failure = 1u;
    CHECK(wdc_extension_registry_initialize(&s_registry, &init) == WDC_EXTENSION_OK);
    CHECK(wdc_extension_registry_start(&s_registry) == WDC_EXTENSION_ERR_LIFECYCLE);
    CHECK(s_mocks[0].quiesce_calls == 1u);
    CHECK(s_mocks[0].live_task == 0u);
    CHECK(s_mocks[0].deinit_calls == 1u);
    CHECK(wdc_extension_registry_requires_reset(&s_registry) == 0u);
    CHECK(wdc_extension_registry_unload_clean(&s_registry) == WDC_EXTENSION_OK);
}

static void case_unhealthy_probation(void)
{
    pulse_extension_init_args_v1 init = init_args();
    fixture(1u);
    s_mocks[0].health_state = PULSE_EXT_HEALTH_FAULTED;
    s_mocks[0].health_fault = PULSE_EXT_ERR_FAULT;
    CHECK(wdc_extension_registry_initialize(&s_registry, &init) == WDC_EXTENSION_OK);
    CHECK(wdc_extension_registry_start(&s_registry) == WDC_EXTENSION_ERR_RESET_REQUIRED);
    CHECK(wdc_extension_registry_requires_reset(&s_registry) == 1u);
    CHECK(s_mocks[0].quiesce_calls == 1u);
    simulate_reset();
}

static void case_duplicate_start(void)
{
    pulse_extension_init_args_v1 init = init_args();
    pulse_extension_quiesce_v1 quiesce = quiesce_args();
    fixture(1u);
    CHECK(wdc_extension_registry_initialize(&s_registry, &init) == WDC_EXTENSION_OK);
    CHECK(wdc_extension_registry_start(&s_registry) == WDC_EXTENSION_OK);
    CHECK(wdc_extension_registry_start(&s_registry) == WDC_EXTENSION_ERR_STATE);
    CHECK(s_mocks[0].start_calls == 1u);
    CHECK(wdc_extension_registry_quiesce(&s_registry, &quiesce) == WDC_EXTENSION_OK);
    CHECK(wdc_extension_registry_deinitialize(&s_registry) == WDC_EXTENSION_OK);
    CHECK(wdc_extension_registry_unload_clean(&s_registry) == WDC_EXTENSION_OK);
}

static void case_invoke_before_start(void)
{
    pulse_extension_init_args_v1 init = init_args();
    pulse_extension_invoke_v1 invoke = invoke_args();
    fixture(1u);
    CHECK(wdc_extension_registry_initialize(&s_registry, &init) == WDC_EXTENSION_OK);
    CHECK(wdc_extension_candidate_invoke(&s_candidates[0], &invoke) ==
          WDC_EXTENSION_ERR_STATE);
    CHECK(s_mocks[0].invoke_calls == 0u);
    CHECK(wdc_extension_registry_deinitialize(&s_registry) == WDC_EXTENSION_OK);
    CHECK(wdc_extension_registry_unload_clean(&s_registry) == WDC_EXTENSION_OK);
}

static void case_invoke_after_quiesce(void)
{
    pulse_extension_init_args_v1 init = init_args();
    pulse_extension_quiesce_v1 quiesce = quiesce_args();
    pulse_extension_invoke_v1 invoke = invoke_args();
    fixture(1u);
    CHECK(wdc_extension_registry_initialize(&s_registry, &init) == WDC_EXTENSION_OK);
    CHECK(wdc_extension_registry_start(&s_registry) == WDC_EXTENSION_OK);
    CHECK(wdc_extension_registry_quiesce(&s_registry, &quiesce) == WDC_EXTENSION_OK);
    CHECK(wdc_extension_candidate_invoke(&s_candidates[0], &invoke) ==
          WDC_EXTENSION_ERR_STATE);
    CHECK(s_mocks[0].invoke_calls == 0u);
    CHECK(wdc_extension_registry_deinitialize(&s_registry) == WDC_EXTENSION_OK);
    CHECK(wdc_extension_registry_unload_clean(&s_registry) == WDC_EXTENSION_OK);
}

static void case_quiescence_timeout_reset(void)
{
    pulse_extension_init_args_v1 init = init_args();
    pulse_extension_quiesce_v1 quiesce = quiesce_args();
    fixture(1u);
    s_mocks[0].quiesce_result = PULSE_EXT_ERR_TIMEOUT;
    CHECK(wdc_extension_registry_initialize(&s_registry, &init) == WDC_EXTENSION_OK);
    CHECK(wdc_extension_registry_start(&s_registry) == WDC_EXTENSION_OK);
    CHECK(wdc_extension_registry_quiesce(&s_registry, &quiesce) ==
          WDC_EXTENSION_ERR_TIMEOUT);
    CHECK(wdc_extension_registry_requires_reset(&s_registry) == 1u);
    CHECK(wdc_extension_registry_deinitialize(&s_registry) ==
          WDC_EXTENSION_ERR_RESET_REQUIRED);
    simulate_reset();
    fixture(1u);
    init = init_args();
    CHECK(wdc_extension_registry_initialize(&s_registry, &init) == WDC_EXTENSION_OK);
    CHECK(wdc_extension_registry_deinitialize(&s_registry) == WDC_EXTENSION_OK);
    CHECK(wdc_extension_registry_unload_clean(&s_registry) == WDC_EXTENSION_OK);
}

static void case_duplicate_deinit(void)
{
    pulse_extension_init_args_v1 init = init_args();
    fixture(1u);
    CHECK(wdc_extension_registry_initialize(&s_registry, &init) == WDC_EXTENSION_OK);
    CHECK(wdc_extension_registry_deinitialize(&s_registry) == WDC_EXTENSION_OK);
    CHECK(wdc_extension_registry_deinitialize(&s_registry) == WDC_EXTENSION_ERR_STATE);
    CHECK(s_mocks[0].deinit_calls == 1u);
    CHECK(wdc_extension_registry_unload_clean(&s_registry) == WDC_EXTENSION_OK);
}

static void case_expired_quiesce_deadline(void)
{
    pulse_extension_init_args_v1 init = init_args();
    pulse_extension_quiesce_v1 quiesce = quiesce_args();
    fixture(1u);
    CHECK(wdc_extension_registry_initialize(&s_registry, &init) == WDC_EXTENSION_OK);
    CHECK(wdc_extension_registry_start(&s_registry) == WDC_EXTENSION_OK);
    quiesce.deadline_ms = parts(s_now_ms);
    CHECK(wdc_extension_registry_quiesce(&s_registry, &quiesce) ==
          WDC_EXTENSION_ERR_TIMEOUT);
    CHECK(s_mocks[0].quiesce_calls == 0u);
    CHECK(wdc_extension_registry_requires_reset(&s_registry) == 1u);
    simulate_reset();
}

static void case_repeated_cycles(void)
{
    uint32_t cycle;
    for (cycle = 0u; cycle < REPEATED_CYCLES; ++cycle) {
        pulse_extension_init_args_v1 init;
        pulse_extension_quiesce_v1 quiesce;
        fixture(1u);
        init = init_args();
        quiesce = quiesce_args();
        CHECK(wdc_extension_registry_initialize(&s_registry, &init) == WDC_EXTENSION_OK);
        CHECK(wdc_extension_registry_start(&s_registry) == WDC_EXTENSION_OK);
        CHECK(wdc_extension_registry_quiesce(&s_registry, &quiesce) == WDC_EXTENSION_OK);
        CHECK(wdc_extension_registry_deinitialize(&s_registry) == WDC_EXTENSION_OK);
        CHECK(wdc_extension_registry_unload_clean(&s_registry) == WDC_EXTENSION_OK);
        CHECK(s_mocks[0].live_task == 0u);
        CHECK(all_zero(&s_candidates[0], sizeof(s_candidates[0])) != 0u);
        CHECK(all_zero(&s_registry, sizeof(s_registry)) != 0u);
    }
    s_repeated_retained_bytes = 0u;
}

typedef void (*CaseFunction)(void);

static void run_case(const char *name, CaseFunction function)
{
    uint32_t before = s_failures;
    function();
    s_cases[s_case_count].name = name;
    s_cases[s_case_count].passed = s_failures == before;
    s_case_count += 1u;
}

int32_t wdc_extension_services_bind(WdcExtensionRegistry *registry)
{
    if (registry == NULL || s_bound_registry != NULL) {
        return WDC_EXTENSION_ERR_STATE;
    }
    s_bound_registry = registry;
    return WDC_EXTENSION_OK;
}

void wdc_extension_services_unbind(WdcExtensionRegistry *registry)
{
    if (s_bound_registry == registry) {
        s_bound_registry = NULL;
    }
}

WdcExtensionRegistry *wdc_extension_services_registry(void)
{
    return s_bound_registry;
}

void wdc_extension_services_cancel_candidate_effects(
    WdcExtensionCandidate *candidate)
{
    (void)candidate;
}

uint64_t wdc_extension_platform_monotonic_ms(void)
{
    return s_now_ms;
}

int32_t wdc_elf_unload(WdcElfImage **image)
{
    if (image == NULL || *image == NULL) {
        return WDC_ELF_ERR_ARGUMENT;
    }
    *image = NULL;
    return WDC_ELF_OK;
}

int main(void)
{
    uint32_t index;
    run_case("happy-lifecycle", case_happy_lifecycle);
    run_case("init-failure-reverse-unwind", case_init_failure);
    run_case("start-failure-before-task", case_start_failure_before_task);
    run_case("start-failure-after-partial-task", case_start_failure_partial_task);
    run_case("unhealthy-probation", case_unhealthy_probation);
    run_case("duplicate-start", case_duplicate_start);
    run_case("invoke-before-start", case_invoke_before_start);
    run_case("invoke-after-quiesce", case_invoke_after_quiesce);
    run_case("quiescence-timeout-reset", case_quiescence_timeout_reset);
    run_case("duplicate-deinit", case_duplicate_deinit);
    run_case("expired-quiesce-deadline", case_expired_quiesce_deadline);
    run_case("repeated-lifecycle-cycles", case_repeated_cycles);

    printf("{\"schema\":\"pulse.esp32.hx3-lifecycle-smoke.v1\",");
    printf("\"status\":\"%s\",", s_failures == 0u ? "PASS" : "FAIL");
    printf("\"case_count\":%u,\"cases\":[", s_case_count);
    for (index = 0u; index < s_case_count; ++index) {
        printf("%s{\"name\":\"%s\",\"status\":\"%s\"}",
               index == 0u ? "" : ",",
               s_cases[index].name,
               s_cases[index].passed != 0u ? "PASS" : "FAIL");
    }
    printf("],\"reverse_unwind\":{\"init\":%s,\"start\":%s},",
           s_init_unwind_reverse != 0u ? "true" : "false",
           s_start_unwind_reverse != 0u ? "true" : "false");
    printf("\"simulated_reset_count\":%u,", s_simulated_resets);
    printf("\"repeated_cycles\":%u,", REPEATED_CYCLES);
    printf("\"repeated_cycle_retained_bytes\":%u,", s_repeated_retained_bytes);
    printf("\"lifecycle_failures\":%u}\n", s_failures);
    return s_failures == 0u ? 0 : 1;
}
