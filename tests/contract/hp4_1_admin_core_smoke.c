#include <inttypes.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "wdc_admin.h"

#define HP41_CASE_COUNT 14u

typedef struct CaseResult {
    const char *name;
    uint32_t passed;
} CaseResult;

typedef struct FakeAuthorizer {
    uint64_t next_epoch;
    uint32_t calls;
    uint32_t successful;
    uint32_t privilege_mask;
} FakeAuthorizer;

typedef struct FakeVerifier {
    uint32_t calls;
    bool allow;
} FakeVerifier;

typedef struct Harness {
    WdcControlKernel kernel;
    WdcAdminCore core;
    WdcAdminSerialAdapter serial;
    FakeAuthorizer authorizer;
    FakeVerifier verifier;
    uint8_t binding[32];
    uint64_t challenge_id;
} Harness;

static CaseResult s_cases[HP41_CASE_COUNT];
static uint32_t s_case_count;
static uint32_t s_failures;
static uint32_t s_rejection_count;

#define CHECK(condition)                                                       \
    do {                                                                       \
        if (!(condition)) {                                                    \
            s_failures += 1u;                                                  \
        }                                                                      \
    } while (0)

static void record_case(const char *name, uint32_t before)
{
    CHECK(s_case_count < HP41_CASE_COUNT);
    if (s_case_count < HP41_CASE_COUNT) {
        s_cases[s_case_count].name = name;
        s_cases[s_case_count].passed = before == s_failures ? 1u : 0u;
        s_case_count += 1u;
    }
}

static int32_t fake_authorize(
    void *context,
    const WdcAdminAuthorizationChallenge *challenge,
    const uint8_t *proof,
    uint32_t proof_bytes,
    WdcAdminAuthenticatedEntry *out_entry)
{
    FakeAuthorizer *authorizer = (FakeAuthorizer *)context;
    uint32_t index;
    authorizer->calls += 1u;
    if (proof == NULL || proof_bytes != 5u ||
        memcmp(proof, "proof", 5u) != 0) {
        return WDC_ERR_CAPABILITY_DENIED;
    }
    memset(out_entry, 0, sizeof(*out_entry));
    out_entry->struct_size = WDC_ADMIN_AUTHENTICATED_ENTRY_BYTES;
    out_entry->version_major = WDC_ADMIN_VERSION_MAJOR;
    out_entry->version_minor = WDC_ADMIN_VERSION_MINOR;
    out_entry->transport_kind = challenge->start.transport_kind;
    out_entry->authorization_method = challenge->start.authorization_method;
    out_entry->privilege_mask = authorizer->privilege_mask;
    out_entry->authorization_epoch = authorizer->next_epoch;
    out_entry->issued_monotonic_ms = challenge->issued_monotonic_ms;
    out_entry->expires_monotonic_ms =
        challenge->issued_monotonic_ms + 600000u;
    out_entry->session_nonce =
        challenge->start.challenge_id ^ authorizer->next_epoch;
    if (out_entry->session_nonce == 0u) {
        out_entry->session_nonce = authorizer->next_epoch + 1u;
    }
    for (index = 0u; index < sizeof(out_entry->principal_sha256); ++index) {
        out_entry->principal_sha256[index] = (uint8_t)(0x40u + (index % 31u));
    }
    memcpy(out_entry->channel_binding_sha256,
           challenge->start.channel_binding_sha256,
           sizeof(out_entry->channel_binding_sha256));
    authorizer->next_epoch += 1u;
    authorizer->successful += 1u;
    return WDC_OK;
}

static int32_t fake_verify(void *context,
                           const WdcAdminArtifactCandidate *candidate,
                           WdcAdminArtifactVerification *out_verification)
{
    FakeVerifier *verifier = (FakeVerifier *)context;
    verifier->calls += 1u;
    memset(out_verification, 0, sizeof(*out_verification));
    out_verification->struct_size = sizeof(*out_verification);
    out_verification->version_major = WDC_ADMIN_VERSION_MAJOR;
    out_verification->version_minor = WDC_ADMIN_VERSION_MINOR;
    out_verification->status = verifier->allow ? WDC_OK
                                               : WDC_ERR_CAPABILITY_DENIED;
    out_verification->complete_artifact_valid = verifier->allow ? 1u : 0u;
    out_verification->host_compatible = verifier->allow ? 1u : 0u;
    out_verification->security_floor_valid = verifier->allow ? 1u : 0u;
    out_verification->artifact_authority_valid = verifier->allow ? 1u : 0u;
    (void)candidate;
    return out_verification->status;
}

static void init_harness(Harness *harness, uint32_t command_mask)
{
    WdcAdminCoreConfig config;
    uint32_t index;
    memset(harness, 0, sizeof(*harness));
    for (index = 0u; index < sizeof(harness->binding); ++index) {
        harness->binding[index] = (uint8_t)(0xa0u + (index % 29u));
    }
    harness->authorizer.next_epoch = 1u;
    harness->authorizer.privilege_mask = WDC_ADMIN_PRIVILEGE_ALL;
    harness->verifier.allow = true;
    harness->challenge_id = 0x1000u;
    CHECK(wdc_control_kernel_init(&harness->kernel,
                                  wdc_control_profile_c6_minimum()) == WDC_OK);
    memset(&config, 0, sizeof(config));
    config.control_kernel = &harness->kernel;
    config.authorizer.authorize = fake_authorize;
    config.authorizer.context = &harness->authorizer;
    config.artifact_verifier.verify = fake_verify;
    config.artifact_verifier.context = &harness->verifier;
    config.initial_mode = WDC_ADMIN_MODE_NORMAL;
    config.enabled_commands_mask = command_mask;
    memcpy(config.boot_channel_binding_sha256,
           harness->binding,
           sizeof(config.boot_channel_binding_sha256));
    CHECK(wdc_admin_core_init(&harness->core, &config) == WDC_OK);
    CHECK(wdc_admin_serial_init(&harness->serial, &harness->core) == WDC_OK);
}

static int32_t authorize(Harness *harness,
                         uint64_t now_ms,
                         const uint8_t *proof,
                         uint32_t proof_bytes,
                         WdcAdminPreacceptResult *out_rejection)
{
    WdcAdminAuthorizationStart start;
    uint64_t deadline = 0u;
    int32_t status;
    memset(&start, 0, sizeof(start));
    start.transport_kind = WDC_ADMIN_TRANSPORT_SERIAL_PHYSICAL_V1;
    start.authorization_method = WDC_ADMIN_AUTH_METHOD_LOCAL_PHYSICAL;
    start.attended_physical_entry = 1u;
    start.challenge_id = harness->challenge_id;
    harness->challenge_id += 1u;
    memcpy(start.channel_binding_sha256,
           harness->binding,
           sizeof(start.channel_binding_sha256));
    status = wdc_admin_authorization_begin(&harness->core, &start, now_ms,
                                            &deadline, out_rejection);
    if (status != WDC_OK) {
        return status;
    }
    CHECK(deadline == now_ms + WDC_ADMIN_CHALLENGE_DEADLINE_MS);
    return wdc_admin_authorization_finish(&harness->core, proof, proof_bytes,
                                           now_ms + 1u, out_rejection);
}

static WdcAdminRequest status_request(const Harness *harness,
                                      uint64_t request_id,
                                      uint64_t sequence,
                                      uint64_t now_ms)
{
    WdcAdminRequest request;
    memset(&request, 0, sizeof(request));
    request.struct_size = WDC_ADMIN_REQUEST_BYTES;
    request.version_major = WDC_ADMIN_VERSION_MAJOR;
    request.version_minor = WDC_ADMIN_VERSION_MINOR;
    request.command = WDC_ADMIN_COMMAND_STATUS;
    request.slot = WDC_ADMIN_SLOT_NONE;
    request.request_id = request_id;
    request.deadline_ms = now_ms + 1000u;
    request.authorization_epoch = harness->core.session.authorization_epoch;
    request.session_nonce = harness->core.session.session_nonce;
    request.command_sequence = sequence;
    return request;
}

static void put_u16_le(uint8_t *bytes, uint16_t value)
{
    bytes[0] = (uint8_t)value;
    bytes[1] = (uint8_t)(value >> 8u);
}

static void put_u32_le(uint8_t *bytes, uint32_t value)
{
    bytes[0] = (uint8_t)value;
    bytes[1] = (uint8_t)(value >> 8u);
    bytes[2] = (uint8_t)(value >> 16u);
    bytes[3] = (uint8_t)(value >> 24u);
}

static void put_u64_le(uint8_t *bytes, uint64_t value)
{
    put_u32_le(bytes, (uint32_t)value);
    put_u32_le(bytes + 4u, (uint32_t)(value >> 32u));
}

static uint32_t encode_frame(const WdcAdminRequest *request, uint8_t *frame)
{
    uint8_t *bytes = frame + 4u;
    memset(frame, 0, 4u + WDC_ADMIN_REQUEST_BYTES);
    put_u32_le(frame, WDC_ADMIN_REQUEST_BYTES);
    put_u32_le(bytes + 0u, request->struct_size);
    put_u16_le(bytes + 4u, request->version_major);
    put_u16_le(bytes + 6u, request->version_minor);
    put_u32_le(bytes + 8u, request->command);
    put_u32_le(bytes + 12u, request->flags);
    put_u32_le(bytes + 16u, request->payload_bytes);
    put_u32_le(bytes + 20u, request->slot);
    put_u32_le(bytes + 24u, request->expected_total_bytes);
    put_u32_le(bytes + 28u, request->reserved0);
    put_u64_le(bytes + 32u, request->request_id);
    put_u64_le(bytes + 40u, request->deadline_ms);
    put_u64_le(bytes + 48u, request->authorization_epoch);
    put_u64_le(bytes + 56u, request->session_nonce);
    put_u64_le(bytes + 64u, request->command_sequence);
    memcpy(bytes + 72u, request->artifact_sha256,
           sizeof(request->artifact_sha256));
    memcpy(bytes + 104u, request->reserved1,
           sizeof(request->reserved1));
    return 4u + WDC_ADMIN_REQUEST_BYTES;
}

static void complete_status(Harness *harness,
                            uint64_t now_ms,
                            WdcAdminTerminalRecord *out_terminal)
{
    WdcControlWorkItem work;
    WdcAdminAcceptedCommand accepted;
    WdcAdminTerminalMetadata metadata;
    uint8_t response[16];
    uint32_t response_bytes = 0u;
    static const uint8_t status_payload[] = "host-ok";
    memset(&work, 0, sizeof(work));
    CHECK(wdc_control_next(&harness->kernel, &work) == WDC_OK);
    CHECK(wdc_admin_begin_command(&harness->core, &work, now_ms,
                                  &accepted) == WDC_OK);
    CHECK(accepted.control_source == WDC_CONTROL_SOURCE_ADMINISTRATION);
    CHECK(accepted.payload_bytes == 0u);
    CHECK(wdc_admin_write_response(&harness->core, status_payload,
                                   sizeof(status_payload) - 1u) == WDC_OK);
    memset(&metadata, 0, sizeof(metadata));
    metadata.final_state = WDC_ADMIN_MODE_NORMAL;
    metadata.slot = WDC_ADMIN_SLOT_NONE;
    CHECK(wdc_admin_complete(&harness->core,
                             WDC_ADMIN_TERMINAL_SUCCEEDED,
                             WDC_OK,
                             &metadata,
                             now_ms + 1u) == WDC_OK);
    CHECK(wdc_admin_take_terminal(&harness->core, out_terminal,
                                  response, sizeof(response),
                                  &response_bytes) == WDC_OK);
    CHECK(response_bytes == sizeof(status_payload) - 1u);
    CHECK(memcmp(response, status_payload, response_bytes) == 0);
}

static void run_layout_and_storage(void)
{
    uint32_t before = s_failures;
    CHECK(sizeof(WdcAdminAuthenticatedEntry) == 128u);
    CHECK(sizeof(WdcAdminRequest) == 112u);
    CHECK(sizeof(WdcAdminTerminalRecord) == 64u);
    CHECK(sizeof(WdcAdminAuditRecord) == 160u);
    CHECK(sizeof(WdcAdminCore) <= WDC_ADMIN_CORE_STATIC_BUDGET_BYTES);
    CHECK(sizeof(WdcAdminSerialAdapter) <=
          WDC_ADMIN_SERIAL_STATIC_BUDGET_BYTES);
    CHECK(wdc_admin_fixed_storage_bytes() <=
          WDC_ADMIN_FIXED_STORAGE_BUDGET_BYTES);
    record_case("fixed-layout-and-storage-budget", before);
}

static void run_attended_replaceable_authority(void)
{
    Harness harness;
    WdcAdminAuthorizationStart start;
    WdcAdminPreacceptResult rejection;
    uint64_t deadline = 0u;
    uint32_t before = s_failures;
    init_harness(&harness, WDC_ADMIN_HP41_COMMAND_MASK);
    memset(&start, 0, sizeof(start));
    start.transport_kind = WDC_ADMIN_TRANSPORT_SERIAL_PHYSICAL_V1;
    start.authorization_method = WDC_ADMIN_AUTH_METHOD_LOCAL_PHYSICAL;
    start.challenge_id = 1u;
    memcpy(start.channel_binding_sha256, harness.binding,
           sizeof(start.channel_binding_sha256));
    CHECK(wdc_admin_authorization_begin(&harness.core, &start, 100u,
                                         &deadline, &rejection) ==
          WDC_ERR_CAPABILITY_DENIED);
    CHECK(rejection.rejection == WDC_ADMIN_REJECTION_UNAUTHORIZED);
    CHECK(harness.authorizer.calls == 0u);
    start.attended_physical_entry = 1u;
    start.transport_kind =
        WDC_ADMIN_TRANSPORT_AUTHENTICATED_EXTERNAL_V1_RESERVED;
    CHECK(wdc_admin_authorization_begin(&harness.core, &start, 101u,
                                         &deadline, &rejection) ==
          WDC_ERR_CAPABILITY_DENIED);
    CHECK(harness.authorizer.calls == 0u);
    CHECK(authorize(&harness, 102u, (const uint8_t *)"proof", 5u,
                    &rejection) == WDC_OK);
    CHECK(harness.authorizer.calls == 1u);
    CHECK(wdc_admin_authorization_state(&harness.core) ==
          WDC_ADMIN_AUTH_AUTHORIZED);
    record_case("attended-replaceable-authority", before);
}

static void run_authorization_rate_limit(void)
{
    Harness harness;
    WdcAdminPreacceptResult rejection;
    WdcAdminAuthorizationStart start;
    uint64_t deadline = 0u;
    uint32_t attempt;
    uint32_t before = s_failures;
    init_harness(&harness, WDC_ADMIN_HP41_COMMAND_MASK);
    for (attempt = 0u; attempt < WDC_ADMIN_AUTHORIZATION_FAILURE_LIMIT;
         ++attempt) {
        uint64_t attempt_ms = attempt == 0u ? 1000u : 60900u;
        CHECK(authorize(&harness, attempt_ms,
                        (const uint8_t *)"wrong", 5u,
                        &rejection) == WDC_ERR_CAPABILITY_DENIED);
        CHECK(rejection.rejection == WDC_ADMIN_REJECTION_UNAUTHORIZED);
    }
    memset(&start, 0, sizeof(start));
    start.transport_kind = WDC_ADMIN_TRANSPORT_SERIAL_PHYSICAL_V1;
    start.authorization_method = WDC_ADMIN_AUTH_METHOD_LOCAL_PHYSICAL;
    start.attended_physical_entry = 1u;
    start.challenge_id = 99u;
    memcpy(start.channel_binding_sha256, harness.binding,
           sizeof(start.channel_binding_sha256));
    CHECK(wdc_admin_authorization_begin(&harness.core, &start, 61000u,
                                         &deadline, &rejection) ==
          WDC_ERR_RATE_LIMITED);
    CHECK(rejection.rejection == WDC_ADMIN_REJECTION_RATE_LIMITED);
    CHECK(wdc_control_lane_outstanding(
              &harness.kernel,
              WDC_CONTROL_PRIORITY_ADMINISTRATION) == 0u);
    CHECK(authorize(&harness, 90901u, (const uint8_t *)"proof", 5u,
                    &rejection) == WDC_OK);
    record_case("authorization-window-and-backoff", before);
}

static void run_replay_and_preaccept_immutability(void)
{
    Harness harness;
    WdcAdminPreacceptResult rejection;
    WdcAdminRequest request;
    uint32_t before = s_failures;
    init_harness(&harness, WDC_ADMIN_HP41_COMMAND_MASK);
    CHECK(authorize(&harness, 100u, (const uint8_t *)"proof", 5u,
                    &rejection) == WDC_OK);
    request = status_request(&harness, 1u, 1u, 200u);
    request.session_nonce += 1u;
    CHECK(wdc_admin_submit(&harness.core, &request, NULL, 0u, 200u,
                           &rejection) == WDC_ERR_CAPABILITY_DENIED);
    CHECK(rejection.rejection == WDC_ADMIN_REJECTION_UNAUTHORIZED);
    request = status_request(&harness, 2u, 2u, 201u);
    CHECK(wdc_admin_submit(&harness.core, &request, NULL, 0u, 201u,
                           &rejection) == WDC_ERR_NOT_SYNCHRONIZED);
    CHECK(rejection.rejection == WDC_ADMIN_REJECTION_OUT_OF_ORDER);
    request = status_request(&harness, 3u, 1u, 202u);
    request.reserved0 = 1u;
    CHECK(wdc_admin_submit(&harness.core, &request, NULL, 0u, 202u,
                           &rejection) == WDC_ERR_BAD_LENGTH);
    CHECK(rejection.rejection == WDC_ADMIN_REJECTION_BOUNDS);
    request = status_request(&harness, 4u, 1u, 203u);
    request.command = WDC_ADMIN_COMMAND_BEGIN_UPDATE;
    request.slot = 1u;
    CHECK(wdc_admin_submit(&harness.core, &request, NULL, 0u, 203u,
                           &rejection) == WDC_ERR_UNSUPPORTED_OPCODE);
    CHECK(rejection.rejection == WDC_ADMIN_REJECTION_UNSUPPORTED);
    CHECK(wdc_admin_next_command_sequence(&harness.core) == 1u);
    CHECK(wdc_control_lane_outstanding(
              &harness.kernel,
              WDC_CONTROL_PRIORITY_ADMINISTRATION) == 0u);
    request = status_request(&harness, 5u, 1u, 204u);
    CHECK(wdc_admin_submit(&harness.core, &request, NULL, 0u, 204u,
                           &rejection) == WDC_OK);
    CHECK(wdc_admin_next_command_sequence(&harness.core) == 2u);
    request = status_request(&harness, 6u, 1u, 205u);
    CHECK(wdc_admin_submit(&harness.core, &request, NULL, 0u, 205u,
                           &rejection) == WDC_ERR_CONTRACT_VIOLATION);
    CHECK(rejection.rejection == WDC_ADMIN_REJECTION_STALE_REPLAY);
    request = status_request(&harness, 7u, 2u, 206u);
    CHECK(wdc_admin_submit(&harness.core, &request, NULL, 0u, 206u,
                           &rejection) == WDC_ERR_BUSY);
    CHECK(rejection.rejection == WDC_ADMIN_REJECTION_BUSY);
    s_rejection_count += 6u;
    record_case("preaccept-rejection-does-not-own-capacity", before);
}

static void run_application_pressure_isolated(void)
{
    Harness harness;
    WdcAdminPreacceptResult rejection;
    WdcAdminRequest request;
    WdcControlWorkRequest application;
    WdcControlCompletion overflow;
    WdcAdminTerminalRecord terminal;
    uint32_t ticket;
    uint32_t index;
    uint32_t before = s_failures;
    init_harness(&harness, WDC_ADMIN_HP41_COMMAND_MASK);
    CHECK(authorize(&harness, 100u, (const uint8_t *)"proof", 5u,
                    &rejection) == WDC_OK);
    memset(&application, 0, sizeof(application));
    application.source = WDC_CONTROL_SOURCE_APPLICATION;
    application.operation_id = 0x415050u;
    for (index = 0u; index < 16u; ++index) {
        application.correlation_id = index + 1u;
        ticket = 0u;
        memset(&overflow, 0, sizeof(overflow));
        CHECK(wdc_control_submit(&harness.kernel, &application, &ticket,
                                 &overflow) == WDC_OK);
    }
    request = status_request(&harness, 1u, 1u, 200u);
    CHECK(wdc_admin_submit(&harness.core, &request, NULL, 0u, 200u,
                           &rejection) == WDC_OK);
    CHECK(wdc_control_lane_outstanding(
              &harness.kernel,
              WDC_CONTROL_PRIORITY_APPLICATION) == 16u);
    CHECK(wdc_control_lane_outstanding(
              &harness.kernel,
              WDC_CONTROL_PRIORITY_ADMINISTRATION) == 1u);
    complete_status(&harness, 201u, &terminal);
    CHECK(terminal.result == WDC_ADMIN_TERMINAL_SUCCEEDED);
    record_case("application-pressure-cannot-consume-admin", before);
}

static void run_terminal_exactly_once(void)
{
    Harness harness;
    WdcAdminPreacceptResult rejection;
    WdcAdminRequest request;
    WdcControlWorkItem work;
    WdcAdminAcceptedCommand accepted;
    WdcAdminTerminalMetadata metadata;
    WdcAdminTerminalRecord terminal;
    uint8_t response[8];
    uint32_t response_bytes = 0u;
    static const uint8_t body[] = "ready";
    uint32_t before = s_failures;
    init_harness(&harness, WDC_ADMIN_HP41_COMMAND_MASK);
    CHECK(authorize(&harness, 100u, (const uint8_t *)"proof", 5u,
                    &rejection) == WDC_OK);
    request = status_request(&harness, 1u, 1u, 200u);
    CHECK(wdc_admin_submit(&harness.core, &request, NULL, 0u, 200u,
                           &rejection) == WDC_OK);
    CHECK(wdc_control_next(&harness.kernel, &work) == WDC_OK);
    CHECK(wdc_admin_begin_command(&harness.core, &work, 201u,
                                  &accepted) == WDC_OK);
    CHECK(wdc_admin_write_response(&harness.core, body,
                                   sizeof(body) - 1u) == WDC_OK);
    CHECK(wdc_admin_write_response(&harness.core, body,
                                   sizeof(body) - 1u) ==
          WDC_ERR_INVALID_STATE);
    memset(&metadata, 0, sizeof(metadata));
    metadata.final_state = WDC_ADMIN_MODE_NORMAL;
    metadata.slot = WDC_ADMIN_SLOT_NONE;
    CHECK(wdc_admin_complete(&harness.core,
                             WDC_ADMIN_TERMINAL_SUCCEEDED,
                             WDC_OK, &metadata, 202u) == WDC_OK);
    CHECK(wdc_admin_complete(&harness.core,
                             WDC_ADMIN_TERMINAL_FAILED,
                             WDC_ERR_UNKNOWN, &metadata, 203u) ==
          WDC_ERR_INVALID_STATE);
    CHECK(wdc_admin_take_terminal(&harness.core, &terminal, response, 1u,
                                  &response_bytes) ==
          WDC_ERR_RESPONSE_TOO_SMALL);
    CHECK(wdc_admin_take_terminal(&harness.core, &terminal,
                                  response, sizeof(response),
                                  &response_bytes) == WDC_OK);
    CHECK(terminal.result == WDC_ADMIN_TERMINAL_SUCCEEDED);
    CHECK(terminal.request_id == 1u);
    CHECK(response_bytes == sizeof(body) - 1u);
    CHECK(wdc_admin_take_terminal(&harness.core, &terminal,
                                  response, sizeof(response),
                                  &response_bytes) == WDC_ERR_NOT_AVAILABLE);
    record_case("first-terminal-write-and-one-response", before);
}

static void run_serial_fragmentation(void)
{
    Harness harness;
    WdcAdminPreacceptResult rejection;
    WdcAdminRequest request;
    WdcAdminTerminalRecord terminal;
    uint8_t frame[4u + WDC_ADMIN_REQUEST_BYTES];
    uint32_t frame_bytes;
    uint32_t consumed = 0u;
    bool complete = false;
    uint32_t before = s_failures;
    init_harness(&harness, WDC_ADMIN_HP41_COMMAND_MASK);
    CHECK(authorize(&harness, 100u, (const uint8_t *)"proof", 5u,
                    &rejection) == WDC_OK);
    request = status_request(&harness, 1u, 1u, 200u);
    frame_bytes = encode_frame(&request, frame);
    CHECK(wdc_admin_serial_feed(&harness.serial, frame, 2u, 200u,
                                &consumed, &complete, &rejection) == WDC_OK);
    CHECK(consumed == 2u && !complete);
    CHECK(wdc_admin_serial_feed(&harness.serial, frame + 2u,
                                frame_bytes - 2u, 200u,
                                &consumed, &complete, &rejection) == WDC_OK);
    CHECK(consumed == frame_bytes - 2u && complete);
    CHECK(wdc_admin_command_lifecycle(&harness.core) ==
          WDC_ADMIN_LIFECYCLE_ACCEPTED);
    complete_status(&harness, 201u, &terminal);
    record_case("serial-fragment-normalization", before);
}

static void run_serial_cannot_authorize(void)
{
    Harness harness;
    WdcAdminPreacceptResult rejection;
    WdcAdminRequest request;
    uint8_t frame[4u + WDC_ADMIN_REQUEST_BYTES];
    uint32_t consumed = 0u;
    bool complete = false;
    uint32_t before = s_failures;
    init_harness(&harness, WDC_ADMIN_HP41_COMMAND_MASK);
    request = status_request(&harness, 1u, 1u, 100u);
    CHECK(wdc_admin_serial_feed(&harness.serial, frame,
                                encode_frame(&request, frame), 100u,
                                &consumed, &complete, &rejection) ==
          WDC_ERR_CAPABILITY_DENIED);
    CHECK(complete);
    CHECK(rejection.rejection == WDC_ADMIN_REJECTION_UNAUTHORIZED);
    CHECK(harness.authorizer.calls == 0u);
    CHECK(wdc_admin_next_command_sequence(&harness.core) == 1u);
    s_rejection_count += 1u;
    record_case("serial-bytes-cannot-self-authorize", before);
}

static void run_serial_frame_bounds(void)
{
    Harness harness;
    WdcAdminPreacceptResult rejection;
    uint8_t prefix[4];
    uint32_t consumed = 0u;
    bool complete = false;
    uint32_t before = s_failures;
    init_harness(&harness, WDC_ADMIN_HP41_COMMAND_MASK);
    put_u32_le(prefix, WDC_ADMIN_MAX_FRAME_BYTES);
    CHECK(wdc_admin_serial_feed(&harness.serial, prefix, sizeof(prefix), 1u,
                                &consumed, &complete, &rejection) ==
          WDC_ERR_BAD_LENGTH);
    CHECK(complete && consumed == sizeof(prefix));
    CHECK(rejection.rejection == WDC_ADMIN_REJECTION_BOUNDS);
    put_u32_le(prefix, WDC_ADMIN_REQUEST_BYTES - 1u);
    CHECK(wdc_admin_serial_feed(&harness.serial, prefix, sizeof(prefix), 2u,
                                &consumed, &complete, &rejection) ==
          WDC_ERR_BAD_ENCODING);
    CHECK(rejection.rejection == WDC_ADMIN_REJECTION_BAD_FRAME);
    CHECK(harness.serial.received_bytes == 0u);
    s_rejection_count += 2u;
    record_case("serial-frame-bounds-reset", before);
}

static void run_inflight_deadline_terminal(void)
{
    Harness harness;
    WdcAdminPreacceptResult rejection;
    WdcAdminRequest request;
    WdcControlWorkItem work;
    WdcAdminAcceptedCommand accepted;
    WdcAdminTerminalRecord terminal;
    uint8_t response[1];
    uint32_t response_bytes = 0u;
    uint32_t before = s_failures;
    init_harness(&harness, WDC_ADMIN_HP41_COMMAND_MASK);
    CHECK(authorize(&harness, 100u, (const uint8_t *)"proof", 5u,
                    &rejection) == WDC_OK);
    request = status_request(&harness, 1u, 1u, 200u);
    request.deadline_ms = 210u;
    CHECK(wdc_admin_submit(&harness.core, &request, NULL, 0u, 200u,
                           &rejection) == WDC_OK);
    CHECK(wdc_control_next(&harness.kernel, &work) == WDC_OK);
    CHECK(wdc_admin_begin_command(&harness.core, &work, 201u,
                                  &accepted) == WDC_OK);
    CHECK(wdc_admin_poll(&harness.core, 210u) == WDC_OK);
    CHECK(wdc_admin_command_lifecycle(&harness.core) ==
          WDC_ADMIN_LIFECYCLE_TERMINAL);
    CHECK(wdc_admin_take_terminal(&harness.core, &terminal,
                                  response, sizeof(response),
                                  &response_bytes) == WDC_OK);
    CHECK(terminal.result == WDC_ADMIN_TERMINAL_TIMED_OUT);
    CHECK(terminal.status == WDC_ERR_TIMEOUT);
    record_case("inflight-deadline-terminal", before);
}

static void run_queued_expiry_terminal(void)
{
    Harness harness;
    WdcAdminPreacceptResult rejection;
    WdcAdminRequest request;
    WdcControlWorkItem work;
    WdcAdminAcceptedCommand accepted;
    WdcAdminTerminalRecord terminal;
    uint8_t response[1];
    uint32_t response_bytes = 0u;
    uint32_t before = s_failures;
    init_harness(&harness, WDC_ADMIN_HP41_COMMAND_MASK);
    CHECK(authorize(&harness, 100u, (const uint8_t *)"proof", 5u,
                    &rejection) == WDC_OK);
    request = status_request(&harness, 1u, 1u, 200u);
    request.deadline_ms = 210u;
    CHECK(wdc_admin_submit(&harness.core, &request, NULL, 0u, 200u,
                           &rejection) == WDC_OK);
    CHECK(wdc_control_next(&harness.kernel, &work) == WDC_OK);
    CHECK(wdc_admin_begin_command(&harness.core, &work, 211u,
                                  &accepted) == WDC_ERR_TIMEOUT);
    CHECK(wdc_admin_take_terminal(&harness.core, &terminal,
                                  response, sizeof(response),
                                  &response_bytes) == WDC_OK);
    CHECK(terminal.result == WDC_ADMIN_TERMINAL_TIMED_OUT);
    record_case("queued-expiry-still-owns-terminal", before);
}

static void run_epoch_high_water(void)
{
    Harness harness;
    WdcAdminPreacceptResult rejection;
    WdcAdminRequest stale;
    uint64_t old_epoch;
    uint64_t old_nonce;
    uint32_t before = s_failures;
    init_harness(&harness, WDC_ADMIN_HP41_COMMAND_MASK);
    CHECK(authorize(&harness, 100u, (const uint8_t *)"proof", 5u,
                    &rejection) == WDC_OK);
    old_epoch = harness.core.session.authorization_epoch;
    old_nonce = harness.core.session.session_nonce;
    CHECK(wdc_admin_session_close(&harness.core, 200u) == WDC_OK);
    CHECK(authorize(&harness, 201u, (const uint8_t *)"proof", 5u,
                    &rejection) == WDC_OK);
    CHECK(harness.core.session.authorization_epoch > old_epoch);
    stale = status_request(&harness, 1u, 1u, 202u);
    stale.authorization_epoch = old_epoch;
    stale.session_nonce = old_nonce;
    CHECK(wdc_admin_submit(&harness.core, &stale, NULL, 0u, 202u,
                           &rejection) == WDC_ERR_CAPABILITY_DENIED);
    CHECK(wdc_admin_next_command_sequence(&harness.core) == 1u);
    s_rejection_count += 1u;
    record_case("authorization-epoch-high-water", before);
}

static void run_audit_overwrite_loss(void)
{
    Harness harness;
    WdcAdminPreacceptResult rejection;
    WdcAdminAuditEmission emission;
    WdcAdminAuditRecord record;
    uint32_t index;
    uint32_t before = s_failures;
    init_harness(&harness, WDC_ADMIN_HP41_COMMAND_MASK);
    CHECK(authorize(&harness, 100u, (const uint8_t *)"proof", 5u,
                    &rejection) == WDC_OK);
    memset(&emission, 0, sizeof(emission));
    emission.event = WDC_ADMIN_AUDIT_STAGING;
    emission.outcome = WDC_ADMIN_AUDIT_OBSERVED;
    emission.from_state = WDC_ADMIN_MODE_NORMAL;
    emission.to_state = WDC_ADMIN_MODE_NORMAL;
    emission.slot = WDC_ADMIN_SLOT_NONE;
    for (index = 0u; index < 40u; ++index) {
        CHECK(wdc_admin_audit_emit(&harness.core, &emission,
                                   200u + index) == WDC_OK);
    }
    CHECK(wdc_admin_audit_pending(&harness.core) ==
          WDC_ADMIN_AUDIT_RING_RECORDS);
    CHECK(wdc_admin_audit_losses(&harness.core) == 10u);
    for (index = 0u; index < WDC_ADMIN_AUDIT_RING_RECORDS; ++index) {
        CHECK(wdc_admin_take_audit(&harness.core, &record) == WDC_OK);
        CHECK(record.struct_size == WDC_ADMIN_AUDIT_RECORD_BYTES);
        CHECK(record.reserved[0] == 0u);
    }
    CHECK(wdc_admin_take_audit(&harness.core, &record) ==
          WDC_ERR_NOT_AVAILABLE);
    record_case("audit-overwrite-latches-loss", before);
}

static void run_verifier_seam_fail_closed(void)
{
    Harness harness;
    WdcAdminArtifactCandidate candidate;
    WdcAdminArtifactVerification verification;
    uint32_t before = s_failures;
    init_harness(&harness, WDC_ADMIN_HP41_COMMAND_MASK);
    memset(&candidate, 0, sizeof(candidate));
    candidate.struct_size = sizeof(candidate);
    candidate.version_major = WDC_ADMIN_VERSION_MAJOR;
    candidate.version_minor = WDC_ADMIN_VERSION_MINOR;
    candidate.slot = 1u;
    candidate.stored_bytes = 1024u;
    candidate.artifact_sha256[0] = 1u;
    candidate.running_host_fingerprint_sha256[0] = 1u;
    CHECK(wdc_admin_verify_artifact(&harness.core, &candidate,
                                    &verification, 100u) ==
          WDC_ERR_INVALID_STATE);
    CHECK(harness.verifier.calls == 0u);
    CHECK(harness.core.artifact_verifier.verify == fake_verify);
    CHECK(harness.core.authorizer.authorize == fake_authorize);
    record_case("replaceable-verifier-fails-closed-before-hp4-2", before);
}

int main(void)
{
    uint32_t index;
    run_layout_and_storage();
    run_attended_replaceable_authority();
    run_authorization_rate_limit();
    run_replay_and_preaccept_immutability();
    run_application_pressure_isolated();
    run_terminal_exactly_once();
    run_serial_fragmentation();
    run_serial_cannot_authorize();
    run_serial_frame_bounds();
    run_inflight_deadline_terminal();
    run_queued_expiry_terminal();
    run_epoch_high_water();
    run_audit_overwrite_loss();
    run_verifier_seam_fail_closed();

    CHECK(s_case_count == HP41_CASE_COUNT);
    for (index = 0u; index < s_case_count; ++index) {
        CHECK(s_cases[index].passed == 1u);
    }
    printf("{\"schema\":\"pulse.esp32.hp4_1-admin-core-smoke.v1\","
           "\"status\":\"%s\",\"failures\":%" PRIu32
           ",\"case_count\":%" PRIu32 ",\"rejections\":%" PRIu32
           ",\"core_static_bytes\":%zu,\"serial_static_bytes\":%zu"
           ",\"fixed_storage_bytes\":%" PRIu32 ",\"cases\":[",
           s_failures == 0u ? "PASS" : "FAIL",
           s_failures,
           s_case_count,
           s_rejection_count,
           sizeof(WdcAdminCore),
           sizeof(WdcAdminSerialAdapter),
           wdc_admin_fixed_storage_bytes());
    for (index = 0u; index < s_case_count; ++index) {
        printf("%s{\"name\":\"%s\",\"status\":\"%s\"}",
               index == 0u ? "" : ",",
               s_cases[index].name,
               s_cases[index].passed != 0u ? "PASS" : "FAIL");
    }
    printf("]}\n");
    return s_failures == 0u ? 0 : 1;
}
