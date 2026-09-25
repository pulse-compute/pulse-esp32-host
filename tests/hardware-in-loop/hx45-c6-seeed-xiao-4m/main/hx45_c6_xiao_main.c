#include <inttypes.h>
#include <pthread.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "esp_attr.h"
#include "esp_chip_info.h"
#include "esp_flash.h"
#include "esp_heap_caps.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "wdc_abi.h"
#include "wdc_diag.h"
#include "wdc_events.h"
#include "wdc_extension.h"
#include "wdc_extension_bridge.h"
#include "wdc_runtime.h"
#include "wdc_static_wasm.h"

#if !CONFIG_IDF_TARGET_ESP32C6
#error "The Seeed Studio HX4.5 harness is valid only for ESP32-C6"
#endif

#define HX45_BOARD_NAME "Seeed Studio XIAO ESP32C6"
#define HX45_FLASH_BYTES (4u * 1024u * 1024u)
#define HX45_EVENT_TICK 0x5449434bu
#define HX45_EVENT_UNKNOWN 0x554e4b4eu
#define HX45_OPERATION_ECHO 0x4543484fu
#define HX45_WARMUP_CYCLES 1u
#define HX45_MEASURED_CYCLES 5u
#define HX45_EVENT_WAIT_MS 2000u
#define HX45_QUIESCE_WINDOW_MS 2000u
#define HX45_STACK_HEADROOM_MIN_BYTES 512u
#define HX45_MAIN_STACK_HEADROOM_MIN_BYTES 1024u
#define HX45_INTERNAL_FREE_MIN_BYTES 8192u
#define HX45_INTERNAL_LARGEST_MIN_BYTES 4096u
#define HX45_RESET_MAGIC 0x48583435u
#define HX45_RESET_SCHEMA 1u
#define HX45_RESET_EXPECTED 1u
#define HX45_RESET_FAILURE 2u
#define HX45_DRIVER_PTHREAD_STACK_BYTES 16384u
#ifdef PULSE_HX5B_PRESSURE
#define HX5B_QUEUE_ROUNDS 8u
#define HX5B_LATENCY_SAMPLES \
    (HX5B_QUEUE_ROUNDS * WDC_EVENT_QUEUE_CAPACITY_DEFAULT)
#endif

extern const uint8_t pulse_hx45_extension_elf[];
extern const uint32_t pulse_hx45_extension_elf_len;
extern const uint32_t pulse_hx45_extension_build_token;
extern const char pulse_hx45_extension_sha256[];
extern const char pulse_hx45_common_wasm_sha256[];

typedef struct HeapSample {
    uint32_t internal_free;
    uint32_t internal_minimum;
    uint32_t internal_largest;
    uint32_t psram_free;
    uint32_t psram_minimum;
    uint32_t psram_largest;
} HeapSample;

typedef struct ResetEvidence {
    uint32_t magic;
    uint32_t schema;
    uint32_t build_token;
    uint32_t phase;
    uint32_t failures;
    uint32_t measured_cycles;
    uint32_t fault_code;
    int32_t fault_status;
    uint32_t reset_required;
    uint32_t breadcrumb_magic;
    uint32_t breadcrumb_generation;
    uint32_t minimum_internal_free;
    uint32_t minimum_internal_largest;
    uint32_t minimum_psram_free;
    uint32_t minimum_psram_largest;
    uint32_t minimum_stack_headroom;
    uint32_t minimum_main_stack_headroom;
    uint32_t maximum_queue_high_water;
    uint32_t checksum;
} ResetEvidence;

typedef struct CycleContext {
    WdcExtensionInspection inspection;
    WdcExtensionCandidate candidate;
    WdcExtensionRegistry registry;
    WdcRuntime runtime;
    WdcExtensionBridge bridge;
} CycleContext;

typedef struct CycleResult {
    HeapSample before;
    HeapSample after;
    uint32_t stack_headroom_bytes;
    uint32_t main_stack_headroom_bytes;
    uint32_t queue_high_water;
    uint32_t bridge_latency_ms;
    uint32_t load_ms;
    uint32_t start_ms;
    uint32_t quiesce_ms;
    uint32_t deinit_ms;
    uint32_t internal_recovered;
    uint32_t psram_recovered;
} CycleResult;

RTC_NOINIT_ATTR static ResetEvidence s_reset_evidence;
static CycleContext s_cycle;
static uint32_t s_failures;
static uint32_t s_minimum_internal_free = UINT32_MAX;
static uint32_t s_minimum_internal_largest = UINT32_MAX;
static uint32_t s_minimum_psram_free;
static uint32_t s_minimum_psram_largest;
static uint32_t s_minimum_stack_headroom = UINT32_MAX;
static uint32_t s_minimum_main_stack_headroom = UINT32_MAX;
static uint32_t s_maximum_queue_high_water;
static uint32_t s_last_load_ms;
static uint32_t s_last_start_ms;

static uint64_t monotonic_ms(void)
{
    int64_t value = esp_timer_get_time();
    return value <= 0 ? 0u : (uint64_t)value / 1000u;
}

static uint32_t elapsed_ms(uint64_t started)
{
    uint64_t finished = monotonic_ms();
    uint64_t elapsed = finished >= started ? finished - started : 0u;
    return elapsed > UINT32_MAX ? UINT32_MAX : (uint32_t)elapsed;
}

static pulse_u64_parts_v1 u64_parts(uint64_t value)
{
    pulse_u64_parts_v1 parts;
    parts.lo = (uint32_t)value;
    parts.hi = (uint32_t)(value >> 32u);
    return parts;
}

static HeapSample heap_sample(void)
{
    HeapSample sample;
    sample.internal_free =
        (uint32_t)heap_caps_get_free_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
    sample.internal_minimum =
        (uint32_t)heap_caps_get_minimum_free_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
    sample.internal_largest =
        (uint32_t)heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
    /* Keep zero-valued fields in the stable marker schema. This board has no
     * PSRAM and all extension/WAMR allocations must survive in internal RAM. */
    sample.psram_free = 0u;
    sample.psram_minimum = 0u;
    sample.psram_largest = 0u;
    if (sample.internal_free < s_minimum_internal_free) {
        s_minimum_internal_free = sample.internal_free;
    }
    if (sample.internal_largest < s_minimum_internal_largest) {
        s_minimum_internal_largest = sample.internal_largest;
    }
    return sample;
}

static HeapSample print_heap_stage(uint32_t cycle, const char *stage)
{
    HeapSample sample = heap_sample();
    printf("PULSE_HX45_HEAP {\"cycle\":%" PRIu32
           ",\"stage\":\"%s\",\"internal_free\":%" PRIu32
           ",\"internal_minimum\":%" PRIu32
           ",\"internal_largest\":%" PRIu32
           ",\"psram_free\":%" PRIu32
           ",\"psram_minimum\":%" PRIu32
           ",\"psram_largest\":%" PRIu32 "}\n",
           cycle,
           stage,
           sample.internal_free,
           sample.internal_minimum,
           sample.internal_largest,
           sample.psram_free,
           sample.psram_minimum,
           sample.psram_largest);
    fflush(stdout);
    return sample;
}

static bool record_case(const char *name, int32_t observed, int32_t expected)
{
    bool passed = observed == expected;
    if (!passed) {
        s_failures += 1u;
    }
    printf("PULSE_HX45_CASE {\"name\":\"%s\",\"observed\":%" PRId32
           ",\"expected\":%" PRId32 ",\"status\":\"%s\"}\n",
           name,
           observed,
           expected,
           passed ? "PASS" : "FAIL");
    fflush(stdout);
    return passed;
}

static bool record_condition(const char *name, bool condition)
{
    return record_case(name, condition ? 1 : 0, 1);
}

static bool record_heap_headroom(const HeapSample *sample)
{
    bool passed = true;
    passed = record_condition("internal-free-headroom",
                              sample->internal_free >=
                                  HX45_INTERNAL_FREE_MIN_BYTES) && passed;
    passed = record_condition("internal-largest-headroom",
                              sample->internal_largest >=
                                  HX45_INTERNAL_LARGEST_MIN_BYTES) && passed;
    return passed;
}

static uint32_t sample_main_stack(uint32_t cycle, const char *stage)
{
    uint32_t headroom = (uint32_t)uxTaskGetStackHighWaterMark(NULL);
    if (headroom < s_minimum_main_stack_headroom) {
        s_minimum_main_stack_headroom = headroom;
    }
    printf("PULSE_HX45_MAIN_STACK {\"cycle\":%" PRIu32
           ",\"stage\":\"%s\",\"headroom_bytes\":%" PRIu32 "}\n",
           cycle,
           stage,
           headroom);
    fflush(stdout);
    return headroom;
}

static int32_t allow_effect(void *context,
                            uint32_t opcode,
                            const uint8_t *request,
                            uint32_t request_len,
                            int32_t *decision)
{
    (void)context;
    (void)request;
    (void)request_len;
    if (decision == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    *decision = opcode == WDC_OP_EFFECT_INVOKE ? WDC_OK :
                                                    WDC_ERR_CAPABILITY_DENIED;
    return WDC_OK;
}

static pulse_extension_init_args_v1 init_args(uint32_t cycle)
{
    pulse_extension_init_args_v1 args;
    memset(&args, 0, sizeof(args));
    args.struct_size = sizeof(args);
    args.activation_epoch = u64_parts((uint64_t)cycle + 1u);
    args.boot_monotonic_ms = u64_parts(monotonic_ms());
    args.host_event_queue_capacity = WDC_EVENT_QUEUE_CAPACITY_DEFAULT;
    args.host_max_event_payload_bytes = WDC_EVENT_PAYLOAD_MAX;
    args.host_max_effect_completion_bytes = WDC_EXTENSION_EFFECT_PAYLOAD_MAX;
    args.host_max_inflight_effects = 1u;
    return args;
}

static bool wait_for_extension_event(void)
{
    uint32_t elapsed = 0u;
    while (wdc_events_pending() == 0u && elapsed < HX45_EVENT_WAIT_MS) {
        vTaskDelay(pdMS_TO_TICKS(10u));
        elapsed += 10u;
    }
    return wdc_events_pending() != 0u;
}

static bool load_and_start_extension(uint32_t cycle)
{
    WdcExtensionProfile profile;
    pulse_extension_init_args_v1 args;
    uint64_t started;
    int32_t status;

    memset(&s_cycle, 0, sizeof(s_cycle));
    s_last_load_ms = 0u;
    s_last_start_ms = 0u;
    if (!record_case("events-init", wdc_events_init(), WDC_OK)) {
        return false;
    }
    wdc_extension_profile_esp32c6(&profile);
    status = wdc_extension_inspect(pulse_hx45_extension_elf,
                                   pulse_hx45_extension_elf_len,
                                   &profile,
                                   &s_cycle.inspection);
    if (!record_case("elf-inspect", status, WDC_EXTENSION_OK)) {
        return false;
    }
    started = monotonic_ms();
    status = wdc_extension_load_descriptor(pulse_hx45_extension_elf,
                                           pulse_hx45_extension_elf_len,
                                           &s_cycle.inspection,
                                           &s_cycle.candidate);
    s_last_load_ms = elapsed_ms(started);
    if (!record_case("elf-load-descriptor", status, WDC_EXTENSION_OK)) {
        return false;
    }
    wdc_extension_registry_init(&s_cycle.registry);
    if (!record_case("registry-add",
                     wdc_extension_registry_add(&s_cycle.registry,
                                                &s_cycle.candidate),
                     WDC_EXTENSION_OK) ||
        !record_case("registry-seal",
                     wdc_extension_registry_seal(&s_cycle.registry),
                     WDC_EXTENSION_OK)) {
        return false;
    }
    args = init_args(cycle);
    if (!record_case("extension-initialize",
                     wdc_extension_registry_initialize(&s_cycle.registry, &args),
                     WDC_EXTENSION_OK)) {
        return false;
    }
    started = monotonic_ms();
    status = wdc_extension_registry_start(&s_cycle.registry);
    s_last_start_ms = elapsed_ms(started);
    if (!record_case("extension-start", status, WDC_EXTENSION_OK)) {
        return false;
    }
    return record_condition("extension-event-arrived", wait_for_extension_event());
}

static bool configure_wasm_and_bridge(void)
{
    WdcRuntimeConfig runtime_config = wdc_runtime_default_config();
    WdcExtensionBridgeConfig bridge_config = wdc_extension_bridge_default_config();

    if (!record_case("wamr-init",
                     wdc_runtime_init(&s_cycle.runtime, &runtime_config),
                     WDC_OK) ||
        !record_case("common-wasm-load",
                     wdc_runtime_load_static(&s_cycle.runtime,
                                             wdc_hx4_event_effect_wasm,
                                             wdc_hx4_event_effect_wasm_len),
                     WDC_OK) ||
        !record_case("common-wasm-exports",
                     wdc_runtime_lookup_exports(&s_cycle.runtime),
                     WDC_OK) ||
        !record_case("common-wasm-init",
                     wdc_runtime_call_init(&s_cycle.runtime),
                     WDC_OK)) {
        return false;
    }
    wdc_host_call_set_authorizer(allow_effect, NULL);
    bridge_config.effect_timeout_ms = 1000u;
    bridge_config.max_effect_request_bytes = 32u;
    bridge_config.max_effect_completion_bytes = 32u;
    bridge_config.expected_event_id = HX45_EVENT_TICK;
    bridge_config.expected_operation_id = HX45_OPERATION_ECHO;
    return record_case("bridge-init",
                       wdc_extension_bridge_init(&s_cycle.bridge,
                                                 &s_cycle.registry,
                                                 &s_cycle.runtime,
                                                 &bridge_config),
                       WDC_OK);
}

static bool exercise_unknown_event(void)
{
    WdcEvent event;
    static const uint8_t payload[] = {'b', 'a', 'd'};
    if (!record_case("unknown-event-make",
                     wdc_event_make(&event,
                                    HX45_EVENT_UNKNOWN,
                                    WDC_EVENT_RESOURCE_NONE,
                                    monotonic_ms(),
                                    payload,
                                    sizeof(payload)),
                     WDC_OK) ||
        !record_case("unknown-event-post", wdc_events_post(&event), WDC_OK)) {
        return false;
    }
    return record_case("unknown-event-rejected-on-target",
                       wdc_extension_bridge_process_next(&s_cycle.bridge),
                       WDC_ERR_UNSUPPORTED_OPCODE);
}

#ifdef PULSE_HX5B_PRESSURE
static void sort_u32(uint32_t *values, uint32_t count)
{
    uint32_t index;
    for (index = 1u; index < count; ++index) {
        uint32_t value = values[index];
        uint32_t position = index;
        while (position != 0u && values[position - 1u] > value) {
            values[position] = values[position - 1u];
            position -= 1u;
        }
        values[position] = value;
    }
}

static bool run_hx5b_queue_pressure(void)
{
    static const uint8_t payload[] = {'h', 'x', '5', 'b'};
    uint32_t latencies[HX5B_LATENCY_SAMPLES];
    uint32_t latency_count = 0u;
    uint32_t accepted = 0u;
    uint32_t rejected = 0u;
    uint32_t recovered = 0u;
    uint32_t high_water = 0u;
    uint32_t dropped_before = wdc_events_dropped();
    uint32_t round;
    bool saturation_ok = true;
    bool drain_ok = true;
    bool roundtrip_ok = true;
    bool passed = true;

    memset(latencies, 0, sizeof(latencies));
    for (round = 0u; round < HX5B_QUEUE_ROUNDS; ++round) {
        uint32_t index;
        for (index = 0u; index < WDC_EVENT_QUEUE_CAPACITY_DEFAULT; ++index) {
            WdcEvent event;
            int32_t status = wdc_event_make(&event,
                                            HX45_EVENT_TICK,
                                            WDC_EVENT_RESOURCE_NONE,
                                            monotonic_ms(),
                                            payload,
                                            sizeof(payload));
            if (status != WDC_OK || wdc_events_post(&event) != WDC_OK) {
                saturation_ok = false;
            } else {
                accepted += 1u;
            }
        }
        {
            WdcEventQueueStats stats;
            WdcEvent overflow;
            int32_t status;
            wdc_events_get_stats(&stats);
            if (stats.pending > high_water) {
                high_water = (uint32_t)stats.pending;
            }
            if (stats.pending != WDC_EVENT_QUEUE_CAPACITY_DEFAULT) {
                saturation_ok = false;
            }
            status = wdc_event_make(&overflow,
                                    HX45_EVENT_TICK,
                                    WDC_EVENT_RESOURCE_NONE,
                                    monotonic_ms(),
                                    payload,
                                    sizeof(payload));
            if (status != WDC_OK || wdc_events_post(&overflow) != WDC_ERR_BUSY) {
                saturation_ok = false;
            } else {
                rejected += 1u;
            }
        }
        for (index = 0u; index < WDC_EVENT_QUEUE_CAPACITY_DEFAULT; ++index) {
            const WdcExtensionBridgeReport *report;
            if (wdc_extension_bridge_process_next(&s_cycle.bridge) != WDC_OK) {
                roundtrip_ok = false;
                continue;
            }
            report = wdc_extension_bridge_get_report(&s_cycle.bridge);
            if (report == NULL || report->effect_invoked != 1u ||
                report->completion_accepted != 1u ||
                latency_count >= HX5B_LATENCY_SAMPLES) {
                roundtrip_ok = false;
            } else {
                latencies[latency_count++] = report->completion_latency_ms;
            }
        }
        if (wdc_events_pending() != 0u) {
            drain_ok = false;
        } else {
            recovered += 1u;
        }
    }
    saturation_ok = saturation_ok &&
                    accepted == HX5B_LATENCY_SAMPLES &&
                    rejected == HX5B_QUEUE_ROUNDS &&
                    high_water == WDC_EVENT_QUEUE_CAPACITY_DEFAULT &&
                    wdc_events_dropped() - dropped_before == HX5B_QUEUE_ROUNDS;
    drain_ok = drain_ok && recovered == HX5B_QUEUE_ROUNDS;
    roundtrip_ok = roundtrip_ok && latency_count == HX5B_LATENCY_SAMPLES;
    passed = record_condition("hx5b-queue-saturation", saturation_ok) && passed;
    passed = record_condition("hx5b-queue-drain-recovery", drain_ok) && passed;
    passed = record_condition("hx5b-pressure-roundtrip", roundtrip_ok) && passed;
    sort_u32(latencies, latency_count);
    printf("PULSE_HX45_PRESSURE {\"status\":\"%s\",\"campaign\":\"HX5b\""
           ",\"queue_rounds\":%" PRIu32
           ",\"accepted_events\":%" PRIu32
           ",\"rejected_events\":%" PRIu32
           ",\"recovered_rounds\":%" PRIu32
           ",\"queue_high_water\":%" PRIu32
           ",\"end_pending\":%" PRIu32
           ",\"latency_sample_count\":%" PRIu32
           ",\"latency_minimum_ms\":%" PRIu32
           ",\"latency_p50_ms\":%" PRIu32
           ",\"latency_p95_ms\":%" PRIu32
           ",\"latency_maximum_ms\":%" PRIu32 "}\n",
           passed ? "PASS" : "FAIL",
           (uint32_t)HX5B_QUEUE_ROUNDS,
           accepted,
           rejected,
           recovered,
           high_water,
           (uint32_t)wdc_events_pending(),
           latency_count,
           latency_count == 0u ? 0u : latencies[0],
           latency_count == 0u ? 0u : latencies[(latency_count - 1u) / 2u],
           latency_count == 0u ? 0u :
               latencies[((latency_count * 95u + 99u) / 100u) - 1u],
           latency_count == 0u ? 0u : latencies[latency_count - 1u]);
    fflush(stdout);
    return passed;
}
#endif

static bool run_clean_cycle(uint32_t cycle, bool measured, CycleResult *out)
{
    const WdcExtensionBridgeReport *bridge_report;
    HeapSample active;
    pulse_extension_health_v1 health;
    pulse_extension_quiesce_v1 quiesce;
    int32_t status;
    bool passed = true;

    memset(out, 0, sizeof(*out));
    out->before = print_heap_stage(cycle, "before");
    if (!load_and_start_extension(cycle)) {
        return false;
    }
    out->load_ms = s_last_load_ms;
    out->start_ms = s_last_start_ms;
    (void)print_heap_stage(cycle, "after-extension-start");
    if (!configure_wasm_and_bridge()) {
        return false;
    }
    active = print_heap_stage(cycle, "after-wamr-load");
    passed = record_heap_headroom(&active) && passed;

    status = wdc_extension_bridge_process_next(&s_cycle.bridge);
    if (!record_case("event-effect-roundtrip", status, WDC_OK)) {
        return false;
    }
    bridge_report = wdc_extension_bridge_get_report(&s_cycle.bridge);
    passed = record_condition("roundtrip-report-present", bridge_report != NULL) && passed;
    if (bridge_report != NULL) {
        passed = record_condition("roundtrip-effect-invoked",
                                  bridge_report->effect_invoked == 1u) && passed;
        passed = record_condition("roundtrip-completion-accepted",
                                  bridge_report->completion_accepted == 1u) && passed;
        passed = record_condition("roundtrip-identities",
                                  bridge_report->event_type == HX45_EVENT_TICK &&
                                      bridge_report->operation_id == HX45_OPERATION_ECHO) && passed;
        passed = record_condition("roundtrip-echo",
                                  bridge_report->completion_payload_len == 8u &&
                                      memcmp(bridge_report->completion_payload,
                                             "hx4-echo",
                                             8u) == 0) && passed;
        out->bridge_latency_ms = bridge_report->completion_latency_ms;
    }
    (void)print_heap_stage(cycle, "after-roundtrip");
#ifdef PULSE_HX5B_PRESSURE
    if (measured && cycle == 1u) {
        passed = run_hx5b_queue_pressure() && passed;
    }
#endif

    /*
     * The sealed extension refreshes its historical FreeRTOS stack watermark
     * every 16 idle queue polls. Wait beyond that interval at the default
     * 100 Hz tick before taking the authoritative health sample.
     */
    vTaskDelay(pdMS_TO_TICKS(250u));
    out->main_stack_headroom_bytes = sample_main_stack(cycle, "after-roundtrip");
    passed = record_condition("main-stack-headroom",
                              out->main_stack_headroom_bytes >=
                                  HX45_MAIN_STACK_HEADROOM_MIN_BYTES) && passed;

    memset(&health, 0, sizeof(health));
    health.struct_size = sizeof(health);
    status = wdc_extension_candidate_health(&s_cycle.candidate, &health);
    passed = record_case("extension-health", status, WDC_EXTENSION_OK) && passed;
    passed = record_condition("extension-health-running",
                              health.state == PULSE_EXT_HEALTH_RUNNING) && passed;
    passed = record_condition("extension-pending-zero", health.pending_count == 0u) && passed;
    passed = record_condition("extension-stack-measured",
                              health.task_stack_high_water_bytes >=
                                      HX45_STACK_HEADROOM_MIN_BYTES &&
                                  health.task_stack_high_water_bytes <=
                                      s_cycle.inspection.metadata.task_stack_bytes) && passed;
    passed = record_condition("extension-queue-measured",
                              health.queue_high_water >= 1u &&
                                  health.queue_high_water <=
                                      s_cycle.inspection.metadata.queue_depth) && passed;
    out->stack_headroom_bytes = health.task_stack_high_water_bytes;
    out->queue_high_water = health.queue_high_water;
    if (out->stack_headroom_bytes < s_minimum_stack_headroom) {
        s_minimum_stack_headroom = out->stack_headroom_bytes;
    }
    if (out->queue_high_water > s_maximum_queue_high_water) {
        s_maximum_queue_high_water = out->queue_high_water;
    }

    if (measured && cycle == 1u) {
        passed = exercise_unknown_event() && passed;
    }
    passed = record_case("common-wasm-health",
                         wdc_runtime_call_health(&s_cycle.runtime),
                         WDC_OK) && passed;
    passed = record_case("common-wasm-shutdown",
                         wdc_runtime_call_shutdown(&s_cycle.runtime,
                                                   WDC_SHUTDOWN_NORMAL),
                         WDC_OK) && passed;

    wdc_extension_bridge_deinit(&s_cycle.bridge);
    wdc_host_call_clear_authorizer();
    wdc_runtime_teardown(&s_cycle.runtime);
    memset(&quiesce, 0, sizeof(quiesce));
    quiesce.struct_size = sizeof(quiesce);
    quiesce.reason = 0x48573435u;
    quiesce.deadline_ms = u64_parts(monotonic_ms() + HX45_QUIESCE_WINDOW_MS);
    {
        uint64_t started = monotonic_ms();
        status = wdc_extension_registry_quiesce(&s_cycle.registry, &quiesce);
        out->quiesce_ms = elapsed_ms(started);
    }
    passed = record_case("extension-quiesce", status, WDC_EXTENSION_OK) && passed;
    passed = record_condition("extension-no-reset-required",
                              wdc_extension_registry_requires_reset(
                                  &s_cycle.registry) == 0u) && passed;
    {
        uint64_t started = monotonic_ms();
        status = wdc_extension_registry_deinitialize(&s_cycle.registry);
        out->deinit_ms = elapsed_ms(started);
    }
    passed = record_case("extension-deinitialize", status, WDC_EXTENSION_OK) && passed;
    passed = record_case("extension-unload",
                         wdc_extension_registry_unload_clean(&s_cycle.registry),
                         WDC_EXTENSION_OK) && passed;
    (void)wdc_events_init();
    vTaskDelay(pdMS_TO_TICKS(20u));
    out->after = print_heap_stage(cycle, "after-clean-unload");
    out->internal_recovered =
        out->after.internal_free == out->before.internal_free ? 1u : 0u;
    out->psram_recovered =
        out->after.psram_free == out->before.psram_free ? 1u : 0u;
    if (measured) {
        passed = record_condition("internal-heap-recovered",
                                  out->internal_recovered != 0u) && passed;
    }

    printf("PULSE_HX45_CYCLE {\"cycle\":%" PRIu32
           ",\"measured\":%s,\"status\":\"%s\""
           ",\"internal_before\":%" PRIu32
           ",\"internal_after\":%" PRIu32
           ",\"psram_before\":%" PRIu32
           ",\"psram_after\":%" PRIu32
           ",\"stack_headroom_bytes\":%" PRIu32
           ",\"main_stack_headroom_bytes\":%" PRIu32
           ",\"queue_high_water\":%" PRIu32
           ",\"completion_latency_ms\":%" PRIu32
           ",\"load_ms\":%" PRIu32 ",\"start_ms\":%" PRIu32
           ",\"quiesce_ms\":%" PRIu32 ",\"deinit_ms\":%" PRIu32 "}\n",
           cycle,
           measured ? "true" : "false",
           passed ? "PASS" : "FAIL",
           out->before.internal_free,
           out->after.internal_free,
           out->before.psram_free,
           out->after.psram_free,
           out->stack_headroom_bytes,
           out->main_stack_headroom_bytes,
           out->queue_high_water,
           out->bridge_latency_ms,
           out->load_ms,
           out->start_ms,
           out->quiesce_ms,
           out->deinit_ms);
    fflush(stdout);
    return passed;
}

static bool run_real_wasm_trap(void)
{
    WdcRuntime runtime;
    WdcRuntimeConfig config = wdc_runtime_default_config();
    WdcEvent event;
    const WdcRuntimeReport *report;
    WdcRuntimeOutcome runtime_outcome = WDC_RUNTIME_OUTCOME_NOT_STARTED;
    HeapSample before = print_heap_stage(900u, "before-real-wasm-trap");
    HeapSample active;
    HeapSample after;
    int32_t observed = WDC_ERR_UNKNOWN;
    bool passed = true;

    memset(&runtime, 0, sizeof(runtime));
    passed = record_case("trap-wamr-init",
                         wdc_runtime_init(&runtime, &config),
                         WDC_OK) && passed;
    passed = record_case("trap-wasm-load",
                         wdc_runtime_load_static(&runtime,
                                                 wdc_static_event_trap_wasm,
                                                 wdc_static_event_trap_wasm_len),
                         WDC_OK) && passed;
    passed = record_case("trap-wasm-exports",
                         wdc_runtime_lookup_exports(&runtime),
                         WDC_OK) && passed;
    passed = record_case("trap-wasm-init-call",
                         wdc_runtime_call_init(&runtime),
                         WDC_OK) && passed;
    if (passed && wdc_event_make(&event,
                                 WDC_EVENT_SYSTEM_BOOT,
                                 WDC_EVENT_RESOURCE_NONE,
                                 monotonic_ms(),
                                 NULL,
                                 0u) == WDC_OK) {
        observed = wdc_runtime_dispatch_event(&runtime, &event);
    }
    report = wdc_runtime_get_report(&runtime);
    passed = record_case("real-wasm-event-trap",
                         observed,
                         WDC_ERR_CONTRACT_VIOLATION) && passed;
    passed = record_condition("real-wasm-trap-outcome",
                              report != NULL &&
                                  report->outcome ==
                                      WDC_RUNTIME_OUTCOME_GUEST_TRAPPED) && passed;
    if (report != NULL) {
        runtime_outcome = report->outcome;
    }
    passed = record_condition("trap-main-stack-headroom",
                              sample_main_stack(900u, "after-real-wasm-trap") >=
                                  HX45_MAIN_STACK_HEADROOM_MIN_BYTES) && passed;
    active = print_heap_stage(900u, "during-real-wasm-trap");
    passed = record_heap_headroom(&active) && passed;
    wdc_runtime_teardown(&runtime);
    vTaskDelay(pdMS_TO_TICKS(20u));
    after = print_heap_stage(900u, "after-real-wasm-trap");
    passed = record_condition("trap-internal-heap-recovered",
                              before.internal_free == after.internal_free) && passed;
    printf("PULSE_HX45_TRAP {\"status\":\"%s\",\"observed\":%" PRId32
           ",\"expected\":%d,\"runtime_outcome\":%u}\n",
           passed ? "PASS" : "FAIL",
           observed,
           WDC_ERR_CONTRACT_VIOLATION,
           (unsigned)runtime_outcome);
    fflush(stdout);
    return passed;
}

static uint32_t evidence_checksum(const ResetEvidence *record)
{
    const uint8_t *bytes = (const uint8_t *)record;
    uint32_t hash = 2166136261u;
    size_t index;
    for (index = 0u; index < offsetof(ResetEvidence, checksum); ++index) {
        hash ^= bytes[index];
        hash *= 16777619u;
    }
    return hash;
}

static bool reset_evidence_valid(void)
{
    return s_reset_evidence.magic == HX45_RESET_MAGIC &&
           s_reset_evidence.schema == HX45_RESET_SCHEMA &&
           s_reset_evidence.build_token == pulse_hx45_extension_build_token &&
           s_reset_evidence.checksum == evidence_checksum(&s_reset_evidence);
}

static void save_reset_evidence(uint32_t phase,
                                uint32_t fault_code,
                                int32_t fault_status,
                                uint32_t reset_required,
                                const WdcDiagBreadcrumb *breadcrumb)
{
    memset(&s_reset_evidence, 0, sizeof(s_reset_evidence));
    s_reset_evidence.magic = HX45_RESET_MAGIC;
    s_reset_evidence.schema = HX45_RESET_SCHEMA;
    s_reset_evidence.build_token = pulse_hx45_extension_build_token;
    s_reset_evidence.phase = phase;
    s_reset_evidence.failures = s_failures;
    s_reset_evidence.measured_cycles = HX45_MEASURED_CYCLES;
    s_reset_evidence.fault_code = fault_code;
    s_reset_evidence.fault_status = fault_status;
    s_reset_evidence.reset_required = reset_required;
    if (breadcrumb != NULL) {
        s_reset_evidence.breadcrumb_magic = breadcrumb->magic;
        s_reset_evidence.breadcrumb_generation = breadcrumb->generation;
    }
    s_reset_evidence.minimum_internal_free = s_minimum_internal_free;
    s_reset_evidence.minimum_internal_largest = s_minimum_internal_largest;
    s_reset_evidence.minimum_psram_free = s_minimum_psram_free;
    s_reset_evidence.minimum_psram_largest = s_minimum_psram_largest;
    s_reset_evidence.minimum_stack_headroom = s_minimum_stack_headroom;
    s_reset_evidence.minimum_main_stack_headroom =
        s_minimum_main_stack_headroom;
    s_reset_evidence.maximum_queue_high_water = s_maximum_queue_high_water;
    s_reset_evidence.checksum = evidence_checksum(&s_reset_evidence);
}

static void __attribute__((noreturn)) restart_with_evidence(
    uint32_t phase,
    uint32_t fault_code,
    int32_t fault_status,
    uint32_t reset_required,
    const WdcDiagBreadcrumb *breadcrumb)
{
    save_reset_evidence(phase,
                        fault_code,
                        fault_status,
                        reset_required,
                        breadcrumb);
    printf("PULSE_HX45_RESET_ARMED {\"status\":\"%s\",\"phase\":%" PRIu32
           ",\"fault_code\":%" PRIu32 ",\"fault_status\":%" PRId32
           ",\"reset_required\":%" PRIu32 "}\n",
           phase == HX45_RESET_EXPECTED ? "PASS" : "FAIL",
           phase,
           fault_code,
           fault_status,
           reset_required);
    fflush(stdout);
    vTaskDelay(pdMS_TO_TICKS(250u));
    esp_restart();
    for (;;) {
    }
}

static void run_reset_required_case(void)
{
    pulse_extension_quiesce_v1 quiesce;
    WdcDiagBreadcrumb breadcrumb;
    bool breadcrumb_present;
    int32_t status;
    HeapSample active;

    if (!load_and_start_extension(1000u)) {
        restart_with_evidence(HX45_RESET_FAILURE, 0u, 0, 0u, NULL);
    }
    memset(&quiesce, 0, sizeof(quiesce));
    quiesce.struct_size = sizeof(quiesce);
    quiesce.reason = WDC_EXTENSION_FAULT_QUIESCE;
    quiesce.deadline_ms = u64_parts(monotonic_ms());
    status = wdc_extension_registry_quiesce(&s_cycle.registry, &quiesce);
    (void)record_case("expired-quiesce-requires-timeout",
                      status,
                      WDC_EXTENSION_ERR_TIMEOUT);
    (void)record_condition("expired-quiesce-latches-reset",
                           wdc_extension_registry_requires_reset(
                               &s_cycle.registry) != 0u);
    active = print_heap_stage(1000u, "reset-required");
    (void)record_heap_headroom(&active);
    (void)record_condition("reset-main-stack-headroom",
                           sample_main_stack(1000u, "reset-required") >=
                               HX45_MAIN_STACK_HEADROOM_MIN_BYTES);
    wdc_diag_record_breadcrumb(0,
                               (int32_t)s_cycle.candidate.fault_code,
                               s_cycle.candidate.last_extension_status,
                               0,
                               "pulse-hx45-c6-seeed-xiao-4m",
                               1u,
                               "quiescence deadline expired; authoritative reset required");
    memset(&breadcrumb, 0, sizeof(breadcrumb));
    breadcrumb_present = wdc_diag_get_breadcrumb(&breadcrumb);
    (void)record_condition("reset-breadcrumb-recorded", breadcrumb_present);
    restart_with_evidence(HX45_RESET_EXPECTED,
                          s_cycle.candidate.fault_code,
                          s_cycle.candidate.last_extension_status,
                          wdc_extension_registry_requires_reset(&s_cycle.registry),
                          breadcrumb_present ? &breadcrumb : NULL);
}

static bool board_preflight(uint32_t *out_flash, uint32_t *out_psram)
{
    esp_chip_info_t chip;
    uint32_t flash_size = 0u;
    uint32_t psram_size = 0u;
    esp_chip_info(&chip);
    if (esp_flash_get_physical_size(NULL, &flash_size) != ESP_OK) {
        flash_size = 0u;
    }
    *out_flash = flash_size;
    *out_psram = psram_size;
    printf("PULSE_HX45_BOARD {\"board\":\"%s\",\"target\":\"esp32c6\""
           ",\"chip_model\":%d,\"chip_revision\":%u,\"cores\":%u"
           ",\"flash_bytes\":%" PRIu32 ",\"psram_bytes\":%" PRIu32
           ",\"elf_sha256\":\"%s\",\"common_wasm_sha256\":\"%s\"}\n",
           HX45_BOARD_NAME,
           (int)chip.model,
           (unsigned)chip.revision,
           (unsigned)chip.cores,
           flash_size,
           psram_size,
           pulse_hx45_extension_sha256,
           pulse_hx45_common_wasm_sha256);
    fflush(stdout);
    return record_condition("board-is-esp32c6", chip.model == CHIP_ESP32C6) &&
           record_condition("board-flash-is-4mb", flash_size == HX45_FLASH_BYTES) &&
           record_condition("board-has-no-psram", psram_size == 0u);
}

static void __attribute__((noreturn)) idle_forever(void)
{
    for (;;) {
        vTaskDelay(pdMS_TO_TICKS(10000u));
    }
}

static void finish_after_reset(esp_reset_reason_t reset_reason)
{
    ResetEvidence retained = s_reset_evidence;
    bool expected_phase = retained.phase == HX45_RESET_EXPECTED;
    bool software_reset = reset_reason == ESP_RST_SW;
    bool breadcrumb_valid =
        retained.breadcrumb_magic == WDC_DIAG_BREADCRUMB_MAGIC &&
        retained.breadcrumb_generation != 0u;
    bool reset_latched = retained.reset_required != 0u &&
                         retained.fault_code == WDC_EXTENSION_FAULT_QUIESCE &&
                         retained.fault_status == PULSE_EXT_ERR_TIMEOUT;
    bool passed = expected_phase && software_reset && breadcrumb_valid &&
                  reset_latched && retained.failures == 0u;

    memset(&s_reset_evidence, 0, sizeof(s_reset_evidence));
    printf("PULSE_HX45_RESET_OBSERVED {\"status\":\"%s\",\"reset_reason\":%d"
           ",\"software_reset\":%s,\"breadcrumb_valid\":%s"
           ",\"reset_required\":%" PRIu32 ",\"fault_code\":%" PRIu32
           ",\"fault_status\":%" PRId32 "}\n",
           passed ? "PASS" : "FAIL",
           (int)reset_reason,
           software_reset ? "true" : "false",
           breadcrumb_valid ? "true" : "false",
           retained.reset_required,
           retained.fault_code,
           retained.fault_status);
    printf("PULSE_HX45_FINAL {\"status\":\"%s\",\"board\":\"%s\""
           ",\"measured_cycles\":%" PRIu32
           ",\"minimum_internal_free\":%" PRIu32
           ",\"minimum_internal_largest\":%" PRIu32
           ",\"minimum_psram_free\":%" PRIu32
           ",\"minimum_psram_largest\":%" PRIu32
           ",\"minimum_stack_headroom\":%" PRIu32
           ",\"minimum_main_stack_headroom\":%" PRIu32
           ",\"maximum_queue_high_water\":%" PRIu32
           ",\"target_runtime\":\"%s\"}\n",
           passed ? "PASS" : "FAIL",
           HX45_BOARD_NAME,
           retained.measured_cycles,
           retained.minimum_internal_free,
           retained.minimum_internal_largest,
           retained.minimum_psram_free,
           retained.minimum_psram_largest,
           retained.minimum_stack_headroom,
           retained.minimum_main_stack_headroom,
           retained.maximum_queue_high_water,
           passed ? "NAMED_BOARD_OBSERVED" : "FAILED");
    fflush(stdout);
    idle_forever();
}

static void *hx45_driver_pthread(void *arg)
{
    esp_reset_reason_t reset_reason;
    uint32_t flash_size;
    uint32_t psram_size;
    uint32_t cycle;
    CycleResult result;

    (void)arg;
    vTaskDelay(pdMS_TO_TICKS(1500u));
    reset_reason = esp_reset_reason();
    (void)wdc_diag_init();
    wdc_diag_note_boot((uint32_t)reset_reason,
                       wdc_reset_reason_name((int32_t)reset_reason));
    if (!board_preflight(&flash_size, &psram_size)) {
        printf("PULSE_HX45_FINAL {\"status\":\"FAIL\",\"reason\":\"board-preflight\"}\n");
        fflush(stdout);
        idle_forever();
    }
    (void)flash_size;
    (void)psram_size;

    if (reset_evidence_valid()) {
        finish_after_reset(reset_reason);
    }
    memset(&s_reset_evidence, 0, sizeof(s_reset_evidence));

    printf("PULSE_HX45_BEGIN {\"status\":\"RUNNING\",\"warmup_cycles\":%u"
           ",\"measured_cycles\":%u}\n",
           HX45_WARMUP_CYCLES,
           HX45_MEASURED_CYCLES);
    fflush(stdout);

    for (cycle = 0u; cycle < HX45_WARMUP_CYCLES; ++cycle) {
        if (!run_clean_cycle(cycle, false, &result)) {
            restart_with_evidence(HX45_RESET_FAILURE, 0u, 0, 0u, NULL);
        }
    }
    for (cycle = 1u; cycle <= HX45_MEASURED_CYCLES; ++cycle) {
        if (!run_clean_cycle(cycle, true, &result)) {
            restart_with_evidence(HX45_RESET_FAILURE, 0u, 0, 0u, NULL);
        }
    }
    if (!run_real_wasm_trap()) {
        restart_with_evidence(HX45_RESET_FAILURE, 0u, 0, 0u, NULL);
    }
    run_reset_required_case();
    return NULL;
}

static void hx45_pthread_fail(const char *operation, int status)
{
    printf("PULSE_HX45_FINAL {\"status\":\"FAIL\",\"reason\":"
           "\"pthread-%s\",\"code\":%d}\n",
           operation,
           status);
    fflush(stdout);
    idle_forever();
}

void app_main(void)
{
    pthread_attr_t attributes;
    pthread_t thread;
    int status = pthread_attr_init(&attributes);
    if (status != 0) {
        hx45_pthread_fail("attribute-init", status);
    }
    status = pthread_attr_setdetachstate(&attributes, PTHREAD_CREATE_JOINABLE);
    if (status == 0) {
        status = pthread_attr_setstacksize(&attributes,
                                           HX45_DRIVER_PTHREAD_STACK_BYTES);
    }
    if (status == 0) {
        status = pthread_create(&thread,
                                &attributes,
                                hx45_driver_pthread,
                                NULL);
    }
    (void)pthread_attr_destroy(&attributes);
    if (status != 0) {
        hx45_pthread_fail("create", status);
    }
    status = pthread_join(thread, NULL);
    if (status != 0) {
        hx45_pthread_fail("join", status);
    }
}
