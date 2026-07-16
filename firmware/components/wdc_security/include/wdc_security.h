#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "wdc_abi.h"
#include "wdc_bundle.h"
#include "wdc_profile.h"

#ifdef __cplusplus
extern "C" {
#endif

#define WDC_SECURITY_PROVISION_TEXT_MAX 96u
#define WDC_SECURITY_ENDPOINT_MAX       128u
#define WDC_SECURITY_KEY_ID_MAX         64u

#define WDC_SECURITY_DEFAULT_PROD_SIGNATURE_ALG "ed25519"

/* R9 production/security profile. Development allowances are explicit. */
typedef enum WdcSecurityBuildProfile {
    WDC_SECURITY_PROFILE_DEVELOPMENT = 0,
    WDC_SECURITY_PROFILE_PRODUCTION = 1,
} WdcSecurityBuildProfile;

typedef enum WdcSecurityMode {
    WDC_SECURITY_MODE_DEV = 0,
    WDC_SECURITY_MODE_PRODUCTION = 1,
} WdcSecurityMode;

#define WDC_SECURITY_FLAG_SECURE_BOOT       (1u << 0u)
#define WDC_SECURITY_FLAG_FLASH_ENCRYPTION  (1u << 1u)
#define WDC_SECURITY_FLAG_PROVISIONED_KEYS  (1u << 2u)
#define WDC_SECURITY_FLAG_OTA_ENDPOINT      (1u << 3u)
#define WDC_SECURITY_PRODUCTION_REQUIRED_FLAGS \
    (WDC_SECURITY_FLAG_SECURE_BOOT | WDC_SECURITY_FLAG_FLASH_ENCRYPTION | WDC_SECURITY_FLAG_PROVISIONED_KEYS | WDC_SECURITY_FLAG_OTA_ENDPOINT)

typedef struct WdcSecurityDeviceState {
    uint32_t flags;
} WdcSecurityDeviceState;

typedef struct WdcSecurityPolicy {
    WdcSecurityBuildProfile profile;
    bool production_mode;
    bool require_secure_bundle_signature;
    bool reject_dev_signature;
    bool anti_rollback_enabled;
    bool watchdog_rollback_enabled;
    bool effectful_self_tests_allowed;
    bool boot_diagnostic_probes_allowed;
    bool serial_install_allowed;
    bool profile_mutation_allowed;
    const char *required_signature_alg;
    const char *trusted_signature_key_id;
    const char *ota_endpoint_prefix;
} WdcSecurityPolicy;

typedef struct WdcProvisioningRecord {
    char serial[WDC_SECURITY_PROVISION_TEXT_MAX];
    char device_class[WDC_SECURITY_PROVISION_TEXT_MAX];
    char board_rev[WDC_SECURITY_PROVISION_TEXT_MAX];
    char trusted_signature_key_id[WDC_SECURITY_KEY_ID_MAX];
    char ota_endpoint_prefix[WDC_SECURITY_ENDPOINT_MAX];
    bool provisioned;
} WdcProvisioningRecord;

typedef struct WdcSecurityPreflightReport {
    int32_t status;
    uint32_t required_flags;
    uint32_t missing_flags;
    uint64_t security_floor;
    bool production_mode;
    bool secure_signature_required;
    bool anti_rollback_required;
    bool dev_signature_rejected;
    char reason[WDC_BUNDLE_MAX_REASON_BYTES];
} WdcSecurityPreflightReport;

typedef struct WdcSecurityBundlePolicyConfig {
    WdcSecurityMode mode;
    const WdcDeviceProfile *profile;
    uint64_t min_security_counter;
    const char *trusted_signature_key_id;
    WdcBundleSignatureVerifyFn signature_verify;
    void *signature_verify_ctx;
} WdcSecurityBundlePolicyConfig;

WdcSecurityPolicy wdc_security_development_policy(void);
WdcSecurityPolicy wdc_security_production_policy(void);
const char *wdc_security_profile_name(WdcSecurityBuildProfile profile);

WdcSecurityDeviceState wdc_security_default_dev_state(void);
WdcSecurityDeviceState wdc_security_default_production_state(void);
int32_t wdc_security_preflight(WdcSecurityMode mode,
                               const WdcSecurityDeviceState *state,
                               WdcSecurityPreflightReport *out_report);
WdcBundleVerifyPolicy wdc_security_make_bundle_policy(const WdcSecurityBundlePolicyConfig *config);

uint64_t wdc_security_metadata_security_floor(const WdcBundleMetadataV1 *metadata);
WdcBundleVerifyPolicy wdc_security_make_bundle_verify_policy(const WdcDeviceProfile *profile,
                                                             const WdcBundleMetadataV1 *metadata,
                                                             const WdcSecurityPolicy *security_policy);

int32_t wdc_security_validate_bundle_result(const WdcSecurityPolicy *security_policy,
                                            const WdcBundleVerifyResult *verify_result,
                                            WdcSecurityPreflightReport *out_report);

int32_t wdc_security_validate_provisioning(const WdcProvisioningRecord *record,
                                           const WdcDeviceProfile *profile,
                                           const WdcSecurityPolicy *security_policy);

bool wdc_security_reset_reason_is_watchdog(uint32_t reset_reason);
void wdc_security_log_rejection(const WdcSecurityPreflightReport *report,
                                const WdcBundleVerifyResult *verify_result);

#ifdef __cplusplus
}
#endif
