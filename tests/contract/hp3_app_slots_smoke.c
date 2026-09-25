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

static uint8_t s_bundle[MAX_BUNDLE_BYTES];
static uint8_t s_artifact[MAX_ARTIFACT_BYTES];
static uint8_t s_scratch[MAX_BUNDLE_BYTES];
static uint32_t s_bundle_bytes;
static uint32_t s_artifact_bytes;
static uint32_t s_cases;
static uint32_t s_failures;

#define CHECK(expression)                                                       \
    do {                                                                        \
        if (!(expression)) {                                                    \
            s_failures++;                                                       \
            (void)fprintf(stderr, "CHECK failed at %s:%d: %s\n",             \
                          __FILE__, __LINE__, #expression);                      \
        }                                                                       \
    } while (0)

static void case_done(void)
{
    s_cases++;
}

static int load_bundle(const char *path)
{
    FILE *handle = fopen(path, "rb");
    long size;
    if (handle == NULL) {
        return 0;
    }
    if (fseek(handle, 0L, SEEK_END) != 0) {
        (void)fclose(handle);
        return 0;
    }
    size = ftell(handle);
    if (size <= 0L || (unsigned long)size > sizeof(s_bundle) ||
        fseek(handle, 0L, SEEK_SET) != 0) {
        (void)fclose(handle);
        return 0;
    }
    if (fread(s_bundle, 1u, (size_t)size, handle) != (size_t)size) {
        (void)fclose(handle);
        return 0;
    }
    (void)fclose(handle);
    s_bundle_bytes = (uint32_t)size;
    return 1;
}

static WdcPulseAppArtifactHeaderV1 make_header(uint32_t allowed_targets)
{
    WdcPulseAppArtifactHeaderV1 header;
    static const char app_id[] = "com.example.relay-controller";
    memset(&header, 0, sizeof(header));
    header.magic = WDC_APP_ARTIFACT_MAGIC;
    header.version = WDC_APP_ARTIFACT_VERSION;
    header.header_bytes = WDC_APP_ARTIFACT_HEADER_BYTES;
    header.total_bytes = WDC_APP_ARTIFACT_HEADER_BYTES + s_bundle_bytes;
    header.bundle_bytes = s_bundle_bytes;
    header.application_version = 8u;
    header.security_counter = 8u;
    header.requirements.allowed_target_mask = allowed_targets;
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
    return header;
}

static void build_artifact(uint32_t allowed_targets)
{
    WdcPulseAppArtifactHeaderV1 header = make_header(allowed_targets);
    memcpy(s_artifact, &header, sizeof(header));
    memcpy(s_artifact + sizeof(header), s_bundle, s_bundle_bytes);
    s_artifact_bytes = (uint32_t)sizeof(header) + s_bundle_bytes;
}

static WdcAppSlotVerifyPolicy make_policy(WdcBundleVerifyPolicy *bundle_policy)
{
    WdcAppSlotVerifyPolicy policy;
    memset(&policy, 0, sizeof(policy));
    *bundle_policy = wdc_bundle_make_default_dev_policy(wdc_profile_builtin());
    policy.bundle_policy = bundle_policy;
    return policy;
}

static int32_t stage_artifact(WdcBundleMetadataV1 *metadata,
                              WdcBundleSlotId slot,
                              const WdcHostFingerprintV1 *fingerprint,
                              const WdcAppSlotVerifyPolicy *policy,
                              const uint8_t *artifact,
                              uint32_t artifact_bytes,
                              WdcAppSlotStageResult *result)
{
    WdcAppSlotStageSession session;
    uint32_t offset = 0u;
    int32_t status = wdc_app_slots_stage_begin(&session,
                                               metadata,
                                               slot,
                                               artifact_bytes);
    if (status != WDC_OK) {
        return status;
    }
    while (offset < artifact_bytes) {
        uint32_t remaining = artifact_bytes - offset;
        uint32_t chunk = remaining < 73u ? remaining : 73u;
        status = wdc_app_slots_stage_write(&session,
                                           artifact + offset,
                                           chunk);
        if (status != WDC_OK) {
            return status;
        }
        offset += chunk;
    }
    return wdc_app_slots_stage_finish(&session,
                                      metadata,
                                      fingerprint,
                                      policy,
                                      s_scratch,
                                      sizeof(s_scratch),
                                      result);
}

static WdcControlHeapSnapshot accepted_heap(void)
{
    WdcControlHeapSnapshot heap;
    heap.internal_free_bytes = 327680u;
    heap.internal_largest_block_bytes = 131072u;
    heap.psram_free_bytes = 1048576u;
    return heap;
}

int main(int argc, char **argv)
{
    WdcBundleVerifyPolicy bundle_policy;
    WdcAppSlotVerifyPolicy policy;
    WdcHostFingerprintV1 s3_storage;
    WdcHostFingerprintV1 c6_storage;
    const WdcHostFingerprintV1 *s3;
    const WdcHostFingerprintV1 *c6;
    WdcBundleMetadataV1 metadata;
    WdcAppSlotStageResult stage;
    WdcActivationPolicy activation = wdc_activation_default_policy();
    WdcActivationBootContext boot_context;
    WdcAppSlotBootResult boot;
    WdcControlHeapSnapshot heap = accepted_heap();
    WdcActivationDecision probation_decision;
    WdcActivationProbationEvidence evidence;
    uint8_t corrupted[MAX_ARTIFACT_BYTES];
    int32_t status;

    if (argc != 2 || !load_bundle(argv[1])) {
        (void)fprintf(stderr, "usage: hp3-smoke BUNDLE\n");
        return 2;
    }
    build_artifact(WDC_HOST_TARGET_MASK_ESP32S3);
    policy = make_policy(&bundle_policy);
    s3 = wdc_host_fingerprint_for_target(WDC_HOST_TARGET_ESP32S3);
    c6 = wdc_host_fingerprint_for_target(WDC_HOST_TARGET_ESP32C6);
    CHECK(s3 != NULL);
    CHECK(c6 != NULL);
    s3_storage = *s3;
    c6_storage = *c6;
    s3_storage.capability_mask |= WDC_HOST_CAP_APPLICATION_SLOTS;
    c6_storage.capability_mask |= WDC_HOST_CAP_APPLICATION_SLOTS;
    s3_storage.crc32 = wdc_host_fingerprint_crc32(&s3_storage);
    c6_storage.crc32 = wdc_host_fingerprint_crc32(&c6_storage);
    s3 = &s3_storage;
    c6 = &c6_storage;

    /* 1: fixed, self-checking artifact header. */
    CHECK(sizeof(WdcPulseAppArtifactHeaderV1) == 192u);
    CHECK(wdc_app_artifact_header_validate(
              (const WdcPulseAppArtifactHeaderV1 *)s_artifact) == WDC_OK);
    case_done();

    wdc_ota_host_clear_slots();
    wdc_ota_host_clear_metadata();
    wdc_bundle_metadata_init(&metadata);

    /* 2: an empty host stages and verifies A with two journal commits. */
    status = stage_artifact(&metadata,
                            WDC_BUNDLE_SLOT_A,
                            s3,
                            &policy,
                            s_artifact,
                            s_artifact_bytes,
                            &stage);
    CHECK(status == WDC_OK);
    CHECK(stage.terminal_state == WDC_SLOT_VERIFIED);
    CHECK(stage.metadata_commits == 2u);
    CHECK(stage.application_code_launched == 0u);
    case_done();

    /* 3: explicit trial transition and boot attribution are persisted first. */
    CHECK(wdc_app_slots_mark_trial(&metadata,
                                   WDC_BUNDLE_SLOT_A,
                                   &activation) == WDC_OK);
    boot_context.reset_attribution = WDC_ACTIVATION_RESET_POWER_ON;
    boot_context.boot_sequence = 1u;
    status = wdc_app_slots_boot(&metadata,
                                &activation,
                                &boot_context,
                                s3,
                                &heap,
                                &policy,
                                s_scratch,
                                sizeof(s_scratch),
                                &boot);
    CHECK(status == WDC_OK);
    CHECK(boot.outcome == WDC_APP_SLOT_BOOT_RUN_TRIAL);
    CHECK(boot.application_code_launched == 0u);
    CHECK(metadata.slot_a.state == WDC_SLOT_TRIAL_RUNNING);
    CHECK(metadata.trial_boot_in_progress == 1u);
    case_done();

    /* 4: readiness alone cannot self-confirm before stable probation. */
    memset(&evidence, 0, sizeof(evidence));
    evidence.readiness_observed = true;
    evidence.administration_responsive = true;
    evidence.resource_floors_preserved = true;
    evidence.observed_health_checks = 1u;
    evidence.elapsed_ms = activation.minimum_stable_ms - 1u;
    CHECK(wdc_app_slots_evaluate_probation(&metadata,
                                           WDC_BUNDLE_SLOT_A,
                                           &activation,
                                           &evidence,
                                           &probation_decision) == WDC_ERR_BUSY);
    CHECK(metadata.slot_a.state == WDC_SLOT_TRIAL_RUNNING);
    case_done();

    /* 5: host-owned evidence confirms A and clears boot-in-progress. */
    evidence.elapsed_ms = activation.minimum_stable_ms;
    CHECK(wdc_app_slots_evaluate_probation(&metadata,
                                           WDC_BUNDLE_SLOT_A,
                                           &activation,
                                           &evidence,
                                           &probation_decision) == WDC_OK);
    CHECK(metadata.slot_a.state == WDC_SLOT_CONFIRMED);
    CHECK(metadata.last_good_slot == WDC_BUNDLE_SLOT_A);
    CHECK(metadata.trial_boot_in_progress == 0u);
    case_done();

    /* 6: staging can never target the active/last-confirmed partition. */
    {
        WdcAppSlotStageSession denied;
        CHECK(wdc_app_slots_stage_begin(&denied,
                                        &metadata,
                                        WDC_BUNDLE_SLOT_A,
                                        s_artifact_bytes) == WDC_ERR_INVALID_STATE);
    }
    case_done();

    /* 7: an attributed reset during B trial rejects B and preserves A. */
    CHECK(stage_artifact(&metadata,
                         WDC_BUNDLE_SLOT_B,
                         s3,
                         &policy,
                         s_artifact,
                         s_artifact_bytes,
                         &stage) == WDC_OK);
    CHECK(wdc_app_slots_mark_trial(&metadata,
                                   WDC_BUNDLE_SLOT_B,
                                   &activation) == WDC_OK);
    boot_context.boot_sequence = 2u;
    CHECK(wdc_app_slots_boot(&metadata,
                             &activation,
                             &boot_context,
                             s3,
                             &heap,
                             &policy,
                             s_scratch,
                             sizeof(s_scratch),
                             &boot) == WDC_OK);
    boot_context.reset_attribution = WDC_ACTIVATION_RESET_APPLICATION_WATCHDOG;
    boot_context.boot_sequence = 3u;
    CHECK(wdc_app_slots_boot(&metadata,
                             &activation,
                             &boot_context,
                             s3,
                             &heap,
                             &policy,
                             s_scratch,
                             sizeof(s_scratch),
                             &boot) == WDC_OK);
    CHECK(boot.outcome == WDC_APP_SLOT_BOOT_FALLBACK_REBOOT_REQUIRED);
    CHECK(boot.fallback_slot == WDC_BUNDLE_SLOT_A);
    CHECK(metadata.slot_b.state == WDC_SLOT_REJECTED);
    CHECK(metadata.slot_a.state == WDC_SLOT_CONFIRMED);
    CHECK(metadata.last_reset_attribution ==
          WDC_ACTIVATION_RESET_APPLICATION_WATCHDOG);
    case_done();

    /* 8: B can later pass a complete probation and become last-good. */
    CHECK(stage_artifact(&metadata,
                         WDC_BUNDLE_SLOT_B,
                         s3,
                         &policy,
                         s_artifact,
                         s_artifact_bytes,
                         &stage) == WDC_OK);
    CHECK(wdc_app_slots_mark_trial(&metadata,
                                   WDC_BUNDLE_SLOT_B,
                                   &activation) == WDC_OK);
    boot_context.reset_attribution = WDC_ACTIVATION_RESET_HOST_SOFTWARE;
    boot_context.boot_sequence = 4u;
    CHECK(wdc_app_slots_boot(&metadata,
                             &activation,
                             &boot_context,
                             s3,
                             &heap,
                             &policy,
                             s_scratch,
                             sizeof(s_scratch),
                             &boot) == WDC_OK);
    CHECK(wdc_app_slots_evaluate_probation(&metadata,
                                           WDC_BUNDLE_SLOT_B,
                                           &activation,
                                           &evidence,
                                           &probation_decision) == WDC_OK);
    CHECK(metadata.last_good_slot == WDC_BUNDLE_SLOT_B);
    CHECK(metadata.slot_a.state == WDC_SLOT_CONFIRMED);
    CHECK(metadata.slot_b.state == WDC_SLOT_CONFIRMED);
    case_done();

    /* 9: corrupt inactive bytes are rejected without destroying B. */
    memcpy(corrupted, s_artifact, s_artifact_bytes);
    corrupted[WDC_APP_ARTIFACT_HEADER_BYTES + 7u] ^= 0x40u;
    CHECK(stage_artifact(&metadata,
                         WDC_BUNDLE_SLOT_A,
                         s3,
                         &policy,
                         corrupted,
                         s_artifact_bytes,
                         &stage) == WDC_ERR_CONTRACT_VIOLATION);
    CHECK(metadata.slot_a.state == WDC_SLOT_REJECTED);
    CHECK(metadata.slot_b.state == WDC_SLOT_CONFIRMED);
    CHECK(metadata.last_good_slot == WDC_BUNDLE_SLOT_B);
    case_done();

    /* 10: the security floor rejects an otherwise valid inactive artifact. */
    policy.security_version_floor = 9u;
    CHECK(stage_artifact(&metadata,
                         WDC_BUNDLE_SLOT_A,
                         s3,
                         &policy,
                         s_artifact,
                         s_artifact_bytes,
                         &stage) != WDC_OK);
    CHECK(!stage.security_floor_valid);
    CHECK(metadata.slot_b.state == WDC_SLOT_CONFIRMED);
    policy.security_version_floor = 0u;
    case_done();

    /* 11: production staging fails closed without artifact authority. */
    policy.production_mode = true;
    CHECK(stage_artifact(&metadata,
                         WDC_BUNDLE_SLOT_A,
                         s3,
                         &policy,
                         s_artifact,
                         s_artifact_bytes,
                         &stage) != WDC_OK);
    CHECK(!stage.authority_valid);
    CHECK(metadata.slot_b.state == WDC_SLOT_CONFIRMED);
    policy.production_mode = false;
    case_done();

    /* 12: S3-only intent is rejected against the C6 running fingerprint. */
    {
        WdcBundleMetadataV1 isolated;
        wdc_ota_host_clear_slots();
        wdc_ota_host_clear_metadata();
        wdc_bundle_metadata_init(&isolated);
        CHECK(stage_artifact(&isolated,
                             WDC_BUNDLE_SLOT_A,
                             c6,
                             &policy,
                             s_artifact,
                             s_artifact_bytes,
                             &stage) == WDC_ERR_INVALID_RESOURCE);
        CHECK(!stage.host_compatible);
        CHECK(stage.application_code_launched == 0u);
    }
    case_done();

    /* 13: no viable slot enters explicit host recovery. */
    wdc_ota_host_clear_slots();
    wdc_ota_host_clear_metadata();
    wdc_bundle_metadata_init(&metadata);
    boot_context.reset_attribution = WDC_ACTIVATION_RESET_POWER_ON;
    boot_context.boot_sequence = 5u;
    CHECK(wdc_app_slots_boot(&metadata,
                             &activation,
                             &boot_context,
                             s3,
                             &heap,
                             &policy,
                             s_scratch,
                             sizeof(s_scratch),
                             &boot) == WDC_ERR_NOT_AVAILABLE);
    CHECK(boot.outcome == WDC_APP_SLOT_BOOT_RECOVERY);
    CHECK(boot.recovery);
    CHECK(boot.application_code_launched == 0u);
    case_done();

    /* 14: one corrupt journal record leaves the other authoritative. */
    wdc_bundle_metadata_init(&metadata);
    metadata.slot_a.state = WDC_SLOT_CONFIRMED;
    metadata.active_slot = WDC_BUNDLE_SLOT_A;
    metadata.last_good_slot = WDC_BUNDLE_SLOT_A;
    metadata.metadata_generation = 1u;
    CHECK(wdc_bundle_metadata_seal(&metadata) == WDC_OK);
    CHECK(wdc_ota_write_metadata(&metadata) == WDC_OK);
    metadata.metadata_generation = 2u;
    CHECK(wdc_bundle_metadata_seal(&metadata) == WDC_OK);
    CHECK(wdc_ota_write_metadata(&metadata) == WDC_OK);
    CHECK(wdc_ota_host_corrupt_metadata_record(1u) == WDC_OK);
    {
        WdcBundleMetadataV1 recovered;
        CHECK(wdc_ota_read_metadata(&recovered) == WDC_OK);
        CHECK(recovered.metadata_generation == 1u);
        CHECK(recovered.last_good_slot == WDC_BUNDLE_SLOT_A);
    }
    case_done();

    (void)printf(
        "{\"schema\":\"pulse.esp32.hp3-app-slots-smoke.v1\","
        "\"status\":\"%s\",\"cases\":%lu,\"failures\":%lu,"
        "\"artifact_header_bytes\":%u,\"portable_slot_bytes\":%u,"
        "\"application_code_launched\":false,"
        "\"last_confirmed_preserved\":true,\"recovery_explicit\":true}\n",
        s_failures == 0u ? "PASS" : "FAIL",
        (unsigned long)s_cases,
        (unsigned long)s_failures,
        WDC_APP_ARTIFACT_HEADER_BYTES,
        WDC_APP_SLOT_PORTABLE_MINIMUM_BYTES);
    return s_failures == 0u ? 0 : 1;
}
