#include "wdc_admin_recovery.h"

#include <stddef.h>
#include <string.h>

_Static_assert(sizeof(WdcAdminRecoveryStatus) ==
                   WDC_ADMIN_RECOVERY_STATUS_BYTES,
               "HP4.3 recovery status layout drifted");
_Static_assert(WDC_ADMIN_RECOVERY_RESERVE_BYTES == 16384u,
               "HP4.3 recovery reserve drifted from HP1");

static bool slot_valid(WdcBundleSlotId slot)
{
    return slot == WDC_BUNDLE_SLOT_A || slot == WDC_BUNDLE_SLOT_B;
}

static bool accepted_command_is_current(
    const WdcAdminRecoveryEngine *engine,
    const WdcAdminAcceptedCommand *command)
{
    const WdcAdminCore *core;
    if (engine == NULL || command == NULL || engine->update.core == NULL) {
        return false;
    }
    core = engine->update.core;
    return core->lifecycle == WDC_ADMIN_LIFECYCLE_IN_PROGRESS &&
           core->active_control_ticket == command->control_ticket &&
           core->active_request.request_id == command->request.request_id &&
           core->active_request.command_sequence ==
               command->request.command_sequence &&
           core->active_request.command == command->request.command;
}

static bool authorization_current(const WdcAdminRecoveryEngine *engine,
                                  const WdcAdminAcceptedCommand *command,
                                  uint64_t now_ms)
{
    const WdcAdminCore *core = engine->update.core;
    return core->authorization_state == WDC_ADMIN_AUTH_AUTHORIZED &&
           now_ms < core->session.expires_monotonic_ms &&
           core->session.authorization_epoch ==
               command->request.authorization_epoch &&
           core->session.session_nonce == command->request.session_nonce;
}

static int32_t emit_audit(WdcAdminRecoveryEngine *engine,
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
    return wdc_admin_audit_emit(engine->update.core, &emission, now_ms);
}

static int32_t transition_mode(WdcAdminRecoveryEngine *engine,
                               WdcAdminMode expected,
                               WdcAdminMode next,
                               WdcAdminAuditEvent event,
                               WdcAdminAuditOutcome outcome,
                               int32_t status,
                               uint64_t now_ms)
{
    WdcAdminCore *core = engine->update.core;
    int32_t audit_status;
    if (core == NULL || core->mode != expected) {
        return WDC_ERR_INVALID_STATE;
    }
    core->mode = next;
    audit_status = emit_audit(engine, event, outcome, expected, next, status,
                              WDC_ADMIN_SLOT_NONE, NULL, now_ms);
    if (audit_status != WDC_OK) {
        core->mode = expected;
        return audit_status;
    }
    return WDC_OK;
}

static int32_t complete_current(WdcAdminRecoveryEngine *engine,
                                WdcAdminTerminalResult result,
                                int32_t status,
                                WdcAdminMode final_mode,
                                uint32_t slot,
                                uint64_t now_ms)
{
    WdcAdminTerminalMetadata metadata;
    memset(&metadata, 0, sizeof(metadata));
    metadata.final_state = (uint32_t)final_mode;
    metadata.slot = slot;
    return wdc_admin_complete(engine->update.core, result, status, &metadata,
                              now_ms);
}

static bool boot_recovery_evidence_valid(
    const WdcAppSlotBootResult *result)
{
    return result != NULL && result->status != WDC_OK &&
           result->outcome == WDC_APP_SLOT_BOOT_RECOVERY &&
           result->selected_slot == WDC_BUNDLE_SLOT_NONE &&
           result->fallback_slot == WDC_BUNDLE_SLOT_NONE &&
           result->application_code_launched == 0u &&
           !result->probation && !result->reboot_required &&
           result->recovery;
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

static int32_t fail_entry(WdcAdminRecoveryEngine *engine,
                          int32_t status,
                          uint64_t now_ms)
{
    WdcAdminCore *core = engine->update.core;
    int32_t complete_status;
    if (status == WDC_OK) {
        status = WDC_ERR_CONTRACT_VIOLATION;
    }
    if (core->mode == WDC_ADMIN_MODE_QUIESCE) {
        (void)transition_mode(engine, WDC_ADMIN_MODE_QUIESCE,
                              WDC_ADMIN_MODE_NORMAL,
                              WDC_ADMIN_AUDIT_QUIESCE,
                              WDC_ADMIN_AUDIT_FAILED, status, now_ms);
    }
    complete_status = complete_current(
        engine,
        status == WDC_ERR_TIMEOUT ? WDC_ADMIN_TERMINAL_TIMED_OUT
                                  : WDC_ADMIN_TERMINAL_FAILED,
        status, WDC_ADMIN_MODE_NORMAL, WDC_ADMIN_SLOT_NONE, now_ms);
    return complete_status == WDC_OK ? status : complete_status;
}

static int32_t enter_recovery(WdcAdminRecoveryEngine *engine,
                              uint64_t now_ms)
{
    WdcAdminUpdateQuiesceEvidence evidence;
    uint64_t deadline_ms;
    int32_t status;
    if (engine->update.core->mode != WDC_ADMIN_MODE_NORMAL ||
        wdc_admin_update_state(&engine->update) !=
            WDC_ADMIN_UPDATE_STATE_IDLE ||
        now_ms > UINT64_MAX - WDC_ADMIN_UPDATE_QUIESCE_DEADLINE_MS) {
        return fail_entry(engine, WDC_ERR_INVALID_STATE, now_ms);
    }
    deadline_ms = now_ms + WDC_ADMIN_UPDATE_QUIESCE_DEADLINE_MS;
    status = transition_mode(engine, WDC_ADMIN_MODE_NORMAL,
                             WDC_ADMIN_MODE_QUIESCE,
                             WDC_ADMIN_AUDIT_QUIESCE,
                             WDC_ADMIN_AUDIT_OBSERVED, WDC_OK, now_ms);
    if (status != WDC_OK) {
        return fail_entry(engine, status, now_ms);
    }
    memset(&evidence, 0, sizeof(evidence));
    status = engine->update.lifecycle.quiesce_and_unload(
        engine->update.lifecycle.context, deadline_ms, &evidence);
    if (status != WDC_OK ||
        !quiescence_valid(&evidence, now_ms, deadline_ms)) {
        return fail_entry(engine,
                          status != WDC_OK ? status
                                           : WDC_ERR_CONTRACT_VIOLATION,
                          now_ms);
    }
    status = emit_audit(engine, WDC_ADMIN_AUDIT_QUIESCE,
                        WDC_ADMIN_AUDIT_ALLOWED,
                        WDC_ADMIN_MODE_QUIESCE,
                        WDC_ADMIN_MODE_QUIESCE, WDC_OK,
                        WDC_ADMIN_SLOT_NONE, NULL,
                        evidence.completed_monotonic_ms);
    if (status != WDC_OK) {
        return fail_entry(engine, status, now_ms);
    }
    status = transition_mode(engine, WDC_ADMIN_MODE_QUIESCE,
                             WDC_ADMIN_MODE_RECOVERY,
                             WDC_ADMIN_AUDIT_RECOVERY_ENTRY,
                             WDC_ADMIN_AUDIT_ALLOWED, WDC_OK, now_ms);
    if (status != WDC_OK) {
        return fail_entry(engine, status, now_ms);
    }
    status = wdc_admin_update_set_idle_mode(&engine->update,
                                            WDC_ADMIN_MODE_RECOVERY);
    if (status != WDC_OK) {
        engine->update.core->mode = WDC_ADMIN_MODE_QUIESCE;
        return fail_entry(engine, status, now_ms);
    }
    engine->application_loaded = 0u;
    engine->native_refinements_loaded = 0u;
    engine->reason = WDC_ADMIN_RECOVERY_REASON_ADMINISTRATIVE_TRIGGER;
    return complete_current(engine, WDC_ADMIN_TERMINAL_SUCCEEDED, WDC_OK,
                            WDC_ADMIN_MODE_RECOVERY, WDC_ADMIN_SLOT_NONE,
                            now_ms);
}

static int32_t status_command(WdcAdminRecoveryEngine *engine,
                              uint64_t now_ms)
{
    WdcAdminRecoveryStatus status_response;
    WdcAdminCore *core = engine->update.core;
    int32_t status;
    memset(&status_response, 0, sizeof(status_response));
    status_response.struct_size = sizeof(status_response);
    status_response.version_major = WDC_ADMIN_VERSION_MAJOR;
    status_response.version_minor = WDC_ADMIN_VERSION_MINOR;
    status_response.mode = (uint32_t)core->mode;
    status_response.recovery_reason = (uint32_t)engine->reason;
    status_response.update_state =
        (uint32_t)wdc_admin_update_state(&engine->update);
    status_response.active_slot = (uint32_t)engine->update.metadata->active_slot;
    status_response.last_good_slot =
        (uint32_t)engine->update.metadata->last_good_slot;
    status_response.slot_a_state =
        (uint32_t)engine->update.metadata->slot_a.state;
    status_response.slot_b_state =
        (uint32_t)engine->update.metadata->slot_b.state;
    status_response.application_loaded = engine->application_loaded;
    status_response.native_refinements_loaded =
        engine->native_refinements_loaded;
    status_response.recovery_required =
        wdc_control_recovery_required(core->control_kernel);
    status_response.audit_loss_count = wdc_admin_audit_losses(core);
    status_response.metadata_generation =
        engine->update.metadata->metadata_generation;
    status_response.enabled_commands_mask = core->enabled_commands_mask;
    status = wdc_admin_write_response(
        core, (const uint8_t *)&status_response,
        (uint32_t)sizeof(status_response));
    if (status != WDC_OK) {
        return complete_current(engine, WDC_ADMIN_TERMINAL_FAILED, status,
                                core->mode, WDC_ADMIN_SLOT_NONE, now_ms);
    }
    return complete_current(engine, WDC_ADMIN_TERMINAL_SUCCEEDED, WDC_OK,
                            core->mode, WDC_ADMIN_SLOT_NONE, now_ms);
}

static int32_t abort_recovery(WdcAdminRecoveryEngine *engine,
                              uint64_t now_ms)
{
    if (engine->update.core->mode != WDC_ADMIN_MODE_RECOVERY ||
        wdc_admin_update_state(&engine->update) !=
            WDC_ADMIN_UPDATE_STATE_IDLE) {
        return complete_current(engine, WDC_ADMIN_TERMINAL_FAILED,
                                WDC_ERR_INVALID_STATE,
                                engine->update.core->mode,
                                WDC_ADMIN_SLOT_NONE, now_ms);
    }
    return complete_current(engine, WDC_ADMIN_TERMINAL_SUCCEEDED, WDC_OK,
                            WDC_ADMIN_MODE_RECOVERY, WDC_ADMIN_SLOT_NONE,
                            now_ms);
}

static int32_t reboot_handoff(WdcAdminRecoveryEngine *engine,
                              uint64_t now_ms)
{
    WdcAdminCore *core = engine->update.core;
    WdcAppSlotBootResult viability;
    WdcControlHeapSnapshot heap;
    const WdcBundleSlotRecord *record;
    WdcBundleSlotId slot = engine->update.metadata->active_slot;
    int32_t status;
    memset(&heap, 0, sizeof(heap));
    memset(&viability, 0, sizeof(viability));
    if (core->mode != WDC_ADMIN_MODE_RECOVERY ||
        wdc_admin_update_state(&engine->update) !=
            WDC_ADMIN_UPDATE_STATE_IDLE ||
        engine->application_loaded != 0u ||
        engine->native_refinements_loaded != 0u || !slot_valid(slot)) {
        status = WDC_ERR_INVALID_STATE;
    } else {
        status = engine->update.lifecycle.heap_snapshot_after_unload(
            engine->update.lifecycle.context, &heap);
        if (status == WDC_OK) {
            status = wdc_app_slots_validate_reboot_candidate(
                engine->update.metadata, slot,
                &engine->update.running_host_fingerprint, &heap,
                &engine->update.slot_verify_policy,
                engine->update.working_buffer,
                WDC_ADMIN_UPDATE_WORKING_BYTES, &viability);
        }
    }
    record = slot == WDC_BUNDLE_SLOT_A
                 ? &engine->update.metadata->slot_a
                 : slot == WDC_BUNDLE_SLOT_B
                       ? &engine->update.metadata->slot_b
                       : NULL;
    if (status != WDC_OK || viability.application_code_launched != 0u) {
        int32_t complete_status;
        if (status == WDC_OK) {
            status = WDC_ERR_CONTRACT_VIOLATION;
        }
        (void)emit_audit(engine, WDC_ADMIN_AUDIT_REBOOT_HANDOFF,
                         WDC_ADMIN_AUDIT_FAILED,
                         WDC_ADMIN_MODE_RECOVERY,
                         WDC_ADMIN_MODE_RECOVERY, status,
                         (uint32_t)slot,
                         record != NULL ? record->artifact_sha256 : NULL,
                         now_ms);
        complete_status = complete_current(
            engine, WDC_ADMIN_TERMINAL_FAILED, status,
            WDC_ADMIN_MODE_RECOVERY, (uint32_t)slot, now_ms);
        return complete_status == WDC_OK ? status : complete_status;
    }
    core->mode = WDC_ADMIN_MODE_REBOOT_HANDOFF;
    status = emit_audit(engine, WDC_ADMIN_AUDIT_REBOOT_HANDOFF,
                        WDC_ADMIN_AUDIT_ALLOWED,
                        WDC_ADMIN_MODE_RECOVERY,
                        WDC_ADMIN_MODE_REBOOT_HANDOFF, WDC_OK,
                        (uint32_t)slot, record->artifact_sha256, now_ms);
    if (status != WDC_OK) {
        int32_t complete_status;
        core->mode = WDC_ADMIN_MODE_RECOVERY;
        complete_status = complete_current(
            engine, WDC_ADMIN_TERMINAL_FAILED, status,
            WDC_ADMIN_MODE_RECOVERY, (uint32_t)slot, now_ms);
        return complete_status == WDC_OK ? status : complete_status;
    }
    return complete_current(engine, WDC_ADMIN_TERMINAL_REBOOT_HANDOFF,
                            WDC_OK, WDC_ADMIN_MODE_REBOOT_HANDOFF,
                            (uint32_t)slot, now_ms);
}

int32_t wdc_admin_recovery_init(WdcAdminRecoveryEngine *engine,
                                const WdcAdminRecoveryConfig *config,
                                uint64_t now_ms)
{
    const WdcControlResourceProfile *profile;
    const WdcBundleSlotRecord *normal_record;
    int32_t status;
    if (engine == NULL || config == NULL || config->update.core == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    profile = config->update.core->control_kernel != NULL
                  ? config->update.core->control_kernel->profile
                  : NULL;
    if (config->application_loaded > 1u ||
        config->native_refinements_loaded > 1u || profile == NULL ||
        profile->reserve.recovery_bytes !=
            WDC_ADMIN_RECOVERY_RESERVE_BYTES ||
        config->update.core->enabled_commands_mask !=
            WDC_ADMIN_HP43_COMMAND_MASK ||
        (config->update.core->mode == WDC_ADMIN_MODE_RECOVERY &&
         (config->application_loaded != 0u ||
          config->native_refinements_loaded != 0u ||
          config->update.metadata == NULL ||
          config->update.metadata->active_slot != WDC_BUNDLE_SLOT_NONE ||
          config->update.metadata->last_good_slot != WDC_BUNDLE_SLOT_NONE ||
          !boot_recovery_evidence_valid(config->boot_result))) ||
        (config->update.core->mode == WDC_ADMIN_MODE_NORMAL &&
         (config->boot_result != NULL ||
          config->application_loaded != 1u ||
          config->update.metadata == NULL ||
          !slot_valid(config->update.metadata->active_slot) ||
          config->update.metadata->active_slot !=
              config->update.metadata->last_good_slot))) {
        return WDC_ERR_BAD_ENCODING;
    }
    normal_record = config->update.core->mode == WDC_ADMIN_MODE_NORMAL
                        ? (config->update.metadata->active_slot ==
                                   WDC_BUNDLE_SLOT_A
                               ? &config->update.metadata->slot_a
                               : &config->update.metadata->slot_b)
                        : NULL;
    if (normal_record != NULL &&
        normal_record->state != WDC_SLOT_CONFIRMED) {
        return WDC_ERR_BAD_ENCODING;
    }
    memset(engine, 0, sizeof(*engine));
    status = wdc_admin_update_init(&engine->update, &config->update);
    if (status != WDC_OK) {
        return status;
    }
    engine->application_loaded = config->application_loaded;
    engine->native_refinements_loaded =
        config->native_refinements_loaded;
    if (config->update.core->mode == WDC_ADMIN_MODE_RECOVERY) {
        engine->reason = WDC_ADMIN_RECOVERY_REASON_NO_VIABLE_APPLICATION;
        status = emit_audit(engine, WDC_ADMIN_AUDIT_RECOVERY_ENTRY,
                            WDC_ADMIN_AUDIT_OBSERVED,
                            WDC_ADMIN_MODE_RECOVERY,
                            WDC_ADMIN_MODE_RECOVERY,
                            config->boot_result->status,
                            WDC_ADMIN_SLOT_NONE, NULL, now_ms);
        if (status != WDC_OK) {
            memset(engine, 0, sizeof(*engine));
            return status;
        }
    }
    engine->initialized = true;
    return WDC_OK;
}

int32_t wdc_admin_recovery_execute(WdcAdminRecoveryEngine *engine,
                                   const WdcAdminAcceptedCommand *command,
                                   uint64_t now_ms)
{
    int32_t status;
    if (engine == NULL || command == NULL || !engine->initialized) {
        return WDC_ERR_BAD_POINTER;
    }
    if (!accepted_command_is_current(engine, command)) {
        return WDC_ERR_INVALID_STATE;
    }
    if (now_ms >= command->request.deadline_ms ||
        !authorization_current(engine, command, now_ms)) {
        status = complete_current(engine, WDC_ADMIN_TERMINAL_TIMED_OUT,
                                  WDC_ERR_TIMEOUT,
                                  engine->update.core->mode,
                                  command->request.slot, now_ms);
        return status == WDC_OK ? WDC_ERR_TIMEOUT : status;
    }
    switch ((WdcAdminCommand)command->request.command) {
    case WDC_ADMIN_COMMAND_STATUS:
        return status_command(engine, now_ms);
    case WDC_ADMIN_COMMAND_ENTER_RECOVERY:
        return enter_recovery(engine, now_ms);
    case WDC_ADMIN_COMMAND_REBOOT:
        return reboot_handoff(engine, now_ms);
    case WDC_ADMIN_COMMAND_ABORT:
        if (engine->update.core->mode == WDC_ADMIN_MODE_RECOVERY) {
            return abort_recovery(engine, now_ms);
        }
        return wdc_admin_update_execute(&engine->update, command, now_ms);
    case WDC_ADMIN_COMMAND_BEGIN_UPDATE:
    case WDC_ADMIN_COMMAND_WRITE_CHUNK:
    case WDC_ADMIN_COMMAND_FINISH_UPDATE:
    case WDC_ADMIN_COMMAND_ACTIVATE_TRIAL:
        status = wdc_admin_update_execute(&engine->update, command, now_ms);
        if (engine->update.core->mode == WDC_ADMIN_MODE_UPDATE ||
            engine->update.core->mode == WDC_ADMIN_MODE_RECOVERY ||
            engine->update.core->mode == WDC_ADMIN_MODE_REBOOT_HANDOFF) {
            engine->application_loaded = 0u;
            engine->native_refinements_loaded = 0u;
        }
        return status;
    default:
        return WDC_ERR_UNSUPPORTED_OPCODE;
    }
}

int32_t wdc_admin_recovery_poll(WdcAdminRecoveryEngine *engine,
                                uint64_t now_ms)
{
    if (engine == NULL || !engine->initialized) {
        return WDC_ERR_BAD_POINTER;
    }
    return wdc_admin_update_poll(&engine->update, now_ms);
}

WdcAdminRecoveryReason wdc_admin_recovery_reason(
    const WdcAdminRecoveryEngine *engine)
{
    return engine != NULL && engine->initialized
               ? engine->reason
               : WDC_ADMIN_RECOVERY_REASON_NONE;
}

uint32_t wdc_admin_recovery_static_bytes(void)
{
    return (uint32_t)sizeof(WdcAdminRecoveryEngine);
}

uint32_t wdc_admin_recovery_link_anchor(void)
{
    return 0x48503403u;
}
