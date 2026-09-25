/*
 * HP4.4 composes the complete HP4.1-HP4.3 implementation in one translation
 * unit and drives only its host-private interfaces.  Reusing the HP4.3
 * harness keeps artifact construction and lifecycle fakes identical to the
 * sealed predecessor while this file adds the adversarial matrix.
 */
#define main hp43_embedded_main
#include "hp4_3_admin_recovery_smoke.c"
#undef main

#define HP44_CATEGORY_COUNT 11u
#define HP44_PREACCEPT_CASES 21u
#define HP44_AUTH_REPLAY_CASES 13u
#define HP44_QUIESCE_CASES 12u
#define HP44_RESOURCE_CASES 4u
#define HP44_SAFE_STREAM_CASES 2362u
#define HP44_STREAM_TRANSACTION_CASES 14u
#define HP44_VERIFICATION_CASES 9u
#define HP44_JOURNAL_CASES 1030u
#define HP44_CAPACITY_CASES 10u
#define HP44_TERMINAL_AUDIT_CASES 8u
#define HP44_RECOVERY_CASES 40u
#define HP44_TOTAL_CASES 3523u
#define HP44_INHERITED_NATIVE_CASES 41u

typedef enum Hp44CategoryId {
    HP44_CATEGORY_PREACCEPT = 0,
    HP44_CATEGORY_AUTH_REPLAY = 1,
    HP44_CATEGORY_QUIESCE = 2,
    HP44_CATEGORY_RESOURCE = 3,
    HP44_CATEGORY_SAFE_STREAM = 4,
    HP44_CATEGORY_STREAM_TRANSACTION = 5,
    HP44_CATEGORY_VERIFICATION = 6,
    HP44_CATEGORY_JOURNAL = 7,
    HP44_CATEGORY_CAPACITY = 8,
    HP44_CATEGORY_TERMINAL_AUDIT = 9,
    HP44_CATEGORY_RECOVERY = 10,
} Hp44CategoryId;

typedef struct Hp44Category {
    const char *name;
    uint32_t expected;
    uint32_t observed;
    uint32_t passed;
} Hp44Category;

typedef struct Hp44AuthoritySnapshot {
    uint64_t next_sequence;
    uint32_t mode;
    uint32_t lifecycle;
    uint32_t authorization_state;
    uint32_t active_slot;
    uint32_t last_good_slot;
    uint32_t metadata_generation;
    uint32_t slot_a_state;
    uint32_t slot_b_state;
    uint32_t administration_outstanding;
    uint32_t recovery_outstanding;
    uint32_t application_outstanding;
} Hp44AuthoritySnapshot;

static Hp44Category s_hp44_categories[HP44_CATEGORY_COUNT] = {
    { "preaccept-and-mutation", HP44_PREACCEPT_CASES, 0u, 0u },
    { "authorization-and-replay", HP44_AUTH_REPLAY_CASES, 0u, 0u },
    { "quiesce-and-unload", HP44_QUIESCE_CASES, 0u, 0u },
    { "resource-floor", HP44_RESOURCE_CASES, 0u, 0u },
    { "safe-stream-cut", HP44_SAFE_STREAM_CASES, 0u, 0u },
    { "stream-transaction", HP44_STREAM_TRANSACTION_CASES, 0u, 0u },
    { "verification-rejection", HP44_VERIFICATION_CASES, 0u, 0u },
    { "journal-interruption", HP44_JOURNAL_CASES, 0u, 0u },
    { "capacity-saturation", HP44_CAPACITY_CASES, 0u, 0u },
    { "terminal-and-audit", HP44_TERMINAL_AUDIT_CASES, 0u, 0u },
    { "recovery-interaction", HP44_RECOVERY_CASES, 0u, 0u },
};

static uint32_t hp44_total_observed(void)
{
    uint32_t index;
    uint32_t total = 0u;
    for (index = 0u; index < HP44_CATEGORY_COUNT; ++index) {
        total += s_hp44_categories[index].observed;
    }
    return total;
}

static uint32_t hp44_total_passed(void)
{
    uint32_t index;
    uint32_t total = 0u;
    for (index = 0u; index < HP44_CATEGORY_COUNT; ++index) {
        total += s_hp44_categories[index].passed;
    }
    return total;
}

static void hp44_record(Hp44CategoryId category, uint32_t before)
{
    Hp44Category *record;
    CHECK((uint32_t)category < HP44_CATEGORY_COUNT);
    if ((uint32_t)category >= HP44_CATEGORY_COUNT) {
        return;
    }
    record = &s_hp44_categories[(uint32_t)category];
    record->observed += 1u;
    if (before == s_failures) {
        record->passed += 1u;
    }
}

static Hp44AuthoritySnapshot hp44_snapshot(const Harness *harness)
{
    Hp44AuthoritySnapshot snapshot;
    memset(&snapshot, 0, sizeof(snapshot));
    snapshot.next_sequence = harness->core.next_command_sequence;
    snapshot.mode = (uint32_t)harness->core.mode;
    snapshot.lifecycle = (uint32_t)harness->core.lifecycle;
    snapshot.authorization_state =
        (uint32_t)harness->core.authorization_state;
    snapshot.active_slot = (uint32_t)harness->metadata.active_slot;
    snapshot.last_good_slot = (uint32_t)harness->metadata.last_good_slot;
    snapshot.metadata_generation = harness->metadata.metadata_generation;
    snapshot.slot_a_state = (uint32_t)harness->metadata.slot_a.state;
    snapshot.slot_b_state = (uint32_t)harness->metadata.slot_b.state;
    snapshot.administration_outstanding = wdc_control_lane_outstanding(
        &harness->kernel, WDC_CONTROL_PRIORITY_ADMINISTRATION);
    snapshot.recovery_outstanding = wdc_control_lane_outstanding(
        &harness->kernel, WDC_CONTROL_PRIORITY_SAFETY_RECOVERY);
    snapshot.application_outstanding = wdc_control_lane_outstanding(
        &harness->kernel, WDC_CONTROL_PRIORITY_APPLICATION);
    return snapshot;
}

static void hp44_check_snapshot(const Harness *harness,
                                const Hp44AuthoritySnapshot *expected)
{
    Hp44AuthoritySnapshot actual = hp44_snapshot(harness);
    CHECK(memcmp(&actual, expected, sizeof(actual)) == 0);
}

static void hp44_check_confirmed_a(const Harness *harness,
                                   WdcAdminMode mode)
{
    CHECK(harness->metadata.active_slot == WDC_BUNDLE_SLOT_A);
    CHECK(harness->metadata.last_good_slot == WDC_BUNDLE_SLOT_A);
    CHECK(harness->metadata.slot_a.state == WDC_SLOT_CONFIRMED);
    CHECK(wdc_admin_mode(&harness->core) == mode);
}

static int32_t hp44_submit(Harness *harness,
                           WdcAdminRequest *request,
                           const uint8_t *payload,
                           uint64_t now_ms,
                           WdcAdminPreacceptResult *rejection)
{
    return wdc_admin_submit(&harness->core, request, payload,
                            request->payload_bytes, now_ms, rejection);
}

static void hp44_take_empty_terminal(Harness *harness,
                                     WdcAdminTerminalRecord *terminal)
{
    uint32_t response_bytes = 0u;
    CHECK(wdc_admin_take_terminal(&harness->core, terminal, NULL, 0u,
                                  &response_bytes) == WDC_OK);
    CHECK(response_bytes == 0u);
}

static int32_t hp44_stream_prefix(Harness *harness,
                                  uint32_t bytes,
                                  uint64_t *now_ms,
                                  WdcAdminTerminalRecord *terminal)
{
    uint32_t offset = 0u;
    while (offset < bytes) {
        uint32_t remaining = bytes - offset;
        uint32_t chunk = remaining < WDC_ADMIN_UPDATE_MAX_CHUNK_BYTES
                             ? remaining
                             : WDC_ADMIN_UPDATE_MAX_CHUNK_BYTES;
        int32_t status = execute_command(
            harness, WDC_ADMIN_COMMAND_WRITE_CHUNK,
            s_artifact + offset, chunk, *now_ms, terminal);
        if (status != WDC_OK) {
            return status;
        }
        offset += chunk;
        *now_ms += 2u;
    }
    return WDC_OK;
}

static int32_t hp44_prepare_verified(Harness *harness,
                                     WdcAdminMode origin,
                                     uint64_t *now_ms,
                                     WdcAdminTerminalRecord *terminal)
{
    init_harness(harness, origin, origin == WDC_ADMIN_MODE_NORMAL);
    if (execute_command(harness, WDC_ADMIN_COMMAND_BEGIN_UPDATE,
                        NULL, 0u, *now_ms, terminal) != WDC_OK) {
        return WDC_ERR_UNKNOWN;
    }
    *now_ms += 2u;
    if (hp44_stream_prefix(harness, s_artifact_bytes, now_ms,
                           terminal) != WDC_OK) {
        return WDC_ERR_UNKNOWN;
    }
    if (execute_command(harness, WDC_ADMIN_COMMAND_FINISH_UPDATE,
                        NULL, 0u, *now_ms, terminal) != WDC_OK) {
        return WDC_ERR_UNKNOWN;
    }
    *now_ms += 2u;
    return WDC_OK;
}

static int32_t hp44_execute_status(Harness *harness,
                                   uint64_t now_ms,
                                   WdcAdminTerminalRecord *terminal)
{
    WdcAdminRequest request = make_request(
        harness, WDC_ADMIN_COMMAND_STATUS, 0u, now_ms);
    WdcAdminRecoveryStatus response;
    uint32_t response_bytes = 0u;
    memset(&response, 0, sizeof(response));
    return execute_request(harness, &request, NULL, now_ms, terminal,
                           (uint8_t *)&response, sizeof(response),
                           &response_bytes);
}

static void hp44_finish_accepted_status(Harness *harness,
                                        uint64_t now_ms)
{
    WdcControlWorkItem work;
    WdcAdminAcceptedCommand accepted;
    WdcAdminTerminalRecord terminal;
    WdcAdminRecoveryStatus response;
    uint32_t response_bytes = 0u;
    CHECK(wdc_control_next(&harness->kernel, &work) == WDC_OK);
    CHECK(wdc_admin_begin_command(&harness->core, &work, now_ms,
                                  &accepted) == WDC_OK);
    CHECK(wdc_admin_recovery_execute(&harness->recovery, &accepted,
                                     now_ms) == WDC_OK);
    CHECK(wdc_admin_take_terminal(&harness->core, &terminal,
                                  (uint8_t *)&response,
                                  sizeof(response),
                                  &response_bytes) == WDC_OK);
    CHECK(response_bytes == WDC_ADMIN_RECOVERY_STATUS_BYTES);
}

static void hp44_run_preaccept_matrix(void)
{
    uint32_t variant;
    for (variant = 0u; variant < HP44_PREACCEPT_CASES; ++variant) {
        Harness harness;
        WdcAdminRequest request;
        WdcAdminRequest first;
        WdcAdminPreacceptResult rejection;
        WdcAdminTerminalRecord terminal;
        Hp44AuthoritySnapshot snapshot;
        WdcAdminPreacceptRejection expected = WDC_ADMIN_REJECTION_BOUNDS;
        const uint8_t *payload = NULL;
        uint32_t before = s_failures;
        init_harness(&harness, WDC_ADMIN_MODE_NORMAL, true);
        request = make_request(&harness, WDC_ADMIN_COMMAND_STATUS, 0u, 200u);
        switch (variant) {
        case 0u:
            request.authorization_epoch += 1u;
            expected = WDC_ADMIN_REJECTION_UNAUTHORIZED;
            break;
        case 1u:
            request.session_nonce ^= 1u;
            expected = WDC_ADMIN_REJECTION_UNAUTHORIZED;
            break;
        case 2u:
            request.deadline_ms = 200u;
            expected = WDC_ADMIN_REJECTION_EXPIRED;
            break;
        case 3u:
            request.deadline_ms = 200u + WDC_ADMIN_COMMAND_DEADLINE_MS + 1u;
            expected = WDC_ADMIN_REJECTION_EXPIRED;
            break;
        case 4u:
            request.struct_size -= 1u;
            break;
        case 5u:
            request.version_major += 1u;
            break;
        case 6u:
            request.version_minor += 1u;
            break;
        case 7u:
            request.flags = 1u;
            break;
        case 8u:
            request.reserved0 = 1u;
            break;
        case 9u:
            request.reserved1[0] = 1u;
            break;
        case 10u:
            request.request_id = 0u;
            break;
        case 11u:
            request.command_sequence = 0u;
            break;
        case 12u:
            request.payload_bytes = 1u;
            payload = s_artifact;
            break;
        case 13u:
            request.command = WDC_ADMIN_COMMAND_REBOOT + 1u;
            expected = WDC_ADMIN_REJECTION_UNSUPPORTED;
            break;
        case 14u:
            request.slot = WDC_BUNDLE_SLOT_A;
            break;
        case 15u:
            request = make_request(&harness,
                                   WDC_ADMIN_COMMAND_ENTER_RECOVERY,
                                   0u, 200u);
            request.slot = WDC_BUNDLE_SLOT_B;
            request.expected_total_bytes = s_artifact_bytes;
            memcpy(request.artifact_sha256, s_artifact_sha256,
                   sizeof(request.artifact_sha256));
            break;
        case 16u:
            request = make_request(&harness,
                                   WDC_ADMIN_COMMAND_WRITE_CHUNK,
                                   1u, 200u);
            payload = s_artifact;
            expected = WDC_ADMIN_REJECTION_WRONG_STATE;
            break;
        case 17u:
            harness.core.session.privilege_mask &=
                ~WDC_ADMIN_PRIVILEGE_STATUS;
            expected = WDC_ADMIN_REJECTION_UNAUTHORIZED;
            break;
        case 18u:
            request.command_sequence += 1u;
            expected = WDC_ADMIN_REJECTION_OUT_OF_ORDER;
            break;
        case 19u:
            CHECK(hp44_execute_status(&harness, 180u, &terminal) == WDC_OK);
            request = make_request(&harness, WDC_ADMIN_COMMAND_STATUS,
                                   0u, 200u);
            request.command_sequence = 1u;
            expected = WDC_ADMIN_REJECTION_STALE_REPLAY;
            break;
        case 20u:
            first = request;
            CHECK(hp44_submit(&harness, &first, NULL, 200u,
                              &rejection) == WDC_OK);
            request = make_request(&harness, WDC_ADMIN_COMMAND_STATUS,
                                   0u, 201u);
            expected = WDC_ADMIN_REJECTION_BUSY;
            break;
        default:
            CHECK(false);
            break;
        }
        snapshot = hp44_snapshot(&harness);
        CHECK(hp44_submit(&harness, &request, payload, 200u,
                          &rejection) ==
              wdc_admin_rejection_status(expected));
        CHECK(rejection.rejection == expected);
        hp44_check_snapshot(&harness, &snapshot);
        if (variant == 20u) {
            hp44_finish_accepted_status(&harness, 202u);
        }
        hp44_record(HP44_CATEGORY_PREACCEPT, before);
    }
}

static WdcAdminAuthorizationStart hp44_auth_start(
    const Harness *harness,
    uint64_t challenge_id)
{
    WdcAdminAuthorizationStart start;
    memset(&start, 0, sizeof(start));
    start.transport_kind = WDC_ADMIN_TRANSPORT_SERIAL_PHYSICAL_V1;
    start.authorization_method = WDC_ADMIN_AUTH_METHOD_LOCAL_PHYSICAL;
    start.attended_physical_entry = 1u;
    start.challenge_id = challenge_id;
    memcpy(start.channel_binding_sha256, harness->binding,
           sizeof(start.channel_binding_sha256));
    return start;
}

static void hp44_run_authorization_replay_matrix(void)
{
    uint32_t variant;
    for (variant = 0u; variant < HP44_AUTH_REPLAY_CASES; ++variant) {
        Harness harness;
        WdcAdminAuthorizationStart start;
        WdcAdminPreacceptResult rejection;
        WdcAdminRequest request;
        WdcAdminTerminalRecord terminal;
        WdcAdminRecoveryStatus response;
        Hp44AuthoritySnapshot snapshot;
        uint64_t deadline = 0u;
        uint32_t response_bytes = 0u;
        uint32_t before = s_failures;
        uint32_t index;
        init_harness(&harness, WDC_ADMIN_MODE_NORMAL, true);
        start = hp44_auth_start(&harness, 0x4400u + variant);
        if (variant <= 5u || variant == 10u) {
            CHECK(wdc_admin_session_close(&harness.core, 150u) == WDC_OK);
        }
        switch (variant) {
        case 0u:
            start.transport_kind = WDC_ADMIN_TRANSPORT_NONE;
            CHECK(wdc_admin_authorization_begin(
                      &harness.core, &start, 200u, &deadline,
                      &rejection) == WDC_ERR_CAPABILITY_DENIED);
            CHECK(rejection.rejection == WDC_ADMIN_REJECTION_UNAUTHORIZED);
            break;
        case 1u:
            start.attended_physical_entry = 0u;
            CHECK(wdc_admin_authorization_begin(
                      &harness.core, &start, 200u, &deadline,
                      &rejection) == WDC_ERR_CAPABILITY_DENIED);
            break;
        case 2u:
            start.channel_binding_sha256[0] ^= 1u;
            CHECK(wdc_admin_authorization_begin(
                      &harness.core, &start, 200u, &deadline,
                      &rejection) == WDC_ERR_CAPABILITY_DENIED);
            break;
        case 3u:
            CHECK(wdc_admin_authorization_begin(
                      &harness.core, &start, 200u, &deadline,
                      &rejection) == WDC_OK);
            CHECK(wdc_admin_authorization_finish(
                      &harness.core, (const uint8_t *)"proof", 5u,
                      deadline, &rejection) == WDC_ERR_TIMEOUT);
            CHECK(wdc_admin_authorization_state(&harness.core) ==
                  WDC_ADMIN_AUTH_EXPIRED);
            break;
        case 4u:
            CHECK(wdc_admin_authorization_begin(
                      &harness.core, &start, 200u, &deadline,
                      &rejection) == WDC_OK);
            CHECK(wdc_admin_authorization_finish(
                      &harness.core, (const uint8_t *)"wrong", 5u,
                      201u, &rejection) == WDC_ERR_CAPABILITY_DENIED);
            CHECK(wdc_admin_authorization_state(&harness.core) ==
                  WDC_ADMIN_AUTH_UNAUTHENTICATED);
            break;
        case 5u:
            for (index = 0u;
                 index < WDC_ADMIN_AUTHORIZATION_FAILURE_LIMIT;
                 ++index) {
                start.challenge_id = 0x4500u + index;
                CHECK(wdc_admin_authorization_begin(
                          &harness.core, &start, 200u + index * 2u,
                          &deadline, &rejection) == WDC_OK);
                CHECK(wdc_admin_authorization_finish(
                          &harness.core, (const uint8_t *)"wrong", 5u,
                          201u + index * 2u, &rejection) ==
                      WDC_ERR_CAPABILITY_DENIED);
            }
            start.challenge_id = 0x4600u;
            CHECK(wdc_admin_authorization_begin(
                      &harness.core, &start, 230u, &deadline,
                      &rejection) == WDC_ERR_RATE_LIMITED);
            CHECK(rejection.rejection == WDC_ADMIN_REJECTION_RATE_LIMITED);
            break;
        case 6u:
            CHECK(wdc_admin_poll(
                      &harness.core,
                      harness.core.last_activity_ms +
                          WDC_ADMIN_SESSION_IDLE_DEADLINE_MS) == WDC_OK);
            CHECK(wdc_admin_authorization_state(&harness.core) ==
                  WDC_ADMIN_AUTH_EXPIRED);
            request = make_request(&harness, WDC_ADMIN_COMMAND_STATUS,
                                   0u, 40000u);
            CHECK(hp44_submit(&harness, &request, NULL, 40000u,
                              &rejection) == WDC_ERR_TIMEOUT);
            break;
        case 7u:
            CHECK(wdc_admin_poll(&harness.core,
                                 harness.core.last_activity_ms - 1u) ==
                  WDC_OK);
            CHECK(wdc_admin_authorization_state(&harness.core) ==
                  WDC_ADMIN_AUTH_EXPIRED);
            break;
        case 8u:
            CHECK(wdc_admin_session_close(&harness.core, 150u) == WDC_OK);
            request = make_request(&harness, WDC_ADMIN_COMMAND_STATUS,
                                   0u, 200u);
            CHECK(hp44_submit(&harness, &request, NULL, 200u,
                              &rejection) == WDC_ERR_CAPABILITY_DENIED);
            break;
        case 9u:
            CHECK(wdc_admin_session_revoke(&harness.core, 150u) == WDC_OK);
            request = make_request(&harness, WDC_ADMIN_COMMAND_STATUS,
                                   0u, 200u);
            CHECK(hp44_submit(&harness, &request, NULL, 200u,
                              &rejection) == WDC_ERR_CAPABILITY_DENIED);
            break;
        case 10u:
            harness.authorizer.next_epoch = 1u;
            CHECK(wdc_admin_authorization_begin(
                      &harness.core, &start, 200u, &deadline,
                      &rejection) == WDC_OK);
            CHECK(wdc_admin_authorization_finish(
                      &harness.core, (const uint8_t *)"proof", 5u,
                      201u, &rejection) == WDC_ERR_CAPABILITY_DENIED);
            CHECK(harness.core.authorization_epoch_high_water == 1u);
            break;
        case 11u:
            harness.core.next_command_sequence = UINT64_MAX;
            request = make_request(&harness, WDC_ADMIN_COMMAND_STATUS,
                                   0u, 200u);
            snapshot = hp44_snapshot(&harness);
            CHECK(hp44_submit(&harness, &request, NULL, 200u,
                              &rejection) == WDC_ERR_RATE_LIMITED);
            CHECK(rejection.rejection == WDC_ADMIN_REJECTION_RATE_LIMITED);
            hp44_check_snapshot(&harness, &snapshot);
            CHECK(harness.core.next_command_sequence == UINT64_MAX);
            break;
        case 12u:
            request = make_request(&harness, WDC_ADMIN_COMMAND_STATUS,
                                   0u, 200u);
            request.request_id = 77u;
            memset(&response, 0, sizeof(response));
            CHECK(execute_request(&harness, &request, NULL, 200u,
                                  &terminal, (uint8_t *)&response,
                                  sizeof(response), &response_bytes) ==
                  WDC_OK);
            request = make_request(&harness, WDC_ADMIN_COMMAND_STATUS,
                                   0u, 210u);
            request.request_id = 77u;
            response_bytes = 0u;
            CHECK(execute_request(&harness, &request, NULL, 210u,
                                  &terminal, (uint8_t *)&response,
                                  sizeof(response), &response_bytes) ==
                  WDC_OK);
            CHECK(terminal.command_sequence == 2u);
            break;
        default:
            CHECK(false);
            break;
        }
        hp44_record(HP44_CATEGORY_AUTH_REPLAY, before);
    }
}

static uint32_t s_hp44_quiesce_variant;

static int32_t hp44_adversarial_quiesce(
    void *context,
    uint64_t deadline_ms,
    WdcAdminUpdateQuiesceEvidence *out_evidence)
{
    FakeLifecycle *lifecycle = (FakeLifecycle *)context;
    lifecycle->quiesce_calls += 1u;
    if (s_hp44_quiesce_variant == 0u) {
        return WDC_ERR_IO; /* Guest trap/refusal at the lifecycle boundary. */
    }
    if (s_hp44_quiesce_variant == 1u) {
        return WDC_ERR_TIMEOUT;
    }
    memset(out_evidence, 0, sizeof(*out_evidence));
    out_evidence->guest_quiesced = 1u;
    out_evidence->native_refinements_quiesced = 1u;
    out_evidence->guest_unloaded = 1u;
    out_evidence->native_refinements_unloaded = 1u;
    out_evidence->completed_monotonic_ms = deadline_ms - 1u;
    switch (s_hp44_quiesce_variant) {
    case 2u:
        out_evidence->guest_quiesced = 0u;
        break;
    case 3u:
        out_evidence->native_refinements_quiesced = 0u;
        break;
    case 4u:
        out_evidence->guest_unloaded = 0u;
        break;
    case 5u:
        out_evidence->native_refinements_unloaded = 0u;
        break;
    case 6u:
        out_evidence->guest_loaded_after = 1u;
        break;
    case 7u:
        out_evidence->native_refinements_loaded_after = 1u;
        break;
    case 8u:
        out_evidence->flags = 1u;
        break;
    case 9u:
        out_evidence->reserved = 1u;
        break;
    case 10u:
        out_evidence->completed_monotonic_ms = 0u;
        break;
    case 11u:
        out_evidence->completed_monotonic_ms = deadline_ms;
        break;
    default:
        break;
    }
    return WDC_OK;
}

static void hp44_run_quiesce_matrix(void)
{
    uint32_t variant;
    for (variant = 0u; variant < HP44_QUIESCE_CASES; ++variant) {
        Harness harness;
        WdcAdminTerminalRecord terminal;
        uint32_t before = s_failures;
        init_harness(&harness, WDC_ADMIN_MODE_NORMAL, true);
        s_hp44_quiesce_variant = variant;
        harness.recovery.update.lifecycle.quiesce_and_unload =
            hp44_adversarial_quiesce;
        CHECK(execute_command(&harness,
                              WDC_ADMIN_COMMAND_ENTER_RECOVERY,
                              NULL, 0u, 200u, &terminal) != WDC_OK);
        CHECK(terminal.result ==
              (variant == 1u ? WDC_ADMIN_TERMINAL_TIMED_OUT
                             : WDC_ADMIN_TERMINAL_FAILED));
        hp44_check_confirmed_a(&harness, WDC_ADMIN_MODE_NORMAL);
        CHECK(harness.recovery.application_loaded == 1u);
        hp44_record(HP44_CATEGORY_QUIESCE, before);
    }
}

static void hp44_run_resource_matrix(void)
{
    uint32_t variant;
    for (variant = 0u; variant < HP44_RESOURCE_CASES; ++variant) {
        Harness harness;
        WdcAdminTerminalRecord terminal;
        WdcAdminMode origin = variant == 3u
                                  ? WDC_ADMIN_MODE_RECOVERY
                                  : WDC_ADMIN_MODE_NORMAL;
        uint32_t before = s_failures;
        init_harness(&harness, origin,
                     origin == WDC_ADMIN_MODE_NORMAL);
        if (variant == 0u) {
            harness.lifecycle.heap_status = WDC_ERR_IO;
        } else if (variant == 1u || variant == 3u) {
            harness.lifecycle.heap.internal_free_bytes = 163839u;
        } else {
            harness.lifecycle.heap.internal_largest_block_bytes = 98303u;
        }
        CHECK(execute_command(&harness,
                              WDC_ADMIN_COMMAND_BEGIN_UPDATE,
                              NULL, 0u, 200u, &terminal) != WDC_OK);
        CHECK(terminal.result == WDC_ADMIN_TERMINAL_FAILED);
        if (origin == WDC_ADMIN_MODE_NORMAL) {
            hp44_check_confirmed_a(&harness, WDC_ADMIN_MODE_NORMAL);
        } else {
            CHECK(wdc_admin_mode(&harness.core) ==
                  WDC_ADMIN_MODE_RECOVERY);
            CHECK(harness.metadata.active_slot == WDC_BUNDLE_SLOT_NONE);
            CHECK(harness.metadata.last_good_slot == WDC_BUNDLE_SLOT_NONE);
        }
        hp44_record(HP44_CATEGORY_RESOURCE, before);
    }
}

static void hp44_run_safe_stream_cut_matrix(void)
{
    uint32_t cut;
    CHECK(s_artifact_bytes + 1u == HP44_SAFE_STREAM_CASES);
    for (cut = 0u; cut <= s_artifact_bytes; ++cut) {
        Harness harness;
        WdcAdminTerminalRecord terminal;
        uint64_t now_ms = 202u;
        uint32_t before = s_failures;
        init_harness(&harness, WDC_ADMIN_MODE_NORMAL, true);
        CHECK(execute_command(&harness,
                              WDC_ADMIN_COMMAND_BEGIN_UPDATE,
                              NULL, 0u, 200u, &terminal) == WDC_OK);
        CHECK(hp44_stream_prefix(&harness, cut, &now_ms,
                                 &terminal) == WDC_OK);
        CHECK(execute_command(&harness, WDC_ADMIN_COMMAND_ABORT,
                              NULL, 0u, now_ms, &terminal) == WDC_OK);
        CHECK(terminal.result == WDC_ADMIN_TERMINAL_SUCCEEDED);
        CHECK(terminal.bytes_received == cut);
        hp44_check_confirmed_a(&harness, WDC_ADMIN_MODE_NORMAL);
        hp44_record(HP44_CATEGORY_SAFE_STREAM, before);
    }
}

static void hp44_run_stream_transaction_matrix(void)
{
    uint32_t variant;
    for (variant = 0u;
         variant < HP44_STREAM_TRANSACTION_CASES;
         ++variant) {
        Harness harness;
        WdcAdminRequest request;
        WdcAdminPreacceptResult rejection;
        WdcAdminTerminalRecord terminal;
        WdcControlWorkItem work;
        WdcAdminAcceptedCommand accepted;
        Hp44AuthoritySnapshot snapshot;
        WdcOtaHostFaultPlan fault;
        uint64_t now_ms = 210u;
        uint32_t response_bytes = 0u;
        uint32_t before = s_failures;
        uint32_t index;
        memset(&fault, 0, sizeof(fault));
        if (variant == 9u) {
            now_ms = 200u;
            CHECK(hp44_prepare_verified(&harness,
                                        WDC_ADMIN_MODE_NORMAL,
                                        &now_ms, &terminal) == WDC_OK);
            CHECK(wdc_admin_recovery_poll(
                      &harness.recovery, 900201u) == WDC_ERR_TIMEOUT);
            hp44_check_confirmed_a(&harness, WDC_ADMIN_MODE_NORMAL);
            hp44_record(HP44_CATEGORY_STREAM_TRANSACTION, before);
            continue;
        }
        init_harness(&harness, WDC_ADMIN_MODE_NORMAL, true);
        if (variant == 12u) {
            fault.operation = WDC_OTA_HOST_FAULT_SLOT_ERASE;
            fault.trigger_index = 1u;
            fault.tear_after_bytes = 4096u;
            CHECK(wdc_ota_host_fault_arm(&fault) == WDC_OK);
            CHECK(execute_command(&harness,
                                  WDC_ADMIN_COMMAND_BEGIN_UPDATE,
                                  NULL, 0u, 200u, &terminal) != WDC_OK);
            CHECK(wdc_ota_host_fault_trigger_count() == 1u);
            hp44_check_confirmed_a(&harness, WDC_ADMIN_MODE_NORMAL);
            wdc_ota_host_power_cycle();
            hp44_record(HP44_CATEGORY_STREAM_TRANSACTION, before);
            continue;
        }
        if (variant == 13u) {
            request = make_request(&harness,
                                   WDC_ADMIN_COMMAND_STATUS,
                                   0u, 200u);
            request.deadline_ms = 201u;
            CHECK(hp44_submit(&harness, &request, NULL, 200u,
                              &rejection) == WDC_OK);
            CHECK(wdc_control_next(&harness.kernel, &work) == WDC_OK);
            CHECK(wdc_admin_begin_command(&harness.core, &work, 201u,
                                          &accepted) == WDC_ERR_TIMEOUT);
            hp44_take_empty_terminal(&harness, &terminal);
            CHECK(terminal.result == WDC_ADMIN_TERMINAL_TIMED_OUT);
            CHECK(wdc_admin_take_terminal(&harness.core, &terminal,
                                          NULL, 0u,
                                          &response_bytes) ==
                  WDC_ERR_NOT_AVAILABLE);
            hp44_record(HP44_CATEGORY_STREAM_TRANSACTION, before);
            continue;
        }
        CHECK(execute_command(&harness,
                              WDC_ADMIN_COMMAND_BEGIN_UPDATE,
                              NULL, 0u, 200u, &terminal) == WDC_OK);
        switch (variant) {
        case 0u:
        case 1u:
        case 2u:
            request = make_request(&harness,
                                   WDC_ADMIN_COMMAND_WRITE_CHUNK,
                                   1u, 210u);
            if (variant == 0u) {
                request.slot = WDC_BUNDLE_SLOT_A;
            } else if (variant == 1u) {
                request.expected_total_bytes += 1u;
            } else {
                request.artifact_sha256[0] ^= 1u;
            }
            CHECK(execute_request(&harness, &request, s_artifact,
                                  210u, &terminal, NULL, 0u,
                                  &response_bytes) != WDC_OK);
            CHECK(terminal.result == WDC_ADMIN_TERMINAL_FAILED);
            break;
        case 3u:
            CHECK(execute_command(&harness,
                                  WDC_ADMIN_COMMAND_FINISH_UPDATE,
                                  NULL, 0u, 210u, &terminal) != WDC_OK);
            break;
        case 4u:
            CHECK(hp44_stream_prefix(&harness, s_artifact_bytes,
                                     &now_ms, &terminal) == WDC_OK);
            CHECK(execute_command(&harness,
                                  WDC_ADMIN_COMMAND_WRITE_CHUNK,
                                  s_artifact, 1u, now_ms,
                                  &terminal) != WDC_OK);
            break;
        case 5u:
            request = make_request(&harness,
                                   WDC_ADMIN_COMMAND_WRITE_CHUNK,
                                   0u, 210u);
            snapshot = hp44_snapshot(&harness);
            CHECK(hp44_submit(&harness, &request, NULL, 210u,
                              &rejection) == WDC_ERR_BAD_LENGTH);
            hp44_check_snapshot(&harness, &snapshot);
            CHECK(execute_command(&harness, WDC_ADMIN_COMMAND_ABORT,
                                  NULL, 0u, 211u, &terminal) == WDC_OK);
            break;
        case 6u:
            request = make_request(&harness,
                                   WDC_ADMIN_COMMAND_WRITE_CHUNK,
                                   WDC_ADMIN_UPDATE_MAX_CHUNK_BYTES + 1u,
                                   210u);
            snapshot = hp44_snapshot(&harness);
            CHECK(hp44_submit(&harness, &request, s_artifact, 210u,
                              &rejection) == WDC_ERR_BAD_LENGTH);
            hp44_check_snapshot(&harness, &snapshot);
            CHECK(execute_command(&harness, WDC_ADMIN_COMMAND_ABORT,
                                  NULL, 0u, 211u, &terminal) == WDC_OK);
            break;
        case 7u:
            for (index = 0u;
                 index < WDC_ADMIN_UPDATE_RATE_CHUNKS_PER_WINDOW;
                 ++index) {
                CHECK(execute_command(
                          &harness, WDC_ADMIN_COMMAND_WRITE_CHUNK,
                          s_artifact + index, 1u, 210u + index,
                          &terminal) == WDC_OK);
            }
            CHECK(execute_command(&harness,
                                  WDC_ADMIN_COMMAND_WRITE_CHUNK,
                                  s_artifact + index, 1u, 210u + index,
                                  &terminal) == WDC_ERR_RATE_LIMITED);
            CHECK(terminal.result == WDC_ADMIN_TERMINAL_FAILED);
            break;
        case 8u:
            CHECK(wdc_admin_recovery_poll(
                      &harness.recovery, 30201u) == WDC_ERR_TIMEOUT);
            break;
        case 10u:
            request = make_request(&harness,
                                   WDC_ADMIN_COMMAND_ABORT,
                                   0u, 210u);
            request.artifact_sha256[0] ^= 1u;
            CHECK(execute_request(&harness, &request, NULL, 210u,
                                  &terminal, NULL, 0u,
                                  &response_bytes) != WDC_OK);
            break;
        case 11u:
            fault.operation = WDC_OTA_HOST_FAULT_SLOT_WRITE;
            fault.trigger_index = 1u;
            fault.tear_after_bytes = 1u;
            CHECK(wdc_ota_host_fault_arm(&fault) == WDC_OK);
            CHECK(execute_command(&harness,
                                  WDC_ADMIN_COMMAND_WRITE_CHUNK,
                                  s_artifact, 16u, 210u,
                                  &terminal) == WDC_ERR_IO);
            CHECK(wdc_ota_host_fault_trigger_count() == 1u);
            wdc_ota_host_power_cycle();
            break;
        default:
            CHECK(false);
            break;
        }
        hp44_check_confirmed_a(&harness, WDC_ADMIN_MODE_NORMAL);
        hp44_record(HP44_CATEGORY_STREAM_TRANSACTION, before);
    }
}

static int32_t hp44_deny_artifact_authority(
    void *context,
    const WdcPulseAppArtifactHeaderV1 *header,
    const uint8_t artifact_sha256[WDC_BUNDLE_SHA256_BYTES],
    const WdcBundleVerifyResult *bundle_verify)
{
    (void)context;
    (void)header;
    (void)artifact_sha256;
    (void)bundle_verify;
    return WDC_ERR_CAPABILITY_DENIED;
}

static int32_t hp44_malformed_admin_verifier(
    void *context,
    const WdcAdminArtifactCandidate *candidate,
    WdcAdminArtifactVerification *out_verification)
{
    (void)context;
    (void)candidate;
    memset(out_verification, 0, sizeof(*out_verification));
    out_verification->status = WDC_OK;
    out_verification->complete_artifact_valid = 2u;
    return WDC_OK;
}

static void hp44_mutate_candidate(uint32_t variant)
{
    WdcPulseAppArtifactHeaderV1 header;
    bool header_changed = false;
    memcpy(&header, s_artifact, sizeof(header));
    switch (variant) {
    case 0u:
        header.magic ^= 1u;
        header_changed = true;
        break;
    case 1u:
        s_artifact[WDC_APP_ARTIFACT_HEADER_BYTES + 16u] ^= 1u;
        break;
    case 2u:
        s_artifact[s_artifact_bytes - 1u] ^= 1u;
        wdc_sha256(s_artifact + WDC_APP_ARTIFACT_HEADER_BYTES,
                   s_bundle_bytes, header.bundle_sha256);
        CHECK(wdc_app_artifact_header_seal(&header) == WDC_OK);
        header_changed = true;
        break;
    case 3u:
        header.requirements.allowed_target_mask =
            WDC_HOST_TARGET_MASK_ESP32S3;
        CHECK(wdc_app_artifact_header_seal(&header) == WDC_OK);
        header_changed = true;
        break;
    default:
        break;
    }
    if (header_changed) {
        memcpy(s_artifact, &header, sizeof(header));
    }
    wdc_sha256(s_artifact, s_artifact_bytes, s_artifact_sha256);
}

static void hp44_run_verification_matrix(void)
{
    uint32_t variant;
    for (variant = 0u; variant < HP44_VERIFICATION_CASES; ++variant) {
        Harness harness;
        WdcAdminTerminalRecord terminal;
        uint64_t now_ms = 210u;
        uint32_t before = s_failures;
        build_artifact();
        init_harness(&harness, WDC_ADMIN_MODE_NORMAL, true);
        if (variant <= 3u) {
            hp44_mutate_candidate(variant);
        } else if (variant == 4u) {
            harness.recovery.update.slot_verify_policy.security_version_floor =
                9u;
        } else if (variant == 5u) {
            harness.recovery.update.slot_verify_policy.production_mode = true;
            harness.recovery.update.slot_verify_policy
                .artifact_authority_verify = NULL;
        } else if (variant == 6u) {
            harness.recovery.update.slot_verify_policy.production_mode = true;
            harness.recovery.update.slot_verify_policy
                .artifact_authority_verify = hp44_deny_artifact_authority;
        } else if (variant == 7u) {
            harness.verifier.allow = false;
        } else {
            harness.core.artifact_verifier.verify =
                hp44_malformed_admin_verifier;
        }
        CHECK(execute_command(&harness,
                              WDC_ADMIN_COMMAND_BEGIN_UPDATE,
                              NULL, 0u, 200u, &terminal) == WDC_OK);
        CHECK(hp44_stream_prefix(&harness, s_artifact_bytes,
                                 &now_ms, &terminal) == WDC_OK);
        CHECK(execute_command(&harness,
                              WDC_ADMIN_COMMAND_FINISH_UPDATE,
                              NULL, 0u, now_ms, &terminal) != WDC_OK);
        CHECK(terminal.result == WDC_ADMIN_TERMINAL_FAILED);
        CHECK(terminal.final_state == WDC_ADMIN_MODE_NORMAL);
        hp44_check_confirmed_a(&harness, WDC_ADMIN_MODE_NORMAL);
        CHECK(harness.recovery.update.verification_complete == false);
        hp44_record(HP44_CATEGORY_VERIFICATION, before);
        build_artifact();
    }
}

static void hp44_shift_journal_target(Harness *harness)
{
    harness->metadata.metadata_generation += 1u;
    CHECK(wdc_bundle_metadata_seal(&harness->metadata) == WDC_OK);
    CHECK(wdc_ota_write_metadata(&harness->metadata) == WDC_OK);
    CHECK(wdc_ota_host_metadata_valid_record_count() == 2u);
}

static void hp44_run_journal_matrix(void)
{
    static const WdcOtaHostFaultOperation operations[] = {
        WDC_OTA_HOST_FAULT_METADATA_ERASE,
        WDC_OTA_HOST_FAULT_METADATA_BODY_WRITE,
        WDC_OTA_HOST_FAULT_METADATA_MARKER_WRITE,
    };
    uint32_t limits[3];
    uint32_t target_variant;
    uint32_t operation_index;
    uint32_t cut;
    limits[0] = wdc_ota_host_metadata_record_bytes();
    limits[1] = wdc_ota_host_metadata_body_bytes();
    limits[2] = wdc_ota_host_metadata_marker_bytes();
    CHECK(limits[0] == 256u);
    CHECK(limits[1] == 252u);
    CHECK(limits[2] == 4u);
    CHECK(2u * ((limits[0] + 1u) + (limits[1] + 1u) +
                (limits[2] + 1u)) == HP44_JOURNAL_CASES);
    for (target_variant = 0u; target_variant < 2u; ++target_variant) {
        for (operation_index = 0u;
             operation_index < 3u;
             ++operation_index) {
            for (cut = 0u; cut <= limits[operation_index]; ++cut) {
                Harness harness;
                WdcAdminTerminalRecord terminal;
                WdcOtaHostFaultPlan fault;
                uint64_t now_ms = 210u;
                bool marker_complete =
                    operation_index == 2u && cut == limits[2];
                uint32_t before = s_failures;
                init_harness(&harness, WDC_ADMIN_MODE_NORMAL, true);
                if (target_variant != 0u) {
                    hp44_shift_journal_target(&harness);
                }
                CHECK(execute_command(&harness,
                                      WDC_ADMIN_COMMAND_BEGIN_UPDATE,
                                      NULL, 0u, 200u,
                                      &terminal) == WDC_OK);
                CHECK(hp44_stream_prefix(&harness, s_artifact_bytes,
                                         &now_ms, &terminal) == WDC_OK);
                CHECK(execute_command(&harness,
                                      WDC_ADMIN_COMMAND_FINISH_UPDATE,
                                      NULL, 0u, now_ms,
                                      &terminal) == WDC_OK);
                now_ms += 2u;
                memset(&fault, 0, sizeof(fault));
                fault.operation = operations[operation_index];
                fault.trigger_index = 1u;
                fault.tear_after_bytes = cut;
                CHECK(wdc_ota_host_fault_arm(&fault) == WDC_OK);
                if (marker_complete) {
                    CHECK(execute_command(
                              &harness,
                              WDC_ADMIN_COMMAND_ACTIVATE_TRIAL,
                              NULL, 0u, now_ms, &terminal) == WDC_OK);
                    CHECK(terminal.result ==
                          WDC_ADMIN_TERMINAL_REBOOT_HANDOFF);
                    CHECK(harness.metadata.active_slot ==
                          WDC_BUNDLE_SLOT_B);
                    CHECK(harness.metadata.last_good_slot ==
                          WDC_BUNDLE_SLOT_A);
                    CHECK(harness.metadata.slot_b.state ==
                          WDC_SLOT_TRIAL);
                    CHECK(wdc_admin_mode(&harness.core) ==
                          WDC_ADMIN_MODE_REBOOT_HANDOFF);
                } else {
                    CHECK(execute_command(
                              &harness,
                              WDC_ADMIN_COMMAND_ACTIVATE_TRIAL,
                              NULL, 0u, now_ms, &terminal) != WDC_OK);
                    CHECK(terminal.result ==
                          WDC_ADMIN_TERMINAL_FAILED);
                    hp44_check_confirmed_a(
                        &harness, WDC_ADMIN_MODE_NORMAL);
                }
                CHECK(wdc_ota_host_fault_trigger_count() == 1u);
                wdc_ota_host_power_cycle();
                hp44_record(HP44_CATEGORY_JOURNAL, before);
            }
        }
    }
}

static void hp44_fill_lane(WdcControlKernel *kernel,
                           WdcControlSource source,
                           uint32_t count,
                           bool complete_without_take)
{
    uint32_t tickets[WDC_CONTROL_QUEUE_CAPACITY_MAX];
    WdcControlCompletion rejection;
    WdcControlWorkRequest request;
    WdcControlWorkItem work;
    uint32_t index;
    memset(tickets, 0, sizeof(tickets));
    for (index = 0u; index < count; ++index) {
        memset(&request, 0, sizeof(request));
        memset(&rejection, 0, sizeof(rejection));
        request.source = source;
        request.operation_id = 0x4400u + index;
        request.correlation_id = index + 1u;
        CHECK(wdc_control_submit(kernel, &request, &tickets[index],
                                 &rejection) == WDC_OK);
    }
    if (!complete_without_take) {
        return;
    }
    for (index = 0u; index < count; ++index) {
        CHECK(wdc_control_next(kernel, &work) == WDC_OK);
        CHECK(wdc_control_complete(kernel, work.ticket,
                                   WDC_CONTROL_TERMINAL_SUCCEEDED,
                                   WDC_OK) == WDC_OK);
    }
}

static void hp44_run_capacity_matrix(void)
{
    uint32_t variant;
    for (variant = 0u; variant < HP44_CAPACITY_CASES; ++variant) {
        Harness harness;
        WdcAdminRequest request;
        WdcAdminPreacceptResult rejection;
        WdcAdminTerminalRecord terminal;
        WdcControlIsrCapture capture;
        uint64_t sequence;
        uint32_t before = s_failures;
        uint32_t index;
        init_harness(&harness, WDC_ADMIN_MODE_NORMAL, true);
        CHECK(harness.kernel.profile->reserve.administration_bytes ==
              WDC_ADMIN_FIXED_STORAGE_BUDGET_BYTES);
        CHECK(harness.kernel.profile->reserve.recovery_bytes ==
              WDC_ADMIN_RECOVERY_RESERVE_BYTES);
        CHECK(harness.kernel.profile->policies[3].queue_capacity == 8u);
        CHECK(harness.kernel.profile->policies[4].queue_capacity == 8u);
        switch (variant) {
        case 0u:
            hp44_fill_lane(&harness.kernel,
                           WDC_CONTROL_SOURCE_APPLICATION, 16u, false);
            CHECK(hp44_execute_status(&harness, 200u,
                                      &terminal) == WDC_OK);
            CHECK(wdc_control_lane_outstanding(
                      &harness.kernel,
                      WDC_CONTROL_PRIORITY_APPLICATION) == 16u);
            break;
        case 1u:
            hp44_fill_lane(&harness.kernel,
                           WDC_CONTROL_SOURCE_APPLICATION, 16u, true);
            CHECK(hp44_execute_status(&harness, 200u,
                                      &terminal) == WDC_OK);
            break;
        case 2u:
            hp44_fill_lane(&harness.kernel,
                           WDC_CONTROL_SOURCE_NETWORK_MAINTENANCE,
                           8u, false);
            CHECK(hp44_execute_status(&harness, 200u,
                                      &terminal) == WDC_OK);
            break;
        case 3u:
            hp44_fill_lane(&harness.kernel,
                           WDC_CONTROL_SOURCE_CAPABILITY, 16u, false);
            CHECK(execute_command(&harness,
                                  WDC_ADMIN_COMMAND_ENTER_RECOVERY,
                                  NULL, 0u, 200u, &terminal) == WDC_OK);
            CHECK(wdc_admin_mode(&harness.core) ==
                  WDC_ADMIN_MODE_RECOVERY);
            break;
        case 4u:
            hp44_fill_lane(&harness.kernel,
                           WDC_CONTROL_SOURCE_ADMINISTRATION,
                           8u, false);
            request = make_request(&harness,
                                   WDC_ADMIN_COMMAND_STATUS,
                                   0u, 200u);
            sequence = harness.core.next_command_sequence;
            CHECK(hp44_submit(&harness, &request, NULL, 200u,
                              &rejection) == WDC_ERR_BUSY);
            CHECK(rejection.rejection == WDC_ADMIN_REJECTION_BUSY);
            CHECK(harness.core.next_command_sequence == sequence);
            hp44_check_confirmed_a(&harness, WDC_ADMIN_MODE_NORMAL);
            break;
        case 5u:
            hp44_fill_lane(&harness.kernel,
                           WDC_CONTROL_SOURCE_RECOVERY, 8u, false);
            request = make_request(&harness,
                                   WDC_ADMIN_COMMAND_ENTER_RECOVERY,
                                   0u, 200u);
            sequence = harness.core.next_command_sequence;
            CHECK(hp44_submit(&harness, &request, NULL, 200u,
                              &rejection) == WDC_ERR_BUSY);
            CHECK(harness.core.next_command_sequence == sequence);
            CHECK(wdc_control_recovery_required(&harness.kernel) == 1u);
            hp44_check_confirmed_a(&harness, WDC_ADMIN_MODE_NORMAL);
            break;
        case 6u:
            hp44_fill_lane(&harness.kernel,
                           WDC_CONTROL_SOURCE_ADMINISTRATION,
                           8u, true);
            request = make_request(&harness,
                                   WDC_ADMIN_COMMAND_STATUS,
                                   0u, 200u);
            sequence = harness.core.next_command_sequence;
            CHECK(hp44_submit(&harness, &request, NULL, 200u,
                              &rejection) == WDC_ERR_BUSY);
            CHECK(harness.core.next_command_sequence == sequence);
            break;
        case 7u:
            hp44_fill_lane(&harness.kernel,
                           WDC_CONTROL_SOURCE_RECOVERY, 8u, true);
            request = make_request(&harness,
                                   WDC_ADMIN_COMMAND_ENTER_RECOVERY,
                                   0u, 200u);
            sequence = harness.core.next_command_sequence;
            CHECK(hp44_submit(&harness, &request, NULL, 200u,
                              &rejection) == WDC_ERR_BUSY);
            CHECK(harness.core.next_command_sequence == sequence);
            CHECK(wdc_control_recovery_required(&harness.kernel) == 1u);
            break;
        case 8u:
            hp44_fill_lane(&harness.kernel,
                           WDC_CONTROL_SOURCE_APPLICATION, 16u, false);
            hp44_fill_lane(&harness.kernel,
                           WDC_CONTROL_SOURCE_CAPABILITY, 16u, false);
            hp44_fill_lane(&harness.kernel,
                           WDC_CONTROL_SOURCE_NETWORK_MAINTENANCE,
                           8u, false);
            CHECK(execute_command(&harness,
                                  WDC_ADMIN_COMMAND_ENTER_RECOVERY,
                                  NULL, 0u, 200u, &terminal) == WDC_OK);
            CHECK(wdc_admin_mode(&harness.core) ==
                  WDC_ADMIN_MODE_RECOVERY);
            break;
        case 9u:
            hp44_fill_lane(&harness.kernel,
                           WDC_CONTROL_SOURCE_APPLICATION, 16u, false);
            memset(&capture, 0, sizeof(capture));
            capture.source_id = 1u;
            capture.signal = 1u;
            for (index = 0u; index < WDC_CONTROL_ISR_CAPACITY; ++index) {
                capture.sequence = index + 1u;
                CHECK(wdc_control_capture_isr(&harness.kernel,
                                               &capture) == WDC_OK);
            }
            capture.sequence += 1u;
            CHECK(wdc_control_capture_isr(&harness.kernel,
                                           &capture) == WDC_ERR_BUSY);
            CHECK(wdc_control_isr_overflows(&harness.kernel) == 1u);
            CHECK(execute_command(&harness,
                                  WDC_ADMIN_COMMAND_ENTER_RECOVERY,
                                  NULL, 0u, 200u, &terminal) == WDC_OK);
            CHECK(wdc_admin_mode(&harness.core) ==
                  WDC_ADMIN_MODE_RECOVERY);
            break;
        default:
            CHECK(false);
            break;
        }
        hp44_record(HP44_CATEGORY_CAPACITY, before);
    }
}

static void hp44_execute_status_without_take(Harness *harness,
                                             uint64_t now_ms,
                                             uint32_t *out_ticket)
{
    WdcAdminRequest request = make_request(
        harness, WDC_ADMIN_COMMAND_STATUS, 0u, now_ms);
    WdcAdminPreacceptResult rejection;
    WdcControlWorkItem work;
    WdcAdminAcceptedCommand accepted;
    CHECK(hp44_submit(harness, &request, NULL, now_ms,
                      &rejection) == WDC_OK);
    CHECK(wdc_control_next(&harness->kernel, &work) == WDC_OK);
    CHECK(wdc_admin_begin_command(&harness->core, &work,
                                  now_ms + 1u, &accepted) == WDC_OK);
    if (out_ticket != NULL) {
        *out_ticket = accepted.control_ticket;
    }
    CHECK(wdc_admin_recovery_execute(&harness->recovery, &accepted,
                                     now_ms + 1u) == WDC_OK);
}

static bool hp44_bytes_contain(const uint8_t *bytes,
                               uint32_t bytes_len,
                               const uint8_t *needle,
                               uint32_t needle_len)
{
    uint32_t offset;
    if (bytes == NULL || needle == NULL || needle_len == 0u ||
        needle_len > bytes_len) {
        return false;
    }
    for (offset = 0u; offset <= bytes_len - needle_len; ++offset) {
        if (memcmp(bytes + offset, needle, needle_len) == 0) {
            return true;
        }
    }
    return false;
}

static void hp44_run_terminal_audit_matrix(void)
{
    uint32_t variant;
    for (variant = 0u;
         variant < HP44_TERMINAL_AUDIT_CASES;
         ++variant) {
        Harness harness;
        WdcAdminRequest request;
        WdcAdminPreacceptResult rejection;
        WdcAdminTerminalRecord terminal;
        WdcAdminTerminalRecord retained;
        WdcAdminTerminalMetadata metadata;
        WdcAdminRecoveryStatus response;
        WdcAdminAuditRecord audit;
        WdcControlCompletion completion;
        Hp44AuthoritySnapshot snapshot;
        uint32_t response_bytes = 0u;
        uint32_t ticket = 0u;
        uint32_t before = s_failures;
        uint32_t index;
        init_harness(&harness, WDC_ADMIN_MODE_NORMAL, true);
        memset(&metadata, 0, sizeof(metadata));
        metadata.final_state = WDC_ADMIN_MODE_NORMAL;
        metadata.slot = WDC_ADMIN_SLOT_NONE;
        switch (variant) {
        case 0u:
            hp44_execute_status_without_take(&harness, 200u,
                                             &ticket);
            retained = harness.core.terminal;
            CHECK(wdc_admin_complete(&harness.core,
                                     WDC_ADMIN_TERMINAL_FAILED,
                                     WDC_ERR_IO, &metadata,
                                     202u) == WDC_ERR_INVALID_STATE);
            CHECK(memcmp(&retained, &harness.core.terminal,
                         sizeof(retained)) == 0);
            CHECK(wdc_admin_take_terminal(
                      &harness.core, &terminal,
                      (uint8_t *)&response, sizeof(response),
                      &response_bytes) == WDC_OK);
            CHECK(terminal.result == WDC_ADMIN_TERMINAL_SUCCEEDED);
            break;
        case 1u:
            request = make_request(&harness,
                                   WDC_ADMIN_COMMAND_STATUS,
                                   0u, 200u);
            CHECK(hp44_submit(&harness, &request, NULL, 200u,
                              &rejection) == WDC_OK);
            {
                WdcControlWorkItem work;
                WdcAdminAcceptedCommand accepted;
                uint8_t first[4] = { 1u, 2u, 3u, 4u };
                uint8_t second[4] = { 5u, 6u, 7u, 8u };
                CHECK(wdc_control_next(&harness.kernel, &work) == WDC_OK);
                CHECK(wdc_admin_begin_command(&harness.core, &work,
                                              201u, &accepted) == WDC_OK);
                CHECK(wdc_admin_write_response(&harness.core, first,
                                               sizeof(first)) == WDC_OK);
                CHECK(wdc_admin_write_response(&harness.core, second,
                                               sizeof(second)) ==
                      WDC_ERR_INVALID_STATE);
                CHECK(wdc_admin_complete(&harness.core,
                                         WDC_ADMIN_TERMINAL_SUCCEEDED,
                                         WDC_OK, &metadata,
                                         201u) == WDC_OK);
                response_bytes = 0u;
                CHECK(wdc_admin_take_terminal(
                          &harness.core, &terminal,
                          (uint8_t *)&response, sizeof(response),
                          &response_bytes) == WDC_OK);
                CHECK(response_bytes == sizeof(first));
                CHECK(memcmp(&response, first, sizeof(first)) == 0);
            }
            break;
        case 2u:
            hp44_execute_status_without_take(&harness, 200u,
                                             &ticket);
            CHECK(wdc_admin_take_terminal(
                      &harness.core, &terminal,
                      (uint8_t *)&response, sizeof(response),
                      &response_bytes) == WDC_OK);
            CHECK(wdc_admin_take_terminal(
                      &harness.core, &terminal,
                      (uint8_t *)&response, sizeof(response),
                      &response_bytes) == WDC_ERR_NOT_AVAILABLE);
            break;
        case 3u:
            hp44_execute_status_without_take(&harness, 200u,
                                             &ticket);
            CHECK(wdc_admin_take_terminal(
                      &harness.core, &terminal,
                      (uint8_t *)&response, 1u,
                      &response_bytes) == WDC_ERR_RESPONSE_TOO_SMALL);
            CHECK(wdc_admin_command_lifecycle(&harness.core) ==
                  WDC_ADMIN_LIFECYCLE_TERMINAL);
            CHECK(wdc_admin_take_terminal(
                      &harness.core, &terminal,
                      (uint8_t *)&response, sizeof(response),
                      &response_bytes) == WDC_OK);
            break;
        case 4u:
            snapshot = hp44_snapshot(&harness);
            for (index = 0u; index < 64u; ++index) {
                request = make_request(&harness,
                                       WDC_ADMIN_COMMAND_STATUS,
                                       0u, 200u + index);
                request.session_nonce ^= 1u;
                CHECK(hp44_submit(&harness, &request, NULL,
                                  200u + index, &rejection) ==
                      WDC_ERR_CAPABILITY_DENIED);
            }
            CHECK(wdc_admin_audit_pending(&harness.core) ==
                  WDC_ADMIN_AUDIT_RING_RECORDS);
            CHECK(wdc_admin_audit_losses(&harness.core) == 34u);
            hp44_check_snapshot(&harness, &snapshot);
            break;
        case 5u:
            while (wdc_admin_take_audit(&harness.core, &audit) ==
                   WDC_OK) {
                CHECK(audit.struct_size == WDC_ADMIN_AUDIT_RECORD_BYTES);
                CHECK(!hp44_bytes_contain(
                    (const uint8_t *)&audit, sizeof(audit),
                    (const uint8_t *)"proof", 5u));
                for (index = 0u; index < sizeof(audit.reserved); ++index) {
                    CHECK(audit.reserved[index] == 0u);
                }
            }
            break;
        case 6u:
            request = make_request(&harness,
                                   WDC_ADMIN_COMMAND_STATUS,
                                   0u, 200u);
            request.session_nonce ^= 1u;
            snapshot = hp44_snapshot(&harness);
            CHECK(hp44_submit(&harness, &request, NULL, 200u,
                              &rejection) == WDC_ERR_CAPABILITY_DENIED);
            hp44_check_snapshot(&harness, &snapshot);
            CHECK(!harness.core.terminal_ready);
            break;
        case 7u:
            hp44_execute_status_without_take(&harness, 200u,
                                             &ticket);
            CHECK(wdc_admin_take_terminal(
                      &harness.core, &terminal,
                      (uint8_t *)&response, sizeof(response),
                      &response_bytes) == WDC_OK);
            memset(&completion, 0, sizeof(completion));
            CHECK(wdc_control_take_completion(&harness.kernel, ticket,
                                              &completion) ==
                  WDC_ERR_NOT_AVAILABLE);
            CHECK(wdc_control_lane_outstanding(
                      &harness.kernel,
                      WDC_CONTROL_PRIORITY_ADMINISTRATION) == 0u);
            break;
        default:
            CHECK(false);
            break;
        }
        hp44_record(HP44_CATEGORY_TERMINAL_AUDIT, before);
    }
}

static void hp44_run_recovery_matrix(void)
{
    Harness repeated;
    WdcAdminTerminalRecord terminal;
    WdcBundleMetadataV1 before_metadata;
    WdcOtaHostFaultPlan fault;
    uint8_t corrupted[MAX_ARTIFACT_BYTES];
    uint32_t index;
    uint64_t now_ms;
    init_harness(&repeated, WDC_ADMIN_MODE_RECOVERY, false);
    for (index = 0u; index < 32u; ++index) {
        uint32_t before = s_failures;
        CHECK(execute_command(&repeated, WDC_ADMIN_COMMAND_REBOOT,
                              NULL, 0u, 200u + index * 2u,
                              &terminal) == WDC_ERR_INVALID_STATE);
        CHECK(terminal.result == WDC_ADMIN_TERMINAL_FAILED);
        CHECK(wdc_admin_mode(&repeated.core) ==
              WDC_ADMIN_MODE_RECOVERY);
        CHECK(repeated.metadata.active_slot == WDC_BUNDLE_SLOT_NONE);
        CHECK(repeated.metadata.last_good_slot == WDC_BUNDLE_SLOT_NONE);
        hp44_record(HP44_CATEGORY_RECOVERY, before);
    }
    for (index = 0u; index < 8u; ++index) {
        Harness harness;
        WdcAdminRequest request;
        uint32_t response_bytes = 0u;
        uint32_t before = s_failures;
        now_ms = 210u;
        memset(&fault, 0, sizeof(fault));
        switch (index) {
        case 0u:
            init_harness(&harness, WDC_ADMIN_MODE_RECOVERY, false);
            CHECK(execute_command(&harness,
                                  WDC_ADMIN_COMMAND_BEGIN_UPDATE,
                                  NULL, 0u, 200u, &terminal) == WDC_OK);
            request = make_request(&harness,
                                   WDC_ADMIN_COMMAND_WRITE_CHUNK,
                                   1u, 210u);
            request.artifact_sha256[0] ^= 1u;
            CHECK(execute_request(&harness, &request, s_artifact,
                                  210u, &terminal, NULL, 0u,
                                  &response_bytes) != WDC_OK);
            CHECK(wdc_admin_mode(&harness.core) ==
                  WDC_ADMIN_MODE_RECOVERY);
            break;
        case 1u:
            init_harness(&harness, WDC_ADMIN_MODE_RECOVERY, false);
            harness.verifier.allow = false;
            CHECK(execute_command(&harness,
                                  WDC_ADMIN_COMMAND_BEGIN_UPDATE,
                                  NULL, 0u, 200u, &terminal) == WDC_OK);
            CHECK(hp44_stream_prefix(&harness, s_artifact_bytes,
                                     &now_ms, &terminal) == WDC_OK);
            CHECK(execute_command(&harness,
                                  WDC_ADMIN_COMMAND_FINISH_UPDATE,
                                  NULL, 0u, now_ms, &terminal) != WDC_OK);
            CHECK(wdc_admin_mode(&harness.core) ==
                  WDC_ADMIN_MODE_RECOVERY);
            break;
        case 2u:
            now_ms = 200u;
            CHECK(hp44_prepare_verified(&harness,
                                        WDC_ADMIN_MODE_RECOVERY,
                                        &now_ms, &terminal) == WDC_OK);
            fault.operation = WDC_OTA_HOST_FAULT_METADATA_BODY_WRITE;
            fault.trigger_index = 1u;
            fault.tear_after_bytes = 0u;
            CHECK(wdc_ota_host_fault_arm(&fault) == WDC_OK);
            CHECK(execute_command(&harness,
                                  WDC_ADMIN_COMMAND_ACTIVATE_TRIAL,
                                  NULL, 0u, now_ms,
                                  &terminal) != WDC_OK);
            CHECK(wdc_admin_mode(&harness.core) ==
                  WDC_ADMIN_MODE_RECOVERY);
            CHECK(harness.metadata.active_slot ==
                  WDC_BUNDLE_SLOT_NONE);
            wdc_ota_host_power_cycle();
            break;
        case 3u:
            init_harness(&harness, WDC_ADMIN_MODE_NORMAL, true);
            CHECK(execute_command(&harness,
                                  WDC_ADMIN_COMMAND_ENTER_RECOVERY,
                                  NULL, 0u, 200u, &terminal) == WDC_OK);
            harness.lifecycle.heap_status = WDC_ERR_IO;
            CHECK(execute_command(&harness, WDC_ADMIN_COMMAND_REBOOT,
                                  NULL, 0u, 210u,
                                  &terminal) == WDC_ERR_IO);
            CHECK(wdc_admin_mode(&harness.core) ==
                  WDC_ADMIN_MODE_RECOVERY);
            break;
        case 4u:
            init_harness(&harness, WDC_ADMIN_MODE_NORMAL, true);
            CHECK(execute_command(&harness,
                                  WDC_ADMIN_COMMAND_ENTER_RECOVERY,
                                  NULL, 0u, 200u, &terminal) == WDC_OK);
            memcpy(corrupted, s_artifact, s_artifact_bytes);
            corrupted[s_artifact_bytes - 1u] ^= 1u;
            CHECK(wdc_ota_host_set_slot_image(
                      WDC_BUNDLE_SLOT_A, corrupted,
                      s_artifact_bytes) == WDC_OK);
            CHECK(execute_command(&harness, WDC_ADMIN_COMMAND_REBOOT,
                                  NULL, 0u, 210u,
                                  &terminal) != WDC_OK);
            CHECK(wdc_admin_mode(&harness.core) ==
                  WDC_ADMIN_MODE_RECOVERY);
            break;
        case 5u:
            init_harness(&harness, WDC_ADMIN_MODE_NORMAL, true);
            before_metadata = harness.metadata;
            CHECK(execute_command(&harness,
                                  WDC_ADMIN_COMMAND_ENTER_RECOVERY,
                                  NULL, 0u, 200u, &terminal) == WDC_OK);
            CHECK(execute_command(&harness, WDC_ADMIN_COMMAND_REBOOT,
                                  NULL, 0u, 210u,
                                  &terminal) == WDC_OK);
            CHECK(terminal.result ==
                  WDC_ADMIN_TERMINAL_REBOOT_HANDOFF);
            CHECK(memcmp(&before_metadata, &harness.metadata,
                         sizeof(before_metadata)) == 0);
            break;
        case 6u:
            now_ms = 200u;
            CHECK(hp44_prepare_verified(&harness,
                                        WDC_ADMIN_MODE_RECOVERY,
                                        &now_ms, &terminal) == WDC_OK);
            CHECK(execute_command(&harness, WDC_ADMIN_COMMAND_ABORT,
                                  NULL, 0u, now_ms,
                                  &terminal) == WDC_OK);
            CHECK(wdc_admin_mode(&harness.core) ==
                  WDC_ADMIN_MODE_RECOVERY);
            CHECK(harness.metadata.active_slot ==
                  WDC_BUNDLE_SLOT_NONE);
            CHECK(harness.metadata.slot_a.state == WDC_SLOT_VERIFIED);
            break;
        case 7u:
            init_harness(&harness, WDC_ADMIN_MODE_RECOVERY, false);
            CHECK(execute_command(&harness,
                                  WDC_ADMIN_COMMAND_BEGIN_UPDATE,
                                  NULL, 0u, 200u, &terminal) == WDC_OK);
            CHECK(execute_command(&harness,
                                  WDC_ADMIN_COMMAND_WRITE_CHUNK,
                                  s_artifact, 32u, 210u,
                                  &terminal) == WDC_OK);
            CHECK(wdc_admin_recovery_poll(
                      &harness.recovery, 30211u) == WDC_ERR_TIMEOUT);
            CHECK(wdc_admin_mode(&harness.core) ==
                  WDC_ADMIN_MODE_RECOVERY);
            CHECK(harness.metadata.active_slot ==
                  WDC_BUNDLE_SLOT_NONE);
            break;
        default:
            CHECK(false);
            break;
        }
        hp44_record(HP44_CATEGORY_RECOVERY, before);
    }
}

int main(int argc, char **argv)
{
    uint32_t index;
    uint32_t observed;
    uint32_t passed;
    bool exact;
    if (argc != 2 || !load_bundle(argv[1])) {
        (void)fprintf(stderr, "usage: hp4_4-smoke BUNDLE\n");
        return 2;
    }
    build_artifact();
    CHECK(s_artifact_bytes == 2361u);
    hp44_run_preaccept_matrix();
    hp44_run_authorization_replay_matrix();
    hp44_run_quiesce_matrix();
    hp44_run_resource_matrix();
    hp44_run_safe_stream_cut_matrix();
    hp44_run_stream_transaction_matrix();
    hp44_run_verification_matrix();
    hp44_run_journal_matrix();
    hp44_run_capacity_matrix();
    hp44_run_terminal_audit_matrix();
    hp44_run_recovery_matrix();
    observed = hp44_total_observed();
    passed = hp44_total_passed();
    exact = observed == HP44_TOTAL_CASES && passed == HP44_TOTAL_CASES &&
            s_failures == 0u;
    for (index = 0u; index < HP44_CATEGORY_COUNT; ++index) {
        if (s_hp44_categories[index].observed !=
                s_hp44_categories[index].expected ||
            s_hp44_categories[index].passed !=
                s_hp44_categories[index].expected) {
            exact = false;
        }
    }
    (void)printf(
        "{\"schema\":\"pulse.esp32.hp4_4-admin-adversarial-smoke.v1\","
        "\"status\":\"%s\",\"case_count\":%" PRIu32 ","
        "\"failures\":%" PRIu32 ","
        "\"inherited_native_case_count\":%u,"
        "\"aggregate_native_case_count\":%" PRIu32 ","
        "\"safe_stream_cut_cases\":%u,"
        "\"journal_interruption_cases\":%u,"
        "\"sequence_wrap_prevented\":true,"
        "\"last_confirmed_preserved\":true,"
        "\"ambiguous_boot_authority\":false,"
        "\"factory_host_written\":false,"
        "\"application_code_launched\":false,"
        "\"physical_execution\":false,\"categories\":[",
        exact ? "PASS" : "FAIL", observed, s_failures,
        HP44_INHERITED_NATIVE_CASES,
        observed + HP44_INHERITED_NATIVE_CASES,
        HP44_SAFE_STREAM_CASES, HP44_JOURNAL_CASES);
    for (index = 0u; index < HP44_CATEGORY_COUNT; ++index) {
        (void)printf(
            "%s{\"name\":\"%s\",\"expected\":%" PRIu32 ","
            "\"observed\":%" PRIu32 ",\"passed\":%" PRIu32 "}",
            index == 0u ? "" : ",", s_hp44_categories[index].name,
            s_hp44_categories[index].expected,
            s_hp44_categories[index].observed,
            s_hp44_categories[index].passed);
    }
    (void)printf("]}\n");
    return exact ? 0 : 1;
}
