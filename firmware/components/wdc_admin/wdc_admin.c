#include "wdc_admin.h"

#include <limits.h>
#include <stddef.h>
#include <string.h>

#define WDC_ADMIN_ARRAY_BYTES(value) ((uint32_t)sizeof(value))

_Static_assert(sizeof(WdcAdminAuthenticatedEntry) ==
                   WDC_ADMIN_AUTHENTICATED_ENTRY_BYTES,
               "HP4.0 authenticated-entry layout drifted");
_Static_assert(offsetof(WdcAdminAuthenticatedEntry, authorization_epoch) == 24u,
               "HP4.0 authenticated-entry epoch offset drifted");
_Static_assert(offsetof(WdcAdminAuthenticatedEntry, principal_sha256) == 56u,
               "HP4.0 authenticated-entry principal offset drifted");
_Static_assert(offsetof(WdcAdminAuthenticatedEntry, reserved) == 120u,
               "HP4.0 authenticated-entry reserved offset drifted");

_Static_assert(sizeof(WdcAdminRequest) == WDC_ADMIN_REQUEST_BYTES,
               "HP4.0 request layout drifted");
_Static_assert(offsetof(WdcAdminRequest, request_id) == 32u,
               "HP4.0 request identity offset drifted");
_Static_assert(offsetof(WdcAdminRequest, artifact_sha256) == 72u,
               "HP4.0 request artifact offset drifted");
_Static_assert(offsetof(WdcAdminRequest, reserved1) == 104u,
               "HP4.0 request reserved offset drifted");

_Static_assert(sizeof(WdcAdminTerminalRecord) == WDC_ADMIN_TERMINAL_BYTES,
               "HP4.0 terminal layout drifted");
_Static_assert(offsetof(WdcAdminTerminalRecord, request_id) == 16u,
               "HP4.0 terminal request offset drifted");
_Static_assert(offsetof(WdcAdminTerminalRecord, bytes_received) == 40u,
               "HP4.0 terminal accounting offset drifted");
_Static_assert(offsetof(WdcAdminTerminalRecord, reserved) == 60u,
               "HP4.0 terminal reserved offset drifted");

_Static_assert(sizeof(WdcAdminAuditRecord) == WDC_ADMIN_AUDIT_RECORD_BYTES,
               "HP4.0 audit layout drifted");
_Static_assert(offsetof(WdcAdminAuditRecord, authorization_epoch) == 40u,
               "HP4.0 audit session offset drifted");
_Static_assert(offsetof(WdcAdminAuditRecord, principal_sha256) == 80u,
               "HP4.0 audit principal offset drifted");
_Static_assert(offsetof(WdcAdminAuditRecord, artifact_sha256) == 112u,
               "HP4.0 audit artifact offset drifted");
_Static_assert(offsetof(WdcAdminAuditRecord, reserved) == 152u,
               "HP4.0 audit reserved offset drifted");

_Static_assert(sizeof(WdcAdminCore) <= WDC_ADMIN_CORE_STATIC_BUDGET_BYTES,
               "HP4.1 core exceeds the fixed administration budget");
_Static_assert(sizeof(WdcAdminCore) + sizeof(WdcAdminSerialAdapter) <=
                   WDC_ADMIN_FIXED_STORAGE_BUDGET_BYTES,
               "HP4.1 core and serial adapter exceed the HP1 administration reserve");

static bool bytes_are_zero(const uint8_t *bytes, uint32_t bytes_len)
{
    uint32_t index;
    if (bytes == NULL) {
        return false;
    }
    for (index = 0u; index < bytes_len; ++index) {
        if (bytes[index] != 0u) {
            return false;
        }
    }
    return true;
}

static bool bytes_equal(const uint8_t *left,
                        const uint8_t *right,
                        uint32_t bytes_len)
{
    uint8_t difference = 0u;
    uint32_t index;
    if (left == NULL || right == NULL) {
        return false;
    }
    for (index = 0u; index < bytes_len; ++index) {
        difference = (uint8_t)(difference | (uint8_t)(left[index] ^ right[index]));
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

static bool valid_mode(WdcAdminMode mode)
{
    return mode >= WDC_ADMIN_MODE_NORMAL &&
           mode <= WDC_ADMIN_MODE_REBOOT_HANDOFF;
}

static bool valid_command(uint32_t command)
{
    return command >= (uint32_t)WDC_ADMIN_COMMAND_STATUS &&
           command <= (uint32_t)WDC_ADMIN_COMMAND_REBOOT;
}

static bool valid_terminal_result(WdcAdminTerminalResult result)
{
    return result >= WDC_ADMIN_TERMINAL_SUCCEEDED &&
           result <= WDC_ADMIN_TERMINAL_REBOOT_HANDOFF;
}

static bool terminal_pair_valid(WdcAdminTerminalResult result, int32_t status)
{
    if (result == WDC_ADMIN_TERMINAL_SUCCEEDED ||
        result == WDC_ADMIN_TERMINAL_REBOOT_HANDOFF) {
        return status == WDC_OK;
    }
    return valid_terminal_result(result) && status != WDC_OK;
}

static void set_rejection(WdcAdminPreacceptResult *out,
                          WdcAdminPreacceptRejection rejection,
                          uint64_t request_id,
                          uint64_t sequence)
{
    if (out == NULL) {
        return;
    }
    memset(out, 0, sizeof(*out));
    out->rejection = rejection;
    out->status = wdc_admin_rejection_status(rejection);
    out->request_id = request_id;
    out->command_sequence = sequence;
}

static void append_audit(WdcAdminCore *core,
                         WdcAdminAuditEvent event,
                         WdcAdminAuditOutcome outcome,
                         int32_t status,
                         uint64_t now_ms,
                         const WdcAdminRequest *request,
                         WdcAdminMode from_state,
                         WdcAdminMode to_state,
                         WdcAdminTerminalResult terminal_result,
                         uint32_t slot,
                         uint32_t flags,
                         const uint8_t *artifact_sha256)
{
    WdcAdminAuditRecord *record;
    uint32_t index;
    if (core == NULL || !core->initialized) {
        return;
    }
    if (core->audit_count < WDC_ADMIN_AUDIT_RING_RECORDS) {
        index = (core->audit_head + core->audit_count) %
                WDC_ADMIN_AUDIT_RING_RECORDS;
        core->audit_count += 1u;
    } else {
        index = core->audit_head;
        core->audit_head = (core->audit_head + 1u) %
                           WDC_ADMIN_AUDIT_RING_RECORDS;
        if (core->audit_loss_count != UINT32_MAX) {
            core->audit_loss_count += 1u;
        }
    }
    record = &core->audit[index];
    memset(record, 0, sizeof(*record));
    record->struct_size = WDC_ADMIN_AUDIT_RECORD_BYTES;
    record->version_major = WDC_ADMIN_VERSION_MAJOR;
    record->version_minor = WDC_ADMIN_VERSION_MINOR;
    record->event = (uint32_t)event;
    record->outcome = (uint32_t)outcome;
    record->command = request != NULL ? request->command : 0u;
    record->from_state = (uint32_t)from_state;
    record->to_state = (uint32_t)to_state;
    record->terminal_result = (uint32_t)terminal_result;
    record->status = status;
    record->monotonic_ms = now_ms;
    record->slot = slot;
    record->flags = flags;
    if (core->session.struct_size == WDC_ADMIN_AUTHENTICATED_ENTRY_BYTES) {
        record->transport_kind = core->session.transport_kind;
        record->authorization_epoch = core->session.authorization_epoch;
        record->session_nonce = core->session.session_nonce;
        memcpy(record->principal_sha256,
               core->session.principal_sha256,
               sizeof(record->principal_sha256));
    } else if (core->challenge.start.transport_kind != 0u) {
        record->transport_kind = core->challenge.start.transport_kind;
    }
    if (request != NULL) {
        record->command_sequence = request->command_sequence;
        record->request_id = request->request_id;
        if (artifact_sha256 == NULL) {
            artifact_sha256 = request->artifact_sha256;
        }
    }
    if (artifact_sha256 != NULL) {
        memcpy(record->artifact_sha256,
               artifact_sha256,
               sizeof(record->artifact_sha256));
    }
}

static void reset_rate_window_if_elapsed(WdcAdminCore *core, uint64_t now_ms)
{
    if (core->authorization_failure_count != 0u &&
        now_ms >= core->authorization_window_start_ms &&
        now_ms - core->authorization_window_start_ms >=
            WDC_ADMIN_AUTHORIZATION_WINDOW_MS) {
        core->authorization_failure_count = 0u;
        core->authorization_window_start_ms = 0u;
    }
    if (core->authorization_backoff_until_ms != 0u &&
        now_ms >= core->authorization_backoff_until_ms) {
        core->authorization_backoff_until_ms = 0u;
    }
}

static void record_authorization_failure(WdcAdminCore *core, uint64_t now_ms)
{
    uint64_t deadline;
    reset_rate_window_if_elapsed(core, now_ms);
    if (core->authorization_failure_count == 0u) {
        core->authorization_window_start_ms = now_ms;
    }
    if (core->authorization_failure_count != UINT32_MAX) {
        core->authorization_failure_count += 1u;
    }
    if (core->authorization_failure_count >=
        WDC_ADMIN_AUTHORIZATION_FAILURE_LIMIT) {
        core->authorization_backoff_until_ms =
            checked_deadline(now_ms, WDC_ADMIN_AUTHORIZATION_BACKOFF_MS,
                             &deadline)
                ? deadline
                : UINT64_MAX;
    }
}

static bool authenticated_entry_valid(
    const WdcAdminCore *core,
    const WdcAdminAuthenticatedEntry *entry,
    uint64_t now_ms)
{
    if (entry == NULL ||
        entry->struct_size != WDC_ADMIN_AUTHENTICATED_ENTRY_BYTES ||
        entry->version_major != WDC_ADMIN_VERSION_MAJOR ||
        entry->version_minor != WDC_ADMIN_VERSION_MINOR ||
        entry->transport_kind != core->challenge.start.transport_kind ||
        entry->authorization_method !=
            core->challenge.start.authorization_method ||
        (entry->transport_kind != WDC_ADMIN_TRANSPORT_SERIAL_PHYSICAL_V1 &&
         entry->transport_kind !=
             WDC_ADMIN_TRANSPORT_AUTHENTICATED_EXTERNAL_V1) ||
        entry->privilege_mask == 0u ||
        (entry->privilege_mask & ~WDC_ADMIN_PRIVILEGE_ALL) != 0u ||
        entry->flags != 0u ||
        entry->authorization_epoch <= core->authorization_epoch_high_water ||
        entry->session_nonce == 0u ||
        entry->issued_monotonic_ms > now_ms ||
        entry->expires_monotonic_ms <= now_ms ||
        entry->expires_monotonic_ms < entry->issued_monotonic_ms ||
        entry->expires_monotonic_ms - entry->issued_monotonic_ms >
            WDC_ADMIN_SESSION_LIFETIME_MS ||
        bytes_are_zero(entry->principal_sha256,
                       WDC_ADMIN_ARRAY_BYTES(entry->principal_sha256)) ||
        !bytes_equal(entry->channel_binding_sha256,
                     core->boot_channel_binding_sha256,
                     WDC_ADMIN_ARRAY_BYTES(entry->channel_binding_sha256)) ||
        !bytes_equal(entry->channel_binding_sha256,
                     core->challenge.start.channel_binding_sha256,
                     WDC_ADMIN_ARRAY_BYTES(entry->channel_binding_sha256)) ||
        !bytes_are_zero(entry->reserved,
                        WDC_ADMIN_ARRAY_BYTES(entry->reserved))) {
        return false;
    }
    return true;
}

static uint32_t command_privilege(WdcAdminCommand command,
                                  WdcAdminMode mode)
{
    switch (command) {
    case WDC_ADMIN_COMMAND_STATUS:
        return WDC_ADMIN_PRIVILEGE_STATUS;
    case WDC_ADMIN_COMMAND_BEGIN_UPDATE:
    case WDC_ADMIN_COMMAND_WRITE_CHUNK:
    case WDC_ADMIN_COMMAND_FINISH_UPDATE:
    case WDC_ADMIN_COMMAND_ACTIVATE_TRIAL:
        return WDC_ADMIN_PRIVILEGE_UPDATE;
    case WDC_ADMIN_COMMAND_ABORT:
        return mode == WDC_ADMIN_MODE_RECOVERY
                   ? WDC_ADMIN_PRIVILEGE_RECOVERY
                   : WDC_ADMIN_PRIVILEGE_UPDATE;
    case WDC_ADMIN_COMMAND_ENTER_RECOVERY:
        return WDC_ADMIN_PRIVILEGE_RECOVERY;
    case WDC_ADMIN_COMMAND_REBOOT:
        return WDC_ADMIN_PRIVILEGE_REBOOT;
    default:
        return 0u;
    }
}

static bool command_allowed_in_state(WdcAdminCommand command,
                                     WdcAdminMode mode)
{
    switch (command) {
    case WDC_ADMIN_COMMAND_STATUS:
        return valid_mode(mode);
    case WDC_ADMIN_COMMAND_BEGIN_UPDATE:
        return mode == WDC_ADMIN_MODE_NORMAL ||
               mode == WDC_ADMIN_MODE_RECOVERY;
    case WDC_ADMIN_COMMAND_WRITE_CHUNK:
    case WDC_ADMIN_COMMAND_FINISH_UPDATE:
    case WDC_ADMIN_COMMAND_ACTIVATE_TRIAL:
        return mode == WDC_ADMIN_MODE_UPDATE;
    case WDC_ADMIN_COMMAND_ABORT:
        return mode == WDC_ADMIN_MODE_QUIESCE ||
               mode == WDC_ADMIN_MODE_UPDATE ||
               mode == WDC_ADMIN_MODE_RECOVERY;
    case WDC_ADMIN_COMMAND_ENTER_RECOVERY:
        return mode == WDC_ADMIN_MODE_NORMAL;
    case WDC_ADMIN_COMMAND_REBOOT:
        return mode == WDC_ADMIN_MODE_RECOVERY;
    default:
        return false;
    }
}

static WdcControlSource control_source_for_command(WdcAdminCommand command,
                                                   WdcAdminMode mode)
{
    switch (command) {
    case WDC_ADMIN_COMMAND_ENTER_RECOVERY:
    case WDC_ADMIN_COMMAND_REBOOT:
        return WDC_CONTROL_SOURCE_RECOVERY;
    case WDC_ADMIN_COMMAND_ABORT:
        return mode == WDC_ADMIN_MODE_RECOVERY
                   ? WDC_CONTROL_SOURCE_RECOVERY
                   : WDC_CONTROL_SOURCE_UPDATE;
    case WDC_ADMIN_COMMAND_BEGIN_UPDATE:
    case WDC_ADMIN_COMMAND_WRITE_CHUNK:
    case WDC_ADMIN_COMMAND_FINISH_UPDATE:
    case WDC_ADMIN_COMMAND_ACTIVATE_TRIAL:
        return WDC_CONTROL_SOURCE_UPDATE;
    case WDC_ADMIN_COMMAND_STATUS:
        return WDC_CONTROL_SOURCE_ADMINISTRATION;
    default:
        return WDC_CONTROL_SOURCE_NONE;
    }
}

static bool request_encoding_valid(const WdcAdminRequest *request,
                                   const uint8_t *payload,
                                   uint32_t payload_bytes)
{
    if (request == NULL ||
        request->struct_size != WDC_ADMIN_REQUEST_BYTES ||
        request->version_major != WDC_ADMIN_VERSION_MAJOR ||
        request->version_minor != WDC_ADMIN_VERSION_MINOR ||
        request->flags != 0u || request->reserved0 != 0u ||
        !bytes_are_zero(request->reserved1,
                        WDC_ADMIN_ARRAY_BYTES(request->reserved1)) ||
        request->request_id == 0u || request->command_sequence == 0u ||
        request->deadline_ms == 0u ||
        request->payload_bytes != payload_bytes ||
        payload_bytes > WDC_ADMIN_MAX_PAYLOAD_BYTES ||
        (payload_bytes != 0u && payload == NULL)) {
        return false;
    }
    if (request->command == WDC_ADMIN_COMMAND_STATUS &&
        (payload_bytes != 0u || request->slot != WDC_ADMIN_SLOT_NONE ||
         request->expected_total_bytes != 0u ||
         !bytes_are_zero(request->artifact_sha256,
                         WDC_ADMIN_ARRAY_BYTES(request->artifact_sha256)))) {
        return false;
    }
    return true;
}

static bool request_update_shape_valid(const WdcAdminRequest *request,
                                       uint32_t payload_bytes,
                                       WdcAdminMode mode)
{
    bool slot_valid;
    bool hash_zero;
    if (request == NULL) {
        return false;
    }
    slot_valid = request->slot == 1u || request->slot == 2u;
    hash_zero = bytes_are_zero(
        request->artifact_sha256,
        WDC_ADMIN_ARRAY_BYTES(request->artifact_sha256));
    switch ((WdcAdminCommand)request->command) {
    case WDC_ADMIN_COMMAND_BEGIN_UPDATE:
    case WDC_ADMIN_COMMAND_FINISH_UPDATE:
    case WDC_ADMIN_COMMAND_ACTIVATE_TRIAL:
        return payload_bytes == 0u && slot_valid &&
               request->expected_total_bytes >= 192u && !hash_zero;
    case WDC_ADMIN_COMMAND_WRITE_CHUNK:
        return payload_bytes != 0u &&
               payload_bytes <= WDC_ADMIN_MAX_PAYLOAD_BYTES && slot_valid &&
               request->expected_total_bytes >= 192u && !hash_zero;
    case WDC_ADMIN_COMMAND_ABORT:
        if (mode == WDC_ADMIN_MODE_RECOVERY) {
            return payload_bytes == 0u &&
                   request->slot == WDC_ADMIN_SLOT_NONE &&
                   request->expected_total_bytes == 0u && hash_zero;
        }
        return payload_bytes == 0u && slot_valid &&
               request->expected_total_bytes >= 192u && !hash_zero;
    case WDC_ADMIN_COMMAND_ENTER_RECOVERY:
    case WDC_ADMIN_COMMAND_REBOOT:
        return payload_bytes == 0u &&
               request->slot == WDC_ADMIN_SLOT_NONE &&
               request->expected_total_bytes == 0u && hash_zero;
    default:
        return true;
    }
}

static int32_t reject_request(WdcAdminCore *core,
                              const WdcAdminRequest *request,
                              WdcAdminPreacceptRejection rejection,
                              uint64_t now_ms,
                              WdcAdminPreacceptResult *out_rejection)
{
    WdcAdminAuditEvent event =
        rejection == WDC_ADMIN_REJECTION_STALE_REPLAY ||
                rejection == WDC_ADMIN_REJECTION_OUT_OF_ORDER
            ? WDC_ADMIN_AUDIT_REPLAY_DECISION
            : WDC_ADMIN_AUDIT_COMMAND_ACCEPTANCE;
    uint64_t request_id = request != NULL ? request->request_id : 0u;
    uint64_t sequence = request != NULL ? request->command_sequence : 0u;
    int32_t status = wdc_admin_rejection_status(rejection);
    set_rejection(out_rejection, rejection, request_id, sequence);
    append_audit(core, event, WDC_ADMIN_AUDIT_DENIED, status, now_ms,
                 request, core->mode, core->mode, WDC_ADMIN_TERMINAL_NONE,
                 request != NULL ? request->slot : WDC_ADMIN_SLOT_NONE,
                 0u, NULL);
    return status;
}

static WdcControlTerminalDisposition control_terminal_disposition(
    WdcAdminTerminalResult result)
{
    switch (result) {
    case WDC_ADMIN_TERMINAL_SUCCEEDED:
    case WDC_ADMIN_TERMINAL_REBOOT_HANDOFF:
        return WDC_CONTROL_TERMINAL_SUCCEEDED;
    case WDC_ADMIN_TERMINAL_TIMED_OUT:
        return WDC_CONTROL_TERMINAL_TIMED_OUT;
    case WDC_ADMIN_TERMINAL_CANCELLED:
        return WDC_CONTROL_TERMINAL_CANCELLED;
    case WDC_ADMIN_TERMINAL_FAILED:
    case WDC_ADMIN_TERMINAL_ABORTED:
        return WDC_CONTROL_TERMINAL_FAILED;
    default:
        return WDC_CONTROL_TERMINAL_NONE;
    }
}

int32_t wdc_admin_core_init(WdcAdminCore *core,
                            const WdcAdminCoreConfig *config)
{
    if (core == NULL || config == NULL || config->control_kernel == NULL ||
        config->authorizer.authorize == NULL ||
        config->artifact_verifier.verify == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    if ((config->initial_mode != WDC_ADMIN_MODE_NORMAL &&
         config->initial_mode != WDC_ADMIN_MODE_RECOVERY) ||
        config->enabled_commands_mask == 0u ||
        (config->enabled_commands_mask & ~WDC_ADMIN_COMMAND_MASK_ALL) != 0u ||
        bytes_are_zero(config->boot_channel_binding_sha256,
                       WDC_ADMIN_ARRAY_BYTES(
                           config->boot_channel_binding_sha256)) ||
        config->control_kernel->profile == NULL ||
        wdc_control_validate_profile(config->control_kernel->profile) != WDC_OK) {
        return WDC_ERR_BAD_ENCODING;
    }
    memset(core, 0, sizeof(*core));
    core->control_kernel = config->control_kernel;
    core->authorizer = config->authorizer;
    core->artifact_verifier = config->artifact_verifier;
    core->mode = config->initial_mode;
    core->enabled_commands_mask = config->enabled_commands_mask;
    memcpy(core->boot_channel_binding_sha256,
           config->boot_channel_binding_sha256,
           sizeof(core->boot_channel_binding_sha256));
    core->authorization_state = WDC_ADMIN_AUTH_UNAUTHENTICATED;
    core->next_command_sequence = 1u;
    core->initialized = true;
    return WDC_OK;
}

int32_t wdc_admin_authorization_begin(
    WdcAdminCore *core,
    const WdcAdminAuthorizationStart *start,
    uint64_t now_ms,
    uint64_t *out_deadline_ms,
    WdcAdminPreacceptResult *out_rejection)
{
    uint64_t deadline;
    bool serial_entry;
    bool external_entry;
    if (core == NULL || start == NULL || out_deadline_ms == NULL ||
        out_rejection == NULL || !core->initialized) {
        return WDC_ERR_BAD_POINTER;
    }
    *out_deadline_ms = 0u;
    set_rejection(out_rejection, WDC_ADMIN_REJECTION_NONE, 0u, 0u);
    (void)wdc_admin_poll(core, now_ms);
    reset_rate_window_if_elapsed(core, now_ms);
    if (now_ms < core->authorization_backoff_until_ms) {
        set_rejection(out_rejection, WDC_ADMIN_REJECTION_RATE_LIMITED, 0u, 0u);
        append_audit(core, WDC_ADMIN_AUDIT_AUTHORIZATION,
                     WDC_ADMIN_AUDIT_DENIED, WDC_ERR_RATE_LIMITED, now_ms,
                     NULL, core->mode, core->mode, WDC_ADMIN_TERMINAL_NONE,
                     WDC_ADMIN_SLOT_NONE, 0u, NULL);
        return WDC_ERR_RATE_LIMITED;
    }
    if (core->lifecycle != WDC_ADMIN_LIFECYCLE_NONE ||
        core->authorization_state == WDC_ADMIN_AUTH_AUTHORIZED ||
        core->authorization_state == WDC_ADMIN_AUTH_CHALLENGE_ISSUED) {
        set_rejection(out_rejection, WDC_ADMIN_REJECTION_BUSY, 0u, 0u);
        return WDC_ERR_BUSY;
    }
    serial_entry =
        start->transport_kind == WDC_ADMIN_TRANSPORT_SERIAL_PHYSICAL_V1 &&
        (start->authorization_method == WDC_ADMIN_AUTH_METHOD_LOCAL_PHYSICAL ||
         start->authorization_method ==
             WDC_ADMIN_AUTH_METHOD_REPLACEABLE_AUTHENTICATOR) &&
        start->attended_physical_entry == 1u;
    external_entry =
        start->transport_kind ==
            WDC_ADMIN_TRANSPORT_AUTHENTICATED_EXTERNAL_V1 &&
        start->authorization_method ==
            WDC_ADMIN_AUTH_METHOD_REPLACEABLE_AUTHENTICATOR &&
        start->attended_physical_entry == 0u;
    if ((!serial_entry && !external_entry) || start->flags != 0u ||
        start->challenge_id == 0u ||
        !bytes_equal(start->channel_binding_sha256,
                     core->boot_channel_binding_sha256,
                     WDC_ADMIN_ARRAY_BYTES(start->channel_binding_sha256)) ||
        !checked_deadline(now_ms, WDC_ADMIN_CHALLENGE_DEADLINE_MS,
                          &deadline)) {
        set_rejection(out_rejection, WDC_ADMIN_REJECTION_UNAUTHORIZED, 0u, 0u);
        append_audit(core, WDC_ADMIN_AUDIT_AUTHORIZATION,
                     WDC_ADMIN_AUDIT_DENIED, WDC_ERR_CAPABILITY_DENIED,
                     now_ms, NULL, core->mode, core->mode,
                     WDC_ADMIN_TERMINAL_NONE, WDC_ADMIN_SLOT_NONE, 0u, NULL);
        return WDC_ERR_CAPABILITY_DENIED;
    }
    memset(&core->challenge, 0, sizeof(core->challenge));
    memset(&core->session, 0, sizeof(core->session));
    core->challenge.start = *start;
    core->challenge.issued_monotonic_ms = now_ms;
    core->challenge.deadline_ms = deadline;
    core->authorization_state = WDC_ADMIN_AUTH_CHALLENGE_ISSUED;
    *out_deadline_ms = deadline;
    append_audit(core, WDC_ADMIN_AUDIT_AUTHORIZATION,
                 WDC_ADMIN_AUDIT_OBSERVED, WDC_OK, now_ms, NULL,
                 core->mode, core->mode, WDC_ADMIN_TERMINAL_NONE,
                 WDC_ADMIN_SLOT_NONE, 0u, NULL);
    return WDC_OK;
}

int32_t wdc_admin_authorization_finish(
    WdcAdminCore *core,
    const uint8_t *proof,
    uint32_t proof_bytes,
    uint64_t now_ms,
    WdcAdminPreacceptResult *out_rejection)
{
    WdcAdminAuthenticatedEntry entry;
    int32_t status;
    if (core == NULL || out_rejection == NULL || !core->initialized) {
        return WDC_ERR_BAD_POINTER;
    }
    set_rejection(out_rejection, WDC_ADMIN_REJECTION_NONE, 0u, 0u);
    if (core->authorization_state != WDC_ADMIN_AUTH_CHALLENGE_ISSUED) {
        set_rejection(out_rejection, WDC_ADMIN_REJECTION_WRONG_STATE, 0u, 0u);
        return WDC_ERR_INVALID_STATE;
    }
    if (now_ms >= core->challenge.deadline_ms) {
        core->authorization_state = WDC_ADMIN_AUTH_EXPIRED;
        set_rejection(out_rejection, WDC_ADMIN_REJECTION_EXPIRED, 0u, 0u);
        append_audit(core, WDC_ADMIN_AUDIT_AUTHORIZATION,
                     WDC_ADMIN_AUDIT_DENIED, WDC_ERR_TIMEOUT, now_ms, NULL,
                     core->mode, core->mode, WDC_ADMIN_TERMINAL_NONE,
                     WDC_ADMIN_SLOT_NONE, 0u, NULL);
        memset(&core->challenge, 0, sizeof(core->challenge));
        return WDC_ERR_TIMEOUT;
    }
    if (proof_bytes > WDC_ADMIN_MAX_PAYLOAD_BYTES ||
        (proof_bytes != 0u && proof == NULL)) {
        record_authorization_failure(core, now_ms);
        set_rejection(out_rejection, WDC_ADMIN_REJECTION_BOUNDS, 0u, 0u);
        append_audit(core, WDC_ADMIN_AUDIT_AUTHORIZATION,
                     WDC_ADMIN_AUDIT_DENIED, WDC_ERR_BAD_LENGTH, now_ms,
                     NULL, core->mode, core->mode, WDC_ADMIN_TERMINAL_NONE,
                     WDC_ADMIN_SLOT_NONE, 0u, NULL);
        core->authorization_state = WDC_ADMIN_AUTH_UNAUTHENTICATED;
        memset(&core->challenge, 0, sizeof(core->challenge));
        return WDC_ERR_BAD_LENGTH;
    }
    memset(&entry, 0, sizeof(entry));
    status = core->authorizer.authorize(core->authorizer.context,
                                        &core->challenge,
                                        proof,
                                        proof_bytes,
                                        &entry);
    if (status != WDC_OK || !authenticated_entry_valid(core, &entry, now_ms)) {
        record_authorization_failure(core, now_ms);
        set_rejection(out_rejection, WDC_ADMIN_REJECTION_UNAUTHORIZED, 0u, 0u);
        append_audit(core, WDC_ADMIN_AUDIT_AUTHORIZATION,
                     WDC_ADMIN_AUDIT_DENIED, WDC_ERR_CAPABILITY_DENIED,
                     now_ms, NULL, core->mode, core->mode,
                     WDC_ADMIN_TERMINAL_NONE, WDC_ADMIN_SLOT_NONE, 0u, NULL);
        core->authorization_state = WDC_ADMIN_AUTH_UNAUTHENTICATED;
        memset(&core->challenge, 0, sizeof(core->challenge));
        memset(&entry, 0, sizeof(entry));
        return WDC_ERR_CAPABILITY_DENIED;
    }
    core->session = entry;
    core->authorization_epoch_high_water = entry.authorization_epoch;
    core->next_command_sequence = 1u;
    core->last_activity_ms = now_ms;
    core->authorization_state = WDC_ADMIN_AUTH_AUTHORIZED;
    core->authorization_failure_count = 0u;
    core->authorization_window_start_ms = 0u;
    core->authorization_backoff_until_ms = 0u;
    append_audit(core, WDC_ADMIN_AUDIT_AUTHORIZATION,
                 WDC_ADMIN_AUDIT_ALLOWED, WDC_OK, now_ms, NULL,
                 core->mode, core->mode, WDC_ADMIN_TERMINAL_NONE,
                 WDC_ADMIN_SLOT_NONE, 0u, NULL);
    memset(&core->challenge, 0, sizeof(core->challenge));
    return WDC_OK;
}

int32_t wdc_admin_session_close(WdcAdminCore *core, uint64_t now_ms)
{
    if (core == NULL || !core->initialized) {
        return WDC_ERR_BAD_POINTER;
    }
    if (core->lifecycle != WDC_ADMIN_LIFECYCLE_NONE) {
        return WDC_ERR_BUSY;
    }
    if (core->authorization_state != WDC_ADMIN_AUTH_AUTHORIZED &&
        core->authorization_state != WDC_ADMIN_AUTH_EXPIRED &&
        core->authorization_state != WDC_ADMIN_AUTH_REVOKED) {
        return WDC_ERR_INVALID_STATE;
    }
    core->authorization_state = WDC_ADMIN_AUTH_CLOSED;
    append_audit(core, WDC_ADMIN_AUDIT_AUTHORIZATION,
                 WDC_ADMIN_AUDIT_OBSERVED, WDC_OK, now_ms, NULL,
                 core->mode, core->mode, WDC_ADMIN_TERMINAL_NONE,
                 WDC_ADMIN_SLOT_NONE, 0u, NULL);
    return WDC_OK;
}

int32_t wdc_admin_session_revoke(WdcAdminCore *core, uint64_t now_ms)
{
    if (core == NULL || !core->initialized) {
        return WDC_ERR_BAD_POINTER;
    }
    if (core->lifecycle != WDC_ADMIN_LIFECYCLE_NONE) {
        return WDC_ERR_BUSY;
    }
    if (core->authorization_state != WDC_ADMIN_AUTH_AUTHORIZED) {
        return WDC_ERR_INVALID_STATE;
    }
    core->authorization_state = WDC_ADMIN_AUTH_REVOKED;
    append_audit(core, WDC_ADMIN_AUDIT_AUTHORIZATION,
                 WDC_ADMIN_AUDIT_DENIED, WDC_ERR_CAPABILITY_DENIED, now_ms,
                 NULL, core->mode, core->mode, WDC_ADMIN_TERMINAL_NONE,
                 WDC_ADMIN_SLOT_NONE, 0u, NULL);
    return WDC_OK;
}

int32_t wdc_admin_poll(WdcAdminCore *core, uint64_t now_ms)
{
    bool session_expired;
    WdcAdminTerminalMetadata metadata;
    int32_t status;
    if (core == NULL || !core->initialized) {
        return WDC_ERR_BAD_POINTER;
    }
    reset_rate_window_if_elapsed(core, now_ms);
    if (core->authorization_state == WDC_ADMIN_AUTH_CHALLENGE_ISSUED &&
        now_ms >= core->challenge.deadline_ms) {
        append_audit(core, WDC_ADMIN_AUDIT_AUTHORIZATION,
                     WDC_ADMIN_AUDIT_DENIED, WDC_ERR_TIMEOUT, now_ms, NULL,
                     core->mode, core->mode, WDC_ADMIN_TERMINAL_NONE,
                     WDC_ADMIN_SLOT_NONE, 0u, NULL);
        core->authorization_state = WDC_ADMIN_AUTH_EXPIRED;
        memset(&core->challenge, 0, sizeof(core->challenge));
    }
    if (core->authorization_state != WDC_ADMIN_AUTH_AUTHORIZED) {
        return WDC_OK;
    }
    session_expired = now_ms >= core->session.expires_monotonic_ms ||
                      now_ms < core->last_activity_ms ||
                      now_ms - core->last_activity_ms >=
                          WDC_ADMIN_SESSION_IDLE_DEADLINE_MS;
    if (core->lifecycle == WDC_ADMIN_LIFECYCLE_IN_PROGRESS &&
        (now_ms >= core->active_request.deadline_ms || session_expired)) {
        memset(&metadata, 0, sizeof(metadata));
        metadata.final_state = (uint32_t)core->mode;
        metadata.slot = core->active_request.slot;
        status = wdc_admin_complete(core, WDC_ADMIN_TERMINAL_TIMED_OUT,
                                    WDC_ERR_TIMEOUT, &metadata, now_ms);
        if (status != WDC_OK) {
            return status;
        }
    }
    if (session_expired) {
        core->authorization_state = WDC_ADMIN_AUTH_EXPIRED;
        append_audit(core, WDC_ADMIN_AUDIT_AUTHORIZATION,
                     WDC_ADMIN_AUDIT_DENIED, WDC_ERR_TIMEOUT, now_ms, NULL,
                     core->mode, core->mode, WDC_ADMIN_TERMINAL_NONE,
                     WDC_ADMIN_SLOT_NONE, 0u, NULL);
    }
    return WDC_OK;
}

int32_t wdc_admin_submit(WdcAdminCore *core,
                         const WdcAdminRequest *request,
                         const uint8_t *payload,
                         uint32_t payload_bytes,
                         uint64_t now_ms,
                         WdcAdminPreacceptResult *out_rejection)
{
    WdcAdminCommand command;
    WdcControlSource source;
    WdcControlWorkRequest work;
    WdcControlCompletion control_rejection;
    uint32_t privilege;
    uint32_t ticket = 0u;
    uint32_t correlation;
    int32_t status;
    if (core == NULL || request == NULL || out_rejection == NULL ||
        !core->initialized) {
        return WDC_ERR_BAD_POINTER;
    }
    set_rejection(out_rejection, WDC_ADMIN_REJECTION_NONE,
                  request->request_id, request->command_sequence);
    (void)wdc_admin_poll(core, now_ms);
    if (!request_encoding_valid(request, payload, payload_bytes)) {
        return reject_request(core, request, WDC_ADMIN_REJECTION_BOUNDS,
                              now_ms, out_rejection);
    }
    if (core->authorization_state == WDC_ADMIN_AUTH_EXPIRED) {
        return reject_request(core, request, WDC_ADMIN_REJECTION_EXPIRED,
                              now_ms, out_rejection);
    }
    if (core->authorization_state != WDC_ADMIN_AUTH_AUTHORIZED ||
        request->authorization_epoch != core->session.authorization_epoch ||
        request->session_nonce != core->session.session_nonce) {
        return reject_request(core, request, WDC_ADMIN_REJECTION_UNAUTHORIZED,
                              now_ms, out_rejection);
    }
    if (request->deadline_ms <= now_ms ||
        request->deadline_ms - now_ms > WDC_ADMIN_COMMAND_DEADLINE_MS) {
        return reject_request(core, request, WDC_ADMIN_REJECTION_EXPIRED,
                              now_ms, out_rejection);
    }
    if (request->command_sequence < core->next_command_sequence) {
        return reject_request(core, request,
                              WDC_ADMIN_REJECTION_STALE_REPLAY,
                              now_ms, out_rejection);
    }
    if (request->command_sequence > core->next_command_sequence) {
        return reject_request(core, request,
                              WDC_ADMIN_REJECTION_OUT_OF_ORDER,
                              now_ms, out_rejection);
    }
    /*
     * Sequence zero is never valid.  Refuse the final representable value
     * before ownership is allocated so the replay high-water cannot wrap and
     * reopen an earlier command identity.  The session remains explicitly
     * closable and a fresh, higher authorization epoch may be established.
     */
    if (core->next_command_sequence == UINT64_MAX) {
        return reject_request(core, request,
                              WDC_ADMIN_REJECTION_RATE_LIMITED,
                              now_ms, out_rejection);
    }
    if (!valid_command(request->command)) {
        return reject_request(core, request, WDC_ADMIN_REJECTION_UNSUPPORTED,
                              now_ms, out_rejection);
    }
    command = (WdcAdminCommand)request->command;
    if ((core->enabled_commands_mask & WDC_ADMIN_COMMAND_BIT(command)) == 0u) {
        return reject_request(core, request, WDC_ADMIN_REJECTION_UNSUPPORTED,
                              now_ms, out_rejection);
    }
    if (!request_update_shape_valid(request, payload_bytes, core->mode)) {
        return reject_request(core, request, WDC_ADMIN_REJECTION_BOUNDS,
                              now_ms, out_rejection);
    }
    privilege = command_privilege(command, core->mode);
    if (privilege == 0u ||
        (core->session.privilege_mask & privilege) != privilege) {
        return reject_request(core, request, WDC_ADMIN_REJECTION_UNAUTHORIZED,
                              now_ms, out_rejection);
    }
    if (!command_allowed_in_state(command, core->mode)) {
        return reject_request(core, request, WDC_ADMIN_REJECTION_WRONG_STATE,
                              now_ms, out_rejection);
    }
    if (core->lifecycle != WDC_ADMIN_LIFECYCLE_NONE) {
        return reject_request(core, request, WDC_ADMIN_REJECTION_BUSY,
                              now_ms, out_rejection);
    }
    source = control_source_for_command(command, core->mode);
    if (source == WDC_CONTROL_SOURCE_NONE) {
        return reject_request(core, request, WDC_ADMIN_REJECTION_UNSUPPORTED,
                              now_ms, out_rejection);
    }
    correlation = (uint32_t)(request->request_id ^
                             (request->request_id >> 32u));
    if (correlation == 0u) {
        correlation = 1u;
    }
    memset(&work, 0, sizeof(work));
    work.source = source;
    work.operation_id = request->command;
    work.correlation_id = correlation;
    work.value = payload_bytes;
    memset(&control_rejection, 0, sizeof(control_rejection));
    status = wdc_control_submit(core->control_kernel, &work, &ticket,
                                &control_rejection);
    if (status != WDC_OK) {
        return reject_request(core, request, WDC_ADMIN_REJECTION_BUSY,
                              now_ms, out_rejection);
    }
    core->active_request = *request;
    if (payload_bytes != 0u) {
        memcpy(core->payload, payload, payload_bytes);
    }
    if (payload_bytes < sizeof(core->payload)) {
        memset(core->payload + payload_bytes, 0,
               sizeof(core->payload) - payload_bytes);
    }
    memset(core->response, 0, sizeof(core->response));
    memset(&core->terminal, 0, sizeof(core->terminal));
    core->payload_bytes = payload_bytes;
    core->response_bytes = 0u;
    core->active_control_ticket = ticket;
    core->active_control_source = source;
    core->lifecycle = WDC_ADMIN_LIFECYCLE_ACCEPTED;
    core->terminal_ready = false;
    core->response_written = false;
    core->next_command_sequence += 1u;
    core->last_activity_ms = now_ms;
    append_audit(core, WDC_ADMIN_AUDIT_COMMAND_ACCEPTANCE,
                 WDC_ADMIN_AUDIT_ALLOWED, WDC_OK, now_ms, request,
                 core->mode, core->mode, WDC_ADMIN_TERMINAL_NONE,
                 request->slot, 0u, NULL);
    return WDC_OK;
}

int32_t wdc_admin_begin_command(WdcAdminCore *core,
                                const WdcControlWorkItem *work,
                                uint64_t now_ms,
                                WdcAdminAcceptedCommand *out_command)
{
    WdcAdminTerminalMetadata metadata;
    if (core == NULL || work == NULL || out_command == NULL ||
        !core->initialized) {
        return WDC_ERR_BAD_POINTER;
    }
    memset(out_command, 0, sizeof(*out_command));
    if (core->lifecycle != WDC_ADMIN_LIFECYCLE_ACCEPTED ||
        work->ticket != core->active_control_ticket ||
        work->request.source != core->active_control_source ||
        work->request.operation_id != core->active_request.command) {
        return WDC_ERR_INVALID_STATE;
    }
    core->lifecycle = WDC_ADMIN_LIFECYCLE_IN_PROGRESS;
    if (core->authorization_state != WDC_ADMIN_AUTH_AUTHORIZED ||
        now_ms >= core->active_request.deadline_ms) {
        memset(&metadata, 0, sizeof(metadata));
        metadata.final_state = (uint32_t)core->mode;
        metadata.slot = core->active_request.slot;
        if (wdc_admin_complete(core, WDC_ADMIN_TERMINAL_TIMED_OUT,
                               WDC_ERR_TIMEOUT, &metadata, now_ms) != WDC_OK) {
            return WDC_ERR_CONTRACT_VIOLATION;
        }
        return WDC_ERR_TIMEOUT;
    }
    out_command->control_ticket = core->active_control_ticket;
    out_command->control_source = core->active_control_source;
    out_command->request = core->active_request;
    out_command->payload = core->payload;
    out_command->payload_bytes = core->payload_bytes;
    core->last_activity_ms = now_ms;
    return WDC_OK;
}

int32_t wdc_admin_write_response(WdcAdminCore *core,
                                 const uint8_t *response,
                                 uint32_t response_bytes)
{
    if (core == NULL || !core->initialized) {
        return WDC_ERR_BAD_POINTER;
    }
    if (core->lifecycle != WDC_ADMIN_LIFECYCLE_IN_PROGRESS ||
        core->active_request.command != WDC_ADMIN_COMMAND_STATUS ||
        core->response_written) {
        return WDC_ERR_INVALID_STATE;
    }
    if (response_bytes > WDC_ADMIN_MAX_STATUS_RESPONSE_BYTES ||
        (response_bytes != 0u && response == NULL)) {
        return WDC_ERR_BAD_LENGTH;
    }
    if (response_bytes != 0u) {
        memcpy(core->response, response, response_bytes);
    }
    if (response_bytes < sizeof(core->response)) {
        memset(core->response + response_bytes, 0,
               sizeof(core->response) - response_bytes);
    }
    core->response_bytes = response_bytes;
    core->response_written = true;
    return WDC_OK;
}

int32_t wdc_admin_complete(WdcAdminCore *core,
                           WdcAdminTerminalResult result,
                           int32_t status,
                           const WdcAdminTerminalMetadata *metadata,
                           uint64_t now_ms)
{
    WdcControlTerminalDisposition disposition;
    int32_t control_status;
    if (core == NULL || metadata == NULL || !core->initialized) {
        return WDC_ERR_BAD_POINTER;
    }
    if (core->lifecycle != WDC_ADMIN_LIFECYCLE_IN_PROGRESS ||
        core->terminal_ready) {
        return WDC_ERR_INVALID_STATE;
    }
    if (!terminal_pair_valid(result, status) ||
        !valid_mode((WdcAdminMode)metadata->final_state) ||
        metadata->flags != 0u) {
        return WDC_ERR_BAD_ENCODING;
    }
    disposition = control_terminal_disposition(result);
    control_status = wdc_control_complete(core->control_kernel,
                                          core->active_control_ticket,
                                          disposition,
                                          status);
    if (control_status != WDC_OK) {
        return control_status;
    }
    memset(&core->terminal, 0, sizeof(core->terminal));
    core->terminal.struct_size = WDC_ADMIN_TERMINAL_BYTES;
    core->terminal.version_major = WDC_ADMIN_VERSION_MAJOR;
    core->terminal.version_minor = WDC_ADMIN_VERSION_MINOR;
    core->terminal.result = (uint32_t)result;
    core->terminal.status = status;
    core->terminal.request_id = core->active_request.request_id;
    core->terminal.session_nonce = core->active_request.session_nonce;
    core->terminal.command_sequence = core->active_request.command_sequence;
    core->terminal.bytes_received = metadata->bytes_received;
    core->terminal.metadata_commits = metadata->metadata_commits;
    core->terminal.final_state = metadata->final_state;
    core->terminal.slot = metadata->slot;
    core->terminal.flags = metadata->flags;
    core->terminal_ready = true;
    core->lifecycle = WDC_ADMIN_LIFECYCLE_TERMINAL;
    core->last_activity_ms = now_ms;
    append_audit(core, WDC_ADMIN_AUDIT_TERMINAL_RESULT,
                 status == WDC_OK ? WDC_ADMIN_AUDIT_ALLOWED
                                  : WDC_ADMIN_AUDIT_FAILED,
                 status, now_ms, &core->active_request,
                 core->mode, (WdcAdminMode)metadata->final_state, result,
                 metadata->slot, metadata->flags, NULL);
    return WDC_OK;
}

int32_t wdc_admin_take_terminal(WdcAdminCore *core,
                                WdcAdminTerminalRecord *out_terminal,
                                uint8_t *out_response,
                                uint32_t response_capacity,
                                uint32_t *out_response_bytes)
{
    WdcControlCompletion completion;
    int32_t status;
    if (core == NULL || out_terminal == NULL || out_response_bytes == NULL ||
        !core->initialized) {
        return WDC_ERR_BAD_POINTER;
    }
    *out_response_bytes = 0u;
    if (!core->terminal_ready ||
        core->lifecycle != WDC_ADMIN_LIFECYCLE_TERMINAL) {
        return WDC_ERR_NOT_AVAILABLE;
    }
    if (core->response_bytes > response_capacity ||
        (core->response_bytes != 0u && out_response == NULL)) {
        return WDC_ERR_RESPONSE_TOO_SMALL;
    }
    memset(&completion, 0, sizeof(completion));
    status = wdc_control_take_completion(core->control_kernel,
                                         core->active_control_ticket,
                                         &completion);
    if (status != WDC_OK) {
        return status;
    }
    *out_terminal = core->terminal;
    if (core->response_bytes != 0u) {
        memcpy(out_response, core->response, core->response_bytes);
    }
    *out_response_bytes = core->response_bytes;
    memset(&core->active_request, 0, sizeof(core->active_request));
    memset(&core->terminal, 0, sizeof(core->terminal));
    memset(core->payload, 0, sizeof(core->payload));
    memset(core->response, 0, sizeof(core->response));
    core->active_control_ticket = 0u;
    core->active_control_source = WDC_CONTROL_SOURCE_NONE;
    core->payload_bytes = 0u;
    core->response_bytes = 0u;
    core->terminal_ready = false;
    core->response_written = false;
    core->lifecycle = WDC_ADMIN_LIFECYCLE_NONE;
    return WDC_OK;
}

int32_t wdc_admin_verify_artifact(
    WdcAdminCore *core,
    const WdcAdminArtifactCandidate *candidate,
    WdcAdminArtifactVerification *out_verification,
    uint64_t now_ms)
{
    int32_t status;
    bool result_valid;
    if (core == NULL || candidate == NULL || out_verification == NULL ||
        !core->initialized) {
        return WDC_ERR_BAD_POINTER;
    }
    memset(out_verification, 0, sizeof(*out_verification));
    if (core->lifecycle != WDC_ADMIN_LIFECYCLE_IN_PROGRESS ||
        core->mode != WDC_ADMIN_MODE_UPDATE ||
        (core->active_request.command != WDC_ADMIN_COMMAND_FINISH_UPDATE &&
         core->active_request.command != WDC_ADMIN_COMMAND_ACTIVATE_TRIAL)) {
        return WDC_ERR_INVALID_STATE;
    }
    if (candidate->struct_size != sizeof(*candidate) ||
        candidate->version_major != WDC_ADMIN_VERSION_MAJOR ||
        candidate->version_minor != WDC_ADMIN_VERSION_MINOR ||
        candidate->slot == WDC_ADMIN_SLOT_NONE ||
        candidate->stored_bytes == 0u || candidate->flags != 0u ||
        bytes_are_zero(candidate->artifact_sha256,
                       WDC_ADMIN_ARRAY_BYTES(candidate->artifact_sha256)) ||
        bytes_are_zero(candidate->running_host_fingerprint_sha256,
                       WDC_ADMIN_ARRAY_BYTES(
                           candidate->running_host_fingerprint_sha256)) ||
        !bytes_are_zero(candidate->reserved,
                        WDC_ADMIN_ARRAY_BYTES(candidate->reserved))) {
        return WDC_ERR_BAD_ENCODING;
    }
    status = core->artifact_verifier.verify(
        core->artifact_verifier.context, candidate, out_verification);
    result_valid =
        out_verification->struct_size == sizeof(*out_verification) &&
        out_verification->version_major == WDC_ADMIN_VERSION_MAJOR &&
        out_verification->version_minor == WDC_ADMIN_VERSION_MINOR &&
        out_verification->flags == 0u &&
        out_verification->complete_artifact_valid <= 1u &&
        out_verification->host_compatible <= 1u &&
        out_verification->security_floor_valid <= 1u &&
        out_verification->artifact_authority_valid <= 1u &&
        bytes_are_zero(out_verification->reserved,
                       WDC_ADMIN_ARRAY_BYTES(out_verification->reserved));
    if (status != WDC_OK || !result_valid ||
        out_verification->status != status) {
        append_audit(core, WDC_ADMIN_AUDIT_VERIFICATION,
                     WDC_ADMIN_AUDIT_FAILED,
                     status == WDC_OK ? WDC_ERR_CONTRACT_VIOLATION : status,
                     now_ms, &core->active_request, core->mode, core->mode,
                     WDC_ADMIN_TERMINAL_NONE, candidate->slot, 0u,
                     candidate->artifact_sha256);
        return status == WDC_OK ? WDC_ERR_CONTRACT_VIOLATION : status;
    }
    append_audit(core, WDC_ADMIN_AUDIT_VERIFICATION,
                 status == WDC_OK ? WDC_ADMIN_AUDIT_ALLOWED
                                  : WDC_ADMIN_AUDIT_FAILED,
                 status, now_ms, &core->active_request, core->mode, core->mode,
                 WDC_ADMIN_TERMINAL_NONE, candidate->slot, 0u,
                 candidate->artifact_sha256);
    return status;
}

int32_t wdc_admin_audit_emit(WdcAdminCore *core,
                             const WdcAdminAuditEmission *emission,
                             uint64_t now_ms)
{
    if (core == NULL || emission == NULL || !core->initialized) {
        return WDC_ERR_BAD_POINTER;
    }
    if (emission->event < WDC_ADMIN_AUDIT_AUTHORIZATION ||
        emission->event > WDC_ADMIN_AUDIT_REBOOT_HANDOFF ||
        emission->outcome < WDC_ADMIN_AUDIT_ALLOWED ||
        emission->outcome > WDC_ADMIN_AUDIT_OBSERVED ||
        !valid_mode(emission->from_state) ||
        !valid_mode(emission->to_state) || emission->flags != 0u ||
        (emission->terminal_result != WDC_ADMIN_TERMINAL_NONE &&
         !valid_terminal_result(emission->terminal_result))) {
        return WDC_ERR_BAD_ENCODING;
    }
    append_audit(core, emission->event, emission->outcome, emission->status,
                 now_ms,
                 core->lifecycle != WDC_ADMIN_LIFECYCLE_NONE
                     ? &core->active_request
                     : NULL,
                 emission->from_state, emission->to_state,
                 emission->terminal_result, emission->slot,
                 emission->flags, emission->artifact_sha256);
    return WDC_OK;
}

int32_t wdc_admin_take_audit(WdcAdminCore *core,
                             WdcAdminAuditRecord *out_record)
{
    if (core == NULL || out_record == NULL || !core->initialized) {
        return WDC_ERR_BAD_POINTER;
    }
    if (core->audit_count == 0u) {
        return WDC_ERR_NOT_AVAILABLE;
    }
    *out_record = core->audit[core->audit_head];
    memset(&core->audit[core->audit_head], 0,
           sizeof(core->audit[core->audit_head]));
    core->audit_head = (core->audit_head + 1u) %
                       WDC_ADMIN_AUDIT_RING_RECORDS;
    core->audit_count -= 1u;
    return WDC_OK;
}

WdcAdminAuthorizationState wdc_admin_authorization_state(
    const WdcAdminCore *core)
{
    return core != NULL && core->initialized
               ? core->authorization_state
               : WDC_ADMIN_AUTH_UNAUTHENTICATED;
}

WdcAdminCommandLifecycle wdc_admin_command_lifecycle(
    const WdcAdminCore *core)
{
    return core != NULL && core->initialized
               ? core->lifecycle
               : WDC_ADMIN_LIFECYCLE_NONE;
}

WdcAdminMode wdc_admin_mode(const WdcAdminCore *core)
{
    return core != NULL && core->initialized ? core->mode
                                              : WDC_ADMIN_MODE_NONE;
}

uint64_t wdc_admin_next_command_sequence(const WdcAdminCore *core)
{
    return core != NULL && core->initialized ? core->next_command_sequence
                                              : 0u;
}

uint32_t wdc_admin_audit_pending(const WdcAdminCore *core)
{
    return core != NULL && core->initialized ? core->audit_count : 0u;
}

uint32_t wdc_admin_audit_losses(const WdcAdminCore *core)
{
    return core != NULL && core->initialized ? core->audit_loss_count : 0u;
}

uint32_t wdc_admin_fixed_storage_bytes(void)
{
    return (uint32_t)(sizeof(WdcAdminCore) + sizeof(WdcAdminSerialAdapter));
}

int32_t wdc_admin_rejection_status(WdcAdminPreacceptRejection rejection)
{
    switch (rejection) {
    case WDC_ADMIN_REJECTION_NONE:
        return WDC_OK;
    case WDC_ADMIN_REJECTION_BAD_FRAME:
        return WDC_ERR_BAD_ENCODING;
    case WDC_ADMIN_REJECTION_BOUNDS:
        return WDC_ERR_BAD_LENGTH;
    case WDC_ADMIN_REJECTION_UNAUTHORIZED:
        return WDC_ERR_CAPABILITY_DENIED;
    case WDC_ADMIN_REJECTION_EXPIRED:
        return WDC_ERR_TIMEOUT;
    case WDC_ADMIN_REJECTION_STALE_REPLAY:
        return WDC_ERR_CONTRACT_VIOLATION;
    case WDC_ADMIN_REJECTION_OUT_OF_ORDER:
        return WDC_ERR_NOT_SYNCHRONIZED;
    case WDC_ADMIN_REJECTION_RATE_LIMITED:
        return WDC_ERR_RATE_LIMITED;
    case WDC_ADMIN_REJECTION_BUSY:
        return WDC_ERR_BUSY;
    case WDC_ADMIN_REJECTION_UNSUPPORTED:
        return WDC_ERR_UNSUPPORTED_OPCODE;
    case WDC_ADMIN_REJECTION_WRONG_STATE:
        return WDC_ERR_INVALID_STATE;
    default:
        return WDC_ERR_BAD_ENCODING;
    }
}

uint32_t wdc_admin_link_anchor(void)
{
    return WDC_ADMIN_VERSION_MAJOR;
}
