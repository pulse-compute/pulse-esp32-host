#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "wdc_activation.h"
#include "wdc_bundle.h"
#include "wdc_profile.h"
#include "wdc_runtime.h"

#ifdef __cplusplus
extern "C" {
#endif

#define WDC_APP_BOOT_REASON_MAX 160u

typedef struct WdcAppBootReport {
    int32_t status;
    WdcBundleSlotId selected_slot;
    bool used_active_slot;
    bool probation;
    bool confirmed_candidate;
    bool metadata_written;
    bool rollback;
    bool no_bundle;
    uint32_t bundle_len;
    uint32_t payload_len;
    char bundle_id[WDC_BUNDLE_MAX_ID_BYTES];
    uint32_t bundle_version;
    WdcActivationDecision activation_decision;
    WdcRuntimeReport runtime_report;
    char reason[WDC_APP_BOOT_REASON_MAX];
} WdcAppBootReport;

int32_t wdc_app_boot_active_slot(const WdcDeviceProfile *profile,
                                 WdcBundleMetadataV1 *metadata,
                                 const WdcActivationPolicy *activation_policy,
                                 const WdcBundleVerifyPolicy *verify_policy,
                                 WdcRuntime *runtime,
                                 const WdcRuntimeConfig *runtime_config,
                                 uint8_t *bundle_buffer,
                                 uint32_t bundle_buffer_cap,
                                 WdcAppBootReport *out_report);

void wdc_app_clear_active_authorizer(void);

#ifdef __cplusplus
}
#endif
