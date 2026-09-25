#include "wdc_app_slots.h"

#include <stddef.h>
#include <string.h>

_Static_assert(sizeof(WdcHostApplicationRequirements) == 64u,
               "HP2 application requirement layout must remain fixed");
_Static_assert(sizeof(WdcPulseAppArtifactHeaderV1) ==
                   WDC_APP_ARTIFACT_HEADER_BYTES,
               "HP3 application artifact header must remain 192 bytes");

typedef struct WdcStoredArtifactValidation {
    int32_t status;
    uint32_t streamed_bytes;
    bool header_valid;
    bool bundle_hash_valid;
    bool bundle_valid;
    bool host_compatible;
    bool security_floor_valid;
    bool authority_valid;
    uint8_t artifact_sha256[WDC_BUNDLE_SHA256_BYTES];
    WdcPulseAppArtifactHeaderV1 header;
    WdcBundleVerifyResult bundle_verify;
} WdcStoredArtifactValidation;

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

static bool bytes_equal(const uint8_t *left,
                        const uint8_t *right,
                        uint32_t length)
{
    uint8_t difference = 0u;
    uint32_t index;
    if (left == NULL || right == NULL) {
        return false;
    }
    for (index = 0u; index < length; ++index) {
        difference = (uint8_t)(difference | (left[index] ^ right[index]));
    }
    return difference == 0u;
}

static bool bytes_zero(const uint8_t *bytes, uint32_t length)
{
    uint8_t observed = 0u;
    uint32_t index;
    if (bytes == NULL) {
        return false;
    }
    for (index = 0u; index < length; ++index) {
        observed = (uint8_t)(observed | bytes[index]);
    }
    return observed == 0u;
}

static bool slot_valid(WdcBundleSlotId slot)
{
    return slot == WDC_BUNDLE_SLOT_A || slot == WDC_BUNDLE_SLOT_B;
}

static WdcBundleSlotId other_slot(WdcBundleSlotId slot)
{
    if (slot == WDC_BUNDLE_SLOT_A) {
        return WDC_BUNDLE_SLOT_B;
    }
    if (slot == WDC_BUNDLE_SLOT_B) {
        return WDC_BUNDLE_SLOT_A;
    }
    return WDC_BUNDLE_SLOT_NONE;
}

static WdcBundleSlotRecord *mutable_record(WdcBundleMetadataV1 *metadata,
                                           WdcBundleSlotId slot)
{
    if (metadata == NULL) {
        return NULL;
    }
    if (slot == WDC_BUNDLE_SLOT_A) {
        return &metadata->slot_a;
    }
    if (slot == WDC_BUNDLE_SLOT_B) {
        return &metadata->slot_b;
    }
    return NULL;
}

static const WdcBundleSlotRecord *record_for(
    const WdcBundleMetadataV1 *metadata,
    WdcBundleSlotId slot)
{
    if (metadata == NULL) {
        return NULL;
    }
    if (slot == WDC_BUNDLE_SLOT_A) {
        return &metadata->slot_a;
    }
    if (slot == WDC_BUNDLE_SLOT_B) {
        return &metadata->slot_b;
    }
    return NULL;
}

static bool state_valid(WdcSlotState state)
{
    return state == WDC_SLOT_EMPTY || state == WDC_SLOT_STAGED ||
           state == WDC_SLOT_VERIFIED || state == WDC_SLOT_TRIAL ||
           state == WDC_SLOT_TRIAL_RUNNING || state == WDC_SLOT_CONFIRMED ||
           state == WDC_SLOT_REJECTED;
}

static int32_t metadata_semantics_validate(
    const WdcBundleMetadataV1 *metadata)
{
    const WdcBundleSlotRecord *active;
    const WdcBundleSlotRecord *last_good;
    int32_t status = wdc_bundle_metadata_validate(metadata);
    if (status != WDC_OK) {
        return status;
    }
    if ((!slot_valid(metadata->active_slot) &&
         metadata->active_slot != WDC_BUNDLE_SLOT_NONE) ||
        (!slot_valid(metadata->last_good_slot) &&
         metadata->last_good_slot != WDC_BUNDLE_SLOT_NONE) ||
        !state_valid(metadata->slot_a.state) ||
        !state_valid(metadata->slot_b.state) ||
        metadata->trial_boot_in_progress > 1u ||
        (metadata->last_rejected_slot != WDC_BUNDLE_SLOT_NONE &&
         !slot_valid(metadata->last_rejected_slot))) {
        return WDC_ERR_BAD_ENCODING;
    }
    last_good = record_for(metadata, metadata->last_good_slot);
    if (metadata->last_good_slot != WDC_BUNDLE_SLOT_NONE &&
        (last_good == NULL || last_good->state != WDC_SLOT_CONFIRMED)) {
        return WDC_ERR_CONTRACT_VIOLATION;
    }
    active = record_for(metadata, metadata->active_slot);
    if (metadata->trial_boot_in_progress != 0u &&
        (active == NULL || active->state != WDC_SLOT_TRIAL_RUNNING)) {
        return WDC_ERR_CONTRACT_VIOLATION;
    }
    return WDC_OK;
}

uint32_t wdc_app_artifact_header_crc32(
    const WdcPulseAppArtifactHeaderV1 *header)
{
    WdcPulseAppArtifactHeaderV1 copy;
    if (header == NULL) {
        return 0u;
    }
    memcpy(&copy, header, sizeof(copy));
    copy.header_crc32 = 0u;
    return crc32_bytes((const uint8_t *)&copy, (uint32_t)sizeof(copy));
}

int32_t wdc_app_artifact_header_seal(WdcPulseAppArtifactHeaderV1 *header)
{
    if (header == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    header->header_crc32 = 0u;
    header->header_crc32 = wdc_app_artifact_header_crc32(header);
    return WDC_OK;
}

int32_t wdc_app_artifact_header_validate(
    const WdcPulseAppArtifactHeaderV1 *header)
{
    if (header == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    if (header->magic != WDC_APP_ARTIFACT_MAGIC ||
        header->version != WDC_APP_ARTIFACT_VERSION ||
        header->header_bytes != WDC_APP_ARTIFACT_HEADER_BYTES ||
        header->flags != 0u || header->application_version == 0u ||
        header->security_counter == 0u || header->bundle_bytes == 0u ||
        header->bundle_bytes > UINT32_MAX - WDC_APP_ARTIFACT_HEADER_BYTES ||
        header->total_bytes !=
            WDC_APP_ARTIFACT_HEADER_BYTES + header->bundle_bytes ||
        bytes_zero(header->bundle_sha256, WDC_BUNDLE_SHA256_BYTES) ||
        bytes_zero(header->application_id_sha256,
                   WDC_BUNDLE_SHA256_BYTES) ||
        !bytes_zero(header->reserved, (uint32_t)sizeof(header->reserved)) ||
        (header->requirements.required_capability_mask &
         WDC_HOST_CAP_APPLICATION_SLOTS) == 0u) {
        return WDC_ERR_BAD_ENCODING;
    }
    if (header->header_crc32 != wdc_app_artifact_header_crc32(header)) {
        return WDC_ERR_CONTRACT_VIOLATION;
    }
    return WDC_OK;
}

WdcBundleSlotId wdc_app_slots_inactive_slot(
    const WdcBundleMetadataV1 *metadata)
{
    if (metadata == NULL) {
        return WDC_BUNDLE_SLOT_NONE;
    }
    if (metadata->last_good_slot == WDC_BUNDLE_SLOT_A ||
        metadata->active_slot == WDC_BUNDLE_SLOT_A) {
        return WDC_BUNDLE_SLOT_B;
    }
    if (metadata->last_good_slot == WDC_BUNDLE_SLOT_B ||
        metadata->active_slot == WDC_BUNDLE_SLOT_B) {
        return WDC_BUNDLE_SLOT_A;
    }
    return WDC_BUNDLE_SLOT_A;
}

static int32_t commit_metadata(WdcBundleMetadataV1 *metadata)
{
    WdcBundleMetadataV1 durable;
    int32_t status;
    if (metadata == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    status = wdc_bundle_metadata_seal(metadata);
    if (status != WDC_OK) {
        return status;
    }
    status = wdc_ota_write_metadata(metadata);
    if (status != WDC_OK && wdc_ota_read_metadata(&durable) == WDC_OK) {
        /*
         * A simulated or real reset may happen after any journal byte. Keep
         * the caller's RAM view aligned with whichever complete generation is
         * durably authoritative, including the after-marker boundary where
         * the new record is complete even though the write did not return.
         */
        memcpy(metadata, &durable, sizeof(*metadata));
    }
    return status;
}

int32_t wdc_app_slots_stage_begin(
    WdcAppSlotStageSession *session,
    const WdcBundleMetadataV1 *metadata,
    WdcBundleSlotId slot,
    uint32_t artifact_bytes)
{
    uint32_t capacity = 0u;
    int32_t status;
    if (session == NULL || metadata == NULL || artifact_bytes == 0u) {
        return WDC_ERR_BAD_POINTER;
    }
    memset(session, 0, sizeof(*session));
    status = metadata_semantics_validate(metadata);
    if (status != WDC_OK) {
        return status;
    }
    if (!slot_valid(slot) || slot != wdc_app_slots_inactive_slot(metadata) ||
        slot == metadata->active_slot || slot == metadata->last_good_slot) {
        return WDC_ERR_INVALID_STATE;
    }
    status = wdc_ota_slot_capacity_bytes(slot, &capacity);
    if (status != WDC_OK) {
        return status;
    }
    if (artifact_bytes < WDC_APP_ARTIFACT_HEADER_BYTES ||
        artifact_bytes > capacity) {
        return WDC_ERR_BAD_LENGTH;
    }
    status = wdc_ota_stage_begin(&session->storage, slot, artifact_bytes);
    if (status == WDC_OK) {
        session->slot = slot;
        session->application_code_launched = 0u;
    }
    return status;
}

int32_t wdc_app_slots_stage_write(WdcAppSlotStageSession *session,
                                  const uint8_t *bytes,
                                  uint32_t length)
{
    if (session == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    return wdc_ota_stage_write(&session->storage, bytes, length);
}

int32_t wdc_app_slots_stage_abort(WdcAppSlotStageSession *session)
{
    if (session == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    session->application_code_launched = 0u;
    return wdc_ota_stage_abort(&session->storage);
}

static int32_t stream_hash(WdcBundleSlotId slot,
                           uint32_t offset,
                           uint32_t length,
                           uint8_t out_hash[WDC_BUNDLE_SHA256_BYTES])
{
    uint8_t chunk[WDC_APP_ARTIFACT_READ_CHUNK_BYTES];
    WdcSha256Context hash;
    uint32_t consumed = 0u;
    int32_t status;
    if (out_hash == NULL || length == 0u) {
        return WDC_ERR_BAD_POINTER;
    }
    wdc_sha256_init(&hash);
    while (consumed < length) {
        uint32_t remaining = length - consumed;
        uint32_t count = remaining < sizeof(chunk) ? remaining : sizeof(chunk);
        status = wdc_ota_read_slot_range(slot,
                                         offset + consumed,
                                         chunk,
                                         count);
        if (status != WDC_OK) {
            return status;
        }
        wdc_sha256_update(&hash, chunk, count);
        consumed += count;
    }
    wdc_sha256_final(&hash, out_hash);
    return WDC_OK;
}

static int32_t validate_stored_artifact(
    WdcBundleSlotId slot,
    const WdcBundleSlotRecord *expected_record,
    const WdcHostFingerprintV1 *fingerprint,
    const WdcAppSlotVerifyPolicy *policy,
    uint8_t *bundle_scratch,
    uint32_t bundle_scratch_bytes,
    WdcStoredArtifactValidation *out)
{
    WdcBundleVerifyPolicy bundle_policy;
    WdcHostPrelaunchDecision compatibility;
    uint8_t bundle_hash[WDC_BUNDLE_SHA256_BYTES];
    uint8_t application_id_hash[WDC_BUNDLE_SHA256_BYTES];
    uint32_t capacity = 0u;
    int32_t status;
    if (out == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    memset(out, 0, sizeof(*out));
    out->status = WDC_ERR_UNKNOWN;
    if (!slot_valid(slot) || fingerprint == NULL || policy == NULL ||
        policy->bundle_policy == NULL || bundle_scratch == NULL) {
        out->status = WDC_ERR_BAD_POINTER;
        return out->status;
    }
    status = wdc_ota_read_slot_range(slot,
                                     0u,
                                     (uint8_t *)&out->header,
                                     sizeof(out->header));
    if (status != WDC_OK) {
        out->status = status;
        return status;
    }
    status = wdc_app_artifact_header_validate(&out->header);
    if (status != WDC_OK) {
        out->status = status;
        return status;
    }
    out->header_valid = true;
    status = wdc_ota_slot_capacity_bytes(slot, &capacity);
    if (status != WDC_OK || out->header.total_bytes > capacity ||
        out->header.bundle_bytes > bundle_scratch_bytes) {
        out->status = status != WDC_OK ? status : WDC_ERR_BAD_LENGTH;
        return out->status;
    }
    status = stream_hash(slot,
                         WDC_APP_ARTIFACT_HEADER_BYTES,
                         out->header.bundle_bytes,
                         bundle_hash);
    if (status != WDC_OK ||
        !bytes_equal(bundle_hash,
                     out->header.bundle_sha256,
                     WDC_BUNDLE_SHA256_BYTES)) {
        out->status = status != WDC_OK ? status : WDC_ERR_CONTRACT_VIOLATION;
        return out->status;
    }
    out->bundle_hash_valid = true;
    status = stream_hash(slot,
                         0u,
                         out->header.total_bytes,
                         out->artifact_sha256);
    if (status != WDC_OK) {
        out->status = status;
        return status;
    }
    out->streamed_bytes = out->header.bundle_bytes + out->header.total_bytes;
    if (expected_record != NULL &&
        (expected_record->artifact_format_version !=
             WDC_APP_ARTIFACT_VERSION ||
         expected_record->artifact_bytes != out->header.total_bytes ||
         !bytes_equal(expected_record->artifact_sha256,
                      out->artifact_sha256,
                      WDC_BUNDLE_SHA256_BYTES))) {
        out->status = WDC_ERR_CONTRACT_VIOLATION;
        return out->status;
    }
    status = wdc_ota_read_slot_range(slot,
                                     WDC_APP_ARTIFACT_HEADER_BYTES,
                                     bundle_scratch,
                                     out->header.bundle_bytes);
    if (status != WDC_OK) {
        out->status = status;
        return status;
    }
    bundle_policy = *policy->bundle_policy;
    if (bundle_policy.min_security_counter < policy->security_version_floor) {
        bundle_policy.min_security_counter = policy->security_version_floor;
    }
    status = wdc_bundle_verify(bundle_scratch,
                               out->header.bundle_bytes,
                               &bundle_policy,
                               &out->bundle_verify);
    if (status != WDC_OK) {
        out->status = status;
        return status;
    }
    out->bundle_valid = true;
    wdc_sha256((const uint8_t *)out->bundle_verify.manifest.bundle_id,
               (uint32_t)strlen(out->bundle_verify.manifest.bundle_id),
               application_id_hash);
    if (out->header.application_version !=
            out->bundle_verify.manifest.bundle_version ||
        out->header.security_counter !=
            out->bundle_verify.manifest.security_counter ||
        !bytes_equal(application_id_hash,
                     out->header.application_id_sha256,
                     WDC_BUNDLE_SHA256_BYTES)) {
        out->status = WDC_ERR_CONTRACT_VIOLATION;
        return out->status;
    }
    if (out->header.security_counter < policy->security_version_floor) {
        out->status = WDC_ERR_CAPABILITY_DENIED;
        return out->status;
    }
    out->security_floor_valid = true;
    status = wdc_host_compatibility_check(fingerprint,
                                          &out->header.requirements,
                                          &compatibility);
    if (status != WDC_OK) {
        out->status = status;
        return status;
    }
    out->host_compatible = true;
    if (policy->production_mode &&
        policy->artifact_authority_verify == NULL) {
        out->status = WDC_ERR_NOT_AVAILABLE;
        return out->status;
    }
    if (policy->artifact_authority_verify != NULL) {
        status = policy->artifact_authority_verify(
            policy->artifact_authority_ctx,
            &out->header,
            out->artifact_sha256,
            &out->bundle_verify);
        if (status != WDC_OK) {
            out->status = status;
            return status;
        }
    }
    out->authority_valid = !policy->production_mode ||
                           policy->artifact_authority_verify != NULL;
    out->status = WDC_OK;
    return WDC_OK;
}

static int32_t reject_staged_slot(WdcBundleMetadataV1 *metadata,
                                  WdcBundleSlotId slot,
                                  uint32_t artifact_bytes,
                                  int32_t reason)
{
    WdcBundleSlotRecord *record = mutable_record(metadata, slot);
    if (record == NULL) {
        return WDC_ERR_INVALID_RESOURCE;
    }
    memset(record, 0, sizeof(*record));
    record->state = WDC_SLOT_REJECTED;
    record->artifact_bytes = artifact_bytes;
    record->artifact_format_version = WDC_APP_ARTIFACT_VERSION;
    metadata->last_failure_reason = reason;
    metadata->last_rejected_slot = slot;
    metadata->metadata_generation++;
    return commit_metadata(metadata);
}

int32_t wdc_app_slots_stage_finish(
    WdcAppSlotStageSession *session,
    WdcBundleMetadataV1 *metadata,
    const WdcHostFingerprintV1 *fingerprint,
    const WdcAppSlotVerifyPolicy *policy,
    uint8_t *bundle_scratch,
    uint32_t bundle_scratch_bytes,
    WdcAppSlotStageResult *out_result)
{
    WdcStoredArtifactValidation validation;
    WdcBundleSlotRecord *record;
    uint32_t artifact_bytes;
    int32_t status;
    if (out_result != NULL) {
        memset(out_result, 0, sizeof(*out_result));
        out_result->status = WDC_ERR_UNKNOWN;
        out_result->terminal_state = WDC_SLOT_EMPTY;
    }
    if (session == NULL || metadata == NULL || out_result == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    out_result->slot = session->slot;
    out_result->application_code_launched = 0u;
    artifact_bytes = session->storage.expected_bytes;
    status = metadata_semantics_validate(metadata);
    if (status != WDC_OK) {
        out_result->status = status;
        return status;
    }
    status = wdc_ota_stage_finish(&session->storage);
    if (status != WDC_OK) {
        out_result->status = status;
        return status;
    }
    status = validate_stored_artifact(session->slot,
                                      NULL,
                                      fingerprint,
                                      policy,
                                      bundle_scratch,
                                      bundle_scratch_bytes,
                                      &validation);
    out_result->status = status;
    out_result->streamed_bytes = validation.streamed_bytes;
    out_result->header_valid = validation.header_valid;
    out_result->bundle_hash_valid = validation.bundle_hash_valid;
    out_result->bundle_valid = validation.bundle_valid;
    out_result->host_compatible = validation.host_compatible;
    out_result->security_floor_valid = validation.security_floor_valid;
    out_result->authority_valid = validation.authority_valid;
    out_result->header = validation.header;
    out_result->bundle_verify = validation.bundle_verify;
    memcpy(out_result->artifact_sha256,
           validation.artifact_sha256,
           WDC_BUNDLE_SHA256_BYTES);
    if (status != WDC_OK) {
        int32_t reject_status = reject_staged_slot(metadata,
                                                   session->slot,
                                                   artifact_bytes,
                                                   status);
        if (reject_status == WDC_OK) {
            out_result->metadata_commits = 1u;
            out_result->terminal_state = WDC_SLOT_REJECTED;
        }
        return status;
    }
    record = mutable_record(metadata, session->slot);
    if (record == NULL) {
        out_result->status = WDC_ERR_INVALID_RESOURCE;
        return out_result->status;
    }
    memset(record, 0, sizeof(*record));
    record->state = WDC_SLOT_STAGED;
    record->bundle_version = validation.header.application_version;
    record->security_counter = validation.header.security_counter;
    memcpy(record->payload_sha256,
           validation.bundle_verify.header.payload_sha256,
           WDC_BUNDLE_SHA256_BYTES);
    record->artifact_format_version = WDC_APP_ARTIFACT_VERSION;
    record->artifact_bytes = validation.header.total_bytes;
    memcpy(record->artifact_sha256,
           validation.artifact_sha256,
           WDC_BUNDLE_SHA256_BYTES);
    metadata->metadata_generation++;
    status = commit_metadata(metadata);
    if (status != WDC_OK) {
        out_result->status = status;
        return status;
    }
    out_result->metadata_commits = 1u;
    record->state = WDC_SLOT_VERIFIED;
    metadata->metadata_generation++;
    status = commit_metadata(metadata);
    if (status != WDC_OK) {
        out_result->status = status;
        out_result->terminal_state = WDC_SLOT_STAGED;
        return status;
    }
    out_result->metadata_commits = 2u;
    out_result->terminal_state = WDC_SLOT_VERIFIED;
    out_result->status = WDC_OK;
    return WDC_OK;
}

int32_t wdc_app_slots_mark_trial(
    WdcBundleMetadataV1 *metadata,
    WdcBundleSlotId slot,
    const WdcActivationPolicy *policy)
{
    int32_t status = wdc_activation_prepare_pending(metadata, slot, policy);
    if (status != WDC_OK) {
        return status;
    }
    return commit_metadata(metadata);
}

static void boot_result_init(WdcAppSlotBootResult *result)
{
    if (result != NULL) {
        memset(result, 0, sizeof(*result));
        result->status = WDC_ERR_UNKNOWN;
        result->outcome = WDC_APP_SLOT_BOOT_NOT_EVALUATED;
        result->selected_slot = WDC_BUNDLE_SLOT_NONE;
        result->fallback_slot = WDC_BUNDLE_SLOT_NONE;
        result->application_code_launched = 0u;
    }
}

static void boot_recovery(WdcAppSlotBootResult *result, int32_t status)
{
    result->status = status;
    result->outcome = WDC_APP_SLOT_BOOT_RECOVERY;
    result->selected_slot = WDC_BUNDLE_SLOT_NONE;
    result->recovery = true;
    result->application_code_launched = 0u;
}

static int32_t prepare_reject_boot_slot(WdcBundleMetadataV1 *metadata,
                                        WdcBundleSlotId slot,
                                        int32_t reason)
{
    WdcBundleSlotRecord *record = mutable_record(metadata, slot);
    if (record == NULL) {
        return WDC_ERR_INVALID_RESOURCE;
    }
    record->state = WDC_SLOT_REJECTED;
    metadata->last_failure_reason = reason;
    metadata->last_rejected_slot = slot;
    metadata->trial_boot_in_progress = 0u;
    if (metadata->active_slot == slot) {
        metadata->active_slot = WDC_BUNDLE_SLOT_NONE;
    }
    if (metadata->last_good_slot == slot) {
        metadata->last_good_slot = WDC_BUNDLE_SLOT_NONE;
    }
    metadata->metadata_generation++;
    return WDC_OK;
}

static int32_t reject_boot_slot(WdcBundleMetadataV1 *metadata,
                                WdcBundleSlotId slot,
                                int32_t reason)
{
    int32_t status = prepare_reject_boot_slot(metadata, slot, reason);
    if (status != WDC_OK) {
        return status;
    }
    return commit_metadata(metadata);
}

static int32_t validate_for_boot(
    WdcBundleSlotId slot,
    const WdcBundleSlotRecord *record,
    const WdcHostFingerprintV1 *fingerprint,
    const WdcControlHeapSnapshot *heap,
    const WdcAppSlotVerifyPolicy *verify_policy,
    uint8_t *bundle_scratch,
    uint32_t bundle_scratch_bytes,
    WdcStoredArtifactValidation *validation,
    WdcHostPrelaunchDecision *prelaunch)
{
    int32_t status = validate_stored_artifact(slot,
                                              record,
                                              fingerprint,
                                              verify_policy,
                                              bundle_scratch,
                                              bundle_scratch_bytes,
                                              validation);
    if (status != WDC_OK) {
        return status;
    }
    return wdc_host_prelaunch_check(fingerprint,
                                    &validation->header.requirements,
                                    heap,
                                    prelaunch);
}

int32_t wdc_app_slots_validate_reboot_candidate(
    const WdcBundleMetadataV1 *metadata,
    WdcBundleSlotId slot,
    const WdcHostFingerprintV1 *fingerprint,
    const WdcControlHeapSnapshot *heap,
    const WdcAppSlotVerifyPolicy *verify_policy,
    uint8_t *bundle_scratch,
    uint32_t bundle_scratch_bytes,
    WdcAppSlotBootResult *out_result)
{
    WdcStoredArtifactValidation validation;
    const WdcBundleSlotRecord *record;
    int32_t status;
    boot_result_init(out_result);
    if (metadata == NULL || fingerprint == NULL || heap == NULL ||
        verify_policy == NULL || bundle_scratch == NULL ||
        out_result == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    status = metadata_semantics_validate(metadata);
    record = record_for(metadata, slot);
    if (status != WDC_OK || !slot_valid(slot) ||
        metadata->active_slot != slot || record == NULL ||
        (record->state != WDC_SLOT_CONFIRMED &&
         record->state != WDC_SLOT_TRIAL)) {
        out_result->status = status != WDC_OK ? status
                                               : WDC_ERR_INVALID_STATE;
        return out_result->status;
    }
    out_result->selected_slot = slot;
    memset(&validation, 0, sizeof(validation));
    status = validate_for_boot(slot, record, fingerprint, heap,
                               verify_policy, bundle_scratch,
                               bundle_scratch_bytes, &validation,
                               &out_result->prelaunch);
    out_result->status = status;
    out_result->header = validation.header;
    out_result->bundle_verify = validation.bundle_verify;
    out_result->application_code_launched = 0u;
    if (status != WDC_OK) {
        return status;
    }
    out_result->bundle_offset = WDC_APP_ARTIFACT_HEADER_BYTES;
    out_result->bundle_bytes = validation.header.bundle_bytes;
    out_result->probation = record->state == WDC_SLOT_TRIAL;
    out_result->outcome = out_result->probation
                              ? WDC_APP_SLOT_BOOT_RUN_TRIAL
                              : WDC_APP_SLOT_BOOT_RUN_CONFIRMED;
    return WDC_OK;
}

int32_t wdc_app_slots_boot(
    WdcBundleMetadataV1 *metadata,
    const WdcActivationPolicy *activation_policy,
    const WdcActivationBootContext *boot_context,
    const WdcHostFingerprintV1 *fingerprint,
    const WdcControlHeapSnapshot *heap,
    const WdcAppSlotVerifyPolicy *verify_policy,
    uint8_t *bundle_scratch,
    uint32_t bundle_scratch_bytes,
    WdcAppSlotBootResult *out_result)
{
    WdcStoredArtifactValidation validation;
    const WdcBundleSlotRecord *record;
    WdcBundleSlotId alternate;
    int32_t status;
    boot_result_init(out_result);
    if (metadata == NULL || fingerprint == NULL || heap == NULL ||
        verify_policy == NULL || bundle_scratch == NULL ||
        out_result == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    status = metadata_semantics_validate(metadata);
    if (status != WDC_OK) {
        boot_recovery(out_result, status);
        return status;
    }
    status = wdc_activation_on_boot_attributed(metadata,
                                               activation_policy,
                                               boot_context,
                                               &out_result->activation);
    if (status != WDC_OK) {
        boot_recovery(out_result, status);
        return status;
    }
    if (out_result->activation.metadata_changed) {
        status = commit_metadata(metadata);
        if (status != WDC_OK) {
            boot_recovery(out_result, status);
            return status;
        }
        out_result->metadata_commits++;
    }
    if (out_result->activation.kind ==
        WDC_ACTIVATION_DECISION_ROLLBACK_TO_LAST_GOOD) {
        out_result->status = WDC_OK;
        out_result->outcome =
            WDC_APP_SLOT_BOOT_FALLBACK_REBOOT_REQUIRED;
        out_result->fallback_slot = out_result->activation.fallback_slot;
        out_result->reboot_required = true;
        return WDC_OK;
    }
    if (out_result->activation.slot_to_run == WDC_BUNDLE_SLOT_NONE ||
        out_result->activation.kind == WDC_ACTIVATION_DECISION_NO_BUNDLE ||
        out_result->activation.kind ==
            WDC_ACTIVATION_DECISION_FAULT_NO_FALLBACK ||
        out_result->activation.kind == WDC_ACTIVATION_DECISION_ENTER_RECOVERY) {
        boot_recovery(out_result, WDC_ERR_NOT_AVAILABLE);
        return WDC_ERR_NOT_AVAILABLE;
    }
    out_result->selected_slot = out_result->activation.slot_to_run;
    record = record_for(metadata, out_result->selected_slot);
    status = validate_for_boot(out_result->selected_slot,
                               record,
                               fingerprint,
                               heap,
                               verify_policy,
                               bundle_scratch,
                               bundle_scratch_bytes,
                               &validation,
                               &out_result->prelaunch);
    out_result->header = validation.header;
    out_result->bundle_verify = validation.bundle_verify;
    if (status == WDC_OK) {
        out_result->status = WDC_OK;
        out_result->bundle_offset = WDC_APP_ARTIFACT_HEADER_BYTES;
        out_result->bundle_bytes = validation.header.bundle_bytes;
        out_result->probation = out_result->activation.probation;
        out_result->outcome = out_result->probation
                                  ? WDC_APP_SLOT_BOOT_RUN_TRIAL
                                  : WDC_APP_SLOT_BOOT_RUN_CONFIRMED;
        out_result->application_code_launched = 0u;
        return WDC_OK;
    }
    if (out_result->activation.probation) {
        WdcActivationDecision fault;
        int32_t fault_status = wdc_activation_record_fault(
            metadata,
            out_result->selected_slot,
            status,
            &fault);
        if (fault_status == WDC_OK) {
            fault_status = commit_metadata(metadata);
        }
        if (fault_status != WDC_OK) {
            boot_recovery(out_result, fault_status);
            return fault_status;
        }
        out_result->metadata_commits++;
        out_result->activation = fault;
        out_result->fallback_slot = fault.fallback_slot;
        if (fault.fallback_slot != WDC_BUNDLE_SLOT_NONE) {
            out_result->status = status;
            out_result->outcome =
                WDC_APP_SLOT_BOOT_FALLBACK_REBOOT_REQUIRED;
            out_result->reboot_required = true;
            return status;
        }
        boot_recovery(out_result, status);
        return status;
    }
    if (out_result->prelaunch.outcome ==
        WDC_HOST_PRELAUNCH_DENIED_RESOURCE) {
        boot_recovery(out_result, status);
        return status;
    }
    {
        int32_t rejection_reason = status;
        alternate = other_slot(out_result->selected_slot);
        record = record_for(metadata, alternate);
        if (record != NULL && record->state == WDC_SLOT_CONFIRMED) {
            WdcStoredArtifactValidation alternate_validation;
            WdcHostPrelaunchDecision alternate_prelaunch;
            status = validate_for_boot(alternate,
                                       record,
                                       fingerprint,
                                       heap,
                                       verify_policy,
                                       bundle_scratch,
                                       bundle_scratch_bytes,
                                       &alternate_validation,
                                       &alternate_prelaunch);
            if (status == WDC_OK) {
                status = prepare_reject_boot_slot(metadata,
                                                  out_result->selected_slot,
                                                  rejection_reason);
                if (status == WDC_OK) {
                    metadata->active_slot = alternate;
                    metadata->last_good_slot = alternate;
                    status = commit_metadata(metadata);
                }
                if (status != WDC_OK) {
                    boot_recovery(out_result, status);
                    return status;
                }
                out_result->metadata_commits++;
                out_result->status = WDC_OK;
                out_result->outcome =
                    WDC_APP_SLOT_BOOT_FALLBACK_REBOOT_REQUIRED;
                out_result->fallback_slot = alternate;
                out_result->reboot_required = true;
                return WDC_OK;
            }
        }
        status = reject_boot_slot(metadata,
                                  out_result->selected_slot,
                                  rejection_reason);
        if (status != WDC_OK) {
            boot_recovery(out_result, status);
            return status;
        }
        out_result->metadata_commits++;
    }
    boot_recovery(out_result, WDC_ERR_NOT_AVAILABLE);
    return WDC_ERR_NOT_AVAILABLE;
}

int32_t wdc_app_slots_evaluate_probation(
    WdcBundleMetadataV1 *metadata,
    WdcBundleSlotId slot,
    const WdcActivationPolicy *policy,
    const WdcActivationProbationEvidence *evidence,
    WdcActivationDecision *out_decision)
{
    WdcActivationDecision local_decision;
    WdcActivationDecision *decision =
        out_decision != NULL ? out_decision : &local_decision;
    int32_t status = wdc_activation_evaluate_probation(metadata,
                                                       slot,
                                                       policy,
                                                       evidence,
                                                       decision);
    if (status == WDC_ERR_BUSY) {
        return status;
    }
    if (status == WDC_OK && decision->metadata_changed) {
        return commit_metadata(metadata);
    }
    return status;
}

int32_t wdc_app_slots_record_runtime_fault(
    WdcBundleMetadataV1 *metadata,
    WdcBundleSlotId slot,
    int32_t failure_reason,
    WdcActivationDecision *out_decision)
{
    int32_t status = wdc_activation_record_fault(metadata,
                                                 slot,
                                                 failure_reason,
                                                 out_decision);
    if (status != WDC_OK) {
        return status;
    }
    return commit_metadata(metadata);
}

uint32_t wdc_app_slots_link_anchor(void)
{
    return 0x48503301u;
}
