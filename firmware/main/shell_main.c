#include "shell_config.h"

#include <inttypes.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>

#include "wdc_abi.h"
#include "wdc_activation.h"
#include "wdc_app.h"
#include "wdc_bundle.h"
#include "wdc_caps.h"
#include "wdc_diag.h"
#include "wdc_events.h"
#include "wdc_gpio.h"
#include "wdc_profile.h"
#include "wdc_runtime.h"
#include "wdc_net.h"
#include "wdc_ota.h"
#include "wdc_safety.h"
#include "wdc_security.h"
#include "wdc_static_wasm.h"

/* R4 compatibility note: wdc_caps_install_host_authorizer remains available; R5 wraps it with wdc_safety_install_guarded_authorizer. */

#ifdef ESP_PLATFORM
#include "esp_err.h"
#include "esp_log.h"
#include "esp_ota_ops.h"
#include "esp_partition.h"
#include "esp_system.h"
#include "nvs_flash.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#endif

#ifdef ESP_PLATFORM
static const char *TAG = "wdc_shell";
#endif


#if defined(__GNUC__)
#define WDC_UNUSED_FN __attribute__((unused))
#else
#define WDC_UNUSED_FN
#endif

static WdcRuntimeReport s_r5_runtime_report;
static uint8_t s_r8_bundle_buffer[WDC_R8_BUNDLE_BUFFER_BYTES];

static void wdc_shell_diag(int32_t level, const char *message)
{
    (void)wdc_diag_log(level, message);
}

static void wdc_shell_log_last_audit(const char *label)
{
    WdcCapabilityAuditRecord audit;
    memset(&audit, 0, sizeof(audit));
    wdc_caps_last_audit(&audit);
    char msg[512];
    (void)snprintf(msg,
                   sizeof(msg),
                   "%s bundle=%s opcode=%s resource=%s(%lu) capability=%s decision=%s result=%s",
                   label != NULL ? label : "audit",
                   audit.bundle[0] != '\0' ? audit.bundle : "<none>",
                   audit.opcode_name[0] != '\0' ? audit.opcode_name : wdc_opcode_name(audit.opcode),
                   audit.resource_name[0] != '\0' ? audit.resource_name : "<none>",
                   (unsigned long)audit.resource_id,
                   audit.capability[0] != '\0' ? audit.capability : "<none>",
                   audit.decision[0] != '\0' ? audit.decision : "unknown",
                   wdc_status_name(audit.result));
    wdc_shell_diag(audit.result == WDC_OK ? WDC_LOG_INFO : WDC_LOG_WARN, msg);
}

#ifdef ESP_PLATFORM
static void wdc_shell_log_partition(const char *role, const esp_partition_t *partition)
{
    if (partition == NULL) {
        ESP_LOGW(TAG, "%s partition: not found", role);
        return;
    }

    ESP_LOGI(TAG,
             "%s partition: label=%s type=0x%02x subtype=0x%02x offset=0x%08" PRIx32 " size=0x%08" PRIx32,
             role,
             partition->label,
             (unsigned)partition->type,
             (unsigned)partition->subtype,
             (uint32_t)partition->address,
             (uint32_t)partition->size);
}

static void wdc_shell_print_partition_info(void)
{
    wdc_shell_log_partition("running", esp_ota_get_running_partition());
    wdc_shell_log_partition("boot", esp_ota_get_boot_partition());
    wdc_shell_log_partition("wasm_a", esp_partition_find_first((esp_partition_type_t)0x40, (esp_partition_subtype_t)0x00, "wasm_a"));
    wdc_shell_log_partition("wasm_b", esp_partition_find_first((esp_partition_type_t)0x40, (esp_partition_subtype_t)0x01, "wasm_b"));
    wdc_shell_log_partition("wasm_meta", esp_partition_find_first((esp_partition_type_t)0x40, (esp_partition_subtype_t)0x02, "wasm_meta"));
}

static int32_t wdc_shell_init_metadata_storage(void)
{
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_LOGW(TAG, "NVS init requested erase: %s", esp_err_to_name(err));
        err = nvs_flash_erase();
        if (err != ESP_OK) {
            ESP_LOGE(TAG, "NVS erase failed: %s", esp_err_to_name(err));
            return WDC_ERR_IO;
        }
        err = nvs_flash_init();
    }

    if (err != ESP_OK) {
        ESP_LOGE(TAG, "NVS init failed: %s", esp_err_to_name(err));
        return WDC_ERR_IO;
    }

    ESP_LOGI(TAG, "metadata storage initialized: nvs");
    return WDC_OK;
}
#else
static void wdc_shell_print_partition_info(void)
{
    wdc_shell_diag(WDC_LOG_INFO, "partition info unavailable on host build");
}

static int32_t wdc_shell_init_metadata_storage(void)
{
    wdc_shell_diag(WDC_LOG_INFO, "metadata storage initialized: host stub");
    return WDC_OK;
}
#endif

static int32_t wdc_shell_run_internal_event_self_test(void)
{
    WdcEvent event;
    int32_t status = wdc_event_make(&event, WDC_EVENT_SYSTEM_BOOT, WDC_EVENT_RESOURCE_NONE, 0u, NULL, 0u);
    if (status != WDC_OK) {
        return status;
    }

    status = wdc_events_post(&event);
    if (status != WDC_OK) {
        return status;
    }

    WdcEvent out = {0};
    status = wdc_events_next(&out);
    if (status != WDC_OK) {
        return status;
    }
    if (out.event_type != WDC_EVENT_SYSTEM_BOOT || out.event_id == 0u) {
        return WDC_ERR_BAD_ENCODING;
    }

    uint8_t encoded[128];
    uint32_t encoded_len = 0u;
    status = wdc_event_encode_cbor(&out, encoded, sizeof(encoded), &encoded_len);
    if (status != WDC_OK || encoded_len == 0u) {
        return status == WDC_OK ? WDC_ERR_BAD_ENCODING : status;
    }
    return WDC_OK;
}

static int32_t response_status_value(const uint8_t *rsp, uint32_t rsp_len)
{
    int32_t status = WDC_ERR_UNKNOWN;
    int32_t decode = wdc_cbor_map_find_i32(rsp, rsp_len, WDC_CBOR_KEY_STATUS, &status);
    return decode == WDC_OK ? status : decode;
}

static int32_t WDC_UNUSED_FN wdc_shell_run_r4_capability_self_test(void)
{
    uint8_t req[64];
    uint8_t rsp[64];
    uint32_t rsp_len = 0u;
    WdcCborBuilder b;

    wdc_cbor_builder_init(&b, req, sizeof(req));
    int32_t status = wdc_cbor_begin_map(&b, 2u);
    if (status == WDC_OK) { status = wdc_cbor_put_key_u32(&b, WDC_CBOR_KEY_RESOURCE_ID, WDC_R4_RESOURCE_RELAY_1); }
    if (status == WDC_OK) { status = wdc_cbor_put_key_bool(&b, WDC_CBOR_KEY_VALUE, true); }
    if (status != WDC_OK) { return status; }
    status = wdc_host_call_dispatch(WDC_OP_GPIO_SET, req, wdc_cbor_len(&b), rsp, sizeof(rsp), &rsp_len);
    if (status != WDC_OK) { return status; }
    if (response_status_value(rsp, rsp_len) != WDC_OK) { return WDC_ERR_CONTRACT_VIOLATION; }
    wdc_shell_log_last_audit("capability allow");

    wdc_cbor_builder_init(&b, req, sizeof(req));
    status = wdc_cbor_begin_map(&b, 2u);
    if (status == WDC_OK) { status = wdc_cbor_put_key_u32(&b, WDC_CBOR_KEY_RESOURCE_ID, WDC_R4_RESOURCE_STATUS_LED); }
    if (status == WDC_OK) { status = wdc_cbor_put_key_bool(&b, WDC_CBOR_KEY_VALUE, false); }
    if (status != WDC_OK) { return status; }
    status = wdc_host_call_dispatch(WDC_OP_GPIO_SET, req, wdc_cbor_len(&b), rsp, sizeof(rsp), &rsp_len);
    if (status != WDC_OK) { return status; }
    if (response_status_value(rsp, rsp_len) != WDC_ERR_CAPABILITY_DENIED) { return WDC_ERR_CONTRACT_VIOLATION; }
    wdc_shell_log_last_audit("capability deny");
    return WDC_OK;
}


static uint32_t gpio_set_req(uint8_t *req, uint32_t cap, uint32_t resource_id, bool value)
{
    WdcCborBuilder b;
    wdc_cbor_builder_init(&b, req, cap);
    int32_t status = wdc_cbor_begin_map(&b, 2u);
    if (status == WDC_OK) { status = wdc_cbor_put_key_u32(&b, WDC_CBOR_KEY_RESOURCE_ID, resource_id); }
    if (status == WDC_OK) { status = wdc_cbor_put_key_bool(&b, WDC_CBOR_KEY_VALUE, value); }
    return status == WDC_OK ? wdc_cbor_len(&b) : 0u;
}

static int32_t WDC_UNUSED_FN wdc_shell_run_r5_safety_self_test(const WdcDeviceProfile *profile)
{
    if (profile == NULL) {
        return WDC_ERR_BAD_POINTER;
    }

    int32_t status = wdc_safety_force_safe_outputs("R5 self-test baseline");
    if (status != WDC_OK) {
        return status;
    }

    uint32_t level = 0u;
    status = wdc_hal_gpio_get_level_by_resource(profile, WDC_R4_RESOURCE_RELAY_1, &level);
    if (status != WDC_OK || level != 0u || !wdc_safety_physical_outputs_safe()) {
        return status == WDC_OK ? WDC_ERR_CONTRACT_VIOLATION : status;
    }

    uint8_t req[64];
    uint8_t rsp[64];
    uint32_t rsp_len = 0u;
    uint32_t req_len = gpio_set_req(req, sizeof(req), WDC_R4_RESOURCE_RELAY_1, true);
    if (req_len == 0u) {
        return WDC_ERR_BAD_ENCODING;
    }
    status = wdc_host_call_dispatch(WDC_OP_GPIO_SET, req, req_len, rsp, sizeof(rsp), &rsp_len);
    if (status != WDC_OK) {
        return status;
    }
    if (response_status_value(rsp, rsp_len) != WDC_OK) {
        return WDC_ERR_CONTRACT_VIOLATION;
    }
    status = wdc_hal_gpio_get_level_by_resource(profile, WDC_R4_RESOURCE_RELAY_1, &level);
    if (status != WDC_OK || level != 1u) {
        return status == WDC_OK ? WDC_ERR_CONTRACT_VIOLATION : status;
    }

    status = wdc_safety_stop_app(WDC_SAFETY_FAULT_MANUAL, WDC_ERR_CONTRACT_VIOLATION, "R5 self-test simulated app fault", NULL);
    if (status != WDC_OK) {
        return status;
    }
    status = wdc_hal_gpio_get_level_by_resource(profile, WDC_R4_RESOURCE_RELAY_1, &level);
    if (status != WDC_OK || level != 0u || !wdc_safety_physical_outputs_safe()) {
        return status == WDC_OK ? WDC_ERR_CONTRACT_VIOLATION : status;
    }

    rsp_len = 0u;
    status = wdc_host_call_dispatch(WDC_OP_GPIO_SET, req, req_len, rsp, sizeof(rsp), &rsp_len);
    if (status != WDC_OK) {
        return status;
    }
    if (response_status_value(rsp, rsp_len) != WDC_ERR_INVALID_STATE) {
        return WDC_ERR_CONTRACT_VIOLATION;
    }
    status = wdc_hal_gpio_get_level_by_resource(profile, WDC_R4_RESOURCE_RELAY_1, &level);
    if (status != WDC_OK || level != 0u) {
        return status == WDC_OK ? WDC_ERR_CONTRACT_VIOLATION : status;
    }

    return wdc_safety_mark_app_running("com.example.r5-static-smoke", 5u);
}





static void seed_slot_record(WdcBundleSlotRecord *record, WdcSlotState state, uint32_t version, uint64_t counter, uint8_t fill)
{
    if (record == NULL) {
        return;
    }
    memset(record, 0, sizeof(*record));
    record->state = state;
    record->bundle_version = version;
    record->security_counter = counter;
    memset(record->payload_sha256, fill, WDC_BUNDLE_SHA256_BYTES);
}

static int32_t WDC_UNUSED_FN wdc_shell_run_r7_activation_self_test(void)
{
    WdcBundleMetadataV1 metadata;
    wdc_bundle_metadata_init(&metadata);

    seed_slot_record(&metadata.slot_a, WDC_SLOT_CONFIRMED, 6u, 6u, 0xa6u);
    seed_slot_record(&metadata.slot_b, WDC_SLOT_VERIFIED, 7u, 7u, 0xb7u);
    metadata.active_slot = WDC_BUNDLE_SLOT_A;
    metadata.last_good_slot = WDC_BUNDLE_SLOT_A;
    int32_t status = wdc_bundle_metadata_seal(&metadata);
    if (status != WDC_OK) {
        return status;
    }

    WdcActivationPolicy policy = wdc_activation_default_policy();
    policy.max_candidate_boots = WDC_R7_MAX_CANDIDATE_BOOTS;
    policy.required_health_checks = WDC_R7_PROBATION_HEALTH_CHECKS;

    WdcActivationDecision decision;
    status = wdc_activation_on_boot(&metadata, &policy, &decision);
    if (status != WDC_OK || decision.kind != WDC_ACTIVATION_DECISION_RUN_CONFIRMED || decision.slot_to_run != WDC_BUNDLE_SLOT_A) {
        return status == WDC_OK ? WDC_ERR_CONTRACT_VIOLATION : status;
    }

    status = wdc_activation_prepare_pending(&metadata, WDC_BUNDLE_SLOT_B, &policy);
    if (status != WDC_OK || metadata.active_slot != WDC_BUNDLE_SLOT_B || metadata.slot_b.state != WDC_SLOT_PENDING) {
        return status == WDC_OK ? WDC_ERR_CONTRACT_VIOLATION : status;
    }

    status = wdc_activation_on_boot(&metadata, &policy, &decision);
    if (status != WDC_OK || decision.kind != WDC_ACTIVATION_DECISION_RUN_CANDIDATE ||
        decision.slot_to_run != WDC_BUNDLE_SLOT_B || !decision.probation || metadata.slot_b.state != WDC_SLOT_RUNNING_PENDING) {
        return status == WDC_OK ? WDC_ERR_CONTRACT_VIOLATION : status;
    }

    /* Simulate reset/power loss before confirmation. The next boot must fail B and roll back to A. */
    status = wdc_activation_on_boot(&metadata, &policy, &decision);
    if (status != WDC_OK || decision.kind != WDC_ACTIVATION_DECISION_ROLLBACK_TO_LAST_GOOD ||
        decision.slot_to_run != WDC_BUNDLE_SLOT_A || decision.candidate_slot != WDC_BUNDLE_SLOT_B ||
        metadata.active_slot != WDC_BUNDLE_SLOT_A || metadata.slot_b.state != WDC_SLOT_FAILED) {
        return status == WDC_OK ? WDC_ERR_CONTRACT_VIOLATION : status;
    }

    seed_slot_record(&metadata.slot_b, WDC_SLOT_VERIFIED, 8u, 8u, 0xb8u);
    status = wdc_bundle_metadata_seal(&metadata);
    if (status == WDC_OK) { status = wdc_activation_prepare_pending(&metadata, WDC_BUNDLE_SLOT_B, &policy); }
    if (status == WDC_OK) { status = wdc_activation_on_boot(&metadata, &policy, &decision); }
    if (status != WDC_OK || decision.kind != WDC_ACTIVATION_DECISION_RUN_CANDIDATE) {
        return status == WDC_OK ? WDC_ERR_CONTRACT_VIOLATION : status;
    }
    status = wdc_activation_confirm(&metadata, WDC_BUNDLE_SLOT_B, WDC_R7_PROBATION_HEALTH_CHECKS);
    if (status != WDC_OK || metadata.active_slot != WDC_BUNDLE_SLOT_B || metadata.last_good_slot != WDC_BUNDLE_SLOT_B ||
        metadata.slot_b.state != WDC_SLOT_CONFIRMED || metadata.candidate_boot_count != 0u || metadata.last_failure_reason != WDC_OK) {
        return status == WDC_OK ? WDC_ERR_CONTRACT_VIOLATION : status;
    }

#ifndef ESP_PLATFORM
    status = wdc_ota_write_metadata(&metadata);
    if (status != WDC_OK) {
        return status;
    }
    WdcBundleMetadataV1 persisted;
    status = wdc_ota_read_metadata(&persisted);
    if (status != WDC_OK) {
        return status;
    }
    if (persisted.active_slot != WDC_BUNDLE_SLOT_B || persisted.last_good_slot != WDC_BUNDLE_SLOT_B || persisted.slot_b.state != WDC_SLOT_CONFIRMED) {
        return WDC_ERR_CONTRACT_VIOLATION;
    }
#endif

    char msg[208];
    (void)snprintf(msg,
                   sizeof(msg),
                   "R7 activation self-test decision=%s active=%s last_good=%s version=%lu generation=%lu",
                   wdc_activation_decision_name(decision.kind),
                   wdc_bundle_slot_name(metadata.active_slot),
                   wdc_bundle_slot_name(metadata.last_good_slot),
                   (unsigned long)metadata.slot_b.bundle_version,
                   (unsigned long)metadata.metadata_generation);
    wdc_shell_diag(WDC_LOG_INFO, msg);
    return WDC_OK;
}

static int32_t WDC_UNUSED_FN wdc_shell_run_r6_bundle_metadata_self_test(void)
{
    WdcBundleMetadataV1 metadata;
    wdc_bundle_metadata_init(&metadata);
    int32_t status = wdc_bundle_metadata_validate(&metadata);
    if (status != WDC_OK) {
        return status;
    }
    if (metadata.active_slot != WDC_BUNDLE_SLOT_NONE || metadata.slot_a.state != WDC_SLOT_EMPTY || metadata.slot_b.state != WDC_SLOT_EMPTY) {
        return WDC_ERR_CONTRACT_VIOLATION;
    }
    WdcBundleParsedHeader header;
    status = wdc_ota_read_slot_header(WDC_BUNDLE_SLOT_A, &header);
    if (status == WDC_ERR_NOT_AVAILABLE || status == WDC_ERR_BAD_ENCODING || status == WDC_ERR_BAD_LENGTH) {
        wdc_shell_diag(WDC_LOG_WARN, "R6 wasm_a bundle slot not verified yet; static development smoke remains available");
        return WDC_OK;
    }
    if (status == WDC_OK) {
        char msg[160];
        (void)snprintf(msg,
                       sizeof(msg),
                       "R6 wasm_a header found: manifest=%lu payload=%lu sig=%s/%lu",
                       (unsigned long)header.manifest_len,
                       (unsigned long)header.payload_len,
                       wdc_bundle_signature_alg_name(header.signature_alg),
                       (unsigned long)header.signature_len);
        wdc_shell_diag(WDC_LOG_INFO, msg);
    }
    return status;
}


static uint32_t net_publish_req(uint8_t *req, uint32_t cap, uint32_t resource_id, const char *topic, const uint8_t *payload, uint32_t payload_len)
{
    WdcCborBuilder b;
    wdc_cbor_builder_init(&b, req, cap);
    int32_t status = wdc_cbor_begin_map(&b, 4u);
    if (status == WDC_OK) { status = wdc_cbor_put_key_u32(&b, WDC_CBOR_KEY_RESOURCE_ID, resource_id); }
    if (status == WDC_OK) { status = wdc_cbor_put_key_text(&b, WDC_CBOR_KEY_TOPIC, topic); }
    if (status == WDC_OK) { status = wdc_cbor_put_key_bytes(&b, WDC_CBOR_KEY_DATA, payload, payload_len); }
    if (status == WDC_OK) { status = wdc_cbor_put_key_u32(&b, WDC_CBOR_KEY_QOS, 0u); }
    return status == WDC_OK ? wdc_cbor_len(&b) : 0u;
}

static int32_t WDC_UNUSED_FN wdc_shell_run_r8_network_self_test(const WdcDeviceProfile *profile)
{
    if (profile == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    int32_t status = wdc_net_install_host_bridge(profile);
    if (status == WDC_OK) { status = wdc_net_set_state(WDC_NET_STATE_CONNECTED, "R8 network self-test"); }
    if (status == WDC_OK) { status = wdc_safety_install_guarded_authorizer(profile, wdc_caps_builtin_relay_limited()); }
    if (status == WDC_OK) { status = wdc_safety_mark_app_running("com.example.r8-network-smoke", 8u); }
    if (status != WDC_OK) { return status; }

    uint8_t req[160];
    uint8_t rsp[96];
    uint32_t rsp_len = 0u;
    WdcCborBuilder empty;
    wdc_cbor_builder_init(&empty, req, sizeof(req));
    status = wdc_cbor_begin_map(&empty, 0u);
    if (status == WDC_OK) { status = wdc_host_call_dispatch(WDC_OP_NET_STATUS, req, wdc_cbor_len(&empty), rsp, sizeof(rsp), &rsp_len); }
    if (status != WDC_OK) { return status; }
    if (response_status_value(rsp, rsp_len) != WDC_OK) { return WDC_ERR_CONTRACT_VIOLATION; }
    uint32_t net_state = 0u;
    status = wdc_cbor_map_find_u32(rsp, rsp_len, WDC_CBOR_KEY_NETWORK_STATE, &net_state);
    if (status != WDC_OK || net_state != (uint32_t)WDC_NET_STATE_CONNECTED) {
        return status == WDC_OK ? WDC_ERR_CONTRACT_VIOLATION : status;
    }

    const uint8_t payload[] = { 'o', 'k' };
    uint32_t req_len = net_publish_req(req, sizeof(req), WDC_R8_RESOURCE_MQTT_TELEMETRY, "devices/demo/telemetry/self-test", payload, (uint32_t)sizeof(payload));
    if (req_len == 0u) { return WDC_ERR_BAD_ENCODING; }
    rsp_len = 0u;
    status = wdc_host_call_dispatch(WDC_OP_MQTT_PUBLISH, req, req_len, rsp, sizeof(rsp), &rsp_len);
    if (status != WDC_OK) { return status; }
    if (response_status_value(rsp, rsp_len) != WDC_OK) { return WDC_ERR_CONTRACT_VIOLATION; }

    WdcNetStatus net_status;
    memset(&net_status, 0, sizeof(net_status));
    wdc_net_get_status(&net_status);
    if (net_status.publish_count != 1u || net_status.last_publish.resource_id != WDC_R8_RESOURCE_MQTT_TELEMETRY) {
        return WDC_ERR_CONTRACT_VIOLATION;
    }
    wdc_shell_diag(WDC_LOG_INFO, "R8 network self-test published telemetry through native supervisor");
    return WDC_OK;
}

static int32_t wdc_shell_run_r8_active_slot_probe(const WdcDeviceProfile *profile)
{
    if (profile == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    WdcBundleMetadataV1 metadata;
    int32_t status = wdc_ota_read_metadata(&metadata);
    if (status != WDC_OK) {
        return status;
    }

    WdcActivationPolicy activation_policy = wdc_activation_default_policy();
    activation_policy.max_candidate_boots = WDC_R7_MAX_CANDIDATE_BOOTS;
    activation_policy.required_health_checks = WDC_R7_PROBATION_HEALTH_CHECKS;
#if WDC_BUILD_PROFILE_PROD
    WdcSecurityPolicy security_policy = wdc_security_production_policy();
    WdcBundleVerifyPolicy verify_policy = wdc_security_make_bundle_verify_policy(profile, &metadata, &security_policy);
#else
    WdcBundleVerifyPolicy verify_policy = wdc_bundle_make_default_dev_policy(profile);
#endif
    WdcRuntimeConfig runtime_config = wdc_runtime_default_config();
    runtime_config.instance_stack_bytes = WDC_R8_RUNTIME_STACK_BYTES;
    runtime_config.host_heap_bytes = WDC_R8_RUNTIME_HEAP_BYTES;
    runtime_config.exec_stack_bytes = WDC_R8_EXEC_STACK_BYTES;

    WdcRuntime runtime;
    memset(&runtime, 0, sizeof(runtime));
    WdcAppBootReport report;
    memset(&report, 0, sizeof(report));
    status = wdc_app_boot_active_slot(profile,
                                      &metadata,
                                      &activation_policy,
                                      &verify_policy,
                                      &runtime,
                                      &runtime_config,
                                      s_r8_bundle_buffer,
                                      sizeof(s_r8_bundle_buffer),
                                      &report);
    char msg[512];
    (void)snprintf(msg,
                   sizeof(msg),
                   "R8 active slot probe status=%s slot=%s bundle=%s@%lu payload=%lu reason=%s",
                   wdc_status_name(status),
                   wdc_bundle_slot_name(report.selected_slot),
                   report.bundle_id[0] != '\0' ? report.bundle_id : "<none>",
                   (unsigned long)report.bundle_version,
                   (unsigned long)report.payload_len,
                   report.reason[0] != '\0' ? report.reason : "<none>");
    wdc_shell_diag(status == WDC_OK ? WDC_LOG_INFO : WDC_LOG_WARN, msg);
    if (status == WDC_OK) {
        wdc_runtime_teardown(&runtime);
        return WDC_OK;
    }
    if (status == WDC_ERR_NOT_AVAILABLE || report.no_bundle) {
        return WDC_OK;
    }
    wdc_runtime_teardown(&runtime);
    return status;
}




static int32_t WDC_UNUSED_FN wdc_shell_run_r5_runtime_smoke(void)
{
    WdcRuntimeConfig config = wdc_runtime_default_config();
    config.instance_stack_bytes = WDC_R5_RUNTIME_STACK_BYTES;
    config.host_heap_bytes = WDC_R5_RUNTIME_HEAP_BYTES;
    config.exec_stack_bytes = WDC_R5_EXEC_STACK_BYTES;

    WdcRuntime runtime;
    int32_t status = wdc_runtime_init(&runtime, &config);
    if (status == WDC_OK) { status = wdc_runtime_load_static(&runtime, wdc_static_hello_wasm, wdc_static_hello_wasm_len); }
    if (status == WDC_OK) { status = wdc_runtime_lookup_exports(&runtime); }
    if (status == WDC_OK) { status = wdc_runtime_call_init(&runtime); }
    if (status == WDC_OK) {
        const uint8_t payload[] = { 'b', 'o', 'o', 't' };
        WdcEvent boot_event;
        status = wdc_event_make(&boot_event, WDC_EVENT_SYSTEM_BOOT, WDC_EVENT_RESOURCE_NONE, 1u, payload, (uint16_t)sizeof(payload));
        if (status == WDC_OK) {
            boot_event.event_id = 1u;
            status = wdc_runtime_dispatch_event(&runtime, &boot_event);
        }
    }
    if (status == WDC_OK) { status = wdc_runtime_call_health(&runtime); }
    if (status == WDC_OK) { status = wdc_runtime_call_shutdown(&runtime, WDC_SHUTDOWN_NORMAL); }

    wdc_runtime_copy_report(&runtime, &s_r5_runtime_report);
    char msg[176];
    (void)snprintf(msg, sizeof(msg),
                   "R5 runtime smoke outcome=%s status=%s init=%lu event=%lu health=%lu shutdown=%lu backend=%d",
                   wdc_runtime_outcome_name(s_r5_runtime_report.outcome),
                   wdc_status_name(status),
                   (unsigned long)s_r5_runtime_report.init_result,
                   (unsigned long)s_r5_runtime_report.on_event_result,
                   (unsigned long)s_r5_runtime_report.health_result,
                   (unsigned long)s_r5_runtime_report.shutdown_result,
                   (int)s_r5_runtime_report.backend);
    wdc_shell_diag(status == WDC_OK ? WDC_LOG_INFO : WDC_LOG_ERROR, msg);
    wdc_runtime_teardown(&runtime);
    return status;
}

static void wdc_shell_drain_internal_events_once(void)
{
    WdcEvent event = {0};
    while (wdc_events_next(&event) == WDC_OK) {
        char msg[96];
        (void)snprintf(msg, sizeof(msg), "internal event drained type=0x%04" PRIx32 " resource=%" PRIu32,
                       event.event_type,
                       event.resource_id);
        wdc_shell_diag(WDC_LOG_INFO, msg);
    }
}

#ifdef ESP_PLATFORM
static void wdc_shell_task(void *arg)
#else
static void wdc_shell_task(void)
#endif
{
#ifdef ESP_PLATFORM
    (void)arg;
#endif
    wdc_shell_diag(WDC_LOG_INFO, "shell task started");

#if WDC_NO_BUNDLE_MODE
    wdc_shell_diag(WDC_LOG_WARN, "no-bundle mode active");
#else
    if (s_r5_runtime_report.outcome == WDC_RUNTIME_OUTCOME_OK) {
        wdc_shell_diag(WDC_LOG_INFO, "R5 static runtime smoke already completed");
    } else {
        wdc_shell_diag(WDC_LOG_WARN, "runtime smoke was not confirmed healthy");
    }
#endif

#ifdef ESP_PLATFORM
    for (;;) {
        wdc_shell_drain_internal_events_once();
        vTaskDelay(pdMS_TO_TICKS(WDC_NO_BUNDLE_IDLE_PERIOD_MS));
    }
#else
    wdc_shell_drain_internal_events_once();
#endif
}

void shell_main(void)
{
    (void)wdc_diag_init();

#ifdef ESP_PLATFORM
    const esp_reset_reason_t reset_reason = esp_reset_reason();
    const char *reset_name = wdc_reset_reason_name((int32_t)reset_reason);

    ESP_LOGI(TAG, "%s %s (%s) boot", WDC_SHELL_NAME, WDC_SHELL_VERSION, WDC_SHELL_BUILD_STAGE);
    ESP_LOGI(TAG, "build_id=%s", WDC_SHELL_BUILD_ID);
    ESP_LOGI(TAG, "ABI v%u.%u", (unsigned)WDC_ABI_MAJOR, (unsigned)WDC_ABI_MINOR);
    ESP_LOGI(TAG, "reset_reason=%s(%d)", reset_name, (int)reset_reason);
    wdc_diag_note_boot((uint32_t)reset_reason, reset_name);
#else
    wdc_diag_note_boot(0u, "host");
#endif

    wdc_shell_print_partition_info();

    int32_t status = wdc_shell_init_metadata_storage();
    if (status != WDC_OK) {
        wdc_shell_diag(WDC_LOG_ERROR, "metadata storage initialization failed");
    }

    const WdcDeviceProfile *profile = wdc_profile_builtin();
    status = wdc_profile_validate_basic(profile);
    if (status != WDC_OK) {
        wdc_shell_diag(WDC_LOG_ERROR, "builtin device profile validation failed");
    } else {
        char msg[144];
        (void)snprintf(msg, sizeof(msg), "builtin profile: class=%s hardware=%s board_rev=%s resources=%u gpio=%u",
                       profile->device_class,
                       profile->hardware,
                       profile->board_rev,
                       (unsigned)profile->resource_count,
                       (unsigned)profile->gpio_count);
        wdc_shell_diag(WDC_LOG_INFO, msg);
    }

    status = wdc_events_init();
    if (status != WDC_OK) {
        wdc_shell_diag(WDC_LOG_ERROR, "event queue initialization failed");
    } else {
        wdc_shell_diag(WDC_LOG_INFO, "event queue initialized");
    }

    status = wdc_safety_init(profile);
    if (status != WDC_OK) {
        wdc_shell_diag(WDC_LOG_ERROR, "safety initialization failed");
    } else {
        char msg[112];
        (void)snprintf(msg, sizeof(msg), "R5 safety initialized: outputs=%lu safe=%s",
                       (unsigned long)wdc_hal_safe_gpio_defaults_applied(),
                       wdc_safety_physical_outputs_safe() ? "true" : "false");
        wdc_shell_diag(WDC_LOG_INFO, msg);
    }

    status = wdc_net_init(profile);
    wdc_shell_diag(status == WDC_OK ? WDC_LOG_INFO : WDC_LOG_ERROR,
                   status == WDC_OK ? "R8 network mediator initialized" : "R8 network mediator initialization failed");

#if WDC_ENABLE_EFFECTFUL_SELF_TESTS
    status = wdc_safety_install_guarded_authorizer(profile, wdc_caps_builtin_relay_limited());
    if (status != WDC_OK) {
        wdc_shell_diag(WDC_LOG_ERROR, "safety guarded authorizer installation failed");
    } else {
        wdc_shell_diag(WDC_LOG_INFO, "safety guarded authorizer installed: relay-limited bundle");
        status = wdc_safety_mark_app_running("com.example.relay-controller-r5-limited", 5u);
        if (status == WDC_OK) {
            status = wdc_shell_run_r4_capability_self_test();
        }
        wdc_shell_diag(status == WDC_OK ? WDC_LOG_INFO : WDC_LOG_ERROR,
                       status == WDC_OK ? "R4 capability self-test passed under R5 safety guard" : "R4 capability self-test failed under R5 safety guard");
        if (status == WDC_OK) {
            status = wdc_shell_run_r5_safety_self_test(profile);
        }
        wdc_shell_diag(status == WDC_OK ? WDC_LOG_INFO : WDC_LOG_ERROR,
                       status == WDC_OK ? "R5 safety self-test passed" : "R5 safety self-test failed");
#if WDC_R8_NETWORK_SMOKE
        if (status == WDC_OK) {
            status = wdc_shell_run_r8_network_self_test(profile);
            wdc_shell_diag(status == WDC_OK ? WDC_LOG_INFO : WDC_LOG_ERROR,
                           status == WDC_OK ? "R8 network mediation self-test passed" : "R8 network mediation self-test failed");
        }
#endif
    }
#else
    wdc_shell_diag(WDC_LOG_INFO, "R8.2 production boot: effectful GPIO/network self-tests disabled");
#endif

#if WDC_R6_BUNDLE_VERIFY_SMOKE
    status = wdc_shell_run_r6_bundle_metadata_self_test();
    wdc_shell_diag(status == WDC_OK ? WDC_LOG_INFO : WDC_LOG_ERROR,
                   status == WDC_OK ? "R6 bundle metadata self-test passed" : "R6 bundle metadata self-test failed");
#endif

#if WDC_R7_ACTIVATION_SMOKE
    status = wdc_shell_run_r7_activation_self_test();
    wdc_shell_diag(status == WDC_OK ? WDC_LOG_INFO : WDC_LOG_ERROR,
                   status == WDC_OK ? "R7 activation/rollback self-test passed" : "R7 activation/rollback self-test failed");
#endif

    status = wdc_shell_run_internal_event_self_test();
    wdc_shell_diag(status == WDC_OK ? WDC_LOG_INFO : WDC_LOG_ERROR,
                   status == WDC_OK ? "internal event self-test passed" : "internal event self-test failed");

#if WDC_R8_ACTIVE_SLOT_SMOKE
    status = wdc_shell_run_r8_active_slot_probe(profile);
    wdc_shell_diag(status == WDC_OK ? WDC_LOG_INFO : WDC_LOG_ERROR,
                   status == WDC_OK ? "R8 active slot probe passed" : "R8 active slot probe failed");
#endif

#if WDC_R5_STATIC_RUNTIME_SMOKE
    status = wdc_shell_run_r5_runtime_smoke();
    if (status != WDC_OK) {
        (void)wdc_safety_stop_app(WDC_SAFETY_FAULT_CONTRACT_VIOLATION, status, "R5 static runtime smoke failed", &s_r5_runtime_report);
    } else {
        (void)wdc_safety_enter_no_bundle_mode("R5 static runtime smoke complete; no managed bundle active");
    }
    wdc_shell_diag(status == WDC_OK ? WDC_LOG_INFO : WDC_LOG_ERROR,
                   status == WDC_OK ? "R5 static WASM lifecycle/event smoke passed" : "R5 static WASM lifecycle/event smoke failed");
#endif

#ifdef ESP_PLATFORM
    BaseType_t task_status = xTaskCreate(
        wdc_shell_task,
        WDC_SHELL_TASK_NAME,
        (uint32_t)WDC_SHELL_TASK_STACK_BYTES,
        NULL,
        (UBaseType_t)WDC_SHELL_TASK_PRIORITY,
        NULL);

    if (task_status != pdPASS) {
        ESP_LOGE(TAG, "failed to create shell task");
        wdc_shell_diag(WDC_LOG_ERROR, "failed to create shell task");
    }
#else
    wdc_shell_task();
#endif
}
