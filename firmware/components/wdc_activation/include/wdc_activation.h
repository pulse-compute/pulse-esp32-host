#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "wdc_bundle.h"

#ifdef __cplusplus
extern "C" {
#endif

#define WDC_ACTIVATION_METADATA_SCHEMA "wdc.activation.metadata.v1"
#define WDC_ACTIVATION_DEFAULT_MAX_CANDIDATE_BOOTS 1u

typedef enum WdcActivationDecisionKind {
    WDC_ACTIVATION_DECISION_NO_BUNDLE = 0,
    WDC_ACTIVATION_DECISION_RUN_CONFIRMED = 1,
    WDC_ACTIVATION_DECISION_RUN_CANDIDATE = 2,
    WDC_ACTIVATION_DECISION_ROLLBACK_TO_LAST_GOOD = 3,
    WDC_ACTIVATION_DECISION_FAULT_NO_FALLBACK = 4,
} WdcActivationDecisionKind;

typedef struct WdcActivationPolicy {
    uint32_t max_candidate_boots;
    uint32_t required_health_checks;
    bool fail_running_candidate_on_boot;
} WdcActivationPolicy;

typedef struct WdcActivationDecision {
    WdcActivationDecisionKind kind;
    WdcBundleSlotId slot_to_run;
    WdcBundleSlotId candidate_slot;
    WdcBundleSlotId fallback_slot;
    bool probation;
    bool metadata_changed;
    bool rollback;
    int32_t reason;
    uint32_t candidate_boot_count;
    char message[128];
} WdcActivationDecision;

WdcActivationPolicy wdc_activation_default_policy(void);
const char *wdc_activation_decision_name(WdcActivationDecisionKind kind);

int32_t wdc_activation_prepare_pending(WdcBundleMetadataV1 *metadata,
                                       WdcBundleSlotId slot,
                                       const WdcActivationPolicy *policy);

int32_t wdc_activation_on_boot(WdcBundleMetadataV1 *metadata,
                               const WdcActivationPolicy *policy,
                               WdcActivationDecision *out_decision);

int32_t wdc_activation_confirm(WdcBundleMetadataV1 *metadata,
                               WdcBundleSlotId slot,
                               uint32_t observed_health_checks);

int32_t wdc_activation_record_fault(WdcBundleMetadataV1 *metadata,
                                    WdcBundleSlotId slot,
                                    int32_t failure_reason,
                                    WdcActivationDecision *out_decision);

int32_t wdc_activation_abort_pending(WdcBundleMetadataV1 *metadata,
                                     WdcBundleSlotId slot,
                                     int32_t failure_reason,
                                     WdcActivationDecision *out_decision);

bool wdc_activation_slot_is_runnable(const WdcBundleMetadataV1 *metadata,
                                     WdcBundleSlotId slot);

#ifdef __cplusplus
}
#endif
