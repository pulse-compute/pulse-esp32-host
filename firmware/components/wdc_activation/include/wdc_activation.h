#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "wdc_bundle.h"

#ifdef __cplusplus
extern "C" {
#endif

#define WDC_ACTIVATION_METADATA_SCHEMA "wdc.activation.metadata.v1"
#define WDC_ACTIVATION_DEFAULT_MAX_CANDIDATE_BOOTS 1u
#define WDC_ACTIVATION_DEFAULT_MINIMUM_STABLE_MS 30000u
#define WDC_ACTIVATION_DEFAULT_READINESS_DEADLINE_MS 60000u

typedef enum WdcActivationDecisionKind {
    WDC_ACTIVATION_DECISION_NO_BUNDLE = 0,
    WDC_ACTIVATION_DECISION_RUN_CONFIRMED = 1,
    WDC_ACTIVATION_DECISION_RUN_CANDIDATE = 2,
    WDC_ACTIVATION_DECISION_ROLLBACK_TO_LAST_GOOD = 3,
    WDC_ACTIVATION_DECISION_FAULT_NO_FALLBACK = 4,
    WDC_ACTIVATION_DECISION_ENTER_RECOVERY = 5,
} WdcActivationDecisionKind;

typedef enum WdcActivationResetAttribution {
    WDC_ACTIVATION_RESET_NONE = 0,
    WDC_ACTIVATION_RESET_POWER_ON = 1,
    WDC_ACTIVATION_RESET_HOST_SOFTWARE = 2,
    WDC_ACTIVATION_RESET_GUEST_TRAP = 3,
    WDC_ACTIVATION_RESET_APPLICATION_WATCHDOG = 4,
    WDC_ACTIVATION_RESET_HOST_WATCHDOG = 5,
    WDC_ACTIVATION_RESET_UNKNOWN = 6,
} WdcActivationResetAttribution;

typedef struct WdcActivationPolicy {
    uint32_t max_candidate_boots;
    uint32_t required_health_checks;
    uint32_t minimum_stable_ms;
    uint32_t readiness_deadline_ms;
    uint32_t max_candidate_faults;
    bool fail_running_candidate_on_boot;
    bool require_admin_responsive;
    bool require_resource_floors;
} WdcActivationPolicy;

typedef struct WdcActivationBootContext {
    WdcActivationResetAttribution reset_attribution;
    uint32_t boot_sequence;
} WdcActivationBootContext;

typedef struct WdcActivationProbationEvidence {
    uint32_t elapsed_ms;
    uint32_t observed_health_checks;
    uint32_t fatal_fault_count;
    int32_t fatal_failure_reason;
    bool readiness_observed;
    bool administration_responsive;
    bool resource_floors_preserved;
} WdcActivationProbationEvidence;

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

int32_t wdc_activation_on_boot_attributed(
    WdcBundleMetadataV1 *metadata,
    const WdcActivationPolicy *policy,
    const WdcActivationBootContext *boot_context,
    WdcActivationDecision *out_decision);

int32_t wdc_activation_confirm(WdcBundleMetadataV1 *metadata,
                               WdcBundleSlotId slot,
                               uint32_t observed_health_checks);

int32_t wdc_activation_evaluate_probation(
    WdcBundleMetadataV1 *metadata,
    WdcBundleSlotId slot,
    const WdcActivationPolicy *policy,
    const WdcActivationProbationEvidence *evidence,
    WdcActivationDecision *out_decision);

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
