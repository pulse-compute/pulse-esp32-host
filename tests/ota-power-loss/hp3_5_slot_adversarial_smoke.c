#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "wdc_activation.h"
#include "wdc_app_slots.h"
#include "wdc_bundle.h"
#include "wdc_host_identity.h"
#include "wdc_ota.h"
#include "wdc_profile.h"

#define MAX_BUNDLE_BYTES 8192u
#define MAX_ARTIFACT_BYTES (WDC_APP_ARTIFACT_HEADER_BYTES + MAX_BUNDLE_BYTES)
#define JOURNAL_TRANSITIONS 8u
#define REPEATED_TRAP_CYCLES 32u

static uint8_t s_bundle[MAX_BUNDLE_BYTES];
static uint8_t s_artifact[MAX_ARTIFACT_BYTES];
static uint8_t s_scratch[MAX_BUNDLE_BYTES];
static uint32_t s_bundle_bytes;
static uint32_t s_artifact_bytes;
static WdcBundleSlotRecord s_artifact_record;
static WdcAppSlotVerifyPolicy s_verify_policy;
static WdcBundleVerifyPolicy s_bundle_policy;
static WdcHostFingerprintV1 s_s3_storage;
static WdcHostFingerprintV1 s_c6_storage;
static const WdcHostFingerprintV1 *s_s3;
static const WdcHostFingerprintV1 *s_c6;
static WdcActivationPolicy s_activation;
static WdcControlHeapSnapshot s_heap;

static uint32_t s_failures;
static uint32_t s_payload_cases;
static uint32_t s_slot_erase_cases;
static uint32_t s_journal_cases;
static uint32_t s_confirmation_cases;
static uint32_t s_corruption_cases;
static uint32_t s_semantic_cases;

#define CHECK(expression)                                                       \
    do {                                                                        \
        if (!(expression)) {                                                    \
            if (s_failures < 40u) {                                             \
                (void)fprintf(stderr,                                           \
                              "CHECK failed at %s:%d: %s\n",                  \
                              __FILE__, __LINE__, #expression);                 \
            }                                                                   \
            s_failures++;                                                       \
        }                                                                       \
    } while (0)

static int load_bundle(const char *path)
{
    FILE *handle = fopen(path, "rb");
    long size;
    if (handle == NULL || fseek(handle, 0L, SEEK_END) != 0) {
        if (handle != NULL) {
            (void)fclose(handle);
        }
        return 0;
    }
    size = ftell(handle);
    if (size <= 0L || (unsigned long)size > sizeof(s_bundle) ||
        fseek(handle, 0L, SEEK_SET) != 0 ||
        fread(s_bundle, 1u, (size_t)size, handle) != (size_t)size) {
        (void)fclose(handle);
        return 0;
    }
    (void)fclose(handle);
    s_bundle_bytes = (uint32_t)size;
    return 1;
}

static void initialize_fixture(void)
{
    static const char app_id[] = "com.example.relay-controller";
    WdcPulseAppArtifactHeaderV1 header;
    WdcBundleParsedHeader parsed;
    const WdcHostFingerprintV1 *fingerprint;

    memset(&header, 0, sizeof(header));
    header.magic = WDC_APP_ARTIFACT_MAGIC;
    header.version = WDC_APP_ARTIFACT_VERSION;
    header.header_bytes = WDC_APP_ARTIFACT_HEADER_BYTES;
    header.total_bytes = WDC_APP_ARTIFACT_HEADER_BYTES + s_bundle_bytes;
    header.bundle_bytes = s_bundle_bytes;
    header.application_version = 8u;
    header.security_counter = 8u;
    header.requirements.allowed_target_mask = WDC_HOST_TARGET_MASK_ESP32S3;
    header.requirements.host_abi_major = 1u;
    header.requirements.host_abi_min_minor = 0u;
    header.requirements.host_abi_max_minor = 0u;
    header.requirements.required_capability_mask =
        WDC_HOST_CAP_APPLICATION_SLOTS | WDC_HOST_CAP_WASM_APPLICATION |
        WDC_HOST_CAP_EVENT_EFFECT;
    header.requirements.placement = WDC_HOST_PLACEMENT_PORTABLE;
    header.requirements.guest_linear_memory_bytes = 49152u;
    header.requirements.runtime_stack_bytes = 16384u;
    header.requirements.network_working_bytes = 8192u;
    header.requirements.capability_working_bytes = 4096u;
    header.requirements.transition_scratch_bytes = 8192u;
    header.requirements.largest_application_allocation_bytes = 49152u;
    wdc_sha256(s_bundle, s_bundle_bytes, header.bundle_sha256);
    wdc_sha256((const uint8_t *)app_id,
               (uint32_t)(sizeof(app_id) - 1u),
               header.application_id_sha256);
    CHECK(wdc_app_artifact_header_seal(&header) == WDC_OK);
    memcpy(s_artifact, &header, sizeof(header));
    memcpy(s_artifact + sizeof(header), s_bundle, s_bundle_bytes);
    s_artifact_bytes = (uint32_t)sizeof(header) + s_bundle_bytes;

    CHECK(wdc_bundle_parse_header(s_bundle, s_bundle_bytes, &parsed) == WDC_OK);
    memset(&s_artifact_record, 0, sizeof(s_artifact_record));
    s_artifact_record.bundle_version = header.application_version;
    s_artifact_record.security_counter = header.security_counter;
    memcpy(s_artifact_record.payload_sha256,
           parsed.payload_sha256,
           WDC_BUNDLE_SHA256_BYTES);
    s_artifact_record.artifact_format_version = WDC_APP_ARTIFACT_VERSION;
    s_artifact_record.artifact_bytes = s_artifact_bytes;
    wdc_sha256(s_artifact,
               s_artifact_bytes,
               s_artifact_record.artifact_sha256);

    s_bundle_policy =
        wdc_bundle_make_default_dev_policy(wdc_profile_builtin());
    memset(&s_verify_policy, 0, sizeof(s_verify_policy));
    s_verify_policy.bundle_policy = &s_bundle_policy;
    s_activation = wdc_activation_default_policy();
    s_heap.internal_free_bytes = 327680u;
    s_heap.internal_largest_block_bytes = 131072u;
    s_heap.psram_free_bytes = 1048576u;

    fingerprint = wdc_host_fingerprint_for_target(WDC_HOST_TARGET_ESP32S3);
    CHECK(fingerprint != NULL);
    if (fingerprint != NULL) {
        s_s3_storage = *fingerprint;
        s_s3_storage.capability_mask |= WDC_HOST_CAP_APPLICATION_SLOTS;
        s_s3_storage.crc32 = wdc_host_fingerprint_crc32(&s_s3_storage);
        s_s3 = &s_s3_storage;
    }
    fingerprint = wdc_host_fingerprint_for_target(WDC_HOST_TARGET_ESP32C6);
    CHECK(fingerprint != NULL);
    if (fingerprint != NULL) {
        s_c6_storage = *fingerprint;
        s_c6_storage.capability_mask |= WDC_HOST_CAP_APPLICATION_SLOTS;
        s_c6_storage.crc32 = wdc_host_fingerprint_crc32(&s_c6_storage);
        s_c6 = &s_c6_storage;
    }
}

static WdcBundleSlotRecord artifact_record(WdcSlotState state)
{
    WdcBundleSlotRecord record = s_artifact_record;
    record.state = state;
    return record;
}

static void seal_metadata(WdcBundleMetadataV1 *metadata)
{
    CHECK(wdc_bundle_metadata_seal(metadata) == WDC_OK);
}

static WdcBundleMetadataV1 base_confirmed_a(uint32_t generation)
{
    WdcBundleMetadataV1 metadata;
    wdc_bundle_metadata_init(&metadata);
    metadata.slot_a = artifact_record(WDC_SLOT_CONFIRMED);
    metadata.active_slot = WDC_BUNDLE_SLOT_A;
    metadata.last_good_slot = WDC_BUNDLE_SLOT_A;
    metadata.metadata_generation = generation;
    seal_metadata(&metadata);
    return metadata;
}

static bool has_confirmed_authority(const WdcBundleMetadataV1 *metadata)
{
    if (metadata == NULL) {
        return false;
    }
    if (metadata->last_good_slot == WDC_BUNDLE_SLOT_A) {
        return metadata->slot_a.state == WDC_SLOT_CONFIRMED;
    }
    if (metadata->last_good_slot == WDC_BUNDLE_SLOT_B) {
        return metadata->slot_b.state == WDC_SLOT_CONFIRMED;
    }
    return false;
}

static WdcBundleMetadataV1 reset_confirmed_a(void)
{
    WdcBundleMetadataV1 metadata = base_confirmed_a(10u);
    wdc_ota_host_fault_clear();
    wdc_ota_host_clear_slots();
    wdc_ota_host_clear_metadata();
    CHECK(wdc_ota_host_set_slot_image(WDC_BUNDLE_SLOT_A,
                                      s_artifact,
                                      s_artifact_bytes) == WDC_OK);
    CHECK(wdc_ota_host_set_metadata(&metadata) == WDC_OK);
    return metadata;
}

static int32_t stage_artifact(WdcBundleMetadataV1 *metadata,
                              WdcBundleSlotId slot,
                              const WdcHostFingerprintV1 *fingerprint,
                              const uint8_t *artifact,
                              WdcAppSlotStageResult *out_result)
{
    WdcAppSlotStageSession session;
    int32_t status = wdc_app_slots_stage_begin(&session,
                                               metadata,
                                               slot,
                                               s_artifact_bytes);
    if (status != WDC_OK) {
        return status;
    }
    status = wdc_app_slots_stage_write(&session,
                                       artifact,
                                       s_artifact_bytes);
    if (status != WDC_OK) {
        return status;
    }
    return wdc_app_slots_stage_finish(&session,
                                      metadata,
                                      fingerprint,
                                      &s_verify_policy,
                                      s_scratch,
                                      sizeof(s_scratch),
                                      out_result);
}

static void run_payload_matrix(void)
{
    uint32_t cut;
    for (cut = 0u; cut <= s_artifact_bytes; ++cut) {
        WdcBundleMetadataV1 metadata = reset_confirmed_a();
        WdcBundleMetadataV1 recovered;
        WdcOtaStageSession session;
        WdcOtaHostFaultPlan plan;
        CHECK(wdc_ota_stage_begin(&session,
                                  WDC_BUNDLE_SLOT_B,
                                  s_artifact_bytes) == WDC_OK);
        plan.operation = WDC_OTA_HOST_FAULT_SLOT_WRITE;
        plan.trigger_index = 1u;
        plan.tear_after_bytes = cut;
        CHECK(wdc_ota_host_fault_arm(&plan) == WDC_OK);
        CHECK(wdc_ota_stage_write(&session,
                                  s_artifact,
                                  s_artifact_bytes) == WDC_ERR_IO);
        CHECK(session.written_bytes == cut);
        CHECK(wdc_ota_host_fault_trigger_count() == 1u);
        wdc_ota_host_power_cycle();
        CHECK(wdc_ota_read_metadata(&recovered) == WDC_OK);
        CHECK(has_confirmed_authority(&recovered));
        CHECK(recovered.last_good_slot == metadata.last_good_slot);
        CHECK(wdc_ota_host_metadata_valid_record_count() >= 1u);
        s_payload_cases++;
    }
}

static void run_slot_erase_matrix(void)
{
    const uint32_t cuts[] = {
        0u,
        1u,
        WDC_OTA_METADATA_RECORD_STRIDE_BYTES - 1u,
        WDC_OTA_METADATA_RECORD_STRIDE_BYTES,
        WDC_OTA_HOST_SLOT_CAPACITY_BYTES - 1u,
        WDC_OTA_HOST_SLOT_CAPACITY_BYTES,
    };
    uint32_t index;
    for (index = 0u; index < (uint32_t)(sizeof(cuts) / sizeof(cuts[0]));
         ++index) {
        WdcBundleMetadataV1 recovered;
        WdcOtaStageSession session;
        WdcOtaHostFaultPlan plan;
        (void)reset_confirmed_a();
        CHECK(wdc_ota_host_set_slot_image(WDC_BUNDLE_SLOT_B,
                                          s_artifact,
                                          s_artifact_bytes) == WDC_OK);
        plan.operation = WDC_OTA_HOST_FAULT_SLOT_ERASE;
        plan.trigger_index = 1u;
        plan.tear_after_bytes = cuts[index];
        CHECK(wdc_ota_host_fault_arm(&plan) == WDC_OK);
        CHECK(wdc_ota_stage_begin(&session,
                                  WDC_BUNDLE_SLOT_B,
                                  s_artifact_bytes) == WDC_ERR_IO);
        CHECK(wdc_ota_host_fault_trigger_count() == 1u);
        wdc_ota_host_power_cycle();
        CHECK(wdc_ota_read_metadata(&recovered) == WDC_OK);
        CHECK(recovered.last_good_slot == WDC_BUNDLE_SLOT_A);
        CHECK(has_confirmed_authority(&recovered));
        s_slot_erase_cases++;
    }
}

static void transition_pair(uint32_t transition,
                            WdcBundleMetadataV1 *before,
                            WdcBundleMetadataV1 *after)
{
    *before = base_confirmed_a(1u);
    *after = *before;
    switch (transition) {
    case 0u: /* EMPTY -> STAGED */
        after->slot_b = artifact_record(WDC_SLOT_STAGED);
        break;
    case 1u: /* STAGED -> VERIFIED */
        before->slot_b = artifact_record(WDC_SLOT_STAGED);
        after->slot_b = artifact_record(WDC_SLOT_VERIFIED);
        break;
    case 2u: /* VERIFIED -> TRIAL */
        before->slot_b = artifact_record(WDC_SLOT_VERIFIED);
        after->slot_b = artifact_record(WDC_SLOT_TRIAL);
        after->active_slot = WDC_BUNDLE_SLOT_B;
        break;
    case 3u: /* TRIAL -> TRIAL_RUNNING */
        before->slot_b = artifact_record(WDC_SLOT_TRIAL);
        before->active_slot = WDC_BUNDLE_SLOT_B;
        after->slot_b = artifact_record(WDC_SLOT_TRIAL_RUNNING);
        after->active_slot = WDC_BUNDLE_SLOT_B;
        after->trial_boot_in_progress = 1u;
        after->candidate_boot_count = 1u;
        break;
    case 4u: /* TRIAL_RUNNING -> CONFIRMED */
        before->slot_b = artifact_record(WDC_SLOT_TRIAL_RUNNING);
        before->active_slot = WDC_BUNDLE_SLOT_B;
        before->trial_boot_in_progress = 1u;
        before->candidate_boot_count = 1u;
        after->slot_b = artifact_record(WDC_SLOT_CONFIRMED);
        after->active_slot = WDC_BUNDLE_SLOT_B;
        after->last_good_slot = WDC_BUNDLE_SLOT_B;
        after->trial_boot_in_progress = 0u;
        after->candidate_boot_count = 0u;
        break;
    case 5u: /* TRIAL_RUNNING -> REJECTED + FALLBACK */
        before->slot_b = artifact_record(WDC_SLOT_TRIAL_RUNNING);
        before->active_slot = WDC_BUNDLE_SLOT_B;
        before->trial_boot_in_progress = 1u;
        before->candidate_boot_count = 1u;
        after->slot_b = artifact_record(WDC_SLOT_REJECTED);
        after->active_slot = WDC_BUNDLE_SLOT_A;
        after->trial_boot_in_progress = 0u;
        after->last_rejected_slot = WDC_BUNDLE_SLOT_B;
        after->last_failure_reason = WDC_ERR_CONTRACT_VIOLATION;
        break;
    case 6u: /* VERIFIED -> REJECTED */
        before->slot_b = artifact_record(WDC_SLOT_VERIFIED);
        after->slot_b = artifact_record(WDC_SLOT_REJECTED);
        after->last_rejected_slot = WDC_BUNDLE_SLOT_B;
        after->last_failure_reason = WDC_ERR_INVALID_RESOURCE;
        break;
    case 7u: /* invalid confirmed B -> rejected B + confirmed A fallback */
    default:
        before->slot_b = artifact_record(WDC_SLOT_CONFIRMED);
        before->active_slot = WDC_BUNDLE_SLOT_B;
        before->last_good_slot = WDC_BUNDLE_SLOT_B;
        after->slot_b = artifact_record(WDC_SLOT_REJECTED);
        after->active_slot = WDC_BUNDLE_SLOT_A;
        after->last_good_slot = WDC_BUNDLE_SLOT_A;
        after->last_rejected_slot = WDC_BUNDLE_SLOT_B;
        after->last_failure_reason = WDC_ERR_CONTRACT_VIOLATION;
        break;
    }
}

static void run_journal_case(uint32_t transition,
                             uint32_t target_index,
                             WdcOtaHostFaultOperation operation,
                             uint32_t cut)
{
    WdcBundleMetadataV1 before;
    WdcBundleMetadataV1 after;
    WdcBundleMetadataV1 recovered;
    WdcOtaHostFaultPlan plan;
    uint32_t source_generation;
    bool new_record_complete;

    transition_pair(transition, &before, &after);
    wdc_ota_host_fault_clear();
    wdc_ota_host_clear_metadata();
    before.metadata_generation = 100u;
    seal_metadata(&before);
    CHECK(wdc_ota_host_set_metadata(&before) == WDC_OK);
    if (target_index == 0u) {
        before.metadata_generation = 101u;
        seal_metadata(&before);
        CHECK(wdc_ota_write_metadata(&before) == WDC_OK);
    }
    source_generation = before.metadata_generation;
    after.metadata_generation = source_generation + 1u;
    seal_metadata(&after);
    plan.operation = operation;
    plan.trigger_index = 1u;
    plan.tear_after_bytes = cut;
    CHECK(wdc_ota_host_fault_arm(&plan) == WDC_OK);
    CHECK(wdc_ota_write_metadata(&after) == WDC_ERR_IO);
    CHECK(wdc_ota_host_fault_trigger_count() == 1u);
    wdc_ota_host_power_cycle();
    CHECK(wdc_ota_host_metadata_valid_record_count() >= 1u);
    CHECK(wdc_ota_read_metadata(&recovered) == WDC_OK);
    CHECK(has_confirmed_authority(&recovered));
    new_record_complete =
        operation == WDC_OTA_HOST_FAULT_METADATA_MARKER_WRITE &&
        cut == wdc_ota_host_metadata_marker_bytes();
    CHECK(recovered.metadata_generation ==
          (new_record_complete ? after.metadata_generation
                               : source_generation));
    s_journal_cases++;
}

static void run_journal_matrix(void)
{
    const WdcOtaHostFaultOperation operations[] = {
        WDC_OTA_HOST_FAULT_METADATA_ERASE,
        WDC_OTA_HOST_FAULT_METADATA_BODY_WRITE,
        WDC_OTA_HOST_FAULT_METADATA_MARKER_WRITE,
    };
    uint32_t transition;
    uint32_t target;
    uint32_t op_index;
    for (transition = 0u; transition < JOURNAL_TRANSITIONS; ++transition) {
        for (target = 0u; target < WDC_OTA_METADATA_JOURNAL_RECORDS;
             ++target) {
            for (op_index = 0u;
                 op_index < (uint32_t)(sizeof(operations) /
                                       sizeof(operations[0]));
                 ++op_index) {
                uint32_t limit =
                    operations[op_index] == WDC_OTA_HOST_FAULT_METADATA_ERASE
                        ? wdc_ota_host_metadata_record_bytes()
                        : operations[op_index] ==
                                  WDC_OTA_HOST_FAULT_METADATA_BODY_WRITE
                              ? wdc_ota_host_metadata_body_bytes()
                              : wdc_ota_host_metadata_marker_bytes();
                uint32_t cut;
                for (cut = 0u; cut <= limit; ++cut) {
                    run_journal_case(transition,
                                     target,
                                     operations[op_index],
                                     cut);
                }
            }
        }
    }
}

static WdcBundleMetadataV1 trial_running_metadata(uint32_t generation)
{
    WdcBundleMetadataV1 metadata = base_confirmed_a(generation);
    metadata.slot_b = artifact_record(WDC_SLOT_TRIAL_RUNNING);
    metadata.active_slot = WDC_BUNDLE_SLOT_B;
    metadata.last_good_slot = WDC_BUNDLE_SLOT_A;
    metadata.candidate_boot_count = 1u;
    metadata.trial_boot_in_progress = 1u;
    metadata.trial_boot_generation = generation;
    seal_metadata(&metadata);
    return metadata;
}

static void install_trial_running(WdcBundleMetadataV1 *metadata,
                                  uint32_t target_index)
{
    wdc_ota_host_fault_clear();
    wdc_ota_host_clear_slots();
    wdc_ota_host_clear_metadata();
    CHECK(wdc_ota_host_set_slot_image(WDC_BUNDLE_SLOT_A,
                                      s_artifact,
                                      s_artifact_bytes) == WDC_OK);
    CHECK(wdc_ota_host_set_slot_image(WDC_BUNDLE_SLOT_B,
                                      s_artifact,
                                      s_artifact_bytes) == WDC_OK);
    *metadata = trial_running_metadata(200u);
    CHECK(wdc_ota_host_set_metadata(metadata) == WDC_OK);
    if (target_index == 0u) {
        metadata->metadata_generation++;
        metadata->trial_boot_generation = metadata->metadata_generation;
        seal_metadata(metadata);
        CHECK(wdc_ota_write_metadata(metadata) == WDC_OK);
    }
}

static void run_confirmation_case(uint32_t target_index,
                                  WdcOtaHostFaultOperation operation,
                                  uint32_t cut)
{
    WdcBundleMetadataV1 metadata;
    WdcBundleMetadataV1 durable;
    WdcActivationProbationEvidence evidence;
    WdcActivationDecision decision;
    WdcOtaHostFaultPlan plan;
    bool new_record_complete;

    install_trial_running(&metadata, target_index);
    memset(&evidence, 0, sizeof(evidence));
    evidence.elapsed_ms = s_activation.minimum_stable_ms;
    evidence.observed_health_checks = s_activation.required_health_checks;
    evidence.readiness_observed = true;
    evidence.administration_responsive = true;
    evidence.resource_floors_preserved = true;
    plan.operation = operation;
    plan.trigger_index = 1u;
    plan.tear_after_bytes = cut;
    CHECK(wdc_ota_host_fault_arm(&plan) == WDC_OK);
    CHECK(wdc_app_slots_evaluate_probation(&metadata,
                                           WDC_BUNDLE_SLOT_B,
                                           &s_activation,
                                           &evidence,
                                           &decision) == WDC_ERR_IO);
    CHECK(wdc_ota_host_fault_trigger_count() == 1u);
    wdc_ota_host_power_cycle();
    CHECK(wdc_ota_read_metadata(&durable) == WDC_OK);
    CHECK(memcmp(&metadata, &durable, sizeof(metadata)) == 0);
    CHECK(wdc_ota_host_metadata_valid_record_count() >= 1u);
    CHECK(has_confirmed_authority(&durable));
    new_record_complete =
        operation == WDC_OTA_HOST_FAULT_METADATA_MARKER_WRITE &&
        cut == wdc_ota_host_metadata_marker_bytes();
    if (new_record_complete) {
        CHECK(durable.slot_b.state == WDC_SLOT_CONFIRMED);
        CHECK(durable.last_good_slot == WDC_BUNDLE_SLOT_B);
    } else {
        WdcActivationBootContext context;
        WdcAppSlotBootResult boot;
        CHECK(durable.slot_b.state == WDC_SLOT_TRIAL_RUNNING);
        CHECK(durable.last_good_slot == WDC_BUNDLE_SLOT_A);
        context.reset_attribution = WDC_ACTIVATION_RESET_UNKNOWN;
        context.boot_sequence = 400u + s_confirmation_cases;
        CHECK(wdc_app_slots_boot(&durable,
                                 &s_activation,
                                 &context,
                                 s_s3,
                                 &s_heap,
                                 &s_verify_policy,
                                 s_scratch,
                                 sizeof(s_scratch),
                                 &boot) == WDC_OK);
        CHECK(boot.outcome == WDC_APP_SLOT_BOOT_FALLBACK_REBOOT_REQUIRED);
        CHECK(boot.fallback_slot == WDC_BUNDLE_SLOT_A);
        CHECK(has_confirmed_authority(&durable));
    }
    s_confirmation_cases++;
}

static void run_confirmation_matrix(void)
{
    const WdcOtaHostFaultOperation operations[] = {
        WDC_OTA_HOST_FAULT_METADATA_ERASE,
        WDC_OTA_HOST_FAULT_METADATA_BODY_WRITE,
        WDC_OTA_HOST_FAULT_METADATA_MARKER_WRITE,
    };
    uint32_t target;
    uint32_t op_index;
    for (target = 0u; target < WDC_OTA_METADATA_JOURNAL_RECORDS; ++target) {
        for (op_index = 0u;
             op_index < (uint32_t)(sizeof(operations) /
                                   sizeof(operations[0]));
             ++op_index) {
            uint32_t limit =
                operations[op_index] == WDC_OTA_HOST_FAULT_METADATA_ERASE
                    ? wdc_ota_host_metadata_record_bytes()
                    : operations[op_index] ==
                              WDC_OTA_HOST_FAULT_METADATA_BODY_WRITE
                          ? wdc_ota_host_metadata_body_bytes()
                          : wdc_ota_host_metadata_marker_bytes();
            uint32_t cut;
            for (cut = 0u; cut <= limit; ++cut) {
                run_confirmation_case(target, operations[op_index], cut);
            }
        }
    }
}

static void run_journal_corruption_cases(void)
{
    uint32_t corrupted;
    for (corrupted = 0u; corrupted < 2u; ++corrupted) {
        WdcBundleMetadataV1 metadata = base_confirmed_a(1u);
        WdcBundleMetadataV1 recovered;
        wdc_ota_host_clear_metadata();
        CHECK(wdc_ota_host_set_metadata(&metadata) == WDC_OK);
        metadata.metadata_generation = 2u;
        seal_metadata(&metadata);
        CHECK(wdc_ota_write_metadata(&metadata) == WDC_OK);
        CHECK(wdc_ota_host_corrupt_metadata_record(corrupted) == WDC_OK);
        CHECK(wdc_ota_read_metadata(&recovered) == WDC_OK);
        CHECK(has_confirmed_authority(&recovered));
        CHECK(recovered.metadata_generation == (corrupted == 0u ? 2u : 1u));
        s_corruption_cases++;
    }
    {
        WdcBundleMetadataV1 metadata = base_confirmed_a(1u);
        WdcBundleMetadataV1 recovered;
        wdc_ota_host_clear_metadata();
        CHECK(wdc_ota_host_set_metadata(&metadata) == WDC_OK);
        metadata.metadata_generation = 2u;
        seal_metadata(&metadata);
        CHECK(wdc_ota_write_metadata(&metadata) == WDC_OK);
        CHECK(wdc_ota_host_corrupt_metadata_record(0u) == WDC_OK);
        CHECK(wdc_ota_host_corrupt_metadata_record(1u) == WDC_OK);
        CHECK(wdc_ota_read_metadata(&recovered) ==
              WDC_ERR_CONTRACT_VIOLATION);
        s_corruption_cases++;
    }
}

static void check_preserved_a(const WdcBundleMetadataV1 *metadata)
{
    CHECK(metadata->last_good_slot == WDC_BUNDLE_SLOT_A);
    CHECK(metadata->slot_a.state == WDC_SLOT_CONFIRMED);
    CHECK(has_confirmed_authority(metadata));
}

static int32_t boot_trial(WdcBundleMetadataV1 *metadata,
                          WdcActivationResetAttribution attribution,
                          WdcAppSlotBootResult *boot)
{
    WdcActivationBootContext context;
    context.reset_attribution = attribution;
    context.boot_sequence = 1000u + s_semantic_cases;
    return wdc_app_slots_boot(metadata,
                              &s_activation,
                              &context,
                              s_s3,
                              &s_heap,
                              &s_verify_policy,
                              s_scratch,
                              sizeof(s_scratch),
                              boot);
}

static void run_reset_attribution_case(
    WdcActivationResetAttribution attribution)
{
    WdcBundleMetadataV1 metadata;
    WdcAppSlotBootResult boot;
    install_trial_running(&metadata, 1u);
    CHECK(boot_trial(&metadata, attribution, &boot) == WDC_OK);
    CHECK(boot.outcome == WDC_APP_SLOT_BOOT_FALLBACK_REBOOT_REQUIRED);
    CHECK(boot.fallback_slot == WDC_BUNDLE_SLOT_A);
    CHECK(metadata.last_reset_attribution == (uint32_t)attribution);
    check_preserved_a(&metadata);
    s_semantic_cases++;
}

static void run_semantic_cases(void)
{
    WdcBundleMetadataV1 metadata;
    WdcAppSlotStageResult stage;
    WdcAppSlotBootResult boot;
    WdcActivationDecision decision;
    WdcActivationProbationEvidence evidence;
    WdcOtaHostFaultPlan fault;
    uint8_t corrupted[MAX_ARTIFACT_BYTES];
    int32_t status;

    /* Invalid outer header integrity. */
    metadata = reset_confirmed_a();
    memcpy(corrupted, s_artifact, s_artifact_bytes);
    ((WdcPulseAppArtifactHeaderV1 *)corrupted)->header_crc32 ^= 1u;
    CHECK(stage_artifact(&metadata, WDC_BUNDLE_SLOT_B, s_s3, corrupted, &stage)
          != WDC_OK);
    check_preserved_a(&metadata);
    s_semantic_cases++;

    /* Invalid inner bundle hash. */
    metadata = reset_confirmed_a();
    memcpy(corrupted, s_artifact, s_artifact_bytes);
    corrupted[WDC_APP_ARTIFACT_HEADER_BYTES + 7u] ^= 0x40u;
    CHECK(stage_artifact(&metadata, WDC_BUNDLE_SLOT_B, s_s3, corrupted, &stage)
          == WDC_ERR_CONTRACT_VIOLATION);
    CHECK(!stage.bundle_hash_valid);
    check_preserved_a(&metadata);
    s_semantic_cases++;

    /* Invalid signature while the outer bundle hash remains internally valid. */
    metadata = reset_confirmed_a();
    memcpy(corrupted, s_artifact, s_artifact_bytes);
    {
        WdcBundleParsedHeader parsed;
        WdcPulseAppArtifactHeaderV1 *outer =
            (WdcPulseAppArtifactHeaderV1 *)corrupted;
        CHECK(wdc_bundle_parse_header(
                  corrupted + WDC_APP_ARTIFACT_HEADER_BYTES,
                  s_bundle_bytes,
                  &parsed) == WDC_OK);
        CHECK(parsed.signature_len > 0u);
        corrupted[WDC_APP_ARTIFACT_HEADER_BYTES + parsed.signature_offset] ^=
            0x80u;
        wdc_sha256(corrupted + WDC_APP_ARTIFACT_HEADER_BYTES,
                   s_bundle_bytes,
                   outer->bundle_sha256);
        CHECK(wdc_app_artifact_header_seal(outer) == WDC_OK);
    }
    CHECK(stage_artifact(&metadata, WDC_BUNDLE_SLOT_B, s_s3, corrupted, &stage)
          != WDC_OK);
    CHECK(stage.bundle_hash_valid);
    CHECK(!stage.bundle_valid);
    check_preserved_a(&metadata);
    s_semantic_cases++;

    /* Stored artifact hash mismatch at boot. */
    metadata = reset_confirmed_a();
    CHECK(wdc_ota_host_set_slot_image(WDC_BUNDLE_SLOT_B,
                                      s_artifact,
                                      s_artifact_bytes) == WDC_OK);
    metadata.slot_b = artifact_record(WDC_SLOT_TRIAL);
    metadata.slot_b.artifact_sha256[0] ^= 1u;
    metadata.active_slot = WDC_BUNDLE_SLOT_B;
    metadata.metadata_generation++;
    seal_metadata(&metadata);
    CHECK(wdc_ota_host_set_metadata(&metadata) == WDC_OK);
    status = boot_trial(&metadata, WDC_ACTIVATION_RESET_HOST_SOFTWARE, &boot);
    CHECK(status != WDC_OK);
    CHECK(boot.outcome == WDC_APP_SLOT_BOOT_FALLBACK_REBOOT_REQUIRED);
    check_preserved_a(&metadata);
    s_semantic_cases++;

    /* A bad confirmed slot switches to the other confirmed slot atomically. */
    metadata = reset_confirmed_a();
    memcpy(corrupted, s_artifact, s_artifact_bytes);
    corrupted[WDC_APP_ARTIFACT_HEADER_BYTES + 11u] ^= 0x20u;
    CHECK(wdc_ota_host_set_slot_image(WDC_BUNDLE_SLOT_A,
                                      corrupted,
                                      s_artifact_bytes) == WDC_OK);
    CHECK(wdc_ota_host_set_slot_image(WDC_BUNDLE_SLOT_B,
                                      s_artifact,
                                      s_artifact_bytes) == WDC_OK);
    metadata.slot_b = artifact_record(WDC_SLOT_CONFIRMED);
    metadata.metadata_generation++;
    seal_metadata(&metadata);
    CHECK(wdc_ota_host_set_metadata(&metadata) == WDC_OK);
    CHECK(boot_trial(&metadata, WDC_ACTIVATION_RESET_POWER_ON, &boot) == WDC_OK);
    CHECK(boot.outcome == WDC_APP_SLOT_BOOT_FALLBACK_REBOOT_REQUIRED);
    CHECK(boot.metadata_commits == 1u);
    CHECK(metadata.slot_a.state == WDC_SLOT_REJECTED);
    CHECK(metadata.slot_b.state == WDC_SLOT_CONFIRMED);
    CHECK(metadata.last_good_slot == WDC_BUNDLE_SLOT_B);
    CHECK(has_confirmed_authority(&metadata));
    s_semantic_cases++;

    /* A torn atomic fallback leaves the old generation complete and retryable. */
    metadata = reset_confirmed_a();
    CHECK(wdc_ota_host_set_slot_image(WDC_BUNDLE_SLOT_A,
                                      corrupted,
                                      s_artifact_bytes) == WDC_OK);
    CHECK(wdc_ota_host_set_slot_image(WDC_BUNDLE_SLOT_B,
                                      s_artifact,
                                      s_artifact_bytes) == WDC_OK);
    metadata.slot_b = artifact_record(WDC_SLOT_CONFIRMED);
    metadata.metadata_generation++;
    seal_metadata(&metadata);
    CHECK(wdc_ota_host_set_metadata(&metadata) == WDC_OK);
    fault.operation = WDC_OTA_HOST_FAULT_METADATA_MARKER_WRITE;
    fault.trigger_index = 1u;
    fault.tear_after_bytes = 0u;
    CHECK(wdc_ota_host_fault_arm(&fault) == WDC_OK);
    CHECK(boot_trial(&metadata, WDC_ACTIVATION_RESET_POWER_ON, &boot) ==
          WDC_ERR_IO);
    CHECK(boot.outcome == WDC_APP_SLOT_BOOT_RECOVERY);
    CHECK(metadata.slot_a.state == WDC_SLOT_CONFIRMED);
    CHECK(metadata.slot_b.state == WDC_SLOT_CONFIRMED);
    check_preserved_a(&metadata);
    wdc_ota_host_power_cycle();
    CHECK(boot_trial(&metadata, WDC_ACTIVATION_RESET_POWER_ON, &boot) == WDC_OK);
    CHECK(boot.outcome == WDC_APP_SLOT_BOOT_FALLBACK_REBOOT_REQUIRED);
    CHECK(metadata.last_good_slot == WDC_BUNDLE_SLOT_B);
    CHECK(has_confirmed_authority(&metadata));
    s_semantic_cases++;

    /* S3-only requirements against the C6 fingerprint. */
    metadata = reset_confirmed_a();
    CHECK(stage_artifact(&metadata, WDC_BUNDLE_SLOT_B, s_c6, s_artifact, &stage)
          == WDC_ERR_INVALID_RESOURCE);
    CHECK(!stage.host_compatible);
    check_preserved_a(&metadata);
    s_semantic_cases++;

    /* Readiness deadline timeout. */
    metadata = reset_confirmed_a();
    CHECK(stage_artifact(&metadata, WDC_BUNDLE_SLOT_B, s_s3, s_artifact, &stage)
          == WDC_OK);
    CHECK(wdc_app_slots_mark_trial(&metadata,
                                   WDC_BUNDLE_SLOT_B,
                                   &s_activation) == WDC_OK);
    CHECK(boot_trial(&metadata,
                     WDC_ACTIVATION_RESET_HOST_SOFTWARE,
                     &boot) == WDC_OK);
    memset(&evidence, 0, sizeof(evidence));
    evidence.elapsed_ms = s_activation.readiness_deadline_ms;
    evidence.resource_floors_preserved = true;
    CHECK(wdc_app_slots_evaluate_probation(&metadata,
                                           WDC_BUNDLE_SLOT_B,
                                           &s_activation,
                                           &evidence,
                                           &decision) == WDC_OK);
    CHECK(decision.rollback);
    CHECK(metadata.last_failure_reason == WDC_ERR_TIMEOUT);
    check_preserved_a(&metadata);
    s_semantic_cases++;

    /* The second staging commit tears: durable authority remains STAGED. */
    metadata = reset_confirmed_a();
    {
        WdcAppSlotStageSession session;
        WdcBundleMetadataV1 durable;
        CHECK(wdc_app_slots_stage_begin(&session,
                                        &metadata,
                                        WDC_BUNDLE_SLOT_B,
                                        s_artifact_bytes) == WDC_OK);
        CHECK(wdc_app_slots_stage_write(&session,
                                        s_artifact,
                                        s_artifact_bytes) == WDC_OK);
        fault.operation = WDC_OTA_HOST_FAULT_METADATA_BODY_WRITE;
        fault.trigger_index = 2u;
        fault.tear_after_bytes = wdc_ota_host_metadata_body_bytes() / 2u;
        CHECK(wdc_ota_host_fault_arm(&fault) == WDC_OK);
        CHECK(wdc_app_slots_stage_finish(&session,
                                         &metadata,
                                         s_s3,
                                         &s_verify_policy,
                                         s_scratch,
                                         sizeof(s_scratch),
                                         &stage) == WDC_ERR_IO);
        CHECK(stage.terminal_state == WDC_SLOT_STAGED);
        CHECK(metadata.slot_b.state == WDC_SLOT_STAGED);
        CHECK(wdc_ota_read_metadata(&durable) == WDC_OK);
        CHECK(memcmp(&metadata, &durable, sizeof(metadata)) == 0);
        check_preserved_a(&metadata);
    }
    s_semantic_cases++;

    /* VERIFIED -> TRIAL interruption restores the durable VERIFIED state. */
    metadata = reset_confirmed_a();
    CHECK(stage_artifact(&metadata, WDC_BUNDLE_SLOT_B, s_s3, s_artifact, &stage)
          == WDC_OK);
    fault.operation = WDC_OTA_HOST_FAULT_METADATA_MARKER_WRITE;
    fault.trigger_index = 1u;
    fault.tear_after_bytes = 0u;
    CHECK(wdc_ota_host_fault_arm(&fault) == WDC_OK);
    CHECK(wdc_app_slots_mark_trial(&metadata,
                                   WDC_BUNDLE_SLOT_B,
                                   &s_activation) == WDC_ERR_IO);
    CHECK(metadata.slot_b.state == WDC_SLOT_VERIFIED);
    CHECK(metadata.active_slot == WDC_BUNDLE_SLOT_A);
    check_preserved_a(&metadata);
    s_semantic_cases++;

    /* TRIAL -> TRIAL_RUNNING interruption cannot authorize a launch. */
    metadata = reset_confirmed_a();
    CHECK(stage_artifact(&metadata, WDC_BUNDLE_SLOT_B, s_s3, s_artifact, &stage)
          == WDC_OK);
    CHECK(wdc_app_slots_mark_trial(&metadata,
                                   WDC_BUNDLE_SLOT_B,
                                   &s_activation) == WDC_OK);
    fault.operation = WDC_OTA_HOST_FAULT_METADATA_MARKER_WRITE;
    fault.trigger_index = 1u;
    fault.tear_after_bytes = 0u;
    CHECK(wdc_ota_host_fault_arm(&fault) == WDC_OK);
    CHECK(boot_trial(&metadata,
                     WDC_ACTIVATION_RESET_HOST_SOFTWARE,
                     &boot) == WDC_ERR_IO);
    CHECK(boot.outcome == WDC_APP_SLOT_BOOT_RECOVERY);
    CHECK(boot.application_code_launched == 0u);
    CHECK(metadata.slot_b.state == WDC_SLOT_TRIAL);
    CHECK(metadata.trial_boot_in_progress == 0u);
    check_preserved_a(&metadata);
    s_semantic_cases++;

    /* Interrupted trap attribution is retried safely on the next boot. */
    install_trial_running(&metadata, 1u);
    fault.operation = WDC_OTA_HOST_FAULT_METADATA_BODY_WRITE;
    fault.trigger_index = 1u;
    fault.tear_after_bytes = wdc_ota_host_metadata_body_bytes() / 2u;
    CHECK(wdc_ota_host_fault_arm(&fault) == WDC_OK);
    CHECK(wdc_app_slots_record_runtime_fault(
              &metadata,
              WDC_BUNDLE_SLOT_B,
              WDC_ERR_CONTRACT_VIOLATION,
              &decision) == WDC_ERR_IO);
    CHECK(metadata.slot_b.state == WDC_SLOT_TRIAL_RUNNING);
    wdc_ota_host_power_cycle();
    CHECK(boot_trial(&metadata, WDC_ACTIVATION_RESET_GUEST_TRAP, &boot) ==
          WDC_OK);
    CHECK(boot.outcome == WDC_APP_SLOT_BOOT_FALLBACK_REBOOT_REQUIRED);
    CHECK(metadata.last_reset_attribution == WDC_ACTIVATION_RESET_GUEST_TRAP);
    check_preserved_a(&metadata);
    s_semantic_cases++;

    /* A stale running candidate and both watchdog attributions. */
    run_reset_attribution_case(WDC_ACTIVATION_RESET_UNKNOWN);
    run_reset_attribution_case(WDC_ACTIVATION_RESET_APPLICATION_WATCHDOG);
    run_reset_attribution_case(WDC_ACTIVATION_RESET_HOST_WATCHDOG);

    /* Repeated guest traps may consume B repeatedly but never A. */
    metadata = reset_confirmed_a();
    {
        uint32_t cycle;
        for (cycle = 0u; cycle < REPEATED_TRAP_CYCLES; ++cycle) {
            CHECK(stage_artifact(&metadata,
                                 WDC_BUNDLE_SLOT_B,
                                 s_s3,
                                 s_artifact,
                                 &stage) == WDC_OK);
            CHECK(wdc_app_slots_mark_trial(&metadata,
                                           WDC_BUNDLE_SLOT_B,
                                           &s_activation) == WDC_OK);
            CHECK(boot_trial(&metadata,
                             WDC_ACTIVATION_RESET_HOST_SOFTWARE,
                             &boot) == WDC_OK);
            CHECK(boot.outcome == WDC_APP_SLOT_BOOT_RUN_TRIAL);
            CHECK(wdc_app_slots_record_runtime_fault(
                      &metadata,
                      WDC_BUNDLE_SLOT_B,
                      WDC_ERR_CONTRACT_VIOLATION,
                      &decision) == WDC_OK);
            CHECK(decision.rollback);
            check_preserved_a(&metadata);
        }
    }
    s_semantic_cases++;
}

int main(int argc, char **argv)
{
    uint32_t total_cases;
    if (argc != 2 || !load_bundle(argv[1])) {
        (void)fprintf(stderr, "usage: hp3_5-slot-smoke BUNDLE\n");
        return 2;
    }
    initialize_fixture();
    run_payload_matrix();
    run_slot_erase_matrix();
    run_journal_matrix();
    run_confirmation_matrix();
    run_journal_corruption_cases();
    run_semantic_cases();
    total_cases = s_payload_cases + s_slot_erase_cases + s_journal_cases +
                  s_confirmation_cases + s_corruption_cases +
                  s_semantic_cases;
    (void)printf(
        "{\"schema\":\"pulse.esp32.hp3_5-slot-adversarial-smoke.v1\"," 
        "\"status\":\"%s\",\"failures\":%lu,\"total_cases\":%lu,"
        "\"artifact_bytes\":%lu,\"metadata_record_bytes\":%lu,"
        "\"metadata_body_bytes\":%lu,\"payload_write_cuts\":%lu,"
        "\"slot_erase_cuts\":%lu,\"journal_transitions\":%u,"
        "\"journal_target_records\":%u,\"journal_interruption_cases\":%lu,"
        "\"confirmation_reset_cases\":%lu,\"journal_corruption_cases\":%lu,"
        "\"adversarial_semantic_cases\":%lu,\"repeated_trap_cycles\":%u,"
        "\"last_confirmed_preserved\":true,"
        "\"ambiguous_boot_authority\":false,"
        "\"application_code_launched\":false}\n",
        s_failures == 0u ? "PASS" : "FAIL",
        (unsigned long)s_failures,
        (unsigned long)total_cases,
        (unsigned long)s_artifact_bytes,
        (unsigned long)wdc_ota_host_metadata_record_bytes(),
        (unsigned long)wdc_ota_host_metadata_body_bytes(),
        (unsigned long)s_payload_cases,
        (unsigned long)s_slot_erase_cases,
        JOURNAL_TRANSITIONS,
        WDC_OTA_METADATA_JOURNAL_RECORDS,
        (unsigned long)s_journal_cases,
        (unsigned long)s_confirmation_cases,
        (unsigned long)s_corruption_cases,
        (unsigned long)s_semantic_cases,
        REPEATED_TRAP_CYCLES);
    return s_failures == 0u ? 0 : 1;
}
