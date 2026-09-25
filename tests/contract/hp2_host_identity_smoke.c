#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "wdc_host_identity.h"

#define HP2_CASE_COUNT 8u

typedef struct Hp2Case {
    const char *name;
    uint32_t passed;
} Hp2Case;

static uint32_t s_failures;
static Hp2Case s_cases[HP2_CASE_COUNT];
static uint32_t s_case_count;

#define CHECK(condition) \
    do { \
        if (!(condition)) { \
            s_failures += 1u; \
        } \
    } while (0)

static void record_case(const char *name, uint32_t before)
{
    CHECK(s_case_count < HP2_CASE_COUNT);
    if (s_case_count < HP2_CASE_COUNT) {
        s_cases[s_case_count].name = name;
        s_cases[s_case_count].passed = s_failures == before ? 1u : 0u;
        s_case_count += 1u;
    }
}

static WdcHostApplicationRequirements portable_requirements(void)
{
    WdcHostApplicationRequirements requirements;
    memset(&requirements, 0, sizeof(requirements));
    requirements.allowed_target_mask =
        WDC_HOST_TARGET_MASK_ESP32S3 | WDC_HOST_TARGET_MASK_ESP32C6;
    requirements.host_abi_major = 1u;
    requirements.host_abi_min_minor = 0u;
    requirements.host_abi_max_minor = 0u;
    requirements.required_capability_mask =
        WDC_HOST_CAP_WASM_APPLICATION | WDC_HOST_CAP_EVENT_EFFECT;
    requirements.placement = WDC_HOST_PLACEMENT_PORTABLE;
    requirements.guest_linear_memory_bytes = 49152u;
    requirements.runtime_stack_bytes = 16384u;
    requirements.network_working_bytes = 8192u;
    requirements.capability_working_bytes = 4096u;
    requirements.native_refinement_bytes = 0u;
    requirements.transition_scratch_bytes = 8192u;
    requirements.largest_application_allocation_bytes = 49152u;
    return requirements;
}

static WdcControlHeapSnapshot c6_heap(void)
{
    WdcControlHeapSnapshot heap = { 255032u, 221184u, 0u };
    return heap;
}

static WdcControlHeapSnapshot s3_heap(void)
{
    WdcControlHeapSnapshot heap = { 192691u, 131072u, 2075684u };
    return heap;
}

static void run_exact_fingerprints(void)
{
    const WdcHostFingerprintV1 *s3 =
        wdc_host_fingerprint_for_target(WDC_HOST_TARGET_ESP32S3);
    const WdcHostFingerprintV1 *c6 =
        wdc_host_fingerprint_for_target(WDC_HOST_TARGET_ESP32C6);
    uint32_t before = s_failures;
    CHECK(s3 != NULL);
    CHECK(c6 != NULL);
    CHECK(wdc_host_fingerprint_validate(s3) == WDC_OK);
    CHECK(wdc_host_fingerprint_validate(c6) == WDC_OK);
    CHECK(wdc_host_running_fingerprint() == c6);
    CHECK(s3->flash_bytes == 8388608u);
    CHECK(s3->psram_bytes == 2097152u);
    CHECK(c6->flash_bytes == 4194304u);
    CHECK(c6->psram_bytes == 0u);
    CHECK(s3->capability_mask == WDC_HOST_CAP_ALL_V1);
    CHECK(c6->capability_mask == WDC_HOST_CAP_ALL_V1);
    record_case("exact-build-derived-fingerprints", before);
}

static void run_portable_c6(uint32_t *required_internal,
                            uint32_t *required_largest)
{
    const WdcHostFingerprintV1 *c6 =
        wdc_host_fingerprint_for_target(WDC_HOST_TARGET_ESP32C6);
    WdcHostApplicationRequirements requirements = portable_requirements();
    WdcControlHeapSnapshot heap = c6_heap();
    WdcHostPrelaunchDecision decision;
    uint32_t before = s_failures;
    CHECK(wdc_host_prelaunch_check(c6, &requirements, &heap, &decision) == WDC_OK);
    CHECK(decision.outcome == WDC_HOST_PRELAUNCH_ACCEPTED);
    CHECK(decision.application_code_launched == 0u);
    CHECK(decision.resource.outcome == WDC_CONTROL_ADMISSION_ACCEPTED_PORTABLE);
    CHECK(decision.resource.application_internal_bytes == 77824u);
    CHECK(decision.resource.required_internal_free_bytes == 184320u);
    CHECK(decision.resource.required_largest_block_bytes == 98304u);
    *required_internal = decision.resource.required_internal_free_bytes;
    *required_largest = decision.resource.required_largest_block_bytes;
    record_case("portable-c6-prelaunch-admission", before);
}

static void run_corrupt_fingerprint(void)
{
    WdcHostFingerprintV1 corrupt = *wdc_host_fingerprint_for_target(
        WDC_HOST_TARGET_ESP32C6);
    WdcHostApplicationRequirements requirements = portable_requirements();
    WdcControlHeapSnapshot heap = c6_heap();
    WdcHostPrelaunchDecision decision;
    uint32_t before = s_failures;
    corrupt.build_lock_sha256[0] ^= 1u;
    CHECK(wdc_host_prelaunch_check(&corrupt, &requirements, &heap, &decision) ==
          WDC_ERR_CONTRACT_VIOLATION);
    CHECK(decision.outcome == WDC_HOST_PRELAUNCH_DENIED_FINGERPRINT);
    CHECK(decision.application_code_launched == 0u);
    record_case("corrupt-fingerprint-rejected", before);
}

static void run_target_and_abi_denials(void)
{
    const WdcHostFingerprintV1 *c6 =
        wdc_host_fingerprint_for_target(WDC_HOST_TARGET_ESP32C6);
    WdcHostApplicationRequirements requirements = portable_requirements();
    WdcControlHeapSnapshot heap = c6_heap();
    WdcHostPrelaunchDecision decision;
    uint32_t before = s_failures;
    requirements.allowed_target_mask = WDC_HOST_TARGET_MASK_ESP32S3;
    CHECK(wdc_host_prelaunch_check(c6, &requirements, &heap, &decision) ==
          WDC_ERR_INVALID_RESOURCE);
    CHECK(decision.outcome == WDC_HOST_PRELAUNCH_DENIED_TARGET);
    CHECK(decision.application_code_launched == 0u);
    requirements = portable_requirements();
    requirements.host_abi_min_minor = 1u;
    requirements.host_abi_max_minor = 1u;
    CHECK(wdc_host_prelaunch_check(c6, &requirements, &heap, &decision) ==
          WDC_ERR_UNSUPPORTED_ABI);
    CHECK(decision.outcome == WDC_HOST_PRELAUNCH_DENIED_ABI);
    CHECK(decision.application_code_launched == 0u);
    record_case("target-and-abi-fail-closed", before);
}

static void run_capability_denial(void)
{
    WdcHostFingerprintV1 restricted = *wdc_host_fingerprint_for_target(
        WDC_HOST_TARGET_ESP32C6);
    WdcHostApplicationRequirements requirements = portable_requirements();
    WdcControlHeapSnapshot heap = c6_heap();
    WdcHostPrelaunchDecision decision;
    uint32_t before = s_failures;
    restricted.capability_mask = WDC_HOST_CAP_WASM_APPLICATION;
    restricted.crc32 = wdc_host_fingerprint_crc32(&restricted);
    CHECK(wdc_host_fingerprint_validate(&restricted) == WDC_OK);
    CHECK(wdc_host_prelaunch_check(&restricted, &requirements, &heap, &decision) ==
          WDC_ERR_CAPABILITY_DENIED);
    CHECK(decision.outcome == WDC_HOST_PRELAUNCH_DENIED_CAPABILITY);
    CHECK(decision.application_code_launched == 0u);
    record_case("capability-fail-closed", before);
}

static void run_c6_optimization_denial(void)
{
    const WdcHostFingerprintV1 *c6 =
        wdc_host_fingerprint_for_target(WDC_HOST_TARGET_ESP32C6);
    WdcHostApplicationRequirements requirements = portable_requirements();
    WdcControlHeapSnapshot heap = c6_heap();
    WdcHostPrelaunchDecision decision;
    uint32_t before = s_failures;
    requirements.placement = WDC_HOST_PLACEMENT_TARGET_OPTIMIZED;
    requirements.target_optimization_bytes = 1u;
    CHECK(wdc_host_prelaunch_check(c6, &requirements, &heap, &decision) ==
          WDC_ERR_NO_MEMORY);
    CHECK(decision.outcome == WDC_HOST_PRELAUNCH_DENIED_PLACEMENT);
    CHECK(decision.application_code_launched == 0u);
    record_case("c6-target-optimization-denied", before);
}

static void run_hp1_resource_denial(void)
{
    const WdcHostFingerprintV1 *c6 =
        wdc_host_fingerprint_for_target(WDC_HOST_TARGET_ESP32C6);
    WdcHostApplicationRequirements requirements = portable_requirements();
    WdcControlHeapSnapshot heap = { 184319u, 98304u, 0u };
    WdcHostPrelaunchDecision decision;
    uint32_t before = s_failures;
    CHECK(wdc_host_prelaunch_check(c6, &requirements, &heap, &decision) ==
          WDC_ERR_NO_MEMORY);
    CHECK(decision.outcome == WDC_HOST_PRELAUNCH_DENIED_RESOURCE);
    CHECK(decision.resource.outcome == WDC_CONTROL_ADMISSION_DENIED_INTERNAL_FREE);
    CHECK(decision.application_code_launched == 0u);
    requirements = portable_requirements();
    requirements.requested_task_priority = 9u;
    heap = c6_heap();
    CHECK(wdc_host_prelaunch_check(c6, &requirements, &heap, &decision) ==
          WDC_ERR_CAPABILITY_DENIED);
    CHECK(decision.resource.outcome ==
          WDC_CONTROL_ADMISSION_DENIED_APPLICATION_PRIORITY);
    CHECK(decision.application_code_launched == 0u);
    record_case("hp1-resource-authority-preserved", before);
}

static void run_s3_optimization(uint32_t *required_target_memory)
{
    const WdcHostFingerprintV1 *s3 =
        wdc_host_fingerprint_for_target(WDC_HOST_TARGET_ESP32S3);
    WdcHostApplicationRequirements requirements = portable_requirements();
    WdcControlHeapSnapshot heap = s3_heap();
    WdcHostPrelaunchDecision decision;
    uint32_t before = s_failures;
    requirements.placement = WDC_HOST_PLACEMENT_TARGET_OPTIMIZED;
    requirements.target_optimization_bytes = 262144u;
    CHECK(wdc_host_prelaunch_check(s3, &requirements, &heap, &decision) == WDC_OK);
    CHECK(decision.outcome == WDC_HOST_PRELAUNCH_ACCEPTED);
    CHECK(decision.resource.outcome ==
          WDC_CONTROL_ADMISSION_ACCEPTED_TARGET_OPTIMIZED);
    CHECK(!decision.resource.portable);
    CHECK(decision.resource.required_psram_free_bytes == 393216u);
    CHECK(decision.application_code_launched == 0u);
    *required_target_memory = decision.resource.required_psram_free_bytes;
    record_case("s3-explicit-target-optimization", before);
}

int main(void)
{
    uint32_t required_internal = 0u;
    uint32_t required_largest = 0u;
    uint32_t required_target_memory = 0u;
    uint32_t index;
    run_exact_fingerprints();
    run_portable_c6(&required_internal, &required_largest);
    run_corrupt_fingerprint();
    run_target_and_abi_denials();
    run_capability_denial();
    run_c6_optimization_denial();
    run_hp1_resource_denial();
    run_s3_optimization(&required_target_memory);
    CHECK(s_case_count == HP2_CASE_COUNT);
    printf("{\"schema\":\"pulse.esp32.hp2-host-identity-smoke.v1\","
           "\"status\":\"%s\",\"failures\":%" PRIu32
           ",\"case_count\":%" PRIu32 ",\"cases\":[",
           s_failures == 0u ? "PASS" : "FAIL", s_failures, s_case_count);
    for (index = 0u; index < s_case_count; ++index) {
        printf("%s{\"name\":\"%s\",\"status\":\"%s\"}",
               index == 0u ? "" : ",", s_cases[index].name,
               s_cases[index].passed != 0u ? "PASS" : "FAIL");
    }
    printf("],\"fingerprints\":{\"s3\":\"VALID\",\"c6\":\"VALID\"},"
           "\"c6\":{\"required_internal_free_bytes\":%" PRIu32
           ",\"required_largest_block_bytes\":%" PRIu32 "},"
           "\"s3\":{\"required_target_optimized_free_bytes\":%" PRIu32 "},"
           "\"application_code_launched\":false}\n",
           required_internal, required_largest, required_target_memory);
    return s_failures == 0u ? 0 : 1;
}
