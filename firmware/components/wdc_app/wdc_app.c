#include "wdc_app.h"

#include <stdio.h>
#include <string.h>

#include "wdc_app_slots.h"
#include "wdc_caps.h"
#include "wdc_diag.h"
#include "wdc_ota.h"
#include "wdc_safety.h"

static WdcBundleVerifyResult s_active_verify;

static void report_init(WdcAppBootReport *report)
{
    if (report != NULL) {
        memset(report, 0, sizeof(*report));
        report->status = WDC_ERR_UNKNOWN;
        report->selected_slot = WDC_BUNDLE_SLOT_NONE;
    }
}

static void report_reason(WdcAppBootReport *report, const char *reason)
{
    if (report != NULL && reason != NULL) {
        (void)snprintf(report->reason, sizeof(report->reason), "%s", reason);
    }
}

static const WdcBundleSlotRecord *slot_record(const WdcBundleMetadataV1 *metadata, WdcBundleSlotId slot)
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

static bool hash_equals(const uint8_t a[WDC_BUNDLE_SHA256_BYTES], const uint8_t b[WDC_BUNDLE_SHA256_BYTES])
{
    uint8_t diff = 0u;
    for (uint32_t i = 0u; i < WDC_BUNDLE_SHA256_BYTES; ++i) {
        diff |= (uint8_t)(a[i] ^ b[i]);
    }
    return diff == 0u;
}

static int32_t write_metadata_if_changed(WdcBundleMetadataV1 *metadata,
                                         const WdcActivationDecision *decision,
                                         WdcAppBootReport *report)
{
    if (metadata == NULL || decision == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    if (!decision->metadata_changed) {
        return WDC_OK;
    }
    int32_t status = wdc_ota_write_metadata(metadata);
    if (status == WDC_OK && report != NULL) {
        report->metadata_written = true;
    }
    return status;
}

void wdc_app_clear_active_authorizer(void)
{
    memset(&s_active_verify, 0, sizeof(s_active_verify));
    wdc_host_call_reset_limits();
    wdc_safety_clear_guarded_authorizer();
}

static WdcRuntimeConfig runtime_config_from_manifest(const WdcBundleVerifyResult *verify,
                                                    const WdcRuntimeConfig *requested)
{
    WdcRuntimeConfig config = requested != NULL ? *requested : wdc_runtime_default_config();
    if (verify == NULL || verify->status != WDC_OK) {
        return config;
    }
    if (requested == NULL) {
        config.instance_stack_bytes = verify->manifest.stack_bytes;
        config.exec_stack_bytes = verify->manifest.stack_bytes;
        config.host_heap_bytes = verify->manifest.linear_memory_max_bytes;
        config.max_module_bytes = verify->header.payload_len;
        config.max_event_bytes = verify->manifest.max_event_bytes;
    } else {
        if (config.instance_stack_bytes == 0u || config.instance_stack_bytes > verify->manifest.stack_bytes) {
            config.instance_stack_bytes = verify->manifest.stack_bytes;
        }
        if (config.exec_stack_bytes == 0u || config.exec_stack_bytes > verify->manifest.stack_bytes) {
            config.exec_stack_bytes = verify->manifest.stack_bytes;
        }
        if (config.host_heap_bytes == 0u || config.host_heap_bytes > verify->manifest.linear_memory_max_bytes) {
            config.host_heap_bytes = verify->manifest.linear_memory_max_bytes;
        }
        if (config.max_module_bytes == 0u || config.max_module_bytes > verify->header.payload_len) {
            config.max_module_bytes = verify->header.payload_len;
        }
        if (config.max_event_bytes == 0u || config.max_event_bytes > verify->manifest.max_event_bytes) {
            config.max_event_bytes = verify->manifest.max_event_bytes;
        }
    }
    return config;
}

static void install_host_call_limits_from_manifest(const WdcBundleVerifyResult *verify)
{
    if (verify == NULL || verify->status != WDC_OK) {
        wdc_host_call_reset_limits();
        return;
    }
    WdcHostCallLimits limits;
    limits.max_request_bytes = verify->manifest.max_request_bytes;
    limits.max_response_bytes = verify->manifest.max_response_bytes;
    wdc_host_call_set_limits(&limits);
}

static int32_t fail_runtime(WdcBundleMetadataV1 *metadata,
                            WdcBundleSlotId slot,
                            bool probation,
                            int32_t status,
                            const char *reason,
                            WdcRuntime *runtime,
                            WdcAppBootReport *report)
{
    wdc_host_call_reset_limits();
    WdcRuntimeReport runtime_report;
    memset(&runtime_report, 0, sizeof(runtime_report));
    if (runtime != NULL) {
        wdc_runtime_copy_report(runtime, &runtime_report);
        if (report != NULL) {
            report->runtime_report = runtime_report;
        }
    }
    (void)wdc_safety_stop_app(WDC_SAFETY_FAULT_CONTRACT_VIOLATION, status, reason, runtime != NULL ? &runtime_report : NULL);
    if (probation && metadata != NULL && slot != WDC_BUNDLE_SLOT_NONE) {
        WdcActivationDecision fault_decision;
        int32_t fault_status = wdc_activation_record_fault(metadata, slot, status, &fault_decision);
        if (fault_status == WDC_OK) {
            (void)wdc_ota_write_metadata(metadata);
            if (report != NULL) {
                report->activation_decision = fault_decision;
                report->rollback = fault_decision.rollback;
                report->metadata_written = true;
            }
        }
    }
    return status;
}

int32_t wdc_app_boot_active_slot(const WdcDeviceProfile *profile,
                                 WdcBundleMetadataV1 *metadata,
                                 const WdcActivationPolicy *activation_policy,
                                 const WdcBundleVerifyPolicy *verify_policy,
                                 WdcRuntime *runtime,
                                 const WdcRuntimeConfig *runtime_config,
                                 uint8_t *bundle_buffer,
                                 uint32_t bundle_buffer_cap,
                                 WdcAppBootReport *out_report)
{
    report_init(out_report);
    if (profile == NULL || metadata == NULL || runtime == NULL || bundle_buffer == NULL) {
        report_reason(out_report, "bad pointer");
        return WDC_ERR_BAD_POINTER;
    }
    if (bundle_buffer_cap < WDC_BUNDLE_HEADER_LEN_V1) {
        report_reason(out_report, "bundle buffer too small");
        return WDC_ERR_BAD_LENGTH;
    }

    WdcActivationPolicy local_activation = activation_policy != NULL ? *activation_policy : wdc_activation_default_policy();
    WdcActivationDecision decision;
    int32_t status = wdc_activation_on_boot(metadata, &local_activation, &decision);
    if (status != WDC_OK) {
        if (out_report != NULL) {
            out_report->status = status;
            out_report->activation_decision = decision;
        }
        report_reason(out_report, decision.message[0] != '\0' ? decision.message : "activation boot decision failed");
        return status;
    }
    if (out_report != NULL) {
        out_report->activation_decision = decision;
        out_report->selected_slot = decision.slot_to_run;
        out_report->probation = decision.probation;
        out_report->rollback = decision.rollback;
    }
    status = write_metadata_if_changed(metadata, &decision, out_report);
    if (status != WDC_OK) {
        if (out_report != NULL) { out_report->status = status; }
        report_reason(out_report, "activation metadata write failed");
        return status;
    }

    if (decision.kind == WDC_ACTIVATION_DECISION_NO_BUNDLE || decision.slot_to_run == WDC_BUNDLE_SLOT_NONE) {
        wdc_host_call_reset_limits();
        (void)wdc_safety_enter_no_bundle_mode(decision.message[0] != '\0' ? decision.message : "no active bundle");
        if (out_report != NULL) {
            out_report->status = WDC_ERR_NOT_AVAILABLE;
            out_report->no_bundle = true;
        }
        report_reason(out_report, decision.message[0] != '\0' ? decision.message : "no active bundle");
        return WDC_ERR_NOT_AVAILABLE;
    }

    uint32_t bundle_len = 0u;
    status = wdc_ota_read_slot_to_buffer(decision.slot_to_run, bundle_buffer, bundle_buffer_cap, &bundle_len);
    if (status != WDC_OK) {
        if (out_report != NULL) { out_report->status = status; }
        report_reason(out_report, "active slot read failed");
        return fail_runtime(metadata, decision.slot_to_run, decision.probation, status, "active slot read failed", runtime, out_report);
    }

    WdcBundleVerifyPolicy local_verify = verify_policy != NULL ? *verify_policy : wdc_bundle_make_default_dev_policy(profile);
    if (local_verify.profile == NULL) {
        local_verify.profile = profile;
    }
    memset(&s_active_verify, 0, sizeof(s_active_verify));
    status = wdc_bundle_verify(bundle_buffer, bundle_len, &local_verify, &s_active_verify);
    if (status != WDC_OK) {
        if (out_report != NULL) { out_report->status = status; }
        report_reason(out_report, s_active_verify.reason[0] != '\0' ? s_active_verify.reason : "active bundle verification failed");
        return fail_runtime(metadata, decision.slot_to_run, decision.probation, status, "active bundle verification failed", runtime, out_report);
    }

    const WdcBundleSlotRecord *record = slot_record(metadata, decision.slot_to_run);
    if (record == NULL || !hash_equals(record->payload_sha256, s_active_verify.header.payload_sha256)) {
        status = WDC_ERR_CONTRACT_VIOLATION;
        if (out_report != NULL) { out_report->status = status; }
        report_reason(out_report, "active slot metadata hash mismatch");
        return fail_runtime(metadata, decision.slot_to_run, decision.probation, status, "active slot metadata hash mismatch", runtime, out_report);
    }

    const uint8_t *payload = NULL;
    uint32_t payload_len = 0u;
    status = wdc_bundle_get_payload(bundle_buffer, bundle_len, &s_active_verify.header, &payload, &payload_len);
    if (status != WDC_OK) {
        if (out_report != NULL) { out_report->status = status; }
        report_reason(out_report, "active payload extraction failed");
        return fail_runtime(metadata, decision.slot_to_run, decision.probation, status, "active payload extraction failed", runtime, out_report);
    }

    install_host_call_limits_from_manifest(&s_active_verify);
    WdcRuntimeConfig effective_runtime_config = runtime_config_from_manifest(&s_active_verify, runtime_config);

    status = wdc_safety_install_guarded_authorizer(profile, &s_active_verify.capability_set);
    if (status == WDC_OK) {
        status = wdc_safety_mark_app_running(s_active_verify.manifest.bundle_id, s_active_verify.manifest.bundle_version);
    }
    if (status != WDC_OK) {
        if (out_report != NULL) { out_report->status = status; }
        report_reason(out_report, "active bundle safety authorizer install failed");
        return status;
    }

    status = wdc_runtime_init(runtime, &effective_runtime_config);
    if (status == WDC_OK) { status = wdc_runtime_load_static(runtime, payload, payload_len); }
    if (status == WDC_OK) { status = wdc_runtime_lookup_exports(runtime); }
    if (status == WDC_OK) {
        if (out_report != NULL) {
            out_report->application_code_launched = true;
        }
        status = wdc_runtime_call_init(runtime);
    }
    if (status == WDC_OK) { status = wdc_runtime_call_health(runtime); }
    wdc_runtime_copy_report(runtime, out_report != NULL ? &out_report->runtime_report : NULL);
    if (status != WDC_OK) {
        report_reason(out_report, "active runtime lifecycle failed");
        return fail_runtime(metadata, decision.slot_to_run, decision.probation, status, "active runtime lifecycle failed", runtime, out_report);
    }

    if (out_report != NULL) {
        out_report->status = WDC_OK;
        out_report->used_active_slot = true;
        out_report->selected_slot = decision.slot_to_run;
        out_report->bundle_len = bundle_len;
        out_report->payload_len = payload_len;
        out_report->bundle_version = s_active_verify.manifest.bundle_version;
        (void)snprintf(out_report->bundle_id, sizeof(out_report->bundle_id), "%s", s_active_verify.manifest.bundle_id);
    }
    report_reason(out_report,
                  decision.probation
                      ? "trial bundle loaded; host probation remains open"
                      : "active bundle loaded from confirmed slot");
    return WDC_OK;
}

int32_t wdc_app_boot_managed_slot(
    const WdcDeviceProfile *profile,
    WdcBundleMetadataV1 *metadata,
    const WdcActivationPolicy *activation_policy,
    const WdcActivationBootContext *boot_context,
    const WdcHostFingerprintV1 *fingerprint,
    const WdcControlHeapSnapshot *heap,
    const WdcAppSlotVerifyPolicy *slot_verify_policy,
    WdcRuntime *runtime,
    const WdcRuntimeConfig *runtime_config,
    uint8_t *bundle_buffer,
    uint32_t bundle_buffer_cap,
    WdcAppSlotBootResult *out_slot_report,
    WdcAppBootReport *out_report)
{
    const uint8_t *payload = NULL;
    uint32_t payload_len = 0u;
    int32_t status;
    report_init(out_report);
    if (profile == NULL || metadata == NULL || fingerprint == NULL ||
        heap == NULL || slot_verify_policy == NULL || runtime == NULL ||
        bundle_buffer == NULL || out_slot_report == NULL) {
        report_reason(out_report, "managed slot boot received a bad pointer");
        return WDC_ERR_BAD_POINTER;
    }
    status = wdc_app_slots_boot(metadata,
                                activation_policy,
                                boot_context,
                                fingerprint,
                                heap,
                                slot_verify_policy,
                                bundle_buffer,
                                bundle_buffer_cap,
                                out_slot_report);
    if (out_report != NULL) {
        out_report->prelaunch_checked =
            out_slot_report->prelaunch.outcome !=
            WDC_HOST_PRELAUNCH_NOT_EVALUATED;
        out_report->selected_slot = out_slot_report->selected_slot;
        out_report->probation = out_slot_report->probation;
        out_report->rollback = out_slot_report->reboot_required;
        out_report->activation_decision = out_slot_report->activation;
    }
    if (status != WDC_OK ||
        (out_slot_report->outcome != WDC_APP_SLOT_BOOT_RUN_CONFIRMED &&
         out_slot_report->outcome != WDC_APP_SLOT_BOOT_RUN_TRIAL)) {
        int32_t result = status;
        if (result == WDC_OK) {
            result = out_slot_report->reboot_required
                         ? WDC_ERR_NOT_SYNCHRONIZED
                         : WDC_ERR_NOT_AVAILABLE;
        }
        if (out_report != NULL) {
            out_report->status = result;
            out_report->no_bundle = out_slot_report->recovery;
        }
        report_reason(out_report,
                      out_slot_report->reboot_required
                          ? "managed slot fallback requires reboot"
                          : "managed slot boot entered recovery");
        return result;
    }

    s_active_verify = out_slot_report->bundle_verify;
    status = wdc_bundle_get_payload(bundle_buffer,
                                    out_slot_report->bundle_bytes,
                                    &s_active_verify.header,
                                    &payload,
                                    &payload_len);
    if (status != WDC_OK) {
        report_reason(out_report, "managed slot payload extraction failed");
        return fail_runtime(metadata,
                            out_slot_report->selected_slot,
                            out_slot_report->probation,
                            status,
                            "managed slot payload extraction failed",
                            runtime,
                            out_report);
    }

    install_host_call_limits_from_manifest(&s_active_verify);
    WdcRuntimeConfig effective_runtime_config =
        runtime_config_from_manifest(&s_active_verify, runtime_config);
    status = wdc_safety_install_guarded_authorizer(
        profile,
        &s_active_verify.capability_set);
    if (status == WDC_OK) {
        status = wdc_safety_mark_app_running(
            s_active_verify.manifest.bundle_id,
            s_active_verify.manifest.bundle_version);
    }
    if (status != WDC_OK) {
        report_reason(out_report,
                      "managed slot safety authorizer install failed");
        if (out_report != NULL) {
            out_report->status = status;
        }
        return status;
    }

    status = wdc_runtime_init(runtime, &effective_runtime_config);
    if (status == WDC_OK) {
        status = wdc_runtime_load_static(runtime, payload, payload_len);
    }
    if (status == WDC_OK) {
        status = wdc_runtime_lookup_exports(runtime);
    }
    if (status == WDC_OK) {
        if (out_report != NULL) {
            out_report->application_code_launched = true;
        }
        status = wdc_runtime_call_init(runtime);
    }
    if (status == WDC_OK) {
        status = wdc_runtime_call_health(runtime);
    }
    wdc_runtime_copy_report(runtime,
                            out_report != NULL
                                ? &out_report->runtime_report
                                : NULL);
    if (status != WDC_OK) {
        report_reason(out_report, "managed slot runtime lifecycle failed");
        return fail_runtime(metadata,
                            out_slot_report->selected_slot,
                            out_slot_report->probation,
                            status,
                            "managed slot runtime lifecycle failed",
                            runtime,
                            out_report);
    }
    if (out_report != NULL) {
        out_report->status = WDC_OK;
        out_report->used_active_slot = true;
        out_report->selected_slot = out_slot_report->selected_slot;
        out_report->bundle_len = out_slot_report->bundle_bytes;
        out_report->payload_len = payload_len;
        out_report->bundle_version =
            s_active_verify.manifest.bundle_version;
        (void)snprintf(out_report->bundle_id,
                       sizeof(out_report->bundle_id),
                       "%s",
                       s_active_verify.manifest.bundle_id);
    }
    report_reason(out_report,
                  out_slot_report->probation
                      ? "managed trial launched; host probation remains open"
                      : "managed confirmed application launched");
    return WDC_OK;
}
