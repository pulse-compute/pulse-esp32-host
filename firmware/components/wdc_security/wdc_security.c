#include "wdc_security.h"

#include <stdio.h>
#include <string.h>

#include "wdc_diag.h"

static uint64_t max_u64(uint64_t a, uint64_t b)
{
    return a > b ? a : b;
}


const char *wdc_security_profile_name(WdcSecurityBuildProfile profile)
{
    switch (profile) {
    case WDC_SECURITY_PROFILE_DEVELOPMENT: return "development";
    case WDC_SECURITY_PROFILE_PRODUCTION: return "production";
    default: return "unknown";
    }
}

WdcSecurityPolicy wdc_security_development_policy(void)
{
    WdcSecurityPolicy policy;
    memset(&policy, 0, sizeof(policy));
    policy.profile = WDC_SECURITY_PROFILE_DEVELOPMENT;
    policy.production_mode = false;
    policy.require_secure_bundle_signature = false;
    policy.reject_dev_signature = false;
    policy.anti_rollback_enabled = false;
    policy.watchdog_rollback_enabled = true;
    policy.effectful_self_tests_allowed = true;
    policy.boot_diagnostic_probes_allowed = true;
    policy.serial_install_allowed = true;
    policy.profile_mutation_allowed = true;
    policy.required_signature_alg = "";
    policy.trusted_signature_key_id = "";
    policy.ota_endpoint_prefix = "";
    return policy;
}

WdcSecurityPolicy wdc_security_production_policy(void)
{
    WdcSecurityPolicy policy;
    memset(&policy, 0, sizeof(policy));
    policy.profile = WDC_SECURITY_PROFILE_PRODUCTION;
    policy.production_mode = true;
    policy.require_secure_bundle_signature = true;
    policy.reject_dev_signature = true;
    policy.anti_rollback_enabled = true;
    policy.watchdog_rollback_enabled = true;
    policy.effectful_self_tests_allowed = false;
    policy.boot_diagnostic_probes_allowed = false;
    policy.serial_install_allowed = false;
    policy.profile_mutation_allowed = false;
    policy.required_signature_alg = WDC_SECURITY_DEFAULT_PROD_SIGNATURE_ALG;
    policy.trusted_signature_key_id = "";
    policy.ota_endpoint_prefix = "";
    return policy;
}

uint64_t wdc_security_metadata_security_floor(const WdcBundleMetadataV1 *metadata)
{
    if (metadata == NULL) {
        return 0u;
    }
    uint64_t floor = 0u;
    if (metadata->slot_a.state != WDC_SLOT_EMPTY) {
        floor = max_u64(floor, metadata->slot_a.security_counter);
    }
    if (metadata->slot_b.state != WDC_SLOT_EMPTY) {
        floor = max_u64(floor, metadata->slot_b.security_counter);
    }
    return floor;
}

WdcBundleVerifyPolicy wdc_security_make_bundle_verify_policy(const WdcDeviceProfile *profile,
                                                             const WdcBundleMetadataV1 *metadata,
                                                             const WdcSecurityPolicy *security_policy)
{
    WdcSecurityPolicy local = security_policy != NULL ? *security_policy : wdc_security_production_policy();
    WdcBundleVerifyPolicy verify = wdc_bundle_make_default_dev_policy(profile);
    verify.production_mode = local.production_mode;
    verify.allow_unsigned_dev = !local.production_mode && !local.require_secure_bundle_signature;
    if (local.production_mode || local.reject_dev_signature) {
        verify.dev_hmac_key = NULL;
        verify.dev_hmac_key_len = 0u;
    }
    if (local.anti_rollback_enabled) {
        verify.min_security_counter = wdc_security_metadata_security_floor(metadata);
    }
    if (local.require_secure_bundle_signature) {
        verify.required_signature_alg = local.required_signature_alg != NULL ? local.required_signature_alg : WDC_SECURITY_DEFAULT_PROD_SIGNATURE_ALG;
    }
    if (local.trusted_signature_key_id != NULL && local.trusted_signature_key_id[0] != '\0') {
        verify.trusted_signature_key_id = local.trusted_signature_key_id;
    }
    return verify;
}

static void preflight_reason(WdcSecurityPreflightReport *report, const char *reason)
{
    if (report != NULL) {
        (void)snprintf(report->reason, sizeof(report->reason), "%s", reason != NULL ? reason : "");
    }
}

WdcSecurityDeviceState wdc_security_default_dev_state(void)
{
    WdcSecurityDeviceState state;
    state.flags = 0u;
    return state;
}

WdcSecurityDeviceState wdc_security_default_production_state(void)
{
    WdcSecurityDeviceState state;
    state.flags = WDC_SECURITY_PRODUCTION_REQUIRED_FLAGS;
    return state;
}

int32_t wdc_security_preflight(WdcSecurityMode mode,
                               const WdcSecurityDeviceState *state,
                               WdcSecurityPreflightReport *out_report)
{
    if (out_report != NULL) {
        memset(out_report, 0, sizeof(*out_report));
        out_report->status = WDC_ERR_UNKNOWN;
        out_report->production_mode = mode == WDC_SECURITY_MODE_PRODUCTION;
    }
    if (state == NULL) {
        preflight_reason(out_report, "missing device security state");
        if (out_report != NULL) { out_report->status = WDC_ERR_BAD_POINTER; }
        return WDC_ERR_BAD_POINTER;
    }
    uint32_t required = mode == WDC_SECURITY_MODE_PRODUCTION ? WDC_SECURITY_PRODUCTION_REQUIRED_FLAGS : 0u;
    uint32_t missing = required & ~state->flags;
    if (out_report != NULL) {
        out_report->required_flags = required;
        out_report->missing_flags = missing;
        out_report->secure_signature_required = mode == WDC_SECURITY_MODE_PRODUCTION;
        out_report->anti_rollback_required = mode == WDC_SECURITY_MODE_PRODUCTION;
        out_report->dev_signature_rejected = false;
    }
    if (missing != 0u) {
        preflight_reason(out_report, "production security flags missing");
        if (out_report != NULL) { out_report->status = WDC_ERR_INVALID_STATE; }
        return WDC_ERR_INVALID_STATE;
    }
    preflight_reason(out_report, "security preflight accepted device state");
    if (out_report != NULL) { out_report->status = WDC_OK; }
    return WDC_OK;
}

WdcBundleVerifyPolicy wdc_security_make_bundle_policy(const WdcSecurityBundlePolicyConfig *config)
{
    const WdcDeviceProfile *profile = config != NULL && config->profile != NULL ? config->profile : wdc_profile_builtin();
    WdcBundleVerifyPolicy policy;
    if (config != NULL && config->mode == WDC_SECURITY_MODE_DEV) {
        policy = wdc_bundle_make_default_dev_policy(profile);
        policy.min_security_counter = config->min_security_counter;
        return policy;
    }
    policy = wdc_bundle_make_default_production_policy(profile);
    if (config != NULL) {
        policy.min_security_counter = config->min_security_counter;
        if (config->trusted_signature_key_id != NULL && config->trusted_signature_key_id[0] != '\0') {
            policy.trusted_signature_key_id = config->trusted_signature_key_id;
        }
        policy.signature_verify = config->signature_verify;
        policy.signature_verify_ctx = config->signature_verify_ctx;
    }
    return policy;
}

int32_t wdc_security_validate_bundle_result(const WdcSecurityPolicy *security_policy,
                                            const WdcBundleVerifyResult *verify_result,
                                            WdcSecurityPreflightReport *out_report)
{
    WdcSecurityPolicy local = security_policy != NULL ? *security_policy : wdc_security_production_policy();
    if (out_report != NULL) {
        memset(out_report, 0, sizeof(*out_report));
        out_report->status = WDC_ERR_UNKNOWN;
        out_report->production_mode = local.production_mode;
        out_report->secure_signature_required = local.require_secure_bundle_signature;
        out_report->anti_rollback_required = local.anti_rollback_enabled;
    }
    if (verify_result == NULL) {
        preflight_reason(out_report, "missing verification result");
        if (out_report != NULL) { out_report->status = WDC_ERR_BAD_POINTER; }
        return WDC_ERR_BAD_POINTER;
    }
    if (verify_result->status != WDC_OK) {
        preflight_reason(out_report, verify_result->reason[0] != '\0' ? verify_result->reason : "bundle verification failed");
        if (out_report != NULL) { out_report->status = verify_result->status; }
        return verify_result->status;
    }
    if (local.require_secure_bundle_signature && !verify_result->signature_ok) {
        preflight_reason(out_report, "secure bundle signature is required");
        if (out_report != NULL) { out_report->status = WDC_ERR_CONTRACT_VIOLATION; }
        return WDC_ERR_CONTRACT_VIOLATION;
    }
    if (local.reject_dev_signature && strcmp(verify_result->manifest.signature_alg, "hmac-sha256-dev") == 0) {
        preflight_reason(out_report, "development bundle signature rejected in production");
        if (out_report != NULL) {
            out_report->status = WDC_ERR_CONTRACT_VIOLATION;
            out_report->dev_signature_rejected = true;
        }
        return WDC_ERR_CONTRACT_VIOLATION;
    }
    if (local.require_secure_bundle_signature && local.required_signature_alg != NULL && local.required_signature_alg[0] != '\0' &&
        strcmp(verify_result->manifest.signature_alg, local.required_signature_alg) != 0) {
        preflight_reason(out_report, "bundle signature algorithm is not production trusted");
        if (out_report != NULL) { out_report->status = WDC_ERR_CONTRACT_VIOLATION; }
        return WDC_ERR_CONTRACT_VIOLATION;
    }
    if (local.anti_rollback_enabled && !verify_result->anti_rollback_ok) {
        preflight_reason(out_report, "anti-rollback policy rejected bundle");
        if (out_report != NULL) { out_report->status = WDC_ERR_CONTRACT_VIOLATION; }
        return WDC_ERR_CONTRACT_VIOLATION;
    }
    preflight_reason(out_report, "security preflight accepted bundle");
    if (out_report != NULL) {
        out_report->status = WDC_OK;
        out_report->security_floor = 0u;
    }
    return WDC_OK;
}

int32_t wdc_security_validate_provisioning(const WdcProvisioningRecord *record,
                                           const WdcDeviceProfile *profile,
                                           const WdcSecurityPolicy *security_policy)
{
    WdcSecurityPolicy local = security_policy != NULL ? *security_policy : wdc_security_production_policy();
    if (record == NULL || profile == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    if (!record->provisioned || record->serial[0] == '\0' || record->device_class[0] == '\0') {
        return WDC_ERR_INVALID_STATE;
    }
    if (strcmp(record->device_class, profile->device_class) != 0) {
        return WDC_ERR_INVALID_RESOURCE;
    }
    if (record->board_rev[0] != '\0' && strcmp(record->board_rev, profile->board_rev) != 0) {
        return WDC_ERR_INVALID_RESOURCE;
    }
    if (local.production_mode) {
        if (record->trusted_signature_key_id[0] == '\0') {
            return WDC_ERR_NOT_AVAILABLE;
        }
        if (record->ota_endpoint_prefix[0] == '\0') {
            return WDC_ERR_NOT_AVAILABLE;
        }
    }
    return WDC_OK;
}

bool wdc_security_reset_reason_is_watchdog(uint32_t reset_reason)
{
    switch (reset_reason) {
    case 7u:  /* ESP_RST_INT_WDT in ESP-IDF */
    case 8u:  /* ESP_RST_TASK_WDT in ESP-IDF */
    case 9u:  /* ESP_RST_WDT in ESP-IDF */
    case 100u: /* host-test synthetic watchdog */
        return true;
    default:
        return false;
    }
}

void wdc_security_log_rejection(const WdcSecurityPreflightReport *report,
                                const WdcBundleVerifyResult *verify_result)
{
    char msg[WDC_DIAG_MESSAGE_MAX];
    const char *reason = report != NULL && report->reason[0] != '\0' ? report->reason : "production rejection";
    const char *bundle = verify_result != NULL && verify_result->manifest.bundle_id[0] != '\0' ? verify_result->manifest.bundle_id : "<unknown>";
    int32_t status = report != NULL ? report->status : WDC_ERR_UNKNOWN;

    /* Keep each diagnostic line bounded so production builds with -Werror do not
     * fail on format-truncation, while preserving enough context for audit logs.
     */
    (void)snprintf(msg, sizeof(msg), "prod reject: status=%s", wdc_status_name(status));
    (void)wdc_diag_log(WDC_LOG_ERROR, msg);
    (void)snprintf(msg, sizeof(msg), "prod reject bundle=%.40s", bundle);
    (void)wdc_diag_log(WDC_LOG_ERROR, msg);
    (void)snprintf(msg, sizeof(msg), "prod reject reason=%.48s", reason);
    (void)wdc_diag_log(WDC_LOG_ERROR, msg);
}
