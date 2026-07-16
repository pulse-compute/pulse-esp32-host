#include <assert.h>
#include <string.h>
#include "wdc_abi.h"
#include "wdc_bundle.h"
#include "wdc_diag.h"
#include "wdc_profile.h"
#include "wdc_security.h"

static void check_policy_and_antirollback(void) {
    WdcSecurityPolicy prod = wdc_security_production_policy();
    assert(prod.production_mode);
    assert(prod.require_secure_bundle_signature);
    assert(prod.reject_dev_signature);
    assert(prod.anti_rollback_enabled);
    assert(!prod.effectful_self_tests_allowed);
    assert(!prod.serial_install_allowed);
    assert(strcmp(wdc_security_profile_name(prod.profile), "production") == 0);

    WdcSecurityPolicy dev = wdc_security_development_policy();
    assert(!dev.production_mode);
    assert(dev.serial_install_allowed);
    assert(dev.effectful_self_tests_allowed);

    WdcBundleMetadataV1 metadata;
    wdc_bundle_metadata_init(&metadata);
    metadata.slot_a.state = WDC_SLOT_CONFIRMED;
    metadata.slot_a.security_counter = 7u;
    metadata.slot_b.state = WDC_SLOT_VERIFIED;
    metadata.slot_b.security_counter = 11u;
    assert(wdc_security_metadata_security_floor(&metadata) == 11u);

    WdcBundleVerifyPolicy verify = wdc_security_make_bundle_verify_policy(wdc_profile_builtin(), &metadata, &prod);
    assert(verify.production_mode);
    assert(!verify.allow_unsigned_dev);
    assert(verify.dev_hmac_key == 0);
    assert(verify.dev_hmac_key_len == 0u);
    assert(verify.min_security_counter == 11u);
    assert(verify.required_signature_alg != 0);
    assert(strcmp(verify.required_signature_alg, "ed25519") == 0);
}

static void check_provisioning_and_rejection_report(void) {
    WdcSecurityPolicy prod = wdc_security_production_policy();
    WdcProvisioningRecord record;
    memset(&record, 0, sizeof(record));
    strcpy(record.serial, "relay-0001");
    strcpy(record.device_class, wdc_profile_builtin()->device_class);
    strcpy(record.board_rev, wdc_profile_builtin()->board_rev);
    record.provisioned = true;
    assert(wdc_security_validate_provisioning(&record, wdc_profile_builtin(), &prod) == WDC_ERR_NOT_AVAILABLE);
    strcpy(record.trusted_signature_key_id, "prod-key-1");
    strcpy(record.ota_endpoint_prefix, "https://updates.example.com/relay/");
    assert(wdc_security_validate_provisioning(&record, wdc_profile_builtin(), &prod) == WDC_OK);

    WdcBundleVerifyResult verify;
    memset(&verify, 0, sizeof(verify));
    verify.status = WDC_OK;
    verify.signature_ok = true;
    verify.anti_rollback_ok = true;
    strcpy(verify.manifest.bundle_id, "com.example.bundle");
    strcpy(verify.manifest.signature_alg, "hmac-sha256-dev");
    WdcSecurityPreflightReport report;
    assert(wdc_security_validate_bundle_result(&prod, &verify, &report) == WDC_ERR_CONTRACT_VIOLATION);
    assert(report.dev_signature_rejected);
    wdc_security_log_rejection(&report, &verify);
    WdcDiagMetrics metrics;
    wdc_diag_get_metrics(&metrics);
    assert(metrics.fault_count >= 1u);
}

static void check_diagnostics(void) {
    assert(wdc_diag_init() == WDC_OK);
    wdc_diag_note_boot(100u, "host_watchdog");
    assert(wdc_diag_classify_reset(100u) == WDC_DIAG_RESET_WATCHDOG);
    assert(wdc_security_reset_reason_is_watchdog(100u));
    wdc_diag_record_breadcrumb(4, 2, WDC_ERR_CONTRACT_VIOLATION, 7, "bundle", 9u, "guest trapped");
    WdcDiagBreadcrumb breadcrumb;
    assert(wdc_diag_get_breadcrumb(&breadcrumb));
    assert(breadcrumb.magic == WDC_DIAG_BREADCRUMB_MAGIC);
    assert(breadcrumb.reset_class == WDC_DIAG_RESET_WATCHDOG);
    assert(breadcrumb.fault_status == WDC_ERR_CONTRACT_VIOLATION);
    assert(strcmp(breadcrumb.bundle, "bundle") == 0);
    char json[WDC_DIAG_EXPORT_JSON_MAX];
    uint32_t json_len = 0u;
    assert(wdc_diag_export_json(json, sizeof(json), &json_len) == WDC_OK);
    assert(json_len > 0u);
    assert(strstr(json, "watchdog") != 0);
    assert(strstr(json, "breadcrumb_present") != 0);
}

int main(void) {
    check_diagnostics();
    check_policy_and_antirollback();
    check_provisioning_and_rejection_report();
    return 0;
}
