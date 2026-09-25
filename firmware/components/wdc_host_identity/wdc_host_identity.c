#include "wdc_host_identity.h"

#include <stddef.h>
#include <string.h>

_Static_assert(sizeof(WdcHostFingerprintV1) == 196u,
               "HP2 fingerprint layout must remain fixed");

static int bytes_nonzero(const uint8_t *bytes, uint32_t length)
{
    uint32_t index;
    uint8_t observed = 0u;
    if (bytes == NULL) {
        return 0;
    }
    for (index = 0u; index < length; ++index) {
        observed = (uint8_t)(observed | bytes[index]);
    }
    return observed != 0u;
}

static uint32_t crc32_bytes(const uint8_t *bytes, uint32_t length)
{
    uint32_t crc = 0xffffffffu;
    uint32_t index;
    uint32_t bit;
    for (index = 0u; index < length; ++index) {
        crc ^= bytes[index];
        for (bit = 0u; bit < 8u; ++bit) {
            uint32_t mask = (uint32_t)(0u - (crc & 1u));
            crc = (crc >> 1u) ^ (0xedb88320u & mask);
        }
    }
    return ~crc;
}

uint32_t wdc_host_fingerprint_crc32(const WdcHostFingerprintV1 *fingerprint)
{
    WdcHostFingerprintV1 copy;
    if (fingerprint == NULL) {
        return 0u;
    }
    memcpy(&copy, fingerprint, sizeof(copy));
    copy.crc32 = 0u;
    return crc32_bytes((const uint8_t *)&copy, (uint32_t)sizeof(copy));
}

static const WdcControlResourceProfile *control_profile_for(
    WdcHostResourceProfileId profile)
{
    switch (profile) {
    case WDC_HOST_RESOURCE_PROFILE_S3_PSRAM_V1:
        return wdc_control_profile_s3_psram();
    case WDC_HOST_RESOURCE_PROFILE_C6_MINIMUM_V1:
        return wdc_control_profile_c6_minimum();
    default:
        return NULL;
    }
}

static int fingerprint_resource_coherent(
    const WdcHostFingerprintV1 *fingerprint,
    const WdcControlResourceProfile *profile)
{
    if (profile == NULL || fingerprint == NULL) {
        return 0;
    }
    return fingerprint->fixed_control_reserve_bytes ==
               profile->reserve.fixed_control_reserve_bytes &&
           fingerprint->exclusive_update_working_bytes ==
               profile->reserve.exclusive_update_working_bytes &&
           fingerprint->largest_block_floor_bytes ==
               profile->reserve.largest_block_floor_bytes &&
           fingerprint->maximum_application_internal_bytes ==
               profile->reserve.maximum_application_internal_bytes &&
           fingerprint->maximum_transition_scratch_bytes ==
               profile->reserve.maximum_transition_scratch_bytes &&
           fingerprint->maximum_target_optimized_bytes ==
               profile->reserve.maximum_application_psram_bytes &&
           fingerprint->target_optimized_floor_bytes ==
               profile->reserve.psram_floor_bytes;
}

int32_t wdc_host_fingerprint_validate(const WdcHostFingerprintV1 *fingerprint)
{
    const WdcControlResourceProfile *profile;
    if (fingerprint == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    if (fingerprint->magic != WDC_HOST_FINGERPRINT_MAGIC ||
        fingerprint->version != WDC_HOST_FINGERPRINT_VERSION ||
        fingerprint->struct_bytes != sizeof(*fingerprint) ||
        fingerprint->host_abi_major == 0u ||
        fingerprint->capability_mask == 0u ||
        (fingerprint->capability_mask & ~WDC_HOST_CAP_ALL_V1) != 0u ||
        fingerprint->flash_bytes == 0u ||
        !bytes_nonzero(fingerprint->board_id_sha256,
                       WDC_HOST_FINGERPRINT_SHA256_BYTES) ||
        !bytes_nonzero(fingerprint->host_profile_id_sha256,
                       WDC_HOST_FINGERPRINT_SHA256_BYTES) ||
        !bytes_nonzero(fingerprint->build_lock_sha256,
                       WDC_HOST_FINGERPRINT_SHA256_BYTES) ||
        !bytes_nonzero(fingerprint->compatibility_sha256,
                       WDC_HOST_FINGERPRINT_SHA256_BYTES)) {
        return WDC_ERR_BAD_ENCODING;
    }
    if ((fingerprint->target == WDC_HOST_TARGET_ESP32S3 &&
         (fingerprint->resource_profile !=
              WDC_HOST_RESOURCE_PROFILE_S3_PSRAM_V1 ||
          fingerprint->psram_bytes == 0u)) ||
        (fingerprint->target == WDC_HOST_TARGET_ESP32C6 &&
         (fingerprint->resource_profile !=
              WDC_HOST_RESOURCE_PROFILE_C6_MINIMUM_V1 ||
          fingerprint->psram_bytes != 0u)) ||
        (fingerprint->target != WDC_HOST_TARGET_ESP32S3 &&
         fingerprint->target != WDC_HOST_TARGET_ESP32C6)) {
        return WDC_ERR_BAD_ENCODING;
    }
    profile = control_profile_for(fingerprint->resource_profile);
    if (wdc_control_validate_profile(profile) != WDC_OK ||
        !fingerprint_resource_coherent(fingerprint, profile) ||
        fingerprint->crc32 != wdc_host_fingerprint_crc32(fingerprint)) {
        return WDC_ERR_CONTRACT_VIOLATION;
    }
    return WDC_OK;
}

static int requirements_valid(const WdcHostApplicationRequirements *requirements)
{
    uint64_t internal;
    if (requirements == NULL || requirements->allowed_target_mask == 0u ||
        (requirements->allowed_target_mask &
         ~(WDC_HOST_TARGET_MASK_ESP32S3 | WDC_HOST_TARGET_MASK_ESP32C6)) != 0u ||
        requirements->host_abi_major == 0u ||
        requirements->host_abi_min_minor > requirements->host_abi_max_minor ||
        requirements->required_capability_mask == 0u ||
        (requirements->required_capability_mask & ~WDC_HOST_CAP_ALL_V1) != 0u ||
        (requirements->placement != WDC_HOST_PLACEMENT_PORTABLE &&
         requirements->placement != WDC_HOST_PLACEMENT_TARGET_OPTIMIZED) ||
        requirements->guest_linear_memory_bytes == 0u ||
        requirements->runtime_stack_bytes == 0u ||
        requirements->largest_application_allocation_bytes == 0u ||
        requirements->requests_unbounded_allocation > 1u) {
        return 0;
    }
    internal = (uint64_t)requirements->guest_linear_memory_bytes +
               requirements->runtime_stack_bytes +
               requirements->network_working_bytes +
               requirements->capability_working_bytes +
               requirements->native_refinement_bytes;
    if (internal > UINT32_MAX ||
        requirements->largest_application_allocation_bytes > internal ||
        (requirements->placement == WDC_HOST_PLACEMENT_PORTABLE &&
         requirements->target_optimization_bytes != 0u) ||
        (requirements->placement == WDC_HOST_PLACEMENT_TARGET_OPTIMIZED &&
         requirements->target_optimization_bytes == 0u)) {
        return 0;
    }
    return 1;
}

static int32_t prelaunch_deny(WdcHostPrelaunchDecision *decision,
                              WdcHostPrelaunchOutcome outcome,
                              int32_t status)
{
    decision->outcome = outcome;
    decision->status = status;
    decision->application_code_launched = 0u;
    return status;
}

int32_t wdc_host_compatibility_check(
    const WdcHostFingerprintV1 *fingerprint,
    const WdcHostApplicationRequirements *requirements,
    WdcHostPrelaunchDecision *out_decision)
{
    uint32_t target_mask;
    int32_t status;
    if (out_decision == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    memset(out_decision, 0, sizeof(*out_decision));
    out_decision->status = WDC_ERR_UNKNOWN;
    status = wdc_host_fingerprint_validate(fingerprint);
    if (status != WDC_OK) {
        return prelaunch_deny(out_decision,
                              WDC_HOST_PRELAUNCH_DENIED_FINGERPRINT,
                              status);
    }
    if (!requirements_valid(requirements)) {
        return prelaunch_deny(out_decision,
                              WDC_HOST_PRELAUNCH_DENIED_REQUIREMENTS,
                              WDC_ERR_BAD_ENCODING);
    }
    target_mask = fingerprint->target == WDC_HOST_TARGET_ESP32S3
                      ? WDC_HOST_TARGET_MASK_ESP32S3
                      : WDC_HOST_TARGET_MASK_ESP32C6;
    if ((requirements->allowed_target_mask & target_mask) == 0u) {
        return prelaunch_deny(out_decision,
                              WDC_HOST_PRELAUNCH_DENIED_TARGET,
                              WDC_ERR_INVALID_RESOURCE);
    }
    if (requirements->host_abi_major != fingerprint->host_abi_major ||
        fingerprint->host_abi_minor < requirements->host_abi_min_minor ||
        fingerprint->host_abi_minor > requirements->host_abi_max_minor) {
        return prelaunch_deny(out_decision,
                              WDC_HOST_PRELAUNCH_DENIED_ABI,
                              WDC_ERR_UNSUPPORTED_ABI);
    }
    if ((requirements->required_capability_mask &
         fingerprint->capability_mask) !=
        requirements->required_capability_mask) {
        return prelaunch_deny(out_decision,
                              WDC_HOST_PRELAUNCH_DENIED_CAPABILITY,
                              WDC_ERR_CAPABILITY_DENIED);
    }
    if ((requirements->placement == WDC_HOST_PLACEMENT_PORTABLE &&
         requirements->target_optimization_bytes != 0u) ||
        requirements->target_optimization_bytes >
            fingerprint->maximum_target_optimized_bytes) {
        return prelaunch_deny(out_decision,
                              WDC_HOST_PRELAUNCH_DENIED_PLACEMENT,
                              WDC_ERR_NO_MEMORY);
    }
    out_decision->outcome = WDC_HOST_PRELAUNCH_ACCEPTED;
    out_decision->status = WDC_OK;
    out_decision->application_code_launched = 0u;
    return WDC_OK;
}

int32_t wdc_host_prelaunch_check(
    const WdcHostFingerprintV1 *fingerprint,
    const WdcHostApplicationRequirements *requirements,
    const WdcControlHeapSnapshot *heap,
    WdcHostPrelaunchDecision *out_decision)
{
    const WdcControlResourceProfile *profile;
    WdcControlAdmissionRequest admission;
    int32_t status;
    status = wdc_host_compatibility_check(fingerprint,
                                          requirements,
                                          out_decision);
    if (status != WDC_OK) {
        return status;
    }
    if (heap == NULL) {
        return prelaunch_deny(out_decision,
                              WDC_HOST_PRELAUNCH_DENIED_REQUIREMENTS,
                              WDC_ERR_BAD_POINTER);
    }
    profile = control_profile_for(fingerprint->resource_profile);
    memset(&admission, 0, sizeof(admission));
    admission.heap = *heap;
    admission.guest_linear_memory_bytes =
        requirements->guest_linear_memory_bytes;
    admission.runtime_stack_bytes = requirements->runtime_stack_bytes;
    admission.network_working_bytes = requirements->network_working_bytes;
    admission.capability_working_bytes =
        requirements->capability_working_bytes;
    admission.native_extension_bytes = requirements->native_refinement_bytes;
    admission.transition_scratch_bytes =
        requirements->transition_scratch_bytes;
    admission.largest_application_allocation_bytes =
        requirements->largest_application_allocation_bytes;
    admission.external_application_bytes =
        requirements->target_optimization_bytes;
    admission.requested_task_priority = requirements->requested_task_priority;
    admission.requests_unbounded_allocation =
        requirements->requests_unbounded_allocation != 0u;
    status = wdc_control_admit(profile, &admission, &out_decision->resource);
    if (status != WDC_OK) {
        return prelaunch_deny(out_decision,
                              WDC_HOST_PRELAUNCH_DENIED_RESOURCE,
                              status);
    }
    out_decision->outcome = WDC_HOST_PRELAUNCH_ACCEPTED;
    out_decision->status = WDC_OK;
    out_decision->application_code_launched = 0u;
    return WDC_OK;
}

uint32_t wdc_host_identity_link_anchor(void)
{
    return 0x48503201u;
}
