#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "wdc_activation.h"
#include "wdc_bundle.h"
#include "wdc_host_identity.h"
#include "wdc_ota.h"

#ifdef __cplusplus
extern "C" {
#endif

#define WDC_APP_ARTIFACT_MAGIC 0x50534150u /* PASP */
#define WDC_APP_ARTIFACT_VERSION 1u
#define WDC_APP_ARTIFACT_HEADER_BYTES 192u
#define WDC_APP_ARTIFACT_READ_CHUNK_BYTES 256u
#define WDC_APP_SLOT_PORTABLE_MINIMUM_BYTES (896u * 1024u)
#define WDC_APP_SLOT_S3_BYTES (2u * 1024u * 1024u)

typedef struct WdcPulseAppArtifactHeaderV1 {
    uint32_t magic;
    uint16_t version;
    uint16_t header_bytes;
    uint32_t total_bytes;
    uint32_t bundle_bytes;
    uint32_t application_version;
    uint32_t flags;
    uint64_t security_counter;
    WdcHostApplicationRequirements requirements;
    uint8_t bundle_sha256[WDC_BUNDLE_SHA256_BYTES];
    uint8_t application_id_sha256[WDC_BUNDLE_SHA256_BYTES];
    uint8_t reserved[28];
    uint32_t header_crc32;
} WdcPulseAppArtifactHeaderV1;

typedef int32_t (*WdcAppArtifactAuthorityVerifyFn)(
    void *ctx,
    const WdcPulseAppArtifactHeaderV1 *header,
    const uint8_t artifact_sha256[WDC_BUNDLE_SHA256_BYTES],
    const WdcBundleVerifyResult *bundle_verify);

typedef struct WdcAppSlotVerifyPolicy {
    const WdcBundleVerifyPolicy *bundle_policy;
    uint64_t security_version_floor;
    bool production_mode;
    WdcAppArtifactAuthorityVerifyFn artifact_authority_verify;
    void *artifact_authority_ctx;
} WdcAppSlotVerifyPolicy;

typedef struct WdcAppSlotStageSession {
    WdcOtaStageSession storage;
    WdcBundleSlotId slot;
    uint32_t application_code_launched;
} WdcAppSlotStageSession;

typedef struct WdcAppSlotStageResult {
    int32_t status;
    WdcBundleSlotId slot;
    WdcSlotState terminal_state;
    uint32_t streamed_bytes;
    uint32_t metadata_commits;
    uint32_t application_code_launched;
    bool header_valid;
    bool bundle_hash_valid;
    bool bundle_valid;
    bool host_compatible;
    bool security_floor_valid;
    bool authority_valid;
    uint8_t artifact_sha256[WDC_BUNDLE_SHA256_BYTES];
    WdcPulseAppArtifactHeaderV1 header;
    WdcBundleVerifyResult bundle_verify;
} WdcAppSlotStageResult;

typedef enum WdcAppSlotBootOutcome {
    WDC_APP_SLOT_BOOT_NOT_EVALUATED = 0,
    WDC_APP_SLOT_BOOT_RUN_CONFIRMED = 1,
    WDC_APP_SLOT_BOOT_RUN_TRIAL = 2,
    WDC_APP_SLOT_BOOT_FALLBACK_REBOOT_REQUIRED = 3,
    WDC_APP_SLOT_BOOT_RECOVERY = 4,
} WdcAppSlotBootOutcome;

typedef struct WdcAppSlotBootResult {
    int32_t status;
    WdcAppSlotBootOutcome outcome;
    WdcBundleSlotId selected_slot;
    WdcBundleSlotId fallback_slot;
    uint32_t bundle_offset;
    uint32_t bundle_bytes;
    uint32_t metadata_commits;
    uint32_t application_code_launched;
    bool probation;
    bool reboot_required;
    bool recovery;
    WdcActivationDecision activation;
    WdcHostPrelaunchDecision prelaunch;
    WdcPulseAppArtifactHeaderV1 header;
    WdcBundleVerifyResult bundle_verify;
} WdcAppSlotBootResult;

uint32_t wdc_app_artifact_header_crc32(
    const WdcPulseAppArtifactHeaderV1 *header);
int32_t wdc_app_artifact_header_seal(WdcPulseAppArtifactHeaderV1 *header);
int32_t wdc_app_artifact_header_validate(
    const WdcPulseAppArtifactHeaderV1 *header);

WdcBundleSlotId wdc_app_slots_inactive_slot(
    const WdcBundleMetadataV1 *metadata);

int32_t wdc_app_slots_stage_begin(
    WdcAppSlotStageSession *session,
    const WdcBundleMetadataV1 *metadata,
    WdcBundleSlotId slot,
    uint32_t artifact_bytes);
int32_t wdc_app_slots_stage_write(WdcAppSlotStageSession *session,
                                  const uint8_t *bytes,
                                  uint32_t length);
int32_t wdc_app_slots_stage_abort(WdcAppSlotStageSession *session);
int32_t wdc_app_slots_stage_finish(
    WdcAppSlotStageSession *session,
    WdcBundleMetadataV1 *metadata,
    const WdcHostFingerprintV1 *fingerprint,
    const WdcAppSlotVerifyPolicy *policy,
    uint8_t *bundle_scratch,
    uint32_t bundle_scratch_bytes,
    WdcAppSlotStageResult *out_result);

int32_t wdc_app_slots_mark_trial(
    WdcBundleMetadataV1 *metadata,
    WdcBundleSlotId slot,
    const WdcActivationPolicy *policy);

int32_t wdc_app_slots_boot(
    WdcBundleMetadataV1 *metadata,
    const WdcActivationPolicy *activation_policy,
    const WdcActivationBootContext *boot_context,
    const WdcHostFingerprintV1 *fingerprint,
    const WdcControlHeapSnapshot *heap,
    const WdcAppSlotVerifyPolicy *verify_policy,
    uint8_t *bundle_scratch,
    uint32_t bundle_scratch_bytes,
    WdcAppSlotBootResult *out_result);

/*
 * Read-only HP3 viability proof used by host recovery before a reboot
 * handoff.  It re-runs the complete stored-artifact and HP2 resource checks
 * without changing slot metadata or launching application code.
 */
int32_t wdc_app_slots_validate_reboot_candidate(
    const WdcBundleMetadataV1 *metadata,
    WdcBundleSlotId slot,
    const WdcHostFingerprintV1 *fingerprint,
    const WdcControlHeapSnapshot *heap,
    const WdcAppSlotVerifyPolicy *verify_policy,
    uint8_t *bundle_scratch,
    uint32_t bundle_scratch_bytes,
    WdcAppSlotBootResult *out_result);

int32_t wdc_app_slots_evaluate_probation(
    WdcBundleMetadataV1 *metadata,
    WdcBundleSlotId slot,
    const WdcActivationPolicy *policy,
    const WdcActivationProbationEvidence *evidence,
    WdcActivationDecision *out_decision);

int32_t wdc_app_slots_record_runtime_fault(
    WdcBundleMetadataV1 *metadata,
    WdcBundleSlotId slot,
    int32_t failure_reason,
    WdcActivationDecision *out_decision);

uint32_t wdc_app_slots_link_anchor(void);

#ifdef __cplusplus
}
#endif
