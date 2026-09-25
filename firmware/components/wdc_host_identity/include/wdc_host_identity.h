#pragma once

#include <stdint.h>

#include "wdc_control.h"

#ifdef __cplusplus
extern "C" {
#endif

#define WDC_HOST_FINGERPRINT_MAGIC 0x57444346u /* WDCF */
#define WDC_HOST_FINGERPRINT_VERSION 1u
#define WDC_HOST_FINGERPRINT_SHA256_BYTES 32u

#define WDC_HOST_CAP_WASM_APPLICATION (1u << 0u)
#define WDC_HOST_CAP_EVENT_EFFECT (1u << 1u)
#define WDC_HOST_CAP_NATIVE_REFINEMENT (1u << 2u)
#define WDC_HOST_CAP_APPLICATION_SLOTS (1u << 3u)
#define WDC_HOST_CAP_ALL_V1 \
    (WDC_HOST_CAP_WASM_APPLICATION | WDC_HOST_CAP_EVENT_EFFECT | \
     WDC_HOST_CAP_NATIVE_REFINEMENT | WDC_HOST_CAP_APPLICATION_SLOTS)

typedef enum WdcHostTarget {
    WDC_HOST_TARGET_NONE = 0,
    WDC_HOST_TARGET_ESP32S3 = 1,
    WDC_HOST_TARGET_ESP32C6 = 2,
} WdcHostTarget;

#define WDC_HOST_TARGET_MASK_ESP32S3 (1u << 0u)
#define WDC_HOST_TARGET_MASK_ESP32C6 (1u << 1u)

typedef enum WdcHostResourceProfileId {
    WDC_HOST_RESOURCE_PROFILE_NONE = 0,
    WDC_HOST_RESOURCE_PROFILE_S3_PSRAM_V1 = 1,
    WDC_HOST_RESOURCE_PROFILE_C6_MINIMUM_V1 = 2,
} WdcHostResourceProfileId;

typedef enum WdcHostPlacement {
    WDC_HOST_PLACEMENT_NONE = 0,
    WDC_HOST_PLACEMENT_PORTABLE = 1,
    WDC_HOST_PLACEMENT_TARGET_OPTIMIZED = 2,
} WdcHostPlacement;

typedef enum WdcHostPrelaunchOutcome {
    WDC_HOST_PRELAUNCH_NOT_EVALUATED = 0,
    WDC_HOST_PRELAUNCH_ACCEPTED = 1,
    WDC_HOST_PRELAUNCH_DENIED_FINGERPRINT = 2,
    WDC_HOST_PRELAUNCH_DENIED_REQUIREMENTS = 3,
    WDC_HOST_PRELAUNCH_DENIED_TARGET = 4,
    WDC_HOST_PRELAUNCH_DENIED_ABI = 5,
    WDC_HOST_PRELAUNCH_DENIED_CAPABILITY = 6,
    WDC_HOST_PRELAUNCH_DENIED_PLACEMENT = 7,
    WDC_HOST_PRELAUNCH_DENIED_RESOURCE = 8,
} WdcHostPrelaunchOutcome;

typedef struct WdcHostFingerprintV1 {
    uint32_t magic;
    uint16_t version;
    uint16_t struct_bytes;
    WdcHostTarget target;
    uint32_t host_abi_major;
    uint32_t host_abi_minor;
    uint32_t capability_mask;
    WdcHostResourceProfileId resource_profile;
    uint32_t flash_bytes;
    uint32_t psram_bytes;
    uint32_t fixed_control_reserve_bytes;
    uint32_t exclusive_update_working_bytes;
    uint32_t largest_block_floor_bytes;
    uint32_t maximum_application_internal_bytes;
    uint32_t maximum_transition_scratch_bytes;
    uint32_t maximum_target_optimized_bytes;
    uint32_t target_optimized_floor_bytes;
    uint8_t board_id_sha256[WDC_HOST_FINGERPRINT_SHA256_BYTES];
    uint8_t host_profile_id_sha256[WDC_HOST_FINGERPRINT_SHA256_BYTES];
    uint8_t build_lock_sha256[WDC_HOST_FINGERPRINT_SHA256_BYTES];
    uint8_t compatibility_sha256[WDC_HOST_FINGERPRINT_SHA256_BYTES];
    uint32_t crc32;
} WdcHostFingerprintV1;

typedef struct WdcHostApplicationRequirements {
    uint32_t allowed_target_mask;
    uint32_t host_abi_major;
    uint32_t host_abi_min_minor;
    uint32_t host_abi_max_minor;
    uint32_t required_capability_mask;
    WdcHostPlacement placement;
    uint32_t guest_linear_memory_bytes;
    uint32_t runtime_stack_bytes;
    uint32_t network_working_bytes;
    uint32_t capability_working_bytes;
    uint32_t native_refinement_bytes;
    uint32_t transition_scratch_bytes;
    uint32_t largest_application_allocation_bytes;
    uint32_t target_optimization_bytes;
    uint32_t requested_task_priority;
    uint32_t requests_unbounded_allocation;
} WdcHostApplicationRequirements;

typedef struct WdcHostPrelaunchDecision {
    WdcHostPrelaunchOutcome outcome;
    int32_t status;
    uint32_t application_code_launched;
    WdcControlAdmissionDecision resource;
} WdcHostPrelaunchDecision;

uint32_t wdc_host_fingerprint_crc32(const WdcHostFingerprintV1 *fingerprint);
int32_t wdc_host_fingerprint_validate(const WdcHostFingerprintV1 *fingerprint);
const WdcHostFingerprintV1 *wdc_host_fingerprint_for_target(WdcHostTarget target);
const WdcHostFingerprintV1 *wdc_host_running_fingerprint(void);

int32_t wdc_host_compatibility_check(
    const WdcHostFingerprintV1 *fingerprint,
    const WdcHostApplicationRequirements *requirements,
    WdcHostPrelaunchDecision *out_decision);

int32_t wdc_host_prelaunch_check(
    const WdcHostFingerprintV1 *fingerprint,
    const WdcHostApplicationRequirements *requirements,
    const WdcControlHeapSnapshot *heap,
    WdcHostPrelaunchDecision *out_decision);

uint32_t wdc_host_identity_link_anchor(void);

#ifdef __cplusplus
}
#endif
