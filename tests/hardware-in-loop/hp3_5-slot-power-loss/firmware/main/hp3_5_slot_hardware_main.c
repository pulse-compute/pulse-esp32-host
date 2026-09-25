#include <inttypes.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "esp_chip_info.h"
#include "esp_flash.h"
#include "esp_heap_caps.h"
#include "esp_mac.h"
#include "esp_partition.h"
#if CONFIG_IDF_TARGET_ESP32S3
#include "esp_psram.h"
#endif
#include "esp_system.h"
#include "esp_task_wdt.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "nvs.h"
#include "nvs_flash.h"

#include "hp3_5_campaign_config.h"
#include "wdc_abi.h"
#include "wdc_activation.h"
#include "wdc_app_slots.h"
#include "wdc_bundle.h"
#include "wdc_host_identity.h"
#include "wdc_ota.h"
#include "wdc_profile.h"

#if !CONFIG_IDF_TARGET_ESP32S3 && !CONFIG_IDF_TARGET_ESP32C6
#error "The HP3.5 hardware campaign supports only ESP32-S3 and ESP32-C6"
#endif

#define HP35_STATE_MAGIC 0x48503335u
#define HP35_STATE_SCHEMA 2u
#define HP35_BASELINE_ARM_DELAY_MS 10000u
#define HP35_MAX_BUNDLE_BYTES 8192u
#define HP35_MAX_ARTIFACT_BYTES \
    (WDC_APP_ARTIFACT_HEADER_BYTES + HP35_MAX_BUNDLE_BYTES)
#define HP35_NVS_NAMESPACE "hp35"
#define HP35_NVS_KEY "campaign"

extern const uint8_t pulse_hp35_bundle[];
extern const uint32_t pulse_hp35_bundle_len;

typedef enum Hp35Phase {
    HP35_PHASE_INITIALIZING = 1,
    HP35_PHASE_AFTER_ZERO_PREFIX_RESET = 2,
    HP35_PHASE_AFTER_SECTOR_RESET = 3,
    HP35_PHASE_AFTER_COMPLETE_RESET = 4,
    HP35_PHASE_AFTER_STALE_TRIAL_RESET = 5,
    HP35_PHASE_AFTER_APPLICATION_WDT = 6,
    HP35_PHASE_AFTER_HOST_WDT = 7,
    HP35_PHASE_AFTER_CONFIRMATION_BODY = 8,
    HP35_PHASE_AFTER_CONFIRMATION_MARKER = 9,
    HP35_PHASE_COMPLETE = 10,
} Hp35Phase;

typedef enum Hp35BaselineStep {
    HP35_BASELINE_NONE = 0,
    HP35_BASELINE_STAGE_ARTIFACT = 1,
    HP35_BASELINE_MARK_TRIAL = 2,
    HP35_BASELINE_SELECT_BOOT = 3,
    HP35_BASELINE_CONFIRM = 4,
    HP35_BASELINE_HASH = 5,
    HP35_BASELINE_VERIFY = 6,
} Hp35BaselineStep;

typedef struct Hp35State {
    uint32_t magic;
    uint32_t schema;
    uint32_t phase;
    uint32_t boot_sequence;
    uint32_t baseline_step;
    uint8_t baseline_slot_a_sha256[WDC_BUNDLE_SHA256_BYTES];
    uint32_t crc32;
} Hp35State;

static uint8_t s_artifact[HP35_MAX_ARTIFACT_BYTES];
static uint8_t s_scratch[HP35_MAX_BUNDLE_BYTES];
static uint32_t s_artifact_bytes;
static char s_uid_sha256_hex[65];
static nvs_handle_t s_nvs;

static const char *baseline_step_name(uint32_t step)
{
    switch ((Hp35BaselineStep)step) {
    case HP35_BASELINE_STAGE_ARTIFACT:
        return "stage-artifact";
    case HP35_BASELINE_MARK_TRIAL:
        return "mark-trial";
    case HP35_BASELINE_SELECT_BOOT:
        return "select-boot";
    case HP35_BASELINE_CONFIRM:
        return "confirm";
    case HP35_BASELINE_HASH:
        return "hash";
    case HP35_BASELINE_VERIFY:
        return "verify";
    case HP35_BASELINE_NONE:
    default:
        return "none";
    }
}

static uint32_t crc32_update(uint32_t crc, const uint8_t *data, uint32_t len)
{
    uint32_t index;
    crc = ~crc;
    for (index = 0u; index < len; ++index) {
        uint32_t bit;
        crc ^= data[index];
        for (bit = 0u; bit < 8u; ++bit) {
            uint32_t mask = 0u - (crc & 1u);
            crc = (crc >> 1u) ^ (0xedb88320u & mask);
        }
    }
    return ~crc;
}

static uint32_t state_crc32(const Hp35State *state)
{
    Hp35State copy;
    memcpy(&copy, state, sizeof(copy));
    copy.crc32 = 0u;
    return crc32_update(0u, (const uint8_t *)&copy, (uint32_t)sizeof(copy));
}

static void hex32(const uint8_t bytes[32], char out[65])
{
    static const char digits[] = "0123456789abcdef";
    uint32_t index;
    for (index = 0u; index < 32u; ++index) {
        out[index * 2u] = digits[bytes[index] >> 4u];
        out[index * 2u + 1u] = digits[bytes[index] & 0x0fu];
    }
    out[64] = '\0';
}

static void stop_forever(void)
{
    for (;;) {
        vTaskDelay(pdMS_TO_TICKS(1000u));
    }
}

static void fatal(const char *message, int32_t status)
{
    (void)printf(
        "PULSE_HP35_FATAL {\"schema\":\"pulse.esp32.hp3_5-slot-fatal.v1\","
        "\"status\":\"FAIL\",\"message\":\"%s\",\"error\":%" PRId32 "}\n",
        message,
        status);
    (void)fflush(stdout);
    stop_forever();
}

static void require_status(int32_t status, const char *message)
{
    if (status != WDC_OK) {
        fatal(message, status);
    }
}

static void require_true(bool condition, const char *message)
{
    if (!condition) {
        fatal(message, WDC_ERR_CONTRACT_VIOLATION);
    }
}

static void checkpoint(const char *id, const char *observation)
{
    (void)printf(
        "PULSE_HP35_CHECKPOINT {\"schema\":"
        "\"pulse.esp32.hp3_5-slot-checkpoint.v1\",\"id\":\"%s\","
        "\"status\":\"PASS\",\"observation\":\"%s\"}\n",
        id,
        observation);
    (void)fflush(stdout);
}

static void save_state(Hp35State *state, Hp35Phase phase)
{
    esp_err_t error;
    state->magic = HP35_STATE_MAGIC;
    state->schema = HP35_STATE_SCHEMA;
    state->phase = (uint32_t)phase;
    state->crc32 = state_crc32(state);
    error = nvs_set_blob(s_nvs, HP35_NVS_KEY, state, sizeof(*state));
    if (error == ESP_OK) {
        error = nvs_commit(s_nvs);
    }
    if (error != ESP_OK) {
        fatal("campaign state commit failed", (int32_t)error);
    }
}

static bool load_state(Hp35State *state)
{
    size_t bytes = sizeof(*state);
    esp_err_t error = nvs_get_blob(s_nvs, HP35_NVS_KEY, state, &bytes);
    if (error == ESP_ERR_NVS_NOT_FOUND) {
        memset(state, 0, sizeof(*state));
        return false;
    }
    if (error != ESP_OK || bytes != sizeof(*state) ||
        state->magic != HP35_STATE_MAGIC ||
        state->schema != HP35_STATE_SCHEMA ||
        state->crc32 != state_crc32(state)) {
        fatal("campaign state invalid", (int32_t)error);
    }
    return true;
}

static void restart_at(Hp35State *state, Hp35Phase phase)
{
    state->boot_sequence++;
    save_state(state, phase);
    (void)fflush(stdout);
    esp_restart();
    fatal("esp_restart returned", WDC_ERR_IO);
}

static void watchdog_reset_at(Hp35State *state, Hp35Phase phase)
{
    esp_err_t error;
    state->boot_sequence++;
    save_state(state, phase);
    (void)printf(
        "PULSE_HP35_RESET {\"schema\":\"pulse.esp32.hp3_5-slot-reset.v1\","
        "\"mechanism\":\"task_wdt\",\"phase\":%u}\n",
        (unsigned)phase);
    (void)fflush(stdout);
    error = esp_task_wdt_add(NULL);
    if (error != ESP_OK && error != ESP_ERR_INVALID_STATE) {
        fatal("task watchdog subscription failed", (int32_t)error);
    }
    for (;;) {
        /* Intentionally starve the subscribed campaign task. */
    }
}

static WdcAppSlotVerifyPolicy make_verify_policy(
    WdcBundleVerifyPolicy *bundle_policy)
{
    WdcAppSlotVerifyPolicy policy;
    memset(&policy, 0, sizeof(policy));
    *bundle_policy = wdc_bundle_make_default_dev_policy(wdc_profile_builtin());
    policy.bundle_policy = bundle_policy;
    return policy;
}

static void build_artifact(void)
{
    WdcPulseAppArtifactHeaderV1 header;
    WdcBundleParsedHeader parsed;
    WdcBundleManifestSummary manifest;
    uint32_t allowed_target;
    require_true(pulse_hp35_bundle_len > 0u &&
                     pulse_hp35_bundle_len <= HP35_MAX_BUNDLE_BYTES,
                 "embedded bundle size invalid");
#if CONFIG_IDF_TARGET_ESP32S3
    allowed_target = WDC_HOST_TARGET_MASK_ESP32S3;
#else
    allowed_target = WDC_HOST_TARGET_MASK_ESP32C6;
#endif
    require_status(wdc_bundle_parse_header(pulse_hp35_bundle,
                                           pulse_hp35_bundle_len,
                                           &parsed),
                   "embedded bundle header invalid");
    require_status(wdc_bundle_parse_manifest_summary(
                       (const char *)(pulse_hp35_bundle +
                                      parsed.manifest_offset),
                       parsed.manifest_len,
                       &manifest),
                   "embedded bundle manifest invalid");
    memset(&header, 0, sizeof(header));
    header.magic = WDC_APP_ARTIFACT_MAGIC;
    header.version = WDC_APP_ARTIFACT_VERSION;
    header.header_bytes = WDC_APP_ARTIFACT_HEADER_BYTES;
    header.total_bytes = WDC_APP_ARTIFACT_HEADER_BYTES + pulse_hp35_bundle_len;
    header.bundle_bytes = pulse_hp35_bundle_len;
    header.application_version = manifest.bundle_version;
    header.security_counter = manifest.security_counter;
    header.requirements.allowed_target_mask = allowed_target;
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
    wdc_sha256(pulse_hp35_bundle,
               pulse_hp35_bundle_len,
               header.bundle_sha256);
    wdc_sha256((const uint8_t *)manifest.bundle_id,
               (uint32_t)strlen(manifest.bundle_id),
               header.application_id_sha256);
    require_status(wdc_app_artifact_header_seal(&header),
                   "artifact header seal failed");
    memcpy(s_artifact, &header, sizeof(header));
    memcpy(s_artifact + sizeof(header),
           pulse_hp35_bundle,
           pulse_hp35_bundle_len);
    s_artifact_bytes = header.total_bytes;
}

static WdcControlHeapSnapshot heap_snapshot(void)
{
    WdcControlHeapSnapshot heap;
    heap.internal_free_bytes =
        (uint32_t)heap_caps_get_free_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
    heap.internal_largest_block_bytes = (uint32_t)heap_caps_get_largest_free_block(
        MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
#if CONFIG_IDF_TARGET_ESP32S3
    heap.psram_free_bytes =
        (uint32_t)heap_caps_get_free_size(MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
#else
    heap.psram_free_bytes = 0u;
#endif
    return heap;
}

static int32_t stage_artifact(WdcBundleMetadataV1 *metadata,
                              WdcBundleSlotId slot,
                              const WdcHostFingerprintV1 *fingerprint,
                              const WdcAppSlotVerifyPolicy *policy)
{
    WdcAppSlotStageSession session;
    WdcAppSlotStageResult result;
    uint32_t offset = 0u;
    int32_t status = wdc_app_slots_stage_begin(&session,
                                               metadata,
                                               slot,
                                               s_artifact_bytes);
    if (status != WDC_OK) {
        return status;
    }
    while (offset < s_artifact_bytes) {
        uint32_t remaining = s_artifact_bytes - offset;
        uint32_t chunk = remaining < 73u ? remaining : 73u;
        status = wdc_app_slots_stage_write(&session,
                                           s_artifact + offset,
                                           chunk);
        if (status != WDC_OK) {
            return status;
        }
        offset += chunk;
    }
    status = wdc_app_slots_stage_finish(&session,
                                        metadata,
                                        fingerprint,
                                        policy,
                                        s_scratch,
                                        sizeof(s_scratch),
                                        &result);
    if (status != WDC_OK) {
        (void)printf(
            "PULSE_HP35_STAGE_FAILURE {\"schema\":"
            "\"pulse.esp32.hp3_5-slot-stage-failure.v1\","
            "\"slot\":%u,\"error\":%" PRId32 ","
            "\"terminal_state\":%u,\"streamed_bytes\":%u,"
            "\"metadata_commits\":%u,\"header_valid\":%s,"
            "\"bundle_hash_valid\":%s,\"bundle_valid\":%s,"
            "\"host_compatible\":%s,\"security_floor_valid\":%s,"
            "\"authority_valid\":%s,\"bundle_error\":%" PRId32 "}\n",
            (unsigned)slot,
            status,
            (unsigned)result.terminal_state,
            (unsigned)result.streamed_bytes,
            (unsigned)result.metadata_commits,
            result.header_valid ? "true" : "false",
            result.bundle_hash_valid ? "true" : "false",
            result.bundle_valid ? "true" : "false",
            result.host_compatible ? "true" : "false",
            result.security_floor_valid ? "true" : "false",
            result.authority_valid ? "true" : "false",
            result.bundle_verify.status);
        (void)fflush(stdout);
    }
    if (status == WDC_OK &&
        (result.terminal_state != WDC_SLOT_VERIFIED ||
         result.application_code_launched != 0u)) {
        return WDC_ERR_CONTRACT_VIOLATION;
    }
    return status;
}

static int32_t start_trial_b(WdcBundleMetadataV1 *metadata,
                             const WdcHostFingerprintV1 *fingerprint,
                             const WdcAppSlotVerifyPolicy *verify_policy,
                             const WdcActivationPolicy *activation,
                             uint32_t boot_sequence)
{
    WdcActivationBootContext boot_context;
    WdcAppSlotBootResult boot;
    WdcControlHeapSnapshot heap = heap_snapshot();
    int32_t status = stage_artifact(metadata,
                                    WDC_BUNDLE_SLOT_B,
                                    fingerprint,
                                    verify_policy);
    if (status != WDC_OK) {
        return status;
    }
    status = wdc_app_slots_mark_trial(metadata,
                                      WDC_BUNDLE_SLOT_B,
                                      activation);
    if (status != WDC_OK) {
        return status;
    }
    boot_context.reset_attribution = WDC_ACTIVATION_RESET_HOST_SOFTWARE;
    boot_context.boot_sequence = boot_sequence;
    status = wdc_app_slots_boot(metadata,
                                activation,
                                &boot_context,
                                fingerprint,
                                &heap,
                                verify_policy,
                                s_scratch,
                                sizeof(s_scratch),
                                &boot);
    if (status != WDC_OK || boot.outcome != WDC_APP_SLOT_BOOT_RUN_TRIAL ||
        boot.application_code_launched != 0u ||
        metadata->slot_b.state != WDC_SLOT_TRIAL_RUNNING) {
        return status != WDC_OK ? status : WDC_ERR_CONTRACT_VIOLATION;
    }
    return WDC_OK;
}

static void hash_slot_a(uint8_t out_sha256[32])
{
    uint8_t bytes[HP35_MAX_ARTIFACT_BYTES];
    require_status(wdc_ota_read_slot_range(WDC_BUNDLE_SLOT_A,
                                           0u,
                                           bytes,
                                           s_artifact_bytes),
                   "slot A read failed");
    wdc_sha256(bytes, s_artifact_bytes, out_sha256);
}

static void verify_baseline(const Hp35State *state)
{
    WdcBundleMetadataV1 metadata;
    uint8_t digest[32];
    require_status(wdc_ota_read_metadata(&metadata),
                   "metadata read failed while checking baseline");
    require_true(metadata.slot_a.state == WDC_SLOT_CONFIRMED &&
                     metadata.last_good_slot == WDC_BUNDLE_SLOT_A &&
                     metadata.active_slot == WDC_BUNDLE_SLOT_A,
                 "slot A is not the unambiguous confirmed authority");
    hash_slot_a(digest);
    require_true(memcmp(digest, state->baseline_slot_a_sha256, sizeof(digest)) == 0,
                 "confirmed slot A bytes changed");
}

static void init_baseline(Hp35State *state,
                          const WdcHostFingerprintV1 *fingerprint,
                          const WdcAppSlotVerifyPolicy *verify_policy,
                          const WdcActivationPolicy *activation)
{
    WdcBundleMetadataV1 metadata;
    WdcActivationBootContext boot_context;
    WdcAppSlotBootResult boot;
    WdcActivationProbationEvidence evidence;
    WdcActivationDecision decision;
    WdcControlHeapSnapshot heap = heap_snapshot();
    require_status(wdc_ota_read_metadata(&metadata),
                   "initial metadata read failed");
    require_true(metadata.active_slot == WDC_BUNDLE_SLOT_NONE &&
                     metadata.last_good_slot == WDC_BUNDLE_SLOT_NONE &&
                     metadata.slot_a.state == WDC_SLOT_EMPTY &&
                     metadata.slot_b.state == WDC_SLOT_EMPTY,
                 "fresh full-flash erase required before HP3.5 campaign");
    state->baseline_step = HP35_BASELINE_STAGE_ARTIFACT;
    save_state(state, HP35_PHASE_INITIALIZING);
    require_status(stage_artifact(&metadata,
                                  WDC_BUNDLE_SLOT_A,
                                  fingerprint,
                                  verify_policy),
                   "baseline slot A stage failed");
    state->baseline_step = HP35_BASELINE_MARK_TRIAL;
    save_state(state, HP35_PHASE_INITIALIZING);
    require_status(wdc_app_slots_mark_trial(&metadata,
                                            WDC_BUNDLE_SLOT_A,
                                            activation),
                   "baseline slot A trial transition failed");
    state->baseline_step = HP35_BASELINE_SELECT_BOOT;
    save_state(state, HP35_PHASE_INITIALIZING);
    boot_context.reset_attribution = WDC_ACTIVATION_RESET_POWER_ON;
    boot_context.boot_sequence = state->boot_sequence;
    require_status(wdc_app_slots_boot(&metadata,
                                      activation,
                                      &boot_context,
                                      fingerprint,
                                      &heap,
                                      verify_policy,
                                      s_scratch,
                                      sizeof(s_scratch),
                                      &boot),
                   "baseline slot A boot selection failed");
    require_true(boot.outcome == WDC_APP_SLOT_BOOT_RUN_TRIAL &&
                     boot.application_code_launched == 0u,
                 "baseline trial authority invalid");
    state->baseline_step = HP35_BASELINE_CONFIRM;
    save_state(state, HP35_PHASE_INITIALIZING);
    memset(&evidence, 0, sizeof(evidence));
    evidence.readiness_observed = true;
    evidence.administration_responsive = true;
    evidence.resource_floors_preserved = true;
    evidence.observed_health_checks = activation->required_health_checks;
    evidence.elapsed_ms = activation->minimum_stable_ms;
    require_status(wdc_app_slots_evaluate_probation(&metadata,
                                                    WDC_BUNDLE_SLOT_A,
                                                    activation,
                                                    &evidence,
                                                    &decision),
                   "baseline slot A confirmation failed");
    state->baseline_step = HP35_BASELINE_HASH;
    save_state(state, HP35_PHASE_INITIALIZING);
    hash_slot_a(state->baseline_slot_a_sha256);
    state->baseline_step = HP35_BASELINE_VERIFY;
    save_state(state, HP35_PHASE_INITIALIZING);
    verify_baseline(state);
    checkpoint("baseline-confirmed-authority",
               "slot A confirmed and selected with one durable authority");
}

static void raw_inactive_prefix(uint32_t bytes)
{
    WdcOtaStageSession session;
    uint32_t write_bytes = bytes < s_artifact_bytes ? bytes : s_artifact_bytes;
    require_status(wdc_ota_stage_begin(&session,
                                       WDC_BUNDLE_SLOT_B,
                                       s_artifact_bytes),
                   "inactive slot B erase failed");
    require_status(wdc_ota_stage_write(&session,
                                       s_artifact,
                                       write_bytes),
                   "inactive slot B prefix write failed");
    /* Intentionally omit finish and all metadata writes before reset. */
}

static const esp_partition_t *metadata_partition(void)
{
    const esp_partition_t *partition = esp_partition_find_first(
        (esp_partition_type_t)0x40,
        (esp_partition_subtype_t)0x02,
        "wasm_meta");
    if (partition == NULL ||
        partition->size < 2u * WDC_OTA_METADATA_RECORD_STRIDE_BYTES) {
        fatal("canonical metadata partition missing", WDC_ERR_NOT_AVAILABLE);
    }
    return partition;
}

static void read_record(uint32_t index, WdcOtaMetadataJournalRecord *record)
{
    const esp_partition_t *partition = metadata_partition();
    esp_err_t error = esp_partition_read(
        partition,
        index * WDC_OTA_METADATA_RECORD_STRIDE_BYTES,
        record,
        sizeof(*record));
    if (error != ESP_OK) {
        fatal("metadata journal record read failed", (int32_t)error);
    }
}

static uint32_t best_record_index(void)
{
    WdcOtaMetadataJournalRecord records[2];
    bool valid[2];
    read_record(0u, &records[0]);
    read_record(1u, &records[1]);
    valid[0] = wdc_ota_metadata_journal_record_validate(&records[0]) == WDC_OK;
    valid[1] = wdc_ota_metadata_journal_record_validate(&records[1]) == WDC_OK;
    require_true(valid[0] || valid[1], "metadata journal has no valid authority");
    if (valid[0] && (!valid[1] || records[0].generation >= records[1].generation)) {
        return 0u;
    }
    return 1u;
}

static void force_best_record(uint32_t wanted)
{
    uint32_t attempt;
    for (attempt = 0u; attempt < 3u && best_record_index() != wanted; ++attempt) {
        WdcBundleMetadataV1 metadata;
        require_status(wdc_ota_read_metadata(&metadata),
                       "metadata read failed while rotating journal");
        metadata.metadata_generation++;
        require_status(wdc_bundle_metadata_seal(&metadata),
                       "metadata reseal failed while rotating journal");
        require_status(wdc_ota_write_metadata(&metadata),
                       "metadata journal rotation failed");
    }
    require_true(best_record_index() == wanted,
                 "metadata journal did not rotate to expected record");
}

static void erase_non_authoritative_record(uint32_t index)
{
    const esp_partition_t *partition = metadata_partition();
    esp_err_t error;
    require_true(best_record_index() != index,
                 "refused to erase authoritative metadata record");
    error = esp_partition_erase_range(
        partition,
        index * WDC_OTA_METADATA_RECORD_STRIDE_BYTES,
        WDC_OTA_METADATA_RECORD_STRIDE_BYTES);
    if (error != ESP_OK) {
        fatal("non-authoritative metadata erase failed", (int32_t)error);
    }
}

static void journal_corruption_checkpoints(const Hp35State *state)
{
    WdcBundleMetadataV1 metadata;
    force_best_record(1u);
    erase_non_authoritative_record(0u);
    require_status(wdc_ota_read_metadata(&metadata),
                   "record 1 did not survive record 0 corruption");
    verify_baseline(state);
    checkpoint("journal-record-0-corrupt",
               "record 0 erased while authoritative record 1 preserved slot A");

    force_best_record(0u);
    erase_non_authoritative_record(1u);
    require_status(wdc_ota_read_metadata(&metadata),
                   "record 0 did not survive record 1 corruption");
    verify_baseline(state);
    checkpoint("journal-record-1-corrupt",
               "record 1 erased while authoritative record 0 preserved slot A");
    force_best_record(1u);
}

static void attributed_trial_reset(const Hp35State *state,
                                   WdcActivationResetAttribution attribution,
                                   uint32_t boot_sequence,
                                   const WdcHostFingerprintV1 *fingerprint,
                                   const WdcAppSlotVerifyPolicy *verify_policy,
                                   const WdcActivationPolicy *activation)
{
    WdcBundleMetadataV1 metadata;
    WdcActivationBootContext boot_context;
    WdcAppSlotBootResult boot;
    WdcControlHeapSnapshot heap = heap_snapshot();
    require_status(wdc_ota_read_metadata(&metadata),
                   "trial-reset metadata read failed");
    require_true(metadata.slot_b.state == WDC_SLOT_TRIAL_RUNNING &&
                     metadata.trial_boot_in_progress == 1u,
                 "reset did not preserve a running slot B trial");
    boot_context.reset_attribution = attribution;
    boot_context.boot_sequence = boot_sequence;
    require_status(wdc_app_slots_boot(&metadata,
                                      activation,
                                      &boot_context,
                                      fingerprint,
                                      &heap,
                                      verify_policy,
                                      s_scratch,
                                      sizeof(s_scratch),
                                      &boot),
                   "attributed trial reset handling failed");
    require_true(boot.outcome == WDC_APP_SLOT_BOOT_FALLBACK_REBOOT_REQUIRED &&
                     boot.fallback_slot == WDC_BUNDLE_SLOT_A &&
                     boot.application_code_launched == 0u &&
                     metadata.slot_b.state == WDC_SLOT_REJECTED &&
                     metadata.last_reset_attribution == attribution,
                 "attributed trial reset did not reject slot B");
    verify_baseline(state);
}

static void readiness_and_traps(
    const Hp35State *state,
    const WdcHostFingerprintV1 *fingerprint,
    const WdcAppSlotVerifyPolicy *verify_policy,
    const WdcActivationPolicy *activation,
    uint32_t *boot_sequence)
{
    WdcBundleMetadataV1 metadata;
    WdcActivationProbationEvidence evidence;
    WdcActivationDecision decision;
    uint32_t index;
    require_status(wdc_ota_read_metadata(&metadata),
                   "readiness metadata read failed");
    (*boot_sequence)++;
    require_status(start_trial_b(&metadata,
                                 fingerprint,
                                 verify_policy,
                                 activation,
                                 *boot_sequence),
                   "readiness slot B trial start failed");
    memset(&evidence, 0, sizeof(evidence));
    evidence.elapsed_ms = activation->readiness_deadline_ms;
    evidence.resource_floors_preserved = true;
    require_status(wdc_app_slots_evaluate_probation(&metadata,
                                                    WDC_BUNDLE_SLOT_B,
                                                    activation,
                                                    &evidence,
                                                    &decision),
                   "readiness timeout evaluation failed");
    require_true(decision.rollback &&
                     decision.reason == WDC_ERR_TIMEOUT &&
                     decision.fallback_slot == WDC_BUNDLE_SLOT_A,
                 "readiness timeout did not select confirmed fallback");
    verify_baseline(state);
    checkpoint("readiness-timeout",
               "withheld readiness reached deadline and rejected slot B");

    for (index = 0u; index < 8u; ++index) {
        require_status(wdc_ota_read_metadata(&metadata),
                       "guest-trap metadata read failed");
        (*boot_sequence)++;
        require_status(start_trial_b(&metadata,
                                     fingerprint,
                                     verify_policy,
                                     activation,
                                     *boot_sequence),
                       "guest-trap slot B trial start failed");
        require_status(wdc_app_slots_record_runtime_fault(
                           &metadata,
                           WDC_BUNDLE_SLOT_B,
                           WDC_ERR_CONTRACT_VIOLATION,
                           &decision),
                       "guest-trap fault recording failed");
        require_true(decision.rollback &&
                         decision.fallback_slot == WDC_BUNDLE_SLOT_A,
                     "guest-trap fault did not select slot A");
        verify_baseline(state);
    }
    checkpoint("guest-trap-repeat",
               "eight recorded guest traps rejected slot B and preserved slot A");
}

static uint32_t metadata_record_crc32(WdcOtaMetadataJournalRecord *record)
{
    WdcOtaMetadataJournalRecord copy;
    memcpy(&copy, record, sizeof(copy));
    copy.record_crc = 0u;
    copy.commit_marker = 0u;
    return crc32_update(0u, (const uint8_t *)&copy, (uint32_t)sizeof(copy));
}

static void write_confirmation_record(bool include_marker)
{
    const esp_partition_t *partition = metadata_partition();
    WdcBundleMetadataV1 metadata;
    WdcOtaMetadataJournalRecord record;
    uint32_t target = best_record_index() == 0u ? 1u : 0u;
    uint32_t offset = target * WDC_OTA_METADATA_RECORD_STRIDE_BYTES;
    esp_err_t error;
    require_status(wdc_ota_read_metadata(&metadata),
                   "confirmation metadata read failed");
    require_true(metadata.slot_b.state == WDC_SLOT_TRIAL_RUNNING,
                 "confirmation boundary requires a running slot B trial");
    require_status(wdc_activation_confirm(&metadata,
                                          WDC_BUNDLE_SLOT_B,
                                          1u),
                   "confirmation metadata construction failed");
    memset(&record, 0xff, sizeof(record));
    record.magic = WDC_OTA_METADATA_RECORD_MAGIC;
    record.version = WDC_OTA_METADATA_RECORD_VERSION;
    record.reserved = 0u;
    record.generation = metadata.metadata_generation;
    memcpy(&record.metadata, &metadata, sizeof(record.metadata));
    require_status(wdc_bundle_metadata_seal(&record.metadata),
                   "confirmation record metadata seal failed");
    record.commit_marker = 0u;
    record.record_crc = metadata_record_crc32(&record);
    record.commit_marker = WDC_OTA_METADATA_COMMIT_MARKER;
    erase_non_authoritative_record(target);
    error = esp_partition_write(partition,
                                offset,
                                &record,
                                offsetof(WdcOtaMetadataJournalRecord,
                                         commit_marker));
    if (error != ESP_OK) {
        fatal("confirmation record body write failed", (int32_t)error);
    }
    if (include_marker) {
        error = esp_partition_write(
            partition,
            offset + offsetof(WdcOtaMetadataJournalRecord, commit_marker),
            &record.commit_marker,
            sizeof(record.commit_marker));
        if (error != ESP_OK) {
            fatal("confirmation record marker write failed", (int32_t)error);
        }
    }
}

static void emit_board_identity(void)
{
    esp_chip_info_t chip;
    uint32_t flash_bytes = 0u;
    uint8_t mac[6];
    uint8_t uid_input[16] = {'p', 'u', 'l', 's', 'e', '-', 'h', 'p', '3', '5'};
    uint8_t uid_sha256[32];
    esp_chip_info(&chip);
    require_true(esp_flash_get_physical_size(NULL, &flash_bytes) == ESP_OK,
                 "flash size query failed");
    require_true(flash_bytes == HP35_FLASH_BYTES,
                 "physical flash size does not match named board");
#if CONFIG_IDF_TARGET_ESP32S3
    require_true(chip.model == CHIP_ESP32S3,
                 "chip is not ESP32-S3");
    require_true((uint32_t)esp_psram_get_size() == HP35_PSRAM_BYTES,
                 "physical PSRAM size does not match named board");
#else
    require_true(chip.model == CHIP_ESP32C6,
                 "chip is not ESP32-C6");
#endif
    require_true(esp_efuse_mac_get_default(mac) == ESP_OK,
                 "eFuse MAC query failed");
    memcpy(uid_input + 10u, mac, sizeof(mac));
    wdc_sha256(uid_input, sizeof(uid_input), uid_sha256);
    hex32(uid_sha256, s_uid_sha256_hex);
    (void)printf(
        "PULSE_HP35_BOARD {\"schema\":\"pulse.esp32.hp3_5-slot-board-start.v1\","
        "\"campaign_id\":\"%s\",\"campaign_sha256\":\"%s\","
        "\"board_id\":\"%s\",\"target\":\"%s\","
        "\"flash_bytes\":%u,\"psram_bytes\":%u,"
        "\"physical_board_uid_sha256\":\"%s\","
        "\"partition_sha256\":\"%s\",\"bundle_sha256\":\"%s\"}\n",
        HP35_CAMPAIGN_ID,
        HP35_CAMPAIGN_SHA256,
        HP35_BOARD_ID,
        HP35_TARGET,
        HP35_FLASH_BYTES,
        HP35_PSRAM_BYTES,
        s_uid_sha256_hex,
        HP35_PARTITION_SHA256,
        HP35_BUNDLE_SHA256);
    (void)fflush(stdout);
}

static void emit_final(void)
{
    (void)printf(
        "PULSE_HP35_FINAL {\"schema\":\"pulse.esp32.hp3_5-slot-final.v1\","
        "\"status\":\"PASS\",\"checkpoint_count\":13,"
        "\"invariants\":{\"last_confirmed_destroyed\":false,"
        "\"ambiguous_boot_authority\":false,"
        "\"application_code_launched_before_authority\":false},"
        "\"claim_boundary\":{\"inactive_slot_only\":true,"
        "\"factory_host_partition_written\":false,"
        "\"host_firmware_ota\":false,\"external_provider\":false,"
        "\"rax\":false}}\n");
    (void)fflush(stdout);
}

void app_main(void)
{
    Hp35State state;
    bool have_state;
    WdcBundleVerifyPolicy bundle_policy;
    WdcAppSlotVerifyPolicy verify_policy;
    WdcActivationPolicy activation = wdc_activation_default_policy();
    const WdcHostFingerprintV1 *fingerprint;
    WdcBundleMetadataV1 metadata;
    esp_reset_reason_t reset_reason = esp_reset_reason();
    esp_err_t error = nvs_flash_init();
    if (error != ESP_OK) {
        fatal("NVS initialization failed without erasing evidence", (int32_t)error);
    }
    error = nvs_open(HP35_NVS_NAMESPACE, NVS_READWRITE, &s_nvs);
    if (error != ESP_OK) {
        fatal("campaign NVS namespace open failed", (int32_t)error);
    }
    emit_board_identity();
    build_artifact();
    fingerprint = wdc_host_running_fingerprint();
    require_true(fingerprint != NULL,
                 "running host fingerprint target is unavailable");
    require_status(wdc_host_fingerprint_validate(fingerprint),
                   "running host fingerprint validation failed");
    require_true(fingerprint->flash_bytes == HP35_FLASH_BYTES,
                 "running host fingerprint flash size mismatch");
    require_true(fingerprint->psram_bytes == HP35_PSRAM_BYTES,
                 "running host fingerprint PSRAM size mismatch");
    require_true((fingerprint->capability_mask &
                  WDC_HOST_CAP_APPLICATION_SLOTS) != 0u,
                 "running host fingerprint lacks application slots");
    verify_policy = make_verify_policy(&bundle_policy);
    have_state = load_state(&state);
    if (!have_state) {
        memset(&state, 0, sizeof(state));
        state.boot_sequence = 1u;
        (void)printf(
            "PULSE_HP35_ARMING {\"schema\":"
            "\"pulse.esp32.hp3_5-slot-arming.v1\","
            "\"status\":\"WAITING\",\"delay_ms\":%u}\n",
            (unsigned)HP35_BASELINE_ARM_DELAY_MS);
        (void)fflush(stdout);
        vTaskDelay(pdMS_TO_TICKS(HP35_BASELINE_ARM_DELAY_MS));
        init_baseline(&state,
                      fingerprint,
                      &verify_policy,
                      &activation);
        restart_at(&state, HP35_PHASE_AFTER_ZERO_PREFIX_RESET);
    }

    switch ((Hp35Phase)state.phase) {
    case HP35_PHASE_INITIALIZING:
        (void)printf(
            "PULSE_HP35_BASELINE_INTERRUPTED {\"schema\":"
            "\"pulse.esp32.hp3_5-slot-baseline-interrupted.v1\","
            "\"step\":\"%s\",\"step_id\":%u}\n",
            baseline_step_name(state.baseline_step),
            (unsigned)state.baseline_step);
        (void)fflush(stdout);
        fatal("campaign was interrupted while establishing baseline; restore and erase",
              WDC_ERR_INVALID_STATE);
        break;
    case HP35_PHASE_AFTER_ZERO_PREFIX_RESET:
        require_true(reset_reason == ESP_RST_SW,
                     "zero-prefix checkpoint did not resume from software reset");
        verify_baseline(&state);
        checkpoint("inactive-payload-zero-prefix",
                   "reset before slot B payload preserved confirmed slot A");
        raw_inactive_prefix(4096u);
        restart_at(&state, HP35_PHASE_AFTER_SECTOR_RESET);
        break;
    case HP35_PHASE_AFTER_SECTOR_RESET:
        require_true(reset_reason == ESP_RST_SW,
                     "sector-boundary checkpoint did not resume from software reset");
        verify_baseline(&state);
        checkpoint("inactive-payload-sector-boundary",
                   "reset at 4096 bytes or artifact end preserved confirmed slot A");
        raw_inactive_prefix(s_artifact_bytes);
        restart_at(&state, HP35_PHASE_AFTER_COMPLETE_RESET);
        break;
    case HP35_PHASE_AFTER_COMPLETE_RESET:
        require_true(reset_reason == ESP_RST_SW,
                     "complete-payload checkpoint did not resume from software reset");
        verify_baseline(&state);
        checkpoint("inactive-payload-complete-no-metadata",
                   "complete slot B payload without metadata preserved slot A authority");
        journal_corruption_checkpoints(&state);
        require_status(wdc_ota_read_metadata(&metadata),
                       "stale-trial metadata read failed");
        state.boot_sequence++;
        require_status(start_trial_b(&metadata,
                                     fingerprint,
                                     &verify_policy,
                                     &activation,
                                     state.boot_sequence),
                       "stale slot B trial start failed");
        restart_at(&state, HP35_PHASE_AFTER_STALE_TRIAL_RESET);
        break;
    case HP35_PHASE_AFTER_STALE_TRIAL_RESET:
        require_true(reset_reason == ESP_RST_SW,
                     "stale-trial checkpoint did not resume from software reset");
        attributed_trial_reset(&state,
                               WDC_ACTIVATION_RESET_HOST_SOFTWARE,
                               ++state.boot_sequence,
                               fingerprint,
                               &verify_policy,
                               &activation);
        checkpoint("stale-trial-reset",
                   "running slot B trial was rejected after reset and slot A selected");
        readiness_and_traps(&state,
                            fingerprint,
                            &verify_policy,
                            &activation,
                            &state.boot_sequence);
        require_status(wdc_ota_read_metadata(&metadata),
                       "application-watchdog metadata read failed");
        state.boot_sequence++;
        require_status(start_trial_b(&metadata,
                                     fingerprint,
                                     &verify_policy,
                                     &activation,
                                     state.boot_sequence),
                       "application-watchdog slot B trial start failed");
        watchdog_reset_at(&state, HP35_PHASE_AFTER_APPLICATION_WDT);
        break;
    case HP35_PHASE_AFTER_APPLICATION_WDT:
        require_true(reset_reason == ESP_RST_TASK_WDT,
                     "application-watchdog checkpoint did not resume from task WDT");
        attributed_trial_reset(&state,
                               WDC_ACTIVATION_RESET_APPLICATION_WATCHDOG,
                               ++state.boot_sequence,
                               fingerprint,
                               &verify_policy,
                               &activation);
        checkpoint("application-watchdog-attribution",
                   "task WDT attributed to slot B rejected it and selected slot A");
        require_status(wdc_ota_read_metadata(&metadata),
                       "host-watchdog metadata read failed");
        state.boot_sequence++;
        require_status(start_trial_b(&metadata,
                                     fingerprint,
                                     &verify_policy,
                                     &activation,
                                     state.boot_sequence),
                       "host-watchdog slot B trial start failed");
        watchdog_reset_at(&state, HP35_PHASE_AFTER_HOST_WDT);
        break;
    case HP35_PHASE_AFTER_HOST_WDT:
        require_true(reset_reason == ESP_RST_TASK_WDT,
                     "host-watchdog checkpoint did not resume from task WDT");
        attributed_trial_reset(&state,
                               WDC_ACTIVATION_RESET_HOST_WATCHDOG,
                               ++state.boot_sequence,
                               fingerprint,
                               &verify_policy,
                               &activation);
        checkpoint("host-watchdog-attribution",
                   "task WDT attributed to host rejected slot B and selected slot A");
        require_status(wdc_ota_read_metadata(&metadata),
                       "before-marker metadata read failed");
        state.boot_sequence++;
        require_status(start_trial_b(&metadata,
                                     fingerprint,
                                     &verify_policy,
                                     &activation,
                                     state.boot_sequence),
                       "before-marker slot B trial start failed");
        write_confirmation_record(false);
        restart_at(&state, HP35_PHASE_AFTER_CONFIRMATION_BODY);
        break;
    case HP35_PHASE_AFTER_CONFIRMATION_BODY:
        require_true(reset_reason == ESP_RST_SW,
                     "before-marker checkpoint did not resume from software reset");
        attributed_trial_reset(&state,
                               WDC_ACTIVATION_RESET_HOST_SOFTWARE,
                               ++state.boot_sequence,
                               fingerprint,
                               &verify_policy,
                               &activation);
        checkpoint("confirmation-before-marker",
                   "unmarked confirmation body lost to old trial generation then slot A fallback");
        require_status(wdc_ota_read_metadata(&metadata),
                       "after-marker metadata read failed");
        state.boot_sequence++;
        require_status(start_trial_b(&metadata,
                                     fingerprint,
                                     &verify_policy,
                                     &activation,
                                     state.boot_sequence),
                       "after-marker slot B trial start failed");
        write_confirmation_record(true);
        restart_at(&state, HP35_PHASE_AFTER_CONFIRMATION_MARKER);
        break;
    case HP35_PHASE_AFTER_CONFIRMATION_MARKER:
        require_true(reset_reason == ESP_RST_SW,
                     "after-marker checkpoint did not resume from software reset");
        require_status(wdc_ota_read_metadata(&metadata),
                       "committed confirmation metadata read failed");
        require_true(metadata.slot_b.state == WDC_SLOT_CONFIRMED &&
                         metadata.last_good_slot == WDC_BUNDLE_SLOT_B &&
                         metadata.active_slot == WDC_BUNDLE_SLOT_B &&
                         metadata.trial_boot_in_progress == 0u,
                     "marked confirmation record was not authoritative");
        {
            uint8_t digest[32];
            hash_slot_a(digest);
            require_true(memcmp(digest,
                                state.baseline_slot_a_sha256,
                                sizeof(digest)) == 0,
                         "prior confirmed slot A bytes changed after slot B confirmation");
        }
        checkpoint("confirmation-after-marker",
                   "marked confirmation generation selected slot B while prior slot A bytes remained intact");
        save_state(&state, HP35_PHASE_COMPLETE);
        emit_final();
        stop_forever();
        break;
    case HP35_PHASE_COMPLETE:
        emit_final();
        stop_forever();
        break;
    default:
        fatal("campaign phase is outside the sealed state machine",
              WDC_ERR_BAD_ENCODING);
        break;
    }
}
