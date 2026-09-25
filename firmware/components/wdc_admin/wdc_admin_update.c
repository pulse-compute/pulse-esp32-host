#include "wdc_admin_update.h"

#include <limits.h>
#include <stddef.h>
#include <string.h>

#include "wdc_ota.h"

_Static_assert(WDC_ADMIN_UPDATE_WORKING_BYTES == 65536u,
               "HP4.2 update working set drifted from HP1");
_Static_assert(WDC_ADMIN_UPDATE_LARGEST_ALLOCATION_BYTES == 65536u,
               "HP4.2 largest allocation drifted from HP1");
_Static_assert(WDC_ADMIN_UPDATE_MAX_CHUNK_BYTES ==
                   WDC_ADMIN_MAX_PAYLOAD_BYTES,
               "HP4.2 stream chunk drifted from HP4.0");

static bool bytes_equal(const uint8_t *left,
                        const uint8_t *right,
                        uint32_t length)
{
    uint8_t difference = 0u;
    uint32_t index;
    if (left == NULL || right == NULL) {
        return false;
    }
    for (index = 0u; index < length; ++index) {
        difference = (uint8_t)(difference |
                               (uint8_t)(left[index] ^ right[index]));
    }
    return difference == 0u;
}

static bool checked_deadline(uint64_t now_ms,
                             uint64_t duration_ms,
                             uint64_t *out_deadline_ms)
{
    if (out_deadline_ms == NULL || now_ms > UINT64_MAX - duration_ms) {
        return false;
    }
    *out_deadline_ms = now_ms + duration_ms;
    return true;
}

static bool slot_valid(WdcBundleSlotId slot)
{
    return slot == WDC_BUNDLE_SLOT_A || slot == WDC_BUNDLE_SLOT_B;
}

static const WdcBundleSlotRecord *slot_record(
    const WdcBundleMetadataV1 *metadata,
    WdcBundleSlotId slot)
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

static bool slot_record_equal(const WdcBundleSlotRecord *left,
                              const WdcBundleSlotRecord *right)
{
    return left != NULL && right != NULL && left->state == right->state &&
           left->bundle_version == right->bundle_version &&
           left->security_counter == right->security_counter &&
           left->artifact_format_version == right->artifact_format_version &&
           left->artifact_bytes == right->artifact_bytes &&
           bytes_equal(left->payload_sha256, right->payload_sha256,
                       WDC_BUNDLE_SHA256_BYTES) &&
           bytes_equal(left->artifact_sha256, right->artifact_sha256,
                       WDC_BUNDLE_SHA256_BYTES);
}

static bool authority_preserved(const WdcAdminUpdateEngine *engine,
                                const WdcBundleMetadataV1 *metadata)
{
    const WdcBundleSlotRecord *record;
    if (engine == NULL || metadata == NULL ||
        metadata->active_slot != engine->authority_active_slot ||
        metadata->last_good_slot != engine->authority_last_good_slot) {
        return false;
    }
    if (!slot_valid(engine->authority_last_good_slot)) {
        return engine->authority_last_good_slot == WDC_BUNDLE_SLOT_NONE;
    }
    record = slot_record(metadata, engine->authority_last_good_slot);
    return slot_record_equal(record, &engine->last_confirmed_record);
}

static WdcAdminMode idle_mode(const WdcAdminUpdateEngine *engine)
{
    return engine != NULL && engine->recovery_origin
               ? WDC_ADMIN_MODE_RECOVERY
               : WDC_ADMIN_MODE_NORMAL;
}

static bool command_matches_transaction(const WdcAdminUpdateEngine *engine,
                                        const WdcAdminAcceptedCommand *command)
{
    return engine != NULL && command != NULL &&
           command->request.slot == (uint32_t)engine->target_slot &&
           command->request.expected_total_bytes ==
               engine->expected_total_bytes &&
           bytes_equal(command->request.artifact_sha256,
                       engine->expected_artifact_sha256,
                       WDC_BUNDLE_SHA256_BYTES);
}

static bool accepted_command_is_current(const WdcAdminUpdateEngine *engine,
                                        const WdcAdminAcceptedCommand *command)
{
    const WdcAdminCore *core;
    if (engine == NULL || command == NULL || engine->core == NULL) {
        return false;
    }
    core = engine->core;
    return core->lifecycle == WDC_ADMIN_LIFECYCLE_IN_PROGRESS &&
           core->active_control_ticket == command->control_ticket &&
           core->active_request.request_id == command->request.request_id &&
           core->active_request.command_sequence ==
               command->request.command_sequence &&
           core->active_request.command == command->request.command;
}

static int32_t emit_audit(WdcAdminUpdateEngine *engine,
                          WdcAdminAuditEvent event,
                          WdcAdminAuditOutcome outcome,
                          WdcAdminMode from_state,
                          WdcAdminMode to_state,
                          int32_t status,
                          uint32_t slot,
                          const uint8_t *artifact_sha256,
                          uint64_t now_ms)
{
    WdcAdminAuditEmission emission;
    memset(&emission, 0, sizeof(emission));
    emission.event = event;
    emission.outcome = outcome;
    emission.from_state = from_state;
    emission.to_state = to_state;
    emission.status = status;
    emission.slot = slot;
    if (artifact_sha256 != NULL) {
        memcpy(emission.artifact_sha256, artifact_sha256,
               sizeof(emission.artifact_sha256));
    }
    return wdc_admin_audit_emit(engine->core, &emission, now_ms);
}

static int32_t transition_mode(WdcAdminUpdateEngine *engine,
                               WdcAdminMode expected,
                               WdcAdminMode next,
                               WdcAdminAuditEvent event,
                               WdcAdminAuditOutcome outcome,
                               int32_t status,
                               uint64_t now_ms)
{
    int32_t audit_status;
    if (engine == NULL || engine->core == NULL ||
        engine->core->mode != expected) {
        return WDC_ERR_INVALID_STATE;
    }
    engine->core->mode = next;
    audit_status = emit_audit(engine, event, outcome, expected, next, status,
                              (uint32_t)engine->target_slot,
                              engine->expected_artifact_sha256, now_ms);
    if (audit_status != WDC_OK) {
        engine->core->mode = expected;
        return audit_status;
    }
    return WDC_OK;
}

static void clear_transaction(WdcAdminUpdateEngine *engine,
                              WdcAdminUpdateState next_state)
{
    if (engine == NULL) {
        return;
    }
    memset(&engine->stage, 0, sizeof(engine->stage));
    memset(&engine->stage_result, 0, sizeof(engine->stage_result));
    memset(&engine->admission, 0, sizeof(engine->admission));
    engine->state = next_state;
    engine->target_slot = WDC_BUNDLE_SLOT_NONE;
    engine->authority_active_slot = WDC_BUNDLE_SLOT_NONE;
    engine->authority_last_good_slot = WDC_BUNDLE_SLOT_NONE;
    memset(&engine->last_confirmed_record, 0,
           sizeof(engine->last_confirmed_record));
    engine->expected_total_bytes = 0u;
    engine->streamed_bytes = 0u;
    engine->metadata_commits = 0u;
    engine->rate_window_chunks = 0u;
    engine->rate_window_bytes = 0u;
    engine->transaction_deadline_ms = 0u;
    engine->stream_idle_deadline_ms = 0u;
    engine->rate_window_start_ms = 0u;
    memset(engine->expected_artifact_sha256, 0,
           sizeof(engine->expected_artifact_sha256));
    engine->staging_active = false;
    engine->verification_complete = false;
}

static int32_t complete_current(WdcAdminUpdateEngine *engine,
                                WdcAdminTerminalResult result,
                                int32_t status,
                                WdcAdminMode final_mode,
                                uint32_t slot,
                                uint64_t now_ms)
{
    WdcAdminTerminalMetadata metadata;
    memset(&metadata, 0, sizeof(metadata));
    metadata.bytes_received = engine->streamed_bytes;
    metadata.metadata_commits = engine->metadata_commits;
    metadata.final_state = (uint32_t)final_mode;
    metadata.slot = slot;
    return wdc_admin_complete(engine->core, result, status, &metadata, now_ms);
}

static int32_t abort_staging(WdcAdminUpdateEngine *engine)
{
    int32_t status = WDC_OK;
    if (engine->staging_active) {
        status = wdc_app_slots_stage_abort(&engine->stage);
        engine->staging_active = false;
    }
    return status;
}

static int32_t fail_current(WdcAdminUpdateEngine *engine,
                            int32_t status,
                            uint64_t now_ms)
{
    WdcBundleSlotId target = engine->target_slot;
    WdcAdminMode return_mode = idle_mode(engine);
    int32_t abort_status = abort_staging(engine);
    int32_t complete_status;
    if (status == WDC_OK) {
        status = WDC_ERR_CONTRACT_VIOLATION;
    }
    if (abort_status != WDC_OK) {
        status = abort_status;
    }
    if (!slot_valid(target) && engine->core != NULL &&
        slot_valid((WdcBundleSlotId)engine->core->active_request.slot)) {
        target = (WdcBundleSlotId)engine->core->active_request.slot;
    }
    if (engine->expected_total_bytes != 0u &&
        !authority_preserved(engine, engine->metadata)) {
        status = WDC_ERR_CONTRACT_VIOLATION;
    }
    if (engine->core->mode == WDC_ADMIN_MODE_QUIESCE) {
        (void)transition_mode(engine, WDC_ADMIN_MODE_QUIESCE,
                              return_mode,
                              WDC_ADMIN_AUDIT_QUIESCE,
                              WDC_ADMIN_AUDIT_FAILED, status, now_ms);
    } else if (engine->core->mode == WDC_ADMIN_MODE_UPDATE) {
        (void)transition_mode(engine, WDC_ADMIN_MODE_UPDATE,
                              return_mode,
                              WDC_ADMIN_AUDIT_STAGING,
                              WDC_ADMIN_AUDIT_FAILED, status, now_ms);
    }
    complete_status = complete_current(
        engine,
        status == WDC_ERR_TIMEOUT ? WDC_ADMIN_TERMINAL_TIMED_OUT
                                  : WDC_ADMIN_TERMINAL_FAILED,
        status, return_mode, (uint32_t)target, now_ms);
    clear_transaction(engine, WDC_ADMIN_UPDATE_STATE_IDLE);
    return complete_status == WDC_OK ? status : complete_status;
}

static bool quiescence_valid(const WdcAdminUpdateQuiesceEvidence *evidence,
                             uint64_t started_ms,
                             uint64_t deadline_ms)
{
    return evidence != NULL && evidence->guest_quiesced == 1u &&
           evidence->native_refinements_quiesced == 1u &&
           evidence->guest_unloaded == 1u &&
           evidence->native_refinements_unloaded == 1u &&
           evidence->guest_loaded_after == 0u &&
           evidence->native_refinements_loaded_after == 0u &&
           evidence->flags == 0u && evidence->reserved == 0u &&
           evidence->completed_monotonic_ms >= started_ms &&
           evidence->completed_monotonic_ms < deadline_ms;
}

static int32_t begin_update(WdcAdminUpdateEngine *engine,
                            const WdcAdminAcceptedCommand *command,
                            uint64_t now_ms)
{
    WdcAdminUpdateQuiesceEvidence evidence;
    WdcControlHeapSnapshot heap;
    const WdcBundleSlotRecord *confirmed;
    WdcAdminMode origin;
    WdcAdminMode staging_origin;
    uint64_t quiesce_deadline;
    int32_t status;
    if (engine->state != WDC_ADMIN_UPDATE_STATE_IDLE ||
        (engine->core->mode != WDC_ADMIN_MODE_NORMAL &&
         engine->core->mode != WDC_ADMIN_MODE_RECOVERY) ||
        wdc_bundle_metadata_validate(engine->metadata) != WDC_OK ||
        !slot_valid((WdcBundleSlotId)command->request.slot) ||
        (WdcBundleSlotId)command->request.slot !=
            wdc_app_slots_inactive_slot(engine->metadata)) {
        return fail_current(engine, WDC_ERR_INVALID_STATE, now_ms);
    }
    origin = engine->core->mode;
    engine->recovery_origin = origin == WDC_ADMIN_MODE_RECOVERY;
    confirmed = slot_record(engine->metadata,
                            engine->metadata->last_good_slot);
    if ((origin == WDC_ADMIN_MODE_NORMAL &&
         (engine->metadata->active_slot !=
              engine->metadata->last_good_slot ||
          confirmed == NULL || confirmed->state != WDC_SLOT_CONFIRMED)) ||
        (origin == WDC_ADMIN_MODE_RECOVERY &&
         slot_valid(engine->metadata->last_good_slot) &&
         (confirmed == NULL || confirmed->state != WDC_SLOT_CONFIRMED))) {
        return fail_current(engine, WDC_ERR_INVALID_STATE, now_ms);
    }
    engine->target_slot = (WdcBundleSlotId)command->request.slot;
    engine->authority_active_slot = engine->metadata->active_slot;
    engine->authority_last_good_slot = engine->metadata->last_good_slot;
    if (confirmed != NULL) {
        engine->last_confirmed_record = *confirmed;
    }
    engine->expected_total_bytes = command->request.expected_total_bytes;
    memcpy(engine->expected_artifact_sha256,
           command->request.artifact_sha256,
           sizeof(engine->expected_artifact_sha256));
    if (!checked_deadline(now_ms, WDC_ADMIN_UPDATE_TRANSACTION_DEADLINE_MS,
                          &engine->transaction_deadline_ms)) {
        return fail_current(engine, WDC_ERR_BAD_LENGTH, now_ms);
    }
    staging_origin = origin;
    if (origin == WDC_ADMIN_MODE_NORMAL) {
        if (!checked_deadline(now_ms, WDC_ADMIN_UPDATE_QUIESCE_DEADLINE_MS,
                              &quiesce_deadline)) {
            return fail_current(engine, WDC_ERR_BAD_LENGTH, now_ms);
        }
        engine->state = WDC_ADMIN_UPDATE_STATE_QUIESCING;
        status = transition_mode(engine, WDC_ADMIN_MODE_NORMAL,
                                 WDC_ADMIN_MODE_QUIESCE,
                                 WDC_ADMIN_AUDIT_QUIESCE,
                                 WDC_ADMIN_AUDIT_OBSERVED, WDC_OK, now_ms);
        if (status != WDC_OK) {
            return fail_current(engine, status, now_ms);
        }
        memset(&evidence, 0, sizeof(evidence));
        status = engine->lifecycle.quiesce_and_unload(
            engine->lifecycle.context, quiesce_deadline, &evidence);
        if (status != WDC_OK ||
            !quiescence_valid(&evidence, now_ms, quiesce_deadline)) {
            return fail_current(engine,
                                status != WDC_OK
                                    ? status
                                    : WDC_ERR_CONTRACT_VIOLATION,
                                now_ms);
        }
        status = emit_audit(engine, WDC_ADMIN_AUDIT_QUIESCE,
                            WDC_ADMIN_AUDIT_ALLOWED,
                            WDC_ADMIN_MODE_QUIESCE,
                            WDC_ADMIN_MODE_QUIESCE, WDC_OK,
                            (uint32_t)engine->target_slot,
                            engine->expected_artifact_sha256,
                            evidence.completed_monotonic_ms);
        if (status != WDC_OK) {
            return fail_current(engine, status, now_ms);
        }
        staging_origin = WDC_ADMIN_MODE_QUIESCE;
    }
    memset(&heap, 0, sizeof(heap));
    status = engine->lifecycle.heap_snapshot_after_unload(
        engine->lifecycle.context, &heap);
    if (status == WDC_OK) {
        status = wdc_control_admit_exclusive_update(
            engine->core->control_kernel->profile, &heap,
            &engine->admission);
    }
    if (status != WDC_OK ||
        engine->admission.fixed_control_reserve_bytes != 98304u ||
        engine->admission.exclusive_update_required_bytes != 163840u ||
        engine->admission.required_largest_block_bytes != 98304u) {
        return fail_current(engine,
                            status != WDC_OK ? status :
                                               WDC_ERR_CONTRACT_VIOLATION,
                            now_ms);
    }
    status = wdc_app_slots_stage_begin(&engine->stage, engine->metadata,
                                       engine->target_slot,
                                       engine->expected_total_bytes);
    if (status != WDC_OK) {
        return fail_current(engine, status, now_ms);
    }
    engine->staging_active = true;
    if (!authority_preserved(engine, engine->metadata)) {
        return fail_current(engine, WDC_ERR_CONTRACT_VIOLATION, now_ms);
    }
    status = transition_mode(engine, staging_origin,
                             WDC_ADMIN_MODE_UPDATE,
                             WDC_ADMIN_AUDIT_STAGING,
                             WDC_ADMIN_AUDIT_ALLOWED, WDC_OK, now_ms);
    if (status != WDC_OK) {
        return fail_current(engine, status, now_ms);
    }
    engine->state = WDC_ADMIN_UPDATE_STATE_STREAMING;
    engine->rate_window_start_ms = now_ms;
    if (!checked_deadline(now_ms, WDC_ADMIN_UPDATE_STREAM_IDLE_DEADLINE_MS,
                          &engine->stream_idle_deadline_ms)) {
        return fail_current(engine, WDC_ERR_BAD_LENGTH, now_ms);
    }
    return complete_current(engine, WDC_ADMIN_TERMINAL_SUCCEEDED, WDC_OK,
                            WDC_ADMIN_MODE_UPDATE,
                            (uint32_t)engine->target_slot, now_ms);
}

static int32_t update_rate_gate(WdcAdminUpdateEngine *engine,
                                uint32_t bytes,
                                uint64_t now_ms)
{
    if (now_ms < engine->rate_window_start_ms ||
        now_ms >= engine->stream_idle_deadline_ms ||
        now_ms >= engine->transaction_deadline_ms) {
        return WDC_ERR_TIMEOUT;
    }
    if (now_ms - engine->rate_window_start_ms >=
        WDC_ADMIN_UPDATE_RATE_WINDOW_MS) {
        engine->rate_window_start_ms = now_ms;
        engine->rate_window_chunks = 0u;
        engine->rate_window_bytes = 0u;
    }
    if (engine->rate_window_chunks >=
            WDC_ADMIN_UPDATE_RATE_CHUNKS_PER_WINDOW ||
        engine->rate_window_bytes >
            WDC_ADMIN_UPDATE_RATE_BYTES_PER_WINDOW - bytes) {
        return WDC_ERR_RATE_LIMITED;
    }
    engine->rate_window_chunks += 1u;
    engine->rate_window_bytes += bytes;
    return WDC_OK;
}

static int32_t write_chunk(WdcAdminUpdateEngine *engine,
                           const WdcAdminAcceptedCommand *command,
                           uint64_t now_ms)
{
    int32_t status;
    if (engine->state != WDC_ADMIN_UPDATE_STATE_STREAMING ||
        !engine->staging_active ||
        !command_matches_transaction(engine, command) ||
        command->payload == NULL || command->payload_bytes == 0u ||
        command->payload_bytes > WDC_ADMIN_UPDATE_MAX_CHUNK_BYTES ||
        command->payload_bytes > engine->expected_total_bytes ||
        engine->streamed_bytes >
            engine->expected_total_bytes - command->payload_bytes) {
        return fail_current(engine, WDC_ERR_BAD_LENGTH, now_ms);
    }
    status = update_rate_gate(engine, command->payload_bytes, now_ms);
    if (status != WDC_OK) {
        return fail_current(engine, status, now_ms);
    }
    status = wdc_app_slots_stage_write(&engine->stage, command->payload,
                                       command->payload_bytes);
    if (status != WDC_OK) {
        return fail_current(engine, status, now_ms);
    }
    engine->streamed_bytes += command->payload_bytes;
    if (!checked_deadline(now_ms, WDC_ADMIN_UPDATE_STREAM_IDLE_DEADLINE_MS,
                          &engine->stream_idle_deadline_ms) ||
        !authority_preserved(engine, engine->metadata)) {
        return fail_current(engine, WDC_ERR_CONTRACT_VIOLATION, now_ms);
    }
    status = emit_audit(engine, WDC_ADMIN_AUDIT_STAGING,
                        WDC_ADMIN_AUDIT_ALLOWED, WDC_ADMIN_MODE_UPDATE,
                        WDC_ADMIN_MODE_UPDATE, WDC_OK,
                        (uint32_t)engine->target_slot,
                        engine->expected_artifact_sha256, now_ms);
    if (status != WDC_OK) {
        return fail_current(engine, status, now_ms);
    }
    return complete_current(engine, WDC_ADMIN_TERMINAL_SUCCEEDED, WDC_OK,
                            WDC_ADMIN_MODE_UPDATE,
                            (uint32_t)engine->target_slot, now_ms);
}

static void make_candidate(const WdcAdminUpdateEngine *engine,
                           WdcAdminArtifactCandidate *candidate)
{
    memset(candidate, 0, sizeof(*candidate));
    candidate->struct_size = sizeof(*candidate);
    candidate->version_major = WDC_ADMIN_VERSION_MAJOR;
    candidate->version_minor = WDC_ADMIN_VERSION_MINOR;
    candidate->slot = (uint32_t)engine->target_slot;
    candidate->stored_bytes = engine->stage_result.header.total_bytes;
    candidate->security_version =
        (uint32_t)engine->stage_result.header.security_counter;
    memcpy(candidate->artifact_sha256,
           engine->stage_result.artifact_sha256,
           sizeof(candidate->artifact_sha256));
    memcpy(candidate->running_host_fingerprint_sha256,
           engine->running_host_fingerprint.compatibility_sha256,
           sizeof(candidate->running_host_fingerprint_sha256));
}

static bool verification_allows_trial(
    const WdcAdminArtifactVerification *verification)
{
    return verification != NULL && verification->status == WDC_OK &&
           verification->complete_artifact_valid == 1u &&
           verification->host_compatible == 1u &&
           verification->security_floor_valid == 1u &&
           verification->artifact_authority_valid == 1u;
}

static int32_t verify_candidate(WdcAdminUpdateEngine *engine,
                                uint64_t now_ms)
{
    WdcAdminArtifactCandidate candidate;
    WdcAdminArtifactVerification verification;
    int32_t status;
    if (engine->stage_result.header.security_counter > UINT32_MAX ||
        !bytes_equal(engine->stage_result.artifact_sha256,
                     engine->expected_artifact_sha256,
                     WDC_BUNDLE_SHA256_BYTES)) {
        return WDC_ERR_CONTRACT_VIOLATION;
    }
    make_candidate(engine, &candidate);
    memset(&verification, 0, sizeof(verification));
    status = wdc_admin_verify_artifact(engine->core, &candidate,
                                       &verification, now_ms);
    if (status != WDC_OK || !verification_allows_trial(&verification)) {
        return status != WDC_OK ? status : WDC_ERR_CAPABILITY_DENIED;
    }
    return WDC_OK;
}

static int32_t finish_update(WdcAdminUpdateEngine *engine,
                             const WdcAdminAcceptedCommand *command,
                             uint64_t now_ms)
{
    uint32_t commit_index;
    int32_t status;
    int32_t audit_status = WDC_OK;
    if (engine->state != WDC_ADMIN_UPDATE_STATE_STREAMING ||
        !engine->staging_active ||
        !command_matches_transaction(engine, command) ||
        engine->streamed_bytes != engine->expected_total_bytes ||
        now_ms >= engine->stream_idle_deadline_ms ||
        now_ms >= engine->transaction_deadline_ms) {
        return fail_current(engine, WDC_ERR_INVALID_STATE, now_ms);
    }
    memset(&engine->stage_result, 0, sizeof(engine->stage_result));
    status = wdc_app_slots_stage_finish(
        &engine->stage, engine->metadata, &engine->running_host_fingerprint,
        &engine->slot_verify_policy, engine->working_buffer,
        WDC_ADMIN_UPDATE_WORKING_BYTES, &engine->stage_result);
    engine->staging_active = false;
    engine->metadata_commits += engine->stage_result.metadata_commits;
    for (commit_index = 0u;
         commit_index < engine->stage_result.metadata_commits;
         ++commit_index) {
        audit_status = emit_audit(
            engine, WDC_ADMIN_AUDIT_SLOT_TRANSITION,
            status == WDC_OK ? WDC_ADMIN_AUDIT_ALLOWED
                             : WDC_ADMIN_AUDIT_FAILED,
            WDC_ADMIN_MODE_UPDATE, WDC_ADMIN_MODE_UPDATE,
            status, (uint32_t)engine->target_slot,
            engine->stage_result.artifact_sha256, now_ms);
        if (audit_status != WDC_OK) {
            break;
        }
    }
    if (status != WDC_OK || engine->stage_result.status != WDC_OK ||
        engine->stage_result.terminal_state != WDC_SLOT_VERIFIED ||
        engine->stage_result.application_code_launched != 0u ||
        !engine->stage_result.header_valid ||
        !engine->stage_result.bundle_hash_valid ||
        !engine->stage_result.bundle_valid ||
        !engine->stage_result.host_compatible ||
        !engine->stage_result.security_floor_valid ||
        !engine->stage_result.authority_valid || audit_status != WDC_OK ||
        !authority_preserved(engine, engine->metadata)) {
        return fail_current(engine,
                            status != WDC_OK ? status :
                            audit_status != WDC_OK ? audit_status :
                                               WDC_ERR_CONTRACT_VIOLATION,
                            now_ms);
    }
    status = verify_candidate(engine, now_ms);
    if (status != WDC_OK) {
        return fail_current(engine, status, now_ms);
    }
    engine->verification_complete = true;
    engine->state = WDC_ADMIN_UPDATE_STATE_VERIFIED;
    return complete_current(engine, WDC_ADMIN_TERMINAL_SUCCEEDED, WDC_OK,
                            WDC_ADMIN_MODE_UPDATE,
                            (uint32_t)engine->target_slot, now_ms);
}

static bool durable_trial_matches(const WdcAdminUpdateEngine *engine,
                                  const WdcBundleMetadataV1 *metadata)
{
    const WdcBundleSlotRecord *record =
        slot_record(metadata, engine->target_slot);
    const WdcBundleSlotRecord *last_confirmed =
        slot_record(metadata, engine->authority_last_good_slot);
    return metadata != NULL &&
           metadata->active_slot == engine->target_slot &&
           metadata->last_good_slot == engine->authority_last_good_slot &&
           ((!slot_valid(engine->authority_last_good_slot) &&
             engine->authority_last_good_slot == WDC_BUNDLE_SLOT_NONE) ||
            slot_record_equal(last_confirmed,
                              &engine->last_confirmed_record)) &&
           record != NULL &&
           record->state == WDC_SLOT_TRIAL &&
           record->artifact_bytes == engine->expected_total_bytes &&
           bytes_equal(record->artifact_sha256,
                       engine->expected_artifact_sha256,
                       WDC_BUNDLE_SHA256_BYTES);
}

static bool authorization_current(const WdcAdminUpdateEngine *engine,
                                  const WdcAdminAcceptedCommand *command,
                                  uint64_t now_ms)
{
    const WdcAdminCore *core = engine->core;
    return core->authorization_state == WDC_ADMIN_AUTH_AUTHORIZED &&
           now_ms < core->session.expires_monotonic_ms &&
           now_ms < command->request.deadline_ms &&
           core->session.authorization_epoch ==
               command->request.authorization_epoch &&
           core->session.session_nonce == command->request.session_nonce;
}

static int32_t activate_trial(WdcAdminUpdateEngine *engine,
                              const WdcAdminAcceptedCommand *command,
                              uint64_t now_ms)
{
    WdcBundleMetadataV1 durable;
    int32_t status;
    int32_t read_status;
    WdcBundleSlotId target = engine->target_slot;
    if (engine->state != WDC_ADMIN_UPDATE_STATE_VERIFIED ||
        !engine->verification_complete ||
        !command_matches_transaction(engine, command) ||
        !authorization_current(engine, command, now_ms) ||
        now_ms >= engine->transaction_deadline_ms ||
        !authority_preserved(engine, engine->metadata)) {
        return fail_current(engine, WDC_ERR_CAPABILITY_DENIED, now_ms);
    }
    status = verify_candidate(engine, now_ms);
    if (status != WDC_OK) {
        return fail_current(engine, status, now_ms);
    }
    status = wdc_app_slots_mark_trial(engine->metadata, target,
                                      &engine->activation_policy);
    memset(&durable, 0, sizeof(durable));
    read_status = wdc_ota_read_metadata(&durable);
    if (read_status == WDC_OK && durable_trial_matches(engine, &durable)) {
        *engine->metadata = durable;
        status = WDC_OK;
    } else if (status == WDC_OK) {
        status = read_status != WDC_OK ? read_status
                                       : WDC_ERR_CONTRACT_VIOLATION;
    }
    if (status != WDC_OK) {
        return fail_current(engine, status, now_ms);
    }
    engine->metadata_commits += 1u;
    status = transition_mode(engine, WDC_ADMIN_MODE_UPDATE,
                             WDC_ADMIN_MODE_REBOOT_HANDOFF,
                             WDC_ADMIN_AUDIT_SLOT_TRANSITION,
                             WDC_ADMIN_AUDIT_ALLOWED, WDC_OK, now_ms);
    if (status != WDC_OK) {
        return fail_current(engine, status, now_ms);
    }
    status = emit_audit(engine, WDC_ADMIN_AUDIT_REBOOT_HANDOFF,
                        WDC_ADMIN_AUDIT_OBSERVED,
                        WDC_ADMIN_MODE_REBOOT_HANDOFF,
                        WDC_ADMIN_MODE_REBOOT_HANDOFF, WDC_OK,
                        (uint32_t)target,
                        engine->expected_artifact_sha256, now_ms);
    if (status != WDC_OK) {
        return fail_current(engine, status, now_ms);
    }
    status = complete_current(engine, WDC_ADMIN_TERMINAL_REBOOT_HANDOFF,
                              WDC_OK, WDC_ADMIN_MODE_REBOOT_HANDOFF,
                              (uint32_t)target, now_ms);
    if (status == WDC_OK) {
        clear_transaction(engine, WDC_ADMIN_UPDATE_STATE_REBOOT_HANDOFF);
    }
    return status;
}

static int32_t explicit_abort(WdcAdminUpdateEngine *engine,
                              const WdcAdminAcceptedCommand *command,
                              uint64_t now_ms)
{
    WdcBundleSlotId target = engine->target_slot;
    WdcAdminMode return_mode = idle_mode(engine);
    int32_t status;
    if ((engine->state != WDC_ADMIN_UPDATE_STATE_STREAMING &&
         engine->state != WDC_ADMIN_UPDATE_STATE_VERIFIED) ||
        !command_matches_transaction(engine, command)) {
        return fail_current(engine, WDC_ERR_INVALID_STATE, now_ms);
    }
    status = abort_staging(engine);
    if (status != WDC_OK || !authority_preserved(engine, engine->metadata)) {
        return fail_current(engine,
                            status != WDC_OK ? status :
                                               WDC_ERR_CONTRACT_VIOLATION,
                            now_ms);
    }
    status = transition_mode(engine, WDC_ADMIN_MODE_UPDATE,
                             return_mode,
                             WDC_ADMIN_AUDIT_STAGING,
                             WDC_ADMIN_AUDIT_OBSERVED, WDC_OK, now_ms);
    if (status != WDC_OK) {
        return fail_current(engine, status, now_ms);
    }
    status = complete_current(engine, WDC_ADMIN_TERMINAL_SUCCEEDED, WDC_OK,
                              return_mode, (uint32_t)target,
                              now_ms);
    if (status == WDC_OK) {
        clear_transaction(engine, WDC_ADMIN_UPDATE_STATE_IDLE);
    }
    return status;
}

int32_t wdc_admin_update_init(WdcAdminUpdateEngine *engine,
                              const WdcAdminUpdateConfig *config)
{
    const WdcControlResourceProfile *profile;
    bool target_profile_matches;
    if (engine == NULL || config == NULL || config->core == NULL ||
        config->metadata == NULL ||
        config->running_host_fingerprint == NULL ||
        config->slot_verify_policy == NULL ||
        config->slot_verify_policy->bundle_policy == NULL ||
        config->activation_policy == NULL ||
        config->lifecycle.quiesce_and_unload == NULL ||
        config->lifecycle.heap_snapshot_after_unload == NULL ||
        config->working_buffer == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    profile = config->core->control_kernel != NULL
                  ? config->core->control_kernel->profile
                  : NULL;
    target_profile_matches =
        profile != NULL && profile->target != NULL &&
        ((strcmp(profile->target, "esp32c6") == 0 &&
          !profile->psram_supported &&
          config->running_host_fingerprint->target ==
              WDC_HOST_TARGET_ESP32C6 &&
          config->running_host_fingerprint->resource_profile ==
              WDC_HOST_RESOURCE_PROFILE_C6_MINIMUM_V1) ||
         (strcmp(profile->target, "esp32s3") == 0 &&
          profile->psram_supported &&
          config->running_host_fingerprint->target ==
              WDC_HOST_TARGET_ESP32S3 &&
          config->running_host_fingerprint->resource_profile ==
              WDC_HOST_RESOURCE_PROFILE_S3_PSRAM_V1));
    if (!config->core->initialized ||
        (config->core->mode != WDC_ADMIN_MODE_NORMAL &&
         config->core->mode != WDC_ADMIN_MODE_RECOVERY) ||
        ((config->core->enabled_commands_mask !=
              WDC_ADMIN_HP42_COMMAND_MASK ||
          config->core->mode != WDC_ADMIN_MODE_NORMAL) &&
         config->core->enabled_commands_mask !=
             WDC_ADMIN_HP43_COMMAND_MASK) ||
        config->working_buffer_bytes != WDC_ADMIN_UPDATE_WORKING_BYTES ||
        !target_profile_matches ||
        profile->reserve.fixed_control_reserve_bytes != 98304u ||
        profile->reserve.exclusive_update_working_bytes !=
            WDC_ADMIN_UPDATE_WORKING_BYTES ||
        profile->reserve.update_largest_allocation_bytes !=
            WDC_ADMIN_UPDATE_LARGEST_ALLOCATION_BYTES ||
        profile->reserve.largest_block_floor_bytes != 32768u ||
        config->running_host_fingerprint->fixed_control_reserve_bytes !=
            98304u ||
        config->running_host_fingerprint->exclusive_update_working_bytes !=
            WDC_ADMIN_UPDATE_WORKING_BYTES ||
        config->running_host_fingerprint->largest_block_floor_bytes !=
            32768u ||
        wdc_host_fingerprint_validate(
            config->running_host_fingerprint) != WDC_OK ||
        wdc_bundle_metadata_validate(config->metadata) != WDC_OK) {
        return WDC_ERR_BAD_ENCODING;
    }
    memset(engine, 0, sizeof(*engine));
    engine->core = config->core;
    engine->metadata = config->metadata;
    engine->running_host_fingerprint = *config->running_host_fingerprint;
    engine->bundle_verify_policy =
        *config->slot_verify_policy->bundle_policy;
    engine->slot_verify_policy = *config->slot_verify_policy;
    engine->slot_verify_policy.bundle_policy = &engine->bundle_verify_policy;
    engine->activation_policy = *config->activation_policy;
    engine->lifecycle = config->lifecycle;
    engine->working_buffer = config->working_buffer;
    engine->state = WDC_ADMIN_UPDATE_STATE_IDLE;
    engine->recovery_origin =
        config->core->mode == WDC_ADMIN_MODE_RECOVERY;
    engine->initialized = true;
    return WDC_OK;
}

int32_t wdc_admin_update_execute(WdcAdminUpdateEngine *engine,
                                 const WdcAdminAcceptedCommand *command,
                                 uint64_t now_ms)
{
    if (engine == NULL || command == NULL || !engine->initialized) {
        return WDC_ERR_BAD_POINTER;
    }
    if (!accepted_command_is_current(engine, command)) {
        return WDC_ERR_INVALID_STATE;
    }
    if (now_ms >= command->request.deadline_ms) {
        return fail_current(engine, WDC_ERR_TIMEOUT, now_ms);
    }
    switch ((WdcAdminCommand)command->request.command) {
    case WDC_ADMIN_COMMAND_BEGIN_UPDATE:
        return begin_update(engine, command, now_ms);
    case WDC_ADMIN_COMMAND_WRITE_CHUNK:
        return write_chunk(engine, command, now_ms);
    case WDC_ADMIN_COMMAND_FINISH_UPDATE:
        return finish_update(engine, command, now_ms);
    case WDC_ADMIN_COMMAND_ABORT:
        return explicit_abort(engine, command, now_ms);
    case WDC_ADMIN_COMMAND_ACTIVATE_TRIAL:
        return activate_trial(engine, command, now_ms);
    default:
        return WDC_ERR_UNSUPPORTED_OPCODE;
    }
}

int32_t wdc_admin_update_poll(WdcAdminUpdateEngine *engine,
                              uint64_t now_ms)
{
    int32_t status;
    WdcAdminMode from;
    WdcAdminMode return_mode;
    if (engine == NULL || !engine->initialized) {
        return WDC_ERR_BAD_POINTER;
    }
    if (engine->state != WDC_ADMIN_UPDATE_STATE_STREAMING &&
        engine->state != WDC_ADMIN_UPDATE_STATE_VERIFIED) {
        return WDC_OK;
    }
    if (now_ms < engine->transaction_deadline_ms &&
        (engine->state == WDC_ADMIN_UPDATE_STATE_VERIFIED ||
         now_ms < engine->stream_idle_deadline_ms)) {
        return WDC_OK;
    }
    if (engine->core->lifecycle != WDC_ADMIN_LIFECYCLE_NONE) {
        return WDC_ERR_BUSY;
    }
    status = abort_staging(engine);
    if (status == WDC_OK && !authority_preserved(engine, engine->metadata)) {
        status = WDC_ERR_CONTRACT_VIOLATION;
    }
    from = engine->core->mode;
    return_mode = idle_mode(engine);
    if (from == WDC_ADMIN_MODE_UPDATE) {
        engine->core->mode = return_mode;
    }
    (void)emit_audit(engine, WDC_ADMIN_AUDIT_STAGING,
                     WDC_ADMIN_AUDIT_FAILED, from,
                     return_mode,
                     status == WDC_OK ? WDC_ERR_TIMEOUT : status,
                     (uint32_t)engine->target_slot,
                     engine->expected_artifact_sha256, now_ms);
    clear_transaction(engine, WDC_ADMIN_UPDATE_STATE_IDLE);
    return status == WDC_OK ? WDC_ERR_TIMEOUT : status;
}

int32_t wdc_admin_update_set_idle_mode(WdcAdminUpdateEngine *engine,
                                       WdcAdminMode mode)
{
    if (engine == NULL || !engine->initialized) {
        return WDC_ERR_BAD_POINTER;
    }
    if ((mode != WDC_ADMIN_MODE_NORMAL &&
         mode != WDC_ADMIN_MODE_RECOVERY) ||
        engine->state != WDC_ADMIN_UPDATE_STATE_IDLE ||
        engine->staging_active || engine->verification_complete ||
        engine->core == NULL || engine->core->mode != mode) {
        return WDC_ERR_INVALID_STATE;
    }
    engine->recovery_origin = mode == WDC_ADMIN_MODE_RECOVERY;
    return WDC_OK;
}

WdcAdminUpdateState wdc_admin_update_state(
    const WdcAdminUpdateEngine *engine)
{
    return engine != NULL && engine->initialized
               ? engine->state
               : WDC_ADMIN_UPDATE_STATE_NONE;
}

uint32_t wdc_admin_update_static_bytes(void)
{
    return (uint32_t)sizeof(WdcAdminUpdateEngine);
}

uint32_t wdc_admin_update_link_anchor(void)
{
    return 0x48503403u;
}
