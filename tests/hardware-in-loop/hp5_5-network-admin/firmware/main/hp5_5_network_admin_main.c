#include <inttypes.h>
#include <pthread.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "esp_chip_info.h"
#include "esp_flash.h"
#include "esp_mac.h"
#if CONFIG_IDF_TARGET_ESP32S3
#include "esp_psram.h"
#endif
#include "esp_system.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "nvs.h"
#include "nvs_flash.h"

#include "hp5_5_campaign_config.h"
#include "hp5_5_fixture_blobs.h"
#include "hp5_5_provision.h"
#include "wdc_abi.h"
#include "wdc_activation.h"
#include "wdc_admin.h"
#include "wdc_admin_recovery.h"
#include "wdc_app_slots.h"
#include "wdc_bundle.h"
#include "wdc_caps.h"
#include "wdc_control.h"
#include "wdc_host_identity.h"
#include "wdc_http_platform.h"
#include "wdc_http_service.h"
#include "wdc_net.h"
#include "wdc_ota.h"
#include "wdc_profile.h"
#include "wdc_runtime.h"

#if !CONFIG_IDF_TARGET_ESP32S3 && !CONFIG_IDF_TARGET_ESP32C6
#error "HP5.5 supports only the frozen ESP32-S3 and ESP32-C6 lanes"
#endif

#define HP55_NVS_NAMESPACE "hp55"
#define HP55_NVS_BOOT_KEY "bootseq"
#define HP55_DRIVER_STACK_BYTES 24576u
#define HP55_ADMIN_TASK_STACK_BYTES 8192u
#define HP55_STATS_TASK_STACK_BYTES 4096u
#define HP55_RESTART_DELAY_MS 1500u
#define HP55_STATUS_COMPLETION_DELAY_MS 4000u
#define HP55_APP_PRESSURE_DELAY_MS 8000u
#define HP55_SESSION_NONCE_PREFIX UINT64_C(0x4850353500000000)

static WdcControlKernel s_kernel;
static WdcAdminCore s_admin;
static WdcAdminRecoveryEngine s_recovery;
static WdcHttpService s_http;
static WdcRuntime s_runtime;
static WdcBundleMetadataV1 s_metadata;
static WdcBundleVerifyPolicy s_bundle_policy;
static WdcAppSlotVerifyPolicy s_slot_policy;
static WdcActivationPolicy s_activation;
static uint8_t s_update_working[WDC_ADMIN_UPDATE_WORKING_BYTES];
static bool s_runtime_loaded;
static bool s_recovery_initialized;
static const WdcHostFingerprintV1 *s_running_fingerprint;
static WdcBundleSlotId s_pending_trial_slot = WDC_BUNDLE_SLOT_NONE;
static uint32_t s_pending_trial_version;
static uint64_t s_trial_runtime_started_ms;
static bool s_timeout_once;
static uint32_t s_min_internal_free = UINT32_MAX;
static uint32_t s_min_internal_largest = UINT32_MAX;
static uint32_t s_min_psram_free = UINT32_MAX;
static bool s_wifi_disconnect_observed;
static bool s_wifi_reconnect_observed;
static uint32_t s_wifi_reconnect_elapsed_ms;
static char s_uid_sha256[65];

static uint64_t monotonic_ms(void)
{
    int64_t value = esp_timer_get_time();
    return value > 0 ? (uint64_t)value / 1000u : 0u;
}

static void idle_forever(void)
{
    for (;;) {
        vTaskDelay(pdMS_TO_TICKS(10000u));
    }
}

static void fatal(const char *step, int32_t status)
{
    (void)printf(
        "PULSE_HP55_FATAL {\"schema\":\"pulse.esp32.hp5_5-fatal.v1\","
        "\"step\":\"%s\",\"status\":%" PRId32 "}\n",
        step, status);
    (void)fflush(stdout);
    idle_forever();
}

static void require_status(int32_t status, const char *step)
{
    if (status != WDC_OK) {
        fatal(step, status);
    }
}

static void require_true(bool value, const char *step)
{
    if (!value) {
        fatal(step, WDC_ERR_CONTRACT_VIOLATION);
    }
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

static void checkpoint(const char *identifier, const char *detail)
{
    (void)printf(
        "PULSE_HP55_CHECKPOINT {\"schema\":"
        "\"pulse.esp32.hp5_5-checkpoint.v1\",\"id\":\"%s\","
        "\"detail\":\"%s\"}\n",
        identifier, detail);
    (void)fflush(stdout);
}

static WdcControlHeapSnapshot heap_snapshot(void)
{
    WdcControlHeapSnapshot heap;
    require_status(wdc_control_platform_heap_snapshot(&heap),
                   "physical-heap-snapshot");
    if (heap.internal_free_bytes < s_min_internal_free) {
        s_min_internal_free = heap.internal_free_bytes;
    }
    if (heap.internal_largest_block_bytes < s_min_internal_largest) {
        s_min_internal_largest = heap.internal_largest_block_bytes;
    }
    if (heap.psram_free_bytes < s_min_psram_free) {
        s_min_psram_free = heap.psram_free_bytes;
    }
    return heap;
}

static void emit_stats(void)
{
    WdcHttpServiceStats stats;
    WdcHttpPlatformStatus platform;
    WdcControlHeapSnapshot heap = heap_snapshot();
    wdc_http_service_get_stats(&s_http, &stats);
    wdc_http_platform_get_status(&platform);
    (void)printf(
        "PULSE_HP55_STATS {\"schema\":\"pulse.esp32.hp5_5-stats.v1\","
        "\"internal_free\":%u,\"internal_largest\":%u,"
        "\"psram_free\":%u,\"minimum_internal_free\":%u,"
        "\"minimum_internal_largest\":%u,\"minimum_psram_free\":%u,"
        "\"wifi_connected\":%s,\"reconnect_count\":%u,"
        "\"wifi_disconnect_observed\":%s,"
        "\"wifi_reconnect_observed\":%s,"
        "\"wifi_reconnect_elapsed_ms\":%u,"
        "\"app_response_losses\":%u,\"admin_response_losses\":%u,"
        "\"admin_terminal_losses\":%u,\"duplicate_rejections\":%u,"
        "\"app_timeouts\":%u,\"app_cancelled\":%u,"
        "\"app_trapped\":%u}\n",
        heap.internal_free_bytes, heap.internal_largest_block_bytes,
        heap.psram_free_bytes, s_min_internal_free,
        s_min_internal_largest,
        s_min_psram_free == UINT32_MAX ? 0u : s_min_psram_free,
        platform.wifi_connected ? "true" : "false",
        platform.reconnect_count,
        s_wifi_disconnect_observed ? "true" : "false",
        s_wifi_reconnect_observed ? "true" : "false",
        s_wifi_reconnect_elapsed_ms, stats.app_response_losses,
        stats.admin_response_losses, stats.admin_terminal_losses,
        stats.duplicate_response_rejections, stats.app_timed_out,
        stats.app_cancelled, stats.app_trapped);
    (void)fflush(stdout);
}

static bool text_equals(const WdcCborText *text, const char *value)
{
    size_t bytes = strlen(value);
    return text != NULL && text->ptr != NULL && text->len == bytes &&
           memcmp(text->ptr, value, bytes) == 0;
}

static bool bytes_equals(const WdcCborBytes *bytes, const char *value)
{
    size_t length = strlen(value);
    return bytes != NULL && bytes->ptr != NULL && bytes->len == length &&
           memcmp(bytes->ptr, value, length) == 0;
}

static int32_t allow_http(void *context, uint32_t opcode,
                          const uint8_t *request, uint32_t request_bytes,
                          int32_t *decision)
{
    uint32_t resource_id = 0u;
    (void)context;
    if (decision == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    *decision = opcode == WDC_OP_HTTP_RESPOND && request != NULL &&
                        wdc_cbor_map_find_u32(request, request_bytes,
                                              WDC_CBOR_KEY_RESOURCE_ID,
                                              &resource_id) == WDC_OK &&
                        resource_id == WDC_R8_RESOURCE_HTTP_API
                    ? WDC_OK
                    : WDC_ERR_CAPABILITY_DENIED;
    return WDC_OK;
}

static int32_t guest_respond(uint32_t request_id, uint32_t http_status,
                             const uint8_t *body, uint32_t body_bytes)
{
    uint8_t request[WDC_HTTP_APP_EVENT_MAX_BYTES];
    uint8_t response[32];
    uint32_t response_bytes = 0u;
    WdcCborBuilder builder;
    int32_t status;
    int32_t guest_status = WDC_ERR_BAD_ENCODING;
    wdc_cbor_builder_init(&builder, request, sizeof(request));
    status = wdc_cbor_begin_map(&builder, 4u);
    if (status == WDC_OK) {
        status = wdc_cbor_put_key_u32(&builder, WDC_CBOR_KEY_RESOURCE_ID,
                                      WDC_R8_RESOURCE_HTTP_API);
    }
    if (status == WDC_OK) {
        status = wdc_cbor_put_key_u32(&builder, WDC_CBOR_KEY_REQUEST_ID,
                                      request_id);
    }
    if (status == WDC_OK) {
        status = wdc_cbor_put_key_u32(&builder, WDC_CBOR_KEY_HTTP_STATUS,
                                      http_status);
    }
    if (status == WDC_OK) {
        status = wdc_cbor_put_key_bytes(&builder, WDC_CBOR_KEY_DATA, body,
                                        body_bytes);
    }
    if (status == WDC_OK) {
        status = wdc_host_call_dispatch(WDC_OP_HTTP_RESPOND, request,
                                        wdc_cbor_len(&builder), response,
                                        sizeof(response), &response_bytes);
    }
    if (status == WDC_OK) {
        status = wdc_cbor_map_find_i32(response, response_bytes,
                                       WDC_CBOR_KEY_STATUS, &guest_status);
    }
    return status == WDC_OK ? guest_status : status;
}

static uint64_t http_clock(void *context)
{
    uint64_t now = monotonic_ms();
    (void)context;
    if (s_timeout_once) {
        s_timeout_once = false;
        return now + WDC_HTTP_APP_REQUEST_DEADLINE_MS + 1u;
    }
    return now;
}

static int32_t app_dispatch(void *context, const uint8_t *event_cbor,
                            uint32_t event_bytes, uint64_t deadline_ms)
{
    WdcCborText path = {0};
    WdcCborBytes body = {0};
    uint32_t request_id = 0u;
    static uint8_t oversized[WDC_HTTP_APP_BODY_MAX_BYTES + 1u];
    int32_t first;
    (void)context;
    (void)deadline_ms;
    if (wdc_cbor_map_find_text(event_cbor, event_bytes, WDC_CBOR_KEY_URL,
                               &path) != WDC_OK ||
        wdc_cbor_map_find_bytes(event_cbor, event_bytes, WDC_CBOR_KEY_DATA,
                                &body) != WDC_OK ||
        wdc_cbor_map_find_u32(event_cbor, event_bytes,
                              WDC_CBOR_KEY_REQUEST_ID,
                              &request_id) != WDC_OK) {
        return WDC_ERR_BAD_ENCODING;
    }
    if (text_equals(&path, "/pulse/v1/app/echo")) {
        if (!s_runtime_loaded) {
            return WDC_ERR_NOT_AVAILABLE;
        }
        first = wdc_runtime_call_event_cbor(&s_runtime, event_cbor,
                                            event_bytes);
        checkpoint("common-wasm-app-response",
                   "real WAMR handler dispatched the bounded HTTP event");
        return first;
    }
    if (text_equals(&path, "/pulse/v1/app/empty")) {
        checkpoint("app-empty-response",
                   "bounded handler completed without a response effect");
        return WDC_OK;
    }
    if (text_equals(&path, "/pulse/v1/app/trap")) {
        checkpoint("app-trap-contained", "application failure stayed local");
        return WDC_ERR_CONTRACT_VIOLATION;
    }
    if (!text_equals(&path, "/pulse/v1/app/control")) {
        return WDC_ERR_NOT_AVAILABLE;
    }
    if (bytes_equals(&body, "client-loss")) {
        vTaskDelay(pdMS_TO_TICKS(500u));
        return guest_respond(request_id, 200u,
                             (const uint8_t *)"late-after-loss", 15u);
    }
    if (bytes_equals(&body, "duplicate")) {
        first = guest_respond(request_id, 201u, (const uint8_t *)"first", 5u);
        require_status(first, "first-response");
        require_true(guest_respond(request_id, 202u,
                                   (const uint8_t *)"late", 4u) ==
                         WDC_ERR_CONTRACT_VIOLATION,
                     "duplicate-response-rejection");
        checkpoint("app-first-response-wins",
                   "second response effect was rejected after first ownership");
        return WDC_OK;
    }
    if (bytes_equals(&body, "wrong-id")) {
        require_true(guest_respond(request_id + 1u, 200u,
                                   (const uint8_t *)"wrong", 5u) ==
                         WDC_ERR_CONTRACT_VIOLATION,
                     "wrong-request-id-rejection");
        checkpoint("app-wrong-id-rejected",
                   "response effect with a foreign request id was rejected");
        return WDC_OK;
    }
    if (bytes_equals(&body, "oversize")) {
        memset(oversized, 0x5au, sizeof(oversized));
        require_true(guest_respond(request_id, 200u, oversized,
                                   sizeof(oversized)) == WDC_ERR_BAD_LENGTH,
                     "oversize-response-rejection");
        checkpoint("app-oversize-rejected",
                   "response larger than the application bound was rejected");
        return WDC_OK;
    }
    if (bytes_equals(&body, "timeout")) {
        s_timeout_once = true;
        checkpoint("app-timeout-contained", "deadline advanced at dispatch exit");
        return WDC_OK;
    }
    if (bytes_equals(&body, "cancel")) {
        require_status(wdc_http_service_cancel_app(&s_http, request_id),
                       "application-cancel");
        checkpoint("app-cancellation-contained",
                   "active request cancellation did not affect administration");
        return WDC_OK;
    }
    if (bytes_equals(&body, "pressure")) {
        (void)heap_snapshot();
        vTaskDelay(pdMS_TO_TICKS(HP55_APP_PRESSURE_DELAY_MS));
        (void)heap_snapshot();
        return guest_respond(request_id, 200u,
                             (const uint8_t *)"pressure-complete", 17u);
    }
    if (bytes_equals(&body, "finalize")) {
        emit_stats();
        (void)printf(
            "PULSE_HP55_FINAL {\"schema\":\"pulse.esp32.hp5_5-final.v1\","
            "\"status\":\"PASS\",\"campaign_id\":\"%s\","
            "\"board_id\":\"%s\",\"physical_board_uid_sha256\":\"%s\","
            "\"factory_host_partition_written\":false,"
            "\"host_firmware_ota\":false}\n",
            HP55_CAMPAIGN_ID, HP55_BOARD_ID, s_uid_sha256);
        (void)fflush(stdout);
        return guest_respond(request_id, 200u, (const uint8_t *)"final", 5u);
    }
    return WDC_ERR_BAD_ENCODING;
}

static int32_t admin_authorize(
    void *context, const WdcAdminAuthorizationChallenge *challenge,
    const uint8_t *proof, uint32_t proof_bytes,
    WdcAdminAuthenticatedEntry *out_entry)
{
    uint8_t proof_sha256[32];
    (void)context;
    if (challenge == NULL || proof == NULL || out_entry == NULL ||
        proof_bytes == 0u) {
        return WDC_ERR_CAPABILITY_DENIED;
    }
    wdc_sha256(proof, proof_bytes, proof_sha256);
    if (memcmp(proof_sha256, pulse_hp55_admin_proof_sha256,
               sizeof(proof_sha256)) != 0) {
        memset(proof_sha256, 0, sizeof(proof_sha256));
        return WDC_ERR_CAPABILITY_DENIED;
    }
    memset(out_entry, 0, sizeof(*out_entry));
    out_entry->struct_size = sizeof(*out_entry);
    out_entry->version_major = WDC_ADMIN_VERSION_MAJOR;
    out_entry->version_minor = WDC_ADMIN_VERSION_MINOR;
    out_entry->transport_kind = challenge->start.transport_kind;
    out_entry->authorization_method = challenge->start.authorization_method;
    out_entry->privilege_mask = WDC_ADMIN_PRIVILEGE_ALL;
    out_entry->authorization_epoch = challenge->start.challenge_id;
    out_entry->issued_monotonic_ms = challenge->issued_monotonic_ms;
    out_entry->expires_monotonic_ms = challenge->issued_monotonic_ms + 600000u;
    out_entry->session_nonce =
        HP55_SESSION_NONCE_PREFIX ^ challenge->start.challenge_id;
    memcpy(out_entry->principal_sha256, proof_sha256, sizeof(proof_sha256));
    memcpy(out_entry->channel_binding_sha256,
           challenge->start.channel_binding_sha256,
           sizeof(out_entry->channel_binding_sha256));
    memset(proof_sha256, 0, sizeof(proof_sha256));
    return WDC_OK;
}

static int32_t artifact_authorize(
    void *context, const WdcAdminArtifactCandidate *candidate,
    WdcAdminArtifactVerification *out_verification)
{
    (void)context;
    if (candidate == NULL || out_verification == NULL ||
        (candidate->slot != WDC_BUNDLE_SLOT_A &&
         candidate->slot != WDC_BUNDLE_SLOT_B) ||
        candidate->stored_bytes < WDC_APP_ARTIFACT_HEADER_BYTES) {
        return WDC_ERR_CAPABILITY_DENIED;
    }
    memset(out_verification, 0, sizeof(*out_verification));
    out_verification->struct_size = sizeof(*out_verification);
    out_verification->version_major = WDC_ADMIN_VERSION_MAJOR;
    out_verification->version_minor = WDC_ADMIN_VERSION_MINOR;
    out_verification->status = WDC_OK;
    out_verification->complete_artifact_valid = 1u;
    out_verification->host_compatible = 1u;
    out_verification->security_floor_valid = 1u;
    out_verification->artifact_authority_valid = 1u;
    return WDC_OK;
}

static int32_t lifecycle_quiesce(
    void *context, uint64_t deadline_ms,
    WdcAdminUpdateQuiesceEvidence *out_evidence)
{
    uint64_t now;
    (void)context;
    if (out_evidence == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    if (s_runtime_loaded) {
        wdc_runtime_teardown(&s_runtime);
        s_runtime_loaded = false;
    }
    now = monotonic_ms();
    if (now >= deadline_ms) {
        return WDC_ERR_TIMEOUT;
    }
    memset(out_evidence, 0, sizeof(*out_evidence));
    out_evidence->guest_quiesced = 1u;
    out_evidence->native_refinements_quiesced = 1u;
    out_evidence->guest_unloaded = 1u;
    out_evidence->native_refinements_unloaded = 1u;
    out_evidence->completed_monotonic_ms = now;
    return WDC_OK;
}

static int32_t lifecycle_heap(
    void *context, WdcControlHeapSnapshot *out_heap)
{
    (void)context;
    if (out_heap == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    *out_heap = heap_snapshot();
    return WDC_OK;
}

static WdcAppSlotVerifyPolicy make_slot_policy(void)
{
    WdcAppSlotVerifyPolicy policy;
    memset(&policy, 0, sizeof(policy));
    s_bundle_policy = wdc_bundle_make_default_dev_policy(wdc_profile_builtin());
    policy.bundle_policy = &s_bundle_policy;
    return policy;
}

static int32_t stage_artifact(WdcBundleMetadataV1 *metadata,
                              WdcBundleSlotId slot,
                              const uint8_t *artifact,
                              uint32_t artifact_bytes,
                              const WdcHostFingerprintV1 *fingerprint)
{
    WdcAppSlotStageSession session;
    WdcAppSlotStageResult result;
    uint32_t offset = 0u;
    int32_t status = wdc_app_slots_stage_begin(&session, metadata, slot,
                                               artifact_bytes);
    while (status == WDC_OK && offset < artifact_bytes) {
        uint32_t remaining = artifact_bytes - offset;
        uint32_t chunk = remaining < 512u ? remaining : 512u;
        status = wdc_app_slots_stage_write(&session, artifact + offset, chunk);
        offset += status == WDC_OK ? chunk : 0u;
    }
    if (status == WDC_OK) {
        status = wdc_app_slots_stage_finish(
            &session, metadata, fingerprint, &s_slot_policy,
            s_update_working, sizeof(s_update_working), &result);
    }
    return status;
}

static WdcActivationResetAttribution reset_attribution(esp_reset_reason_t reason)
{
    switch (reason) {
    case ESP_RST_POWERON: return WDC_ACTIVATION_RESET_POWER_ON;
    case ESP_RST_SW: return WDC_ACTIVATION_RESET_HOST_SOFTWARE;
    case ESP_RST_TASK_WDT:
    case ESP_RST_INT_WDT: return WDC_ACTIVATION_RESET_HOST_WATCHDOG;
    default: return WDC_ACTIVATION_RESET_UNKNOWN;
    }
}

static uint32_t next_boot_sequence(void)
{
    nvs_handle_t handle;
    uint32_t sequence = 0u;
    esp_err_t error = nvs_open(HP55_NVS_NAMESPACE, NVS_READWRITE, &handle);
    if (error != ESP_OK) {
        fatal("nvs-open", (int32_t)error);
    }
    error = nvs_get_u32(handle, HP55_NVS_BOOT_KEY, &sequence);
    if (error != ESP_OK && error != ESP_ERR_NVS_NOT_FOUND) {
        nvs_close(handle);
        fatal("nvs-read-boot-sequence", (int32_t)error);
    }
    sequence += 1u;
    error = nvs_set_u32(handle, HP55_NVS_BOOT_KEY, sequence);
    if (error == ESP_OK) {
        error = nvs_commit(handle);
    }
    nvs_close(handle);
    if (error != ESP_OK) {
        fatal("nvs-write-boot-sequence", (int32_t)error);
    }
    return sequence;
}

static void initialize_baseline(const WdcHostFingerprintV1 *fingerprint,
                                uint32_t boot_sequence)
{
    WdcAppSlotBootResult boot;
    WdcActivationBootContext context;
    WdcControlHeapSnapshot heap = heap_snapshot();
    require_true(s_metadata.active_slot == WDC_BUNDLE_SLOT_NONE &&
                     s_metadata.last_good_slot == WDC_BUNDLE_SLOT_NONE,
                 "fresh-full-flash-erase-required");
    require_status(stage_artifact(&s_metadata, WDC_BUNDLE_SLOT_A,
                                  pulse_hp55_baseline_artifact,
                                  pulse_hp55_baseline_artifact_len,
                                  fingerprint),
                   "baseline-stage");
    require_status(wdc_app_slots_mark_trial(&s_metadata, WDC_BUNDLE_SLOT_A,
                                            &s_activation),
                   "baseline-mark-trial");
    memset(&context, 0, sizeof(context));
    context.reset_attribution = WDC_ACTIVATION_RESET_POWER_ON;
    context.boot_sequence = boot_sequence;
    require_status(wdc_app_slots_boot(
                       &s_metadata, &s_activation, &context, fingerprint,
                       &heap, &s_slot_policy, s_update_working,
                       sizeof(s_update_working), &boot),
                   "baseline-boot");
    require_true(boot.outcome == WDC_APP_SLOT_BOOT_RUN_TRIAL &&
                     boot.selected_slot == WDC_BUNDLE_SLOT_A &&
                     boot.header.application_version == 8u,
                 "baseline-running-trial");
    s_pending_trial_slot = boot.selected_slot;
    s_pending_trial_version = boot.header.application_version;
    checkpoint("target-boot-fingerprint",
               "fresh slot A baseline entered trial under the HP5.5 fingerprint");
}

static void handle_boot_authority(const WdcHostFingerprintV1 *fingerprint,
                                  uint32_t boot_sequence,
                                  esp_reset_reason_t reset_reason)
{
    WdcAppSlotBootResult boot;
    WdcActivationBootContext context;
    WdcControlHeapSnapshot heap = heap_snapshot();
    int32_t status = wdc_ota_read_metadata(&s_metadata);
    if (status != WDC_OK) {
        fatal("metadata-read", status);
    }
    if (s_metadata.active_slot == WDC_BUNDLE_SLOT_NONE &&
        s_metadata.last_good_slot == WDC_BUNDLE_SLOT_NONE) {
        initialize_baseline(fingerprint, boot_sequence);
        return;
    }
    memset(&context, 0, sizeof(context));
    context.reset_attribution = reset_attribution(reset_reason);
    context.boot_sequence = boot_sequence;
    status = wdc_app_slots_boot(&s_metadata, &s_activation, &context,
                                fingerprint, &heap, &s_slot_policy,
                                s_update_working, sizeof(s_update_working),
                                &boot);
    if (status != WDC_OK && boot.outcome != WDC_APP_SLOT_BOOT_RECOVERY) {
        fatal("boot-authority", status);
    }
    if (boot.outcome == WDC_APP_SLOT_BOOT_FALLBACK_REBOOT_REQUIRED) {
        checkpoint("stale-trial-fallback",
                   "unconfirmed version 10 trial fell back to last confirmed");
        vTaskDelay(pdMS_TO_TICKS(HP55_RESTART_DELAY_MS));
        esp_restart();
        fatal("fallback-restart-returned", WDC_ERR_IO);
    }
    if (boot.outcome == WDC_APP_SLOT_BOOT_RECOVERY) {
        fatal("unexpected-no-viable-durable-state", status);
    }
    if (boot.outcome == WDC_APP_SLOT_BOOT_RUN_TRIAL) {
        checkpoint("durable-trial-reboot-handoff",
                   "pending artifact became a durable running trial on reboot");
        if (boot.header.application_version == 10u) {
            vTaskDelay(pdMS_TO_TICKS(HP55_RESTART_DELAY_MS));
            esp_restart();
            fatal("stale-trial-restart-returned", WDC_ERR_IO);
        }
        if (boot.header.application_version == 9u) {
            s_pending_trial_slot = boot.selected_slot;
            s_pending_trial_version = boot.header.application_version;
        }
    }
}

static void emit_board(const WdcHostFingerprintV1 *fingerprint)
{
    esp_chip_info_t chip;
    uint32_t flash_bytes = 0u;
    uint32_t psram_bytes = 0u;
    uint8_t mac[6];
    uint8_t uid_input[16] = {'p','u','l','s','e','-','h','p','5','5'};
    uint8_t uid_sha[32];
    esp_chip_info(&chip);
    require_true(esp_flash_get_physical_size(NULL, &flash_bytes) == ESP_OK,
                 "physical-flash-query");
#if CONFIG_IDF_TARGET_ESP32S3
    psram_bytes = (uint32_t)esp_psram_get_size();
    require_true(chip.model == CHIP_ESP32S3, "physical-chip-s3");
#else
    require_true(chip.model == CHIP_ESP32C6, "physical-chip-c6");
#endif
    require_true(flash_bytes == HP55_FLASH_BYTES &&
                     psram_bytes == HP55_PSRAM_BYTES,
                 "named-board-memory-identity");
    require_true(esp_efuse_mac_get_default(mac) == ESP_OK,
                 "physical-board-mac");
    memcpy(uid_input + 10u, mac, sizeof(mac));
    wdc_sha256(uid_input, sizeof(uid_input), uid_sha);
    hex32(uid_sha, s_uid_sha256);
    (void)printf(
        "PULSE_HP55_BOOT {\"schema\":\"pulse.esp32.hp5_5-boot.v1\","
        "\"campaign_id\":\"%s\",\"campaign_sha256\":\"%s\","
        "\"board_id\":\"%s\",\"target\":\"%s\","
        "\"flash_bytes\":%u,\"psram_bytes\":%u,"
        "\"physical_board_uid_sha256\":\"%s\","
        "\"plan_sha256\":\"%s\",\"lock_sha256\":\"%s\","
        "\"fingerprint_sha256\":\"%s\","
        "\"fingerprint_target\":%u}\n",
        HP55_CAMPAIGN_ID, HP55_CAMPAIGN_SHA256, HP55_BOARD_ID,
        HP55_TARGET, flash_bytes, psram_bytes, s_uid_sha256,
        HP55_PLAN_SHA256, HP55_LOCK_SHA256, HP55_FINGERPRINT_SHA256,
        (unsigned)fingerprint->target);
    (void)fflush(stdout);
}

static WdcAdminRecoveryConfig recovery_config(
    WdcAdminCore *core, WdcBundleMetadataV1 *metadata,
    const WdcHostFingerprintV1 *fingerprint)
{
    WdcAdminRecoveryConfig config;
    memset(&config, 0, sizeof(config));
    config.update.core = core;
    config.update.metadata = metadata;
    config.update.running_host_fingerprint = fingerprint;
    config.update.slot_verify_policy = &s_slot_policy;
    config.update.activation_policy = &s_activation;
    config.update.lifecycle.quiesce_and_unload = lifecycle_quiesce;
    config.update.lifecycle.heap_snapshot_after_unload = lifecycle_heap;
    config.update.working_buffer = s_update_working;
    config.update.working_buffer_bytes = sizeof(s_update_working);
    return config;
}

static void no_viable_recovery_self_test(
    const WdcControlResourceProfile *profile,
    const WdcHostFingerprintV1 *fingerprint)
{
    WdcBundleMetadataV1 metadata;
    WdcAdminCoreConfig core_config;
    WdcAdminRecoveryConfig config;
    WdcAppSlotBootResult boot;
    require_status(wdc_control_kernel_init(&s_kernel, profile),
                   "no-viable-kernel");
    memset(&core_config, 0, sizeof(core_config));
    core_config.control_kernel = &s_kernel;
    core_config.authorizer.authorize = admin_authorize;
    core_config.artifact_verifier.verify = artifact_authorize;
    core_config.initial_mode = WDC_ADMIN_MODE_RECOVERY;
    core_config.enabled_commands_mask = WDC_ADMIN_HP43_COMMAND_MASK;
    memcpy(core_config.boot_channel_binding_sha256,
           pulse_hp55_channel_binding_sha256, 32u);
    require_status(wdc_admin_core_init(&s_admin, &core_config),
                   "no-viable-admin-core");
    wdc_bundle_metadata_init(&metadata);
    memset(&boot, 0, sizeof(boot));
    boot.status = WDC_ERR_NOT_AVAILABLE;
    boot.outcome = WDC_APP_SLOT_BOOT_RECOVERY;
    boot.selected_slot = WDC_BUNDLE_SLOT_NONE;
    boot.fallback_slot = WDC_BUNDLE_SLOT_NONE;
    boot.recovery = true;
    config = recovery_config(&s_admin, &metadata, fingerprint);
    config.boot_result = &boot;
    require_status(wdc_admin_recovery_init(&s_recovery, &config,
                                           monotonic_ms()),
                   "no-viable-recovery-init");
    require_true(wdc_admin_recovery_reason(&s_recovery) ==
                     WDC_ADMIN_RECOVERY_REASON_NO_VIABLE_APPLICATION,
                 "no-viable-recovery-reason");
    checkpoint("no-viable-slot-administration",
               "physical target initialized the host-only no-viable recovery lane");
}

static const char *command_name(uint32_t command)
{
    switch ((WdcAdminCommand)command) {
    case WDC_ADMIN_COMMAND_STATUS: return "STATUS";
    case WDC_ADMIN_COMMAND_BEGIN_UPDATE: return "BEGIN_UPDATE";
    case WDC_ADMIN_COMMAND_WRITE_CHUNK: return "WRITE_CHUNK";
    case WDC_ADMIN_COMMAND_FINISH_UPDATE: return "FINISH_UPDATE";
    case WDC_ADMIN_COMMAND_ABORT: return "ABORT";
    case WDC_ADMIN_COMMAND_ENTER_RECOVERY: return "ENTER_RECOVERY";
    case WDC_ADMIN_COMMAND_ACTIVATE_TRIAL: return "ACTIVATE_TRIAL";
    case WDC_ADMIN_COMMAND_REBOOT: return "REBOOT";
    default: return "UNKNOWN";
    }
}

static void initialize_normal_recovery(void)
{
    WdcAdminRecoveryConfig recovery;
    require_true(s_running_fingerprint != NULL,
                 "normal-recovery-fingerprint");
    recovery = recovery_config(&s_admin, &s_metadata,
                               s_running_fingerprint);
    recovery.application_loaded = 1u;
    require_status(wdc_admin_recovery_init(&s_recovery, &recovery,
                                           monotonic_ms()),
                   "admin-recovery-init");
    s_recovery_initialized = true;
}

static void confirm_pending_trial(void)
{
    WdcActivationProbationEvidence evidence;
    WdcActivationDecision decision;
    WdcControlHeapSnapshot heap = heap_snapshot();
    WdcHttpPlatformStatus platform;
    uint64_t now = monotonic_ms();
    wdc_http_platform_get_status(&platform);
    memset(&evidence, 0, sizeof(evidence));
    evidence.elapsed_ms = now >= s_trial_runtime_started_ms &&
            now - s_trial_runtime_started_ms <= UINT32_MAX
        ? (uint32_t)(now - s_trial_runtime_started_ms)
        : UINT32_MAX;
    require_status(wdc_runtime_call_health(&s_runtime),
                   "trial-runtime-health");
    evidence.observed_health_checks = 1u;
    evidence.readiness_observed = s_runtime_loaded &&
        platform.wifi_connected && platform.app_listener_started &&
        platform.admin_listener_started;
    evidence.administration_responsive = true;
    evidence.resource_floors_preserved =
        heap.internal_free_bytes >= HP55_MIN_INTERNAL_FREE_BYTES &&
        heap.internal_largest_block_bytes >=
            HP55_MIN_INTERNAL_LARGEST_BYTES;
#if CONFIG_IDF_TARGET_ESP32S3
    evidence.resource_floors_preserved =
        evidence.resource_floors_preserved &&
        heap.psram_free_bytes >= HP55_MIN_PSRAM_FREE_BYTES;
#endif
    memset(&decision, 0, sizeof(decision));
    require_status(wdc_app_slots_evaluate_probation(
                       &s_metadata, s_pending_trial_slot,
                       &s_activation, &evidence, &decision),
                   "physical-trial-confirm");
    require_true(
        decision.kind == WDC_ACTIVATION_DECISION_RUN_CONFIRMED &&
            decision.metadata_changed && !decision.rollback &&
            s_metadata.active_slot == s_pending_trial_slot &&
            s_metadata.last_good_slot == s_pending_trial_slot,
        "physical-trial-confirmed-authority");
    if (s_pending_trial_version == 9u) {
        checkpoint("trial-confirmed",
                   "version 9 passed real runtime, network, admin, resource, and time probation");
    } else {
        require_true(s_pending_trial_version == 8u,
                     "baseline-trial-version");
        checkpoint("target-boot-fingerprint",
                   "version 8 baseline passed real physical probation");
    }
    s_pending_trial_slot = WDC_BUNDLE_SLOT_NONE;
    s_pending_trial_version = 0u;
    initialize_normal_recovery();
}

static void admin_task(void *argument)
{
    (void)argument;
    for (;;) {
        WdcControlWorkItem work;
        WdcAdminAcceptedCommand accepted;
        memset(&accepted, 0, sizeof(accepted));
        int32_t status = wdc_control_next(&s_kernel, &work);
        if (status != WDC_OK) {
            if (s_recovery_initialized) {
                (void)wdc_admin_recovery_poll(&s_recovery, monotonic_ms());
            }
            vTaskDelay(pdMS_TO_TICKS(10u));
            continue;
        }
        status = wdc_admin_begin_command(&s_admin, &work, monotonic_ms(),
                                         &accepted);
        if (status == WDC_OK &&
            s_pending_trial_slot != WDC_BUNDLE_SLOT_NONE) {
            require_true(
                accepted.request.command == WDC_ADMIN_COMMAND_STATUS,
                "only-status-admitted-during-trial");
            confirm_pending_trial();
        }
        if (status == WDC_OK) {
            require_true(s_recovery_initialized,
                         "recovery-initialized-before-execute");
            if (accepted.request.command == WDC_ADMIN_COMMAND_STATUS) {
                vTaskDelay(pdMS_TO_TICKS(HP55_STATUS_COMPLETION_DELAY_MS));
            }
            status = wdc_admin_recovery_execute(&s_recovery, &accepted,
                                                monotonic_ms());
        }
        (void)printf(
            "PULSE_HP55_ADMIN {\"schema\":\"pulse.esp32.hp5_5-admin.v1\","
            "\"command\":\"%s\",\"request_id\":%" PRIu64 ","
            "\"status\":%" PRId32 ",\"mode\":%u,\"active_slot\":%u,"
            "\"last_good_slot\":%u}\n",
            command_name(accepted.request.command), accepted.request.request_id,
            status, (unsigned)wdc_admin_mode(&s_admin),
            (unsigned)s_metadata.active_slot,
            (unsigned)s_metadata.last_good_slot);
        (void)fflush(stdout);
        if (status == WDC_OK &&
            accepted.request.command == WDC_ADMIN_COMMAND_ABORT) {
            checkpoint("update-abort-preserves-confirmed",
                       "explicit abort returned without changing last confirmed");
        }
        if (status == WDC_OK &&
            accepted.request.command == WDC_ADMIN_COMMAND_FINISH_UPDATE) {
            checkpoint("update-quiesce-stage-verify",
                       "exclusive inactive-slot stream reached verified state");
        }
        if (status == WDC_OK &&
            accepted.request.command == WDC_ADMIN_COMMAND_ENTER_RECOVERY) {
            checkpoint("administrative-recovery",
                       "authenticated command entered host-only recovery");
        }
        if (status == WDC_OK &&
            (accepted.request.command == WDC_ADMIN_COMMAND_ACTIVATE_TRIAL ||
             accepted.request.command == WDC_ADMIN_COMMAND_REBOOT)) {
            emit_stats();
            vTaskDelay(pdMS_TO_TICKS(HP55_RESTART_DELAY_MS));
            esp_restart();
            fatal("admin-restart-returned", WDC_ERR_IO);
        }
    }
}

static void stats_task(void *argument)
{
    (void)argument;
    for (;;) {
        vTaskDelay(pdMS_TO_TICKS(5000u));
        emit_stats();
    }
}

static void start_runtime(void)
{
    WdcRuntimeConfig config = wdc_runtime_default_config();
    require_status(wdc_runtime_init(&s_runtime, &config), "wamr-init");
    require_status(wdc_runtime_load_static(&s_runtime, pulse_hp55_wasm,
                                           pulse_hp55_wasm_len),
                   "wamr-load");
    require_status(wdc_runtime_lookup_exports(&s_runtime), "wamr-exports");
    require_status(wdc_runtime_call_init(&s_runtime), "wamr-module-init");
    s_runtime_loaded = true;
    if (s_pending_trial_slot != WDC_BUNDLE_SLOT_NONE) {
        s_trial_runtime_started_ms = monotonic_ms();
    }
}

static void wifi_reconnect_self_test(void)
{
    uint64_t started = monotonic_ms();
    uint64_t deadline = started + WDC_HTTP_PLATFORM_CONNECT_TIMEOUT_MS;
    require_true(esp_wifi_disconnect() == ESP_OK,
                 "forced-wifi-disconnect");
    while (monotonic_ms() < deadline) {
        WdcNetState state = wdc_net_get_state();
        if (state == WDC_NET_STATE_DISCONNECTED) {
            s_wifi_disconnect_observed = true;
        }
        if (s_wifi_disconnect_observed && state == WDC_NET_STATE_CONNECTED) {
            uint64_t elapsed = monotonic_ms() - started;
            s_wifi_reconnect_elapsed_ms =
                elapsed <= UINT32_MAX ? (uint32_t)elapsed : UINT32_MAX;
            s_wifi_reconnect_observed = true;
            break;
        }
        vTaskDelay(pdMS_TO_TICKS(10u));
    }
    require_true(s_wifi_disconnect_observed && s_wifi_reconnect_observed &&
                     s_wifi_reconnect_elapsed_ms <=
                         WDC_HTTP_PLATFORM_CONNECT_TIMEOUT_MS,
                 "bounded-wifi-reconnect");
    checkpoint("bounded-wifi-reconnect",
               "forced station loss returned to connected within the fixed bound");
}

static void initialize_service(const WdcControlResourceProfile *profile,
                               const WdcHostFingerprintV1 *fingerprint)
{
    WdcAdminCoreConfig core_config;
    WdcHttpServiceConfig service;
    WdcHttpPlatformConfig platform;
    require_status(wdc_control_kernel_init(&s_kernel, profile),
                   "control-kernel-init");
    memset(&core_config, 0, sizeof(core_config));
    core_config.control_kernel = &s_kernel;
    core_config.authorizer.authorize = admin_authorize;
    core_config.artifact_verifier.verify = artifact_authorize;
    core_config.initial_mode = WDC_ADMIN_MODE_NORMAL;
    core_config.enabled_commands_mask = WDC_ADMIN_HP43_COMMAND_MASK;
    memcpy(core_config.boot_channel_binding_sha256,
           pulse_hp55_channel_binding_sha256, 32u);
    require_status(wdc_admin_core_init(&s_admin, &core_config),
                   "admin-core-init");
    s_running_fingerprint = fingerprint;
    s_recovery_initialized = false;
    if (s_pending_trial_slot == WDC_BUNDLE_SLOT_NONE) {
        initialize_normal_recovery();
    }
    require_status(wdc_net_init(wdc_profile_builtin()), "network-init");
    require_status(wdc_caps_install_host_authorizer(
                       wdc_profile_builtin(), wdc_caps_builtin_relay_full()),
                   "capability-authorizer");
    wdc_host_call_set_authorizer(allow_http, NULL);
    start_runtime();
    memset(&service, 0, sizeof(service));
    service.admin_core = &s_admin;
    service.app_dispatch = app_dispatch;
    service.clock = http_clock;
    require_status(wdc_http_service_init(&s_http, &service),
                   "http-service-init");
    require_status(wdc_http_service_register_app_route(
                       &s_http, WDC_HTTP_METHOD_POST,
                       "/pulse/v1/app/echo", WDC_R8_RESOURCE_HTTP_API),
                   "register-echo");
    require_status(wdc_http_service_register_app_route(
                       &s_http, WDC_HTTP_METHOD_GET,
                       "/pulse/v1/app/empty", WDC_R8_RESOURCE_HTTP_API),
                   "register-empty");
    require_status(wdc_http_service_register_app_route(
                       &s_http, WDC_HTTP_METHOD_GET,
                       "/pulse/v1/app/trap", WDC_R8_RESOURCE_HTTP_API),
                   "register-trap");
    require_status(wdc_http_service_register_app_route(
                       &s_http, WDC_HTTP_METHOD_POST,
                       "/pulse/v1/app/control", WDC_R8_RESOURCE_HTTP_API),
                   "register-control");
    require_status(wdc_http_service_start(&s_http), "http-service-start");
    memset(&platform, 0, sizeof(platform));
    platform.service = &s_http;
    platform.wifi_ssid = pulse_hp55_wifi_ssid;
    platform.wifi_password = pulse_hp55_wifi_password;
    platform.server_certificate_pem = pulse_hp55_server_certificate;
    platform.server_certificate_bytes = pulse_hp55_server_certificate_len;
    platform.server_private_key_pem = pulse_hp55_server_private_key;
    platform.server_private_key_bytes = pulse_hp55_server_private_key_len;
    memcpy(platform.boot_channel_binding_sha256,
           pulse_hp55_channel_binding_sha256, 32u);
    platform.app_port = 443u;
    platform.admin_port = 8443u;
    platform.connect_timeout_ms = WDC_HTTP_PLATFORM_CONNECT_TIMEOUT_MS;
    platform.reconnect_attempts = WDC_HTTP_PLATFORM_MAX_RECONNECT_ATTEMPTS;
    require_status(wdc_http_platform_start(&platform), "wifi-tls-start");
    checkpoint("station-associated",
               "station acquired an address before both HTTPS listeners started");
    wifi_reconnect_self_test();
    require_true(xTaskCreate(admin_task, "hp55-admin", HP55_ADMIN_TASK_STACK_BYTES,
                             NULL, 12u, NULL) == pdPASS,
                 "admin-task-create");
    require_true(xTaskCreate(stats_task, "hp55-stats", HP55_STATS_TASK_STACK_BYTES,
                             NULL, 3u, NULL) == pdPASS,
                 "stats-task-create");
    checkpoint("resource-floors-under-pressure",
               "physical heap sampling active for the complete network run");
}

static void *driver(void *argument)
{
    const WdcControlResourceProfile *profile;
    const WdcHostFingerprintV1 *fingerprint;
    uint32_t boot_sequence;
    esp_reset_reason_t reason = esp_reset_reason();
    esp_err_t error;
    (void)argument;
    vTaskDelay(pdMS_TO_TICKS(1000u));
    error = nvs_flash_init();
    if (error != ESP_OK) {
        fatal("nvs-flash-init", (int32_t)error);
    }
    boot_sequence = next_boot_sequence();
    fingerprint = wdc_host_running_fingerprint();
    require_true(fingerprint != NULL, "running-fingerprint-present");
    require_status(wdc_host_fingerprint_validate(fingerprint),
                   "running-fingerprint-valid");
#if CONFIG_IDF_TARGET_ESP32S3
    profile = wdc_control_profile_s3_psram();
#else
    profile = wdc_control_profile_c6_minimum();
#endif
    emit_board(fingerprint);
    s_slot_policy = make_slot_policy();
    s_activation = wdc_activation_default_policy();
    handle_boot_authority(fingerprint, boot_sequence, reason);
    require_true(
        (s_pending_trial_slot != WDC_BUNDLE_SLOT_NONE &&
         s_metadata.active_slot == s_pending_trial_slot) ||
            (s_pending_trial_slot == WDC_BUNDLE_SLOT_NONE &&
             s_metadata.active_slot == s_metadata.last_good_slot),
        "boot-authority-before-admin");
    no_viable_recovery_self_test(profile, fingerprint);
    initialize_service(profile, fingerprint);
    idle_forever();
    return NULL;
}

static void pthread_failure(const char *operation, int status)
{
    (void)printf(
        "PULSE_HP55_FATAL {\"schema\":\"pulse.esp32.hp5_5-fatal.v1\","
        "\"step\":\"pthread-%s\",\"status\":%d}\n",
        operation, status);
    (void)fflush(stdout);
    idle_forever();
}

void app_main(void)
{
    pthread_attr_t attributes;
    pthread_t thread;
    int status = pthread_attr_init(&attributes);
    if (status != 0) {
        pthread_failure("attribute-init", status);
    }
    status = pthread_attr_setdetachstate(&attributes, PTHREAD_CREATE_JOINABLE);
    if (status == 0) {
        status = pthread_attr_setstacksize(&attributes,
                                           HP55_DRIVER_STACK_BYTES);
    }
    if (status == 0) {
        status = pthread_create(&thread, &attributes, driver, NULL);
    }
    (void)pthread_attr_destroy(&attributes);
    if (status != 0) {
        pthread_failure("create", status);
    }
    status = pthread_join(thread, NULL);
    if (status != 0) {
        pthread_failure("join", status);
    }
}
