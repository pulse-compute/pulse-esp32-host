#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "wdc_abi.h"
#include "wdc_control.h"

#ifdef __cplusplus
extern "C" {
#endif

#define WDC_ADMIN_VERSION_MAJOR 1u
#define WDC_ADMIN_VERSION_MINOR 0u

#define WDC_ADMIN_AUTHENTICATED_ENTRY_BYTES 128u
#define WDC_ADMIN_REQUEST_BYTES 112u
#define WDC_ADMIN_TERMINAL_BYTES 64u
#define WDC_ADMIN_AUDIT_RECORD_BYTES 160u
#define WDC_ADMIN_AUDIT_RING_RECORDS 32u
#define WDC_ADMIN_MAX_FRAME_BYTES 2048u
#define WDC_ADMIN_MAX_PAYLOAD_BYTES 1024u
#define WDC_ADMIN_MAX_STATUS_RESPONSE_BYTES 1024u
#define WDC_ADMIN_CHALLENGE_DEADLINE_MS 10000u
#define WDC_ADMIN_COMMAND_DEADLINE_MS 30000u
#define WDC_ADMIN_SESSION_IDLE_DEADLINE_MS 30000u
#define WDC_ADMIN_SESSION_LIFETIME_MS 900000u
#define WDC_ADMIN_AUTHORIZATION_WINDOW_MS 60000u
#define WDC_ADMIN_AUTHORIZATION_FAILURE_LIMIT 8u
#define WDC_ADMIN_AUTHORIZATION_BACKOFF_MS 30000u
#define WDC_ADMIN_CORE_STATIC_BUDGET_BYTES 8192u
#define WDC_ADMIN_SERIAL_STATIC_BUDGET_BYTES 2304u
#define WDC_ADMIN_FIXED_STORAGE_BUDGET_BYTES 12288u
#define WDC_ADMIN_SLOT_NONE UINT32_MAX

typedef enum WdcAdminTransportKind {
    WDC_ADMIN_TRANSPORT_NONE = 0,
    WDC_ADMIN_TRANSPORT_SERIAL_PHYSICAL_V1 = 1,
    WDC_ADMIN_TRANSPORT_AUTHENTICATED_EXTERNAL_V1 = 2,
    WDC_ADMIN_TRANSPORT_AUTHENTICATED_EXTERNAL_V1_RESERVED =
        WDC_ADMIN_TRANSPORT_AUTHENTICATED_EXTERNAL_V1,
} WdcAdminTransportKind;

typedef enum WdcAdminAuthorizationMethod {
    WDC_ADMIN_AUTH_METHOD_NONE = 0,
    WDC_ADMIN_AUTH_METHOD_LOCAL_PHYSICAL = 1,
    WDC_ADMIN_AUTH_METHOD_REPLACEABLE_AUTHENTICATOR = 2,
} WdcAdminAuthorizationMethod;

typedef enum WdcAdminAuthorizationState {
    WDC_ADMIN_AUTH_UNAUTHENTICATED = 0,
    WDC_ADMIN_AUTH_CHALLENGE_ISSUED = 1,
    WDC_ADMIN_AUTH_AUTHORIZED = 2,
    WDC_ADMIN_AUTH_EXPIRED = 3,
    WDC_ADMIN_AUTH_REVOKED = 4,
    WDC_ADMIN_AUTH_CLOSED = 5,
} WdcAdminAuthorizationState;

typedef enum WdcAdminPrivilege {
    WDC_ADMIN_PRIVILEGE_STATUS = 1u << 0u,
    WDC_ADMIN_PRIVILEGE_UPDATE = 1u << 1u,
    WDC_ADMIN_PRIVILEGE_RECOVERY = 1u << 2u,
    WDC_ADMIN_PRIVILEGE_REBOOT = 1u << 3u,
} WdcAdminPrivilege;

#define WDC_ADMIN_PRIVILEGE_ALL \
    (WDC_ADMIN_PRIVILEGE_STATUS | WDC_ADMIN_PRIVILEGE_UPDATE | \
     WDC_ADMIN_PRIVILEGE_RECOVERY | WDC_ADMIN_PRIVILEGE_REBOOT)

typedef enum WdcAdminCommand {
    WDC_ADMIN_COMMAND_NONE = 0,
    WDC_ADMIN_COMMAND_STATUS = 1,
    WDC_ADMIN_COMMAND_BEGIN_UPDATE = 2,
    WDC_ADMIN_COMMAND_WRITE_CHUNK = 3,
    WDC_ADMIN_COMMAND_FINISH_UPDATE = 4,
    WDC_ADMIN_COMMAND_ABORT = 5,
    WDC_ADMIN_COMMAND_ENTER_RECOVERY = 6,
    WDC_ADMIN_COMMAND_ACTIVATE_TRIAL = 7,
    WDC_ADMIN_COMMAND_REBOOT = 8,
} WdcAdminCommand;

#define WDC_ADMIN_COMMAND_BIT(command) \
    (1u << ((uint32_t)(command) - 1u))
#define WDC_ADMIN_COMMAND_MASK_ALL 0x000000ffu
#define WDC_ADMIN_HP41_COMMAND_MASK \
    WDC_ADMIN_COMMAND_BIT(WDC_ADMIN_COMMAND_STATUS)
#define WDC_ADMIN_HP42_COMMAND_MASK                                      \
    (WDC_ADMIN_HP41_COMMAND_MASK |                                      \
     WDC_ADMIN_COMMAND_BIT(WDC_ADMIN_COMMAND_BEGIN_UPDATE) |            \
     WDC_ADMIN_COMMAND_BIT(WDC_ADMIN_COMMAND_WRITE_CHUNK) |             \
     WDC_ADMIN_COMMAND_BIT(WDC_ADMIN_COMMAND_FINISH_UPDATE) |           \
     WDC_ADMIN_COMMAND_BIT(WDC_ADMIN_COMMAND_ABORT) |                   \
     WDC_ADMIN_COMMAND_BIT(WDC_ADMIN_COMMAND_ACTIVATE_TRIAL))
#define WDC_ADMIN_HP43_COMMAND_MASK WDC_ADMIN_COMMAND_MASK_ALL

typedef enum WdcAdminPreacceptRejection {
    WDC_ADMIN_REJECTION_NONE = 0,
    WDC_ADMIN_REJECTION_BAD_FRAME = 1,
    WDC_ADMIN_REJECTION_BOUNDS = 2,
    WDC_ADMIN_REJECTION_UNAUTHORIZED = 3,
    WDC_ADMIN_REJECTION_EXPIRED = 4,
    WDC_ADMIN_REJECTION_STALE_REPLAY = 5,
    WDC_ADMIN_REJECTION_OUT_OF_ORDER = 6,
    WDC_ADMIN_REJECTION_RATE_LIMITED = 7,
    WDC_ADMIN_REJECTION_BUSY = 8,
    WDC_ADMIN_REJECTION_UNSUPPORTED = 9,
    WDC_ADMIN_REJECTION_WRONG_STATE = 10,
} WdcAdminPreacceptRejection;

typedef enum WdcAdminCommandLifecycle {
    WDC_ADMIN_LIFECYCLE_NONE = 0,
    WDC_ADMIN_LIFECYCLE_RECEIVED = 1,
    WDC_ADMIN_LIFECYCLE_ACCEPTED = 2,
    WDC_ADMIN_LIFECYCLE_IN_PROGRESS = 3,
    WDC_ADMIN_LIFECYCLE_TERMINAL = 4,
} WdcAdminCommandLifecycle;

typedef enum WdcAdminTerminalResult {
    WDC_ADMIN_TERMINAL_NONE = 0,
    WDC_ADMIN_TERMINAL_SUCCEEDED = 1,
    WDC_ADMIN_TERMINAL_FAILED = 2,
    WDC_ADMIN_TERMINAL_TIMED_OUT = 3,
    WDC_ADMIN_TERMINAL_CANCELLED = 4,
    WDC_ADMIN_TERMINAL_ABORTED = 5,
    WDC_ADMIN_TERMINAL_REBOOT_HANDOFF = 6,
} WdcAdminTerminalResult;

typedef enum WdcAdminMode {
    WDC_ADMIN_MODE_NONE = 0,
    WDC_ADMIN_MODE_NORMAL = 1,
    WDC_ADMIN_MODE_QUIESCE = 2,
    WDC_ADMIN_MODE_UPDATE = 3,
    WDC_ADMIN_MODE_RECOVERY = 4,
    WDC_ADMIN_MODE_REBOOT_HANDOFF = 5,
} WdcAdminMode;

typedef enum WdcAdminAuditEvent {
    WDC_ADMIN_AUDIT_EVENT_NONE = 0,
    WDC_ADMIN_AUDIT_AUTHORIZATION = 1,
    WDC_ADMIN_AUDIT_REPLAY_DECISION = 2,
    WDC_ADMIN_AUDIT_COMMAND_ACCEPTANCE = 3,
    WDC_ADMIN_AUDIT_QUIESCE = 4,
    WDC_ADMIN_AUDIT_STAGING = 5,
    WDC_ADMIN_AUDIT_VERIFICATION = 6,
    WDC_ADMIN_AUDIT_SLOT_TRANSITION = 7,
    WDC_ADMIN_AUDIT_TERMINAL_RESULT = 8,
    WDC_ADMIN_AUDIT_RECOVERY_ENTRY = 9,
    WDC_ADMIN_AUDIT_REBOOT_HANDOFF = 10,
} WdcAdminAuditEvent;

typedef enum WdcAdminAuditOutcome {
    WDC_ADMIN_AUDIT_OUTCOME_NONE = 0,
    WDC_ADMIN_AUDIT_ALLOWED = 1,
    WDC_ADMIN_AUDIT_DENIED = 2,
    WDC_ADMIN_AUDIT_FAILED = 3,
    WDC_ADMIN_AUDIT_OBSERVED = 4,
} WdcAdminAuditOutcome;

typedef struct WdcAdminAuthenticatedEntry {
    uint32_t struct_size;
    uint16_t version_major;
    uint16_t version_minor;
    uint32_t transport_kind;
    uint32_t authorization_method;
    uint32_t privilege_mask;
    uint32_t flags;
    uint64_t authorization_epoch;
    uint64_t issued_monotonic_ms;
    uint64_t expires_monotonic_ms;
    uint64_t session_nonce;
    uint8_t principal_sha256[32];
    uint8_t channel_binding_sha256[32];
    uint8_t reserved[8];
} WdcAdminAuthenticatedEntry;

typedef struct WdcAdminRequest {
    uint32_t struct_size;
    uint16_t version_major;
    uint16_t version_minor;
    uint32_t command;
    uint32_t flags;
    uint32_t payload_bytes;
    uint32_t slot;
    uint32_t expected_total_bytes;
    uint32_t reserved0;
    uint64_t request_id;
    uint64_t deadline_ms;
    uint64_t authorization_epoch;
    uint64_t session_nonce;
    uint64_t command_sequence;
    uint8_t artifact_sha256[32];
    uint8_t reserved1[8];
} WdcAdminRequest;

typedef struct WdcAdminTerminalRecord {
    uint32_t struct_size;
    uint16_t version_major;
    uint16_t version_minor;
    uint32_t result;
    int32_t status;
    uint64_t request_id;
    uint64_t session_nonce;
    uint64_t command_sequence;
    uint32_t bytes_received;
    uint32_t metadata_commits;
    uint32_t final_state;
    uint32_t slot;
    uint32_t flags;
    uint32_t reserved;
} WdcAdminTerminalRecord;

typedef struct WdcAdminAuditRecord {
    uint32_t struct_size;
    uint16_t version_major;
    uint16_t version_minor;
    uint32_t event;
    uint32_t outcome;
    uint32_t transport_kind;
    uint32_t command;
    uint32_t from_state;
    uint32_t to_state;
    uint32_t terminal_result;
    int32_t status;
    uint64_t authorization_epoch;
    uint64_t session_nonce;
    uint64_t command_sequence;
    uint64_t request_id;
    uint64_t monotonic_ms;
    uint8_t principal_sha256[32];
    uint8_t artifact_sha256[32];
    uint32_t slot;
    uint32_t flags;
    uint8_t reserved[8];
} WdcAdminAuditRecord;

typedef struct WdcAdminAuthorizationStart {
    uint32_t transport_kind;
    uint32_t authorization_method;
    uint32_t attended_physical_entry;
    uint32_t flags;
    uint64_t challenge_id;
    uint8_t channel_binding_sha256[32];
} WdcAdminAuthorizationStart;

typedef struct WdcAdminAuthorizationChallenge {
    WdcAdminAuthorizationStart start;
    uint64_t issued_monotonic_ms;
    uint64_t deadline_ms;
} WdcAdminAuthorizationChallenge;

typedef int32_t (*WdcAdminAuthorizeFn)(
    void *context,
    const WdcAdminAuthorizationChallenge *challenge,
    const uint8_t *proof,
    uint32_t proof_bytes,
    WdcAdminAuthenticatedEntry *out_entry);

typedef struct WdcAdminAuthorizer {
    WdcAdminAuthorizeFn authorize;
    void *context;
} WdcAdminAuthorizer;

typedef struct WdcAdminArtifactCandidate {
    uint32_t struct_size;
    uint16_t version_major;
    uint16_t version_minor;
    uint32_t slot;
    uint32_t stored_bytes;
    uint32_t security_version;
    uint32_t flags;
    uint8_t artifact_sha256[32];
    uint8_t running_host_fingerprint_sha256[32];
    uint8_t reserved[8];
} WdcAdminArtifactCandidate;

typedef struct WdcAdminArtifactVerification {
    uint32_t struct_size;
    uint16_t version_major;
    uint16_t version_minor;
    int32_t status;
    uint32_t complete_artifact_valid;
    uint32_t host_compatible;
    uint32_t security_floor_valid;
    uint32_t artifact_authority_valid;
    uint32_t flags;
    uint8_t reserved[8];
} WdcAdminArtifactVerification;

typedef int32_t (*WdcAdminArtifactVerifyFn)(
    void *context,
    const WdcAdminArtifactCandidate *candidate,
    WdcAdminArtifactVerification *out_verification);

typedef struct WdcAdminArtifactVerifier {
    WdcAdminArtifactVerifyFn verify;
    void *context;
} WdcAdminArtifactVerifier;

typedef struct WdcAdminPreacceptResult {
    WdcAdminPreacceptRejection rejection;
    int32_t status;
    uint64_t request_id;
    uint64_t command_sequence;
} WdcAdminPreacceptResult;

typedef struct WdcAdminAcceptedCommand {
    uint32_t control_ticket;
    WdcControlSource control_source;
    WdcAdminRequest request;
    const uint8_t *payload;
    uint32_t payload_bytes;
} WdcAdminAcceptedCommand;

typedef struct WdcAdminTerminalMetadata {
    uint32_t bytes_received;
    uint32_t metadata_commits;
    uint32_t final_state;
    uint32_t slot;
    uint32_t flags;
} WdcAdminTerminalMetadata;

typedef struct WdcAdminAuditEmission {
    WdcAdminAuditEvent event;
    WdcAdminAuditOutcome outcome;
    WdcAdminMode from_state;
    WdcAdminMode to_state;
    WdcAdminTerminalResult terminal_result;
    int32_t status;
    uint32_t slot;
    uint32_t flags;
    uint8_t artifact_sha256[32];
} WdcAdminAuditEmission;

typedef struct WdcAdminCoreConfig {
    WdcControlKernel *control_kernel;
    WdcAdminAuthorizer authorizer;
    WdcAdminArtifactVerifier artifact_verifier;
    WdcAdminMode initial_mode;
    uint32_t enabled_commands_mask;
    uint8_t boot_channel_binding_sha256[32];
} WdcAdminCoreConfig;

typedef struct WdcAdminCore {
    WdcControlKernel *control_kernel;
    WdcAdminAuthorizer authorizer;
    WdcAdminArtifactVerifier artifact_verifier;
    uint8_t boot_channel_binding_sha256[32];
    WdcAdminAuthorizationChallenge challenge;
    WdcAdminAuthenticatedEntry session;
    WdcAdminRequest active_request;
    WdcAdminTerminalRecord terminal;
    uint8_t payload[WDC_ADMIN_MAX_PAYLOAD_BYTES];
    uint8_t response[WDC_ADMIN_MAX_STATUS_RESPONSE_BYTES];
    WdcAdminAuditRecord audit[WDC_ADMIN_AUDIT_RING_RECORDS];
    WdcAdminMode mode;
    WdcAdminAuthorizationState authorization_state;
    WdcAdminCommandLifecycle lifecycle;
    WdcControlSource active_control_source;
    uint32_t enabled_commands_mask;
    uint32_t active_control_ticket;
    uint32_t payload_bytes;
    uint32_t response_bytes;
    uint32_t audit_head;
    uint32_t audit_count;
    uint32_t audit_loss_count;
    uint32_t authorization_failure_count;
    uint64_t authorization_window_start_ms;
    uint64_t authorization_backoff_until_ms;
    uint64_t authorization_epoch_high_water;
    uint64_t next_command_sequence;
    uint64_t last_activity_ms;
    bool initialized;
    bool terminal_ready;
    bool response_written;
} WdcAdminCore;

typedef struct WdcAdminSerialAdapter {
    WdcAdminCore *core;
    uint8_t frame[WDC_ADMIN_MAX_FRAME_BYTES];
    uint32_t received_bytes;
    uint32_t expected_frame_bytes;
    bool header_ready;
} WdcAdminSerialAdapter;

int32_t wdc_admin_core_init(WdcAdminCore *core,
                            const WdcAdminCoreConfig *config);
int32_t wdc_admin_authorization_begin(
    WdcAdminCore *core,
    const WdcAdminAuthorizationStart *start,
    uint64_t now_ms,
    uint64_t *out_deadline_ms,
    WdcAdminPreacceptResult *out_rejection);
int32_t wdc_admin_authorization_finish(
    WdcAdminCore *core,
    const uint8_t *proof,
    uint32_t proof_bytes,
    uint64_t now_ms,
    WdcAdminPreacceptResult *out_rejection);
int32_t wdc_admin_session_close(WdcAdminCore *core, uint64_t now_ms);
int32_t wdc_admin_session_revoke(WdcAdminCore *core, uint64_t now_ms);
int32_t wdc_admin_poll(WdcAdminCore *core, uint64_t now_ms);

int32_t wdc_admin_submit(WdcAdminCore *core,
                         const WdcAdminRequest *request,
                         const uint8_t *payload,
                         uint32_t payload_bytes,
                         uint64_t now_ms,
                         WdcAdminPreacceptResult *out_rejection);
int32_t wdc_admin_begin_command(WdcAdminCore *core,
                                const WdcControlWorkItem *work,
                                uint64_t now_ms,
                                WdcAdminAcceptedCommand *out_command);
int32_t wdc_admin_write_response(WdcAdminCore *core,
                                 const uint8_t *response,
                                 uint32_t response_bytes);
int32_t wdc_admin_complete(WdcAdminCore *core,
                           WdcAdminTerminalResult result,
                           int32_t status,
                           const WdcAdminTerminalMetadata *metadata,
                           uint64_t now_ms);
int32_t wdc_admin_take_terminal(WdcAdminCore *core,
                                WdcAdminTerminalRecord *out_terminal,
                                uint8_t *out_response,
                                uint32_t response_capacity,
                                uint32_t *out_response_bytes);

int32_t wdc_admin_verify_artifact(
    WdcAdminCore *core,
    const WdcAdminArtifactCandidate *candidate,
    WdcAdminArtifactVerification *out_verification,
    uint64_t now_ms);
int32_t wdc_admin_audit_emit(WdcAdminCore *core,
                             const WdcAdminAuditEmission *emission,
                             uint64_t now_ms);
int32_t wdc_admin_take_audit(WdcAdminCore *core,
                             WdcAdminAuditRecord *out_record);

WdcAdminAuthorizationState wdc_admin_authorization_state(
    const WdcAdminCore *core);
WdcAdminCommandLifecycle wdc_admin_command_lifecycle(
    const WdcAdminCore *core);
WdcAdminMode wdc_admin_mode(const WdcAdminCore *core);
uint64_t wdc_admin_next_command_sequence(const WdcAdminCore *core);
uint32_t wdc_admin_audit_pending(const WdcAdminCore *core);
uint32_t wdc_admin_audit_losses(const WdcAdminCore *core);
uint32_t wdc_admin_fixed_storage_bytes(void);
int32_t wdc_admin_rejection_status(WdcAdminPreacceptRejection rejection);

int32_t wdc_admin_serial_init(WdcAdminSerialAdapter *adapter,
                              WdcAdminCore *core);
void wdc_admin_serial_reset(WdcAdminSerialAdapter *adapter);
int32_t wdc_admin_serial_feed(
    WdcAdminSerialAdapter *adapter,
    const uint8_t *bytes,
    uint32_t bytes_len,
    uint64_t now_ms,
    uint32_t *out_consumed,
    bool *out_frame_complete,
    WdcAdminPreacceptResult *out_rejection);

/* Side-effect-free firmware link anchor. */
uint32_t wdc_admin_link_anchor(void);

#ifdef __cplusplus
}
#endif
