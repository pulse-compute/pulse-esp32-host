#include "wdc_activation.h"

#include <stdio.h>
#include <string.h>

static WdcBundleSlotRecord *mutable_record_for_slot(WdcBundleMetadataV1 *metadata, WdcBundleSlotId slot)
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

static const WdcBundleSlotRecord *record_for_slot(const WdcBundleMetadataV1 *metadata, WdcBundleSlotId slot)
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

static WdcActivationPolicy normalize_policy(const WdcActivationPolicy *policy)
{
    WdcActivationPolicy p = policy != NULL ? *policy : wdc_activation_default_policy();
    if (p.max_candidate_boots == 0u) {
        p.max_candidate_boots = WDC_ACTIVATION_DEFAULT_MAX_CANDIDATE_BOOTS;
    }
    if (p.required_health_checks == 0u) {
        p.required_health_checks = 1u;
    }
    return p;
}

static void decision_init(WdcActivationDecision *decision, WdcActivationDecisionKind kind, int32_t reason, const char *message)
{
    if (decision == NULL) {
        return;
    }
    memset(decision, 0, sizeof(*decision));
    decision->kind = kind;
    decision->slot_to_run = WDC_BUNDLE_SLOT_NONE;
    decision->candidate_slot = WDC_BUNDLE_SLOT_NONE;
    decision->fallback_slot = WDC_BUNDLE_SLOT_NONE;
    decision->reason = reason;
    if (message != NULL) {
        (void)snprintf(decision->message, sizeof(decision->message), "%s", message);
    }
}

static bool slot_is_confirmed(const WdcBundleMetadataV1 *metadata, WdcBundleSlotId slot)
{
    const WdcBundleSlotRecord *record = record_for_slot(metadata, slot);
    return record != NULL && record->state == WDC_SLOT_CONFIRMED;
}

static bool fallback_is_valid(const WdcBundleMetadataV1 *metadata)
{
    return metadata != NULL && metadata->last_good_slot != WDC_BUNDLE_SLOT_NONE && slot_is_confirmed(metadata, metadata->last_good_slot);
}

static int32_t rollback_to_last_good(WdcBundleMetadataV1 *metadata,
                                     WdcBundleSlotId failed_slot,
                                     int32_t failure_reason,
                                     WdcActivationDecision *out_decision,
                                     const char *message)
{
    if (metadata == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    WdcBundleSlotRecord *failed = mutable_record_for_slot(metadata, failed_slot);
    if (failed != NULL) {
        failed->state = WDC_SLOT_FAILED;
    }
    metadata->candidate_fault_count++;
    metadata->last_failure_reason = failure_reason;

    if (fallback_is_valid(metadata)) {
        metadata->active_slot = metadata->last_good_slot;
        metadata->metadata_generation++;
        int32_t seal = wdc_bundle_metadata_seal(metadata);
        decision_init(out_decision, WDC_ACTIVATION_DECISION_ROLLBACK_TO_LAST_GOOD, failure_reason, message != NULL ? message : "candidate failed; rolled back to last good");
        if (out_decision != NULL) {
            out_decision->candidate_slot = failed_slot;
            out_decision->fallback_slot = metadata->last_good_slot;
            out_decision->slot_to_run = metadata->last_good_slot;
            out_decision->rollback = true;
            out_decision->metadata_changed = true;
            out_decision->candidate_boot_count = metadata->candidate_boot_count;
        }
        return seal;
    }

    metadata->active_slot = WDC_BUNDLE_SLOT_NONE;
    metadata->metadata_generation++;
    int32_t seal = wdc_bundle_metadata_seal(metadata);
    decision_init(out_decision, WDC_ACTIVATION_DECISION_FAULT_NO_FALLBACK, failure_reason, message != NULL ? message : "candidate failed; no confirmed fallback");
    if (out_decision != NULL) {
        out_decision->candidate_slot = failed_slot;
        out_decision->fallback_slot = WDC_BUNDLE_SLOT_NONE;
        out_decision->slot_to_run = WDC_BUNDLE_SLOT_NONE;
        out_decision->rollback = true;
        out_decision->metadata_changed = true;
        out_decision->candidate_boot_count = metadata->candidate_boot_count;
    }
    return seal;
}

WdcActivationPolicy wdc_activation_default_policy(void)
{
    WdcActivationPolicy policy;
    policy.max_candidate_boots = WDC_ACTIVATION_DEFAULT_MAX_CANDIDATE_BOOTS;
    policy.required_health_checks = 1u;
    policy.fail_running_candidate_on_boot = true;
    return policy;
}

const char *wdc_activation_decision_name(WdcActivationDecisionKind kind)
{
    switch (kind) {
    case WDC_ACTIVATION_DECISION_NO_BUNDLE:
        return "no_bundle";
    case WDC_ACTIVATION_DECISION_RUN_CONFIRMED:
        return "run_confirmed";
    case WDC_ACTIVATION_DECISION_RUN_CANDIDATE:
        return "run_candidate";
    case WDC_ACTIVATION_DECISION_ROLLBACK_TO_LAST_GOOD:
        return "rollback_to_last_good";
    case WDC_ACTIVATION_DECISION_FAULT_NO_FALLBACK:
        return "fault_no_fallback";
    default:
        return "unknown";
    }
}

bool wdc_activation_slot_is_runnable(const WdcBundleMetadataV1 *metadata, WdcBundleSlotId slot)
{
    const WdcBundleSlotRecord *record = record_for_slot(metadata, slot);
    if (record == NULL) {
        return false;
    }
    return record->state == WDC_SLOT_CONFIRMED ||
           record->state == WDC_SLOT_PENDING ||
           record->state == WDC_SLOT_RUNNING_PENDING;
}

int32_t wdc_activation_prepare_pending(WdcBundleMetadataV1 *metadata,
                                       WdcBundleSlotId slot,
                                       const WdcActivationPolicy *policy)
{
    (void)policy;
    if (metadata == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    int32_t status = wdc_bundle_metadata_validate(metadata);
    if (status != WDC_OK) {
        return status;
    }
    WdcBundleSlotRecord *record = mutable_record_for_slot(metadata, slot);
    if (record == NULL) {
        return WDC_ERR_INVALID_RESOURCE;
    }
    if (record->state != WDC_SLOT_VERIFIED) {
        return WDC_ERR_INVALID_STATE;
    }

    if (metadata->active_slot != WDC_BUNDLE_SLOT_NONE && slot_is_confirmed(metadata, metadata->active_slot)) {
        metadata->last_good_slot = metadata->active_slot;
    }

    record->state = WDC_SLOT_PENDING;
    metadata->active_slot = slot;
    metadata->candidate_boot_count = 0u;
    metadata->candidate_fault_count = 0u;
    metadata->last_failure_reason = WDC_OK;
    metadata->metadata_generation++;
    return wdc_bundle_metadata_seal(metadata);
}

int32_t wdc_activation_on_boot(WdcBundleMetadataV1 *metadata,
                               const WdcActivationPolicy *policy,
                               WdcActivationDecision *out_decision)
{
    if (metadata == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    WdcActivationPolicy p = normalize_policy(policy);
    int32_t status = wdc_bundle_metadata_validate(metadata);
    if (status != WDC_OK) {
        decision_init(out_decision, WDC_ACTIVATION_DECISION_FAULT_NO_FALLBACK, status, "metadata validation failed");
        return status;
    }

    if (metadata->active_slot == WDC_BUNDLE_SLOT_NONE) {
        if (fallback_is_valid(metadata)) {
            metadata->active_slot = metadata->last_good_slot;
            metadata->metadata_generation++;
            status = wdc_bundle_metadata_seal(metadata);
            decision_init(out_decision, WDC_ACTIVATION_DECISION_RUN_CONFIRMED, WDC_OK, "running last good confirmed slot");
            if (out_decision != NULL) {
                out_decision->slot_to_run = metadata->active_slot;
                out_decision->fallback_slot = metadata->last_good_slot;
                out_decision->metadata_changed = true;
            }
            return status;
        }
        decision_init(out_decision, WDC_ACTIVATION_DECISION_NO_BUNDLE, WDC_ERR_NOT_AVAILABLE, "no active or last-good bundle");
        return WDC_OK;
    }

    WdcBundleSlotRecord *record = mutable_record_for_slot(metadata, metadata->active_slot);
    if (record == NULL) {
        return rollback_to_last_good(metadata, metadata->active_slot, WDC_ERR_INVALID_RESOURCE, out_decision, "invalid active slot; rollback attempted");
    }

    switch (record->state) {
    case WDC_SLOT_CONFIRMED: {
        bool changed = metadata->last_good_slot != metadata->active_slot;
        if (changed) {
            metadata->last_good_slot = metadata->active_slot;
            metadata->metadata_generation++;
            status = wdc_bundle_metadata_seal(metadata);
            if (status != WDC_OK) {
                return status;
            }
        }
        decision_init(out_decision, WDC_ACTIVATION_DECISION_RUN_CONFIRMED, WDC_OK, "running confirmed slot");
        if (out_decision != NULL) {
            out_decision->slot_to_run = metadata->active_slot;
            out_decision->fallback_slot = metadata->last_good_slot;
            out_decision->metadata_changed = changed;
        }
        return WDC_OK;
    }

    case WDC_SLOT_PENDING:
        if (metadata->candidate_boot_count >= p.max_candidate_boots) {
            return rollback_to_last_good(metadata, metadata->active_slot, WDC_ERR_TIMEOUT, out_decision, "candidate exceeded boot attempt budget");
        }
        metadata->candidate_boot_count++;
        record->state = WDC_SLOT_RUNNING_PENDING;
        metadata->metadata_generation++;
        status = wdc_bundle_metadata_seal(metadata);
        decision_init(out_decision, WDC_ACTIVATION_DECISION_RUN_CANDIDATE, WDC_OK, "running candidate in probation");
        if (out_decision != NULL) {
            out_decision->slot_to_run = metadata->active_slot;
            out_decision->candidate_slot = metadata->active_slot;
            out_decision->fallback_slot = metadata->last_good_slot;
            out_decision->probation = true;
            out_decision->metadata_changed = true;
            out_decision->candidate_boot_count = metadata->candidate_boot_count;
        }
        return status;

    case WDC_SLOT_RUNNING_PENDING:
        if (p.fail_running_candidate_on_boot) {
            return rollback_to_last_good(metadata, metadata->active_slot, WDC_ERR_NOT_SYNCHRONIZED, out_decision, "candidate rebooted before confirmation");
        }
        decision_init(out_decision, WDC_ACTIVATION_DECISION_RUN_CANDIDATE, WDC_OK, "resuming candidate probation");
        if (out_decision != NULL) {
            out_decision->slot_to_run = metadata->active_slot;
            out_decision->candidate_slot = metadata->active_slot;
            out_decision->fallback_slot = metadata->last_good_slot;
            out_decision->probation = true;
            out_decision->candidate_boot_count = metadata->candidate_boot_count;
        }
        return WDC_OK;

    case WDC_SLOT_VERIFIED:
    case WDC_SLOT_DOWNLOADED:
    case WDC_SLOT_EMPTY:
    case WDC_SLOT_FAILED:
    default:
        return rollback_to_last_good(metadata, metadata->active_slot, WDC_ERR_INVALID_STATE, out_decision, "active slot is not runnable");
    }
}

int32_t wdc_activation_confirm(WdcBundleMetadataV1 *metadata,
                               WdcBundleSlotId slot,
                               uint32_t observed_health_checks)
{
    if (metadata == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    if (observed_health_checks == 0u) {
        return WDC_ERR_INVALID_STATE;
    }
    int32_t status = wdc_bundle_metadata_validate(metadata);
    if (status != WDC_OK) {
        return status;
    }
    if (metadata->active_slot != slot) {
        return WDC_ERR_INVALID_STATE;
    }
    WdcBundleSlotRecord *record = mutable_record_for_slot(metadata, slot);
    if (record == NULL) {
        return WDC_ERR_INVALID_RESOURCE;
    }
    if (record->state != WDC_SLOT_RUNNING_PENDING && record->state != WDC_SLOT_PENDING) {
        return WDC_ERR_INVALID_STATE;
    }
    record->state = WDC_SLOT_CONFIRMED;
    metadata->active_slot = slot;
    metadata->last_good_slot = slot;
    metadata->candidate_boot_count = 0u;
    metadata->candidate_fault_count = 0u;
    metadata->last_failure_reason = WDC_OK;
    metadata->metadata_generation++;
    return wdc_bundle_metadata_seal(metadata);
}

int32_t wdc_activation_record_fault(WdcBundleMetadataV1 *metadata,
                                    WdcBundleSlotId slot,
                                    int32_t failure_reason,
                                    WdcActivationDecision *out_decision)
{
    if (metadata == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    int32_t status = wdc_bundle_metadata_validate(metadata);
    if (status != WDC_OK) {
        return status;
    }
    WdcBundleSlotRecord *record = mutable_record_for_slot(metadata, slot);
    if (record == NULL) {
        return WDC_ERR_INVALID_RESOURCE;
    }
    if (record->state != WDC_SLOT_PENDING && record->state != WDC_SLOT_RUNNING_PENDING) {
        return WDC_ERR_INVALID_STATE;
    }
    return rollback_to_last_good(metadata, slot, failure_reason, out_decision, "candidate faulted during probation");
}

int32_t wdc_activation_abort_pending(WdcBundleMetadataV1 *metadata,
                                     WdcBundleSlotId slot,
                                     int32_t failure_reason,
                                     WdcActivationDecision *out_decision)
{
    return wdc_activation_record_fault(metadata, slot, failure_reason, out_decision);
}
