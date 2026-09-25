#include <inttypes.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "wdc_admin_update.h"
#include "wdc_ota.h"
#include "wdc_profile.h"

#define HP42_CASE_COUNT 15u
#define MAX_BUNDLE_BYTES 8192u
#define MAX_ARTIFACT_BYTES (WDC_APP_ARTIFACT_HEADER_BYTES + MAX_BUNDLE_BYTES)

typedef struct CaseResult {
    const char *name;
    uint32_t passed;
} CaseResult;

typedef struct FakeAuthorizer {
    uint64_t next_epoch;
} FakeAuthorizer;

typedef struct FakeVerifier {
    uint32_t calls;
    bool allow;
} FakeVerifier;

typedef struct FakeLifecycle {
    int32_t quiesce_status;
    int32_t heap_status;
    uint32_t quiesce_calls;
    uint32_t heap_calls;
    bool malformed_evidence;
    WdcControlHeapSnapshot heap;
} FakeLifecycle;

typedef struct Harness {
    WdcControlKernel kernel;
    WdcAdminCore core;
    WdcAdminUpdateEngine update;
    WdcBundleMetadataV1 metadata;
    WdcHostFingerprintV1 fingerprint;
    WdcBundleVerifyPolicy bundle_policy;
    WdcAppSlotVerifyPolicy slot_policy;
    WdcActivationPolicy activation_policy;
    FakeAuthorizer authorizer;
    FakeVerifier verifier;
    FakeLifecycle lifecycle;
    uint8_t binding[32];
    uint8_t working[WDC_ADMIN_UPDATE_WORKING_BYTES];
    uint8_t request_hash[32];
    uint64_t next_request_id;
} Harness;

static uint8_t s_bundle[MAX_BUNDLE_BYTES];
static uint8_t s_artifact[MAX_ARTIFACT_BYTES];
static uint32_t s_bundle_bytes;
static uint32_t s_artifact_bytes;
static uint8_t s_artifact_sha256[32];
static CaseResult s_cases[HP42_CASE_COUNT];
static uint32_t s_case_count;
static uint32_t s_failures;

#define CHECK(condition)                                                       \
    do {                                                                       \
        if (!(condition)) {                                                    \
            s_failures += 1u;                                                  \
            (void)fprintf(stderr, "CHECK failed at %s:%d: %s\n",           \
                          __FILE__, __LINE__, #condition);                     \
        }                                                                      \
    } while (0)

static void record_case(const char *name, uint32_t before)
{
    CHECK(s_case_count < HP42_CASE_COUNT);
    if (s_case_count < HP42_CASE_COUNT) {
        s_cases[s_case_count].name = name;
        s_cases[s_case_count].passed = before == s_failures ? 1u : 0u;
        s_case_count += 1u;
    }
}

static int load_bundle(const char *path)
{
    FILE *handle = fopen(path, "rb");
    long size;
    if (handle == NULL || fseek(handle, 0L, SEEK_END) != 0) {
        if (handle != NULL) {
            (void)fclose(handle);
        }
        return 0;
    }
    size = ftell(handle);
    if (size <= 0L || (unsigned long)size > sizeof(s_bundle) ||
        fseek(handle, 0L, SEEK_SET) != 0 ||
        fread(s_bundle, 1u, (size_t)size, handle) != (size_t)size) {
        (void)fclose(handle);
        return 0;
    }
    (void)fclose(handle);
    s_bundle_bytes = (uint32_t)size;
    return 1;
}

static void build_artifact(void)
{
    WdcPulseAppArtifactHeaderV1 header;
    static const char application_id[] = "com.example.relay-controller";
    memset(&header, 0, sizeof(header));
    header.magic = WDC_APP_ARTIFACT_MAGIC;
    header.version = WDC_APP_ARTIFACT_VERSION;
    header.header_bytes = WDC_APP_ARTIFACT_HEADER_BYTES;
    header.total_bytes = WDC_APP_ARTIFACT_HEADER_BYTES + s_bundle_bytes;
    header.bundle_bytes = s_bundle_bytes;
    header.application_version = 8u;
    header.security_counter = 8u;
    header.requirements.allowed_target_mask = WDC_HOST_TARGET_MASK_ESP32C6;
    header.requirements.host_abi_major = 1u;
    header.requirements.host_abi_min_minor = 0u;
    header.requirements.host_abi_max_minor = 0u;
    header.requirements.required_capability_mask =
        WDC_HOST_CAP_APPLICATION_SLOTS | WDC_HOST_CAP_WASM_APPLICATION |
        WDC_HOST_CAP_EVENT_EFFECT;
    header.requirements.placement = WDC_HOST_PLACEMENT_PORTABLE;
    header.requirements.guest_linear_memory_bytes = 49152u;
    header.requirements.runtime_stack_bytes = 16384u;
    header.requirements.network_working_bytes = 8192u;
    header.requirements.capability_working_bytes = 4096u;
    header.requirements.transition_scratch_bytes = 8192u;
    header.requirements.largest_application_allocation_bytes = 49152u;
    wdc_sha256(s_bundle, s_bundle_bytes, header.bundle_sha256);
    wdc_sha256((const uint8_t *)application_id,
               (uint32_t)(sizeof(application_id) - 1u),
               header.application_id_sha256);
    CHECK(wdc_app_artifact_header_seal(&header) == WDC_OK);
    memcpy(s_artifact, &header, sizeof(header));
    memcpy(s_artifact + sizeof(header), s_bundle, s_bundle_bytes);
    s_artifact_bytes = (uint32_t)sizeof(header) + s_bundle_bytes;
    wdc_sha256(s_artifact, s_artifact_bytes, s_artifact_sha256);
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
    out_entry->privilege_mask = WDC_ADMIN_PRIVILEGE_STATUS |
                                WDC_ADMIN_PRIVILEGE_UPDATE;
    out_entry->authorization_epoch = authorizer->next_epoch++;
    out_entry->issued_monotonic_ms = challenge->issued_monotonic_ms;
    out_entry->expires_monotonic_ms =
        challenge->issued_monotonic_ms + 600000u;
    out_entry->session_nonce = challenge->start.challenge_id ^
                               out_entry->authorization_epoch;
    if (out_entry->session_nonce == 0u) {
        out_entry->session_nonce = 1u;
    }
    for (index = 0u; index < sizeof(out_entry->principal_sha256); ++index) {
        out_entry->principal_sha256[index] = (uint8_t)(index + 1u);
    }
    memcpy(out_entry->channel_binding_sha256,
           challenge->start.channel_binding_sha256,
           sizeof(out_entry->channel_binding_sha256));
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
    CHECK(candidate->slot == WDC_BUNDLE_SLOT_B);
    CHECK(candidate->stored_bytes == s_artifact_bytes);
    CHECK(memcmp(candidate->artifact_sha256, s_artifact_sha256, 32u) == 0);
    return out_verification->status;
}

static int32_t fake_quiesce(
    void *context,
    uint64_t deadline_ms,
    WdcAdminUpdateQuiesceEvidence *out_evidence)
{
    FakeLifecycle *lifecycle = (FakeLifecycle *)context;
    lifecycle->quiesce_calls += 1u;
    if (lifecycle->quiesce_status != WDC_OK) {
        return lifecycle->quiesce_status;
    }
    memset(out_evidence, 0, sizeof(*out_evidence));
    out_evidence->guest_quiesced = 1u;
    out_evidence->native_refinements_quiesced = 1u;
    out_evidence->guest_unloaded = 1u;
    out_evidence->native_refinements_unloaded = 1u;
    out_evidence->completed_monotonic_ms = deadline_ms - 1u;
    if (lifecycle->malformed_evidence) {
        out_evidence->guest_unloaded = 0u;
    }
    return WDC_OK;
}

static int32_t fake_heap(void *context, WdcControlHeapSnapshot *out_heap)
{
    FakeLifecycle *lifecycle = (FakeLifecycle *)context;
    lifecycle->heap_calls += 1u;
    if (lifecycle->heap_status != WDC_OK) {
        return lifecycle->heap_status;
    }
    *out_heap = lifecycle->heap;
    return WDC_OK;
}

static void seed_confirmed_a(WdcBundleMetadataV1 *metadata)
{
    uint32_t index;
    wdc_bundle_metadata_init(metadata);
    metadata->active_slot = WDC_BUNDLE_SLOT_A;
    metadata->last_good_slot = WDC_BUNDLE_SLOT_A;
    metadata->slot_a.state = WDC_SLOT_CONFIRMED;
    metadata->slot_a.bundle_version = 7u;
    metadata->slot_a.security_counter = 7u;
    metadata->slot_a.artifact_format_version = WDC_APP_ARTIFACT_VERSION;
    metadata->slot_a.artifact_bytes = 2048u;
    for (index = 0u; index < 32u; ++index) {
        metadata->slot_a.payload_sha256[index] = (uint8_t)(0x20u + index);
        metadata->slot_a.artifact_sha256[index] = (uint8_t)(0x60u + index);
    }
    metadata->metadata_generation = 1u;
    CHECK(wdc_bundle_metadata_seal(metadata) == WDC_OK);
    CHECK(wdc_ota_host_set_metadata(metadata) == WDC_OK);
}

static void authorize(Harness *harness)
{
    WdcAdminAuthorizationStart start;
    WdcAdminPreacceptResult rejection;
    uint64_t deadline = 0u;
    memset(&start, 0, sizeof(start));
    start.transport_kind = WDC_ADMIN_TRANSPORT_SERIAL_PHYSICAL_V1;
    start.authorization_method = WDC_ADMIN_AUTH_METHOD_LOCAL_PHYSICAL;
    start.attended_physical_entry = 1u;
    start.challenge_id = 0x4200u;
    memcpy(start.channel_binding_sha256, harness->binding,
           sizeof(start.channel_binding_sha256));
    CHECK(wdc_admin_authorization_begin(&harness->core, &start, 100u,
                                         &deadline, &rejection) == WDC_OK);
    CHECK(wdc_admin_authorization_finish(&harness->core,
                                          (const uint8_t *)"proof", 5u,
                                          101u, &rejection) == WDC_OK);
}

static void init_harness(Harness *harness, uint64_t security_floor)
{
    WdcAdminCoreConfig core_config;
    WdcAdminUpdateConfig update_config;
    const WdcHostFingerprintV1 *fingerprint;
    uint32_t index;
    memset(harness, 0, sizeof(*harness));
    wdc_ota_host_clear_slots();
    wdc_ota_host_clear_metadata();
    seed_confirmed_a(&harness->metadata);
    for (index = 0u; index < sizeof(harness->binding); ++index) {
        harness->binding[index] = (uint8_t)(0xa0u + (index % 29u));
    }
    harness->authorizer.next_epoch = 1u;
    harness->verifier.allow = true;
    harness->lifecycle.quiesce_status = WDC_OK;
    harness->lifecycle.heap_status = WDC_OK;
    harness->lifecycle.heap.internal_free_bytes = 196608u;
    harness->lifecycle.heap.internal_largest_block_bytes = 131072u;
    harness->next_request_id = 1u;
    memcpy(harness->request_hash, s_artifact_sha256,
           sizeof(harness->request_hash));
    CHECK(wdc_control_kernel_init(&harness->kernel,
                                  wdc_control_profile_c6_minimum()) == WDC_OK);
    memset(&core_config, 0, sizeof(core_config));
    core_config.control_kernel = &harness->kernel;
    core_config.authorizer.authorize = fake_authorize;
    core_config.authorizer.context = &harness->authorizer;
    core_config.artifact_verifier.verify = fake_verify;
    core_config.artifact_verifier.context = &harness->verifier;
    core_config.initial_mode = WDC_ADMIN_MODE_NORMAL;
    core_config.enabled_commands_mask = WDC_ADMIN_HP42_COMMAND_MASK;
    memcpy(core_config.boot_channel_binding_sha256, harness->binding,
           sizeof(core_config.boot_channel_binding_sha256));
    CHECK(wdc_admin_core_init(&harness->core, &core_config) == WDC_OK);
    authorize(harness);
    fingerprint = wdc_host_fingerprint_for_target(WDC_HOST_TARGET_ESP32C6);
    CHECK(fingerprint != NULL);
    harness->fingerprint = *fingerprint;
    harness->fingerprint.capability_mask |= WDC_HOST_CAP_APPLICATION_SLOTS;
    harness->fingerprint.crc32 =
        wdc_host_fingerprint_crc32(&harness->fingerprint);
    harness->bundle_policy =
        wdc_bundle_make_default_dev_policy(wdc_profile_builtin());
    memset(&harness->slot_policy, 0, sizeof(harness->slot_policy));
    harness->slot_policy.bundle_policy = &harness->bundle_policy;
    harness->slot_policy.security_version_floor = security_floor;
    harness->activation_policy = wdc_activation_default_policy();
    memset(&update_config, 0, sizeof(update_config));
    update_config.core = &harness->core;
    update_config.metadata = &harness->metadata;
    update_config.running_host_fingerprint = &harness->fingerprint;
    update_config.slot_verify_policy = &harness->slot_policy;
    update_config.activation_policy = &harness->activation_policy;
    update_config.lifecycle.quiesce_and_unload = fake_quiesce;
    update_config.lifecycle.heap_snapshot_after_unload = fake_heap;
    update_config.lifecycle.context = &harness->lifecycle;
    update_config.working_buffer = harness->working;
    update_config.working_buffer_bytes = sizeof(harness->working);
    CHECK(wdc_admin_update_init(&harness->update, &update_config) == WDC_OK);
}

static WdcAdminRequest make_request(Harness *harness,
                                    WdcAdminCommand command,
                                    uint32_t payload_bytes,
                                    uint64_t now_ms)
{
    WdcAdminRequest request;
    memset(&request, 0, sizeof(request));
    request.struct_size = WDC_ADMIN_REQUEST_BYTES;
    request.version_major = WDC_ADMIN_VERSION_MAJOR;
    request.version_minor = WDC_ADMIN_VERSION_MINOR;
    request.command = (uint32_t)command;
    request.payload_bytes = payload_bytes;
    request.slot = WDC_BUNDLE_SLOT_B;
    request.expected_total_bytes = s_artifact_bytes;
    request.request_id = harness->next_request_id++;
    request.deadline_ms = now_ms + 1000u;
    request.authorization_epoch = harness->core.session.authorization_epoch;
    request.session_nonce = harness->core.session.session_nonce;
    request.command_sequence = wdc_admin_next_command_sequence(&harness->core);
    memcpy(request.artifact_sha256, harness->request_hash,
           sizeof(request.artifact_sha256));
    return request;
}

static int32_t execute_request(Harness *harness,
                               WdcAdminRequest *request,
                               const uint8_t *payload,
                               uint64_t now_ms,
                               WdcAdminTerminalRecord *out_terminal)
{
    WdcAdminPreacceptResult rejection;
    WdcControlWorkItem work;
    WdcAdminAcceptedCommand accepted;
    uint32_t response_bytes = 0u;
    int32_t status;
    status = wdc_admin_submit(&harness->core, request, payload,
                              request->payload_bytes, now_ms, &rejection);
    if (status != WDC_OK) {
        return status;
    }
    CHECK(wdc_control_next(&harness->kernel, &work) == WDC_OK);
    CHECK(wdc_admin_begin_command(&harness->core, &work, now_ms + 1u,
                                  &accepted) == WDC_OK);
    status = wdc_admin_update_execute(&harness->update, &accepted,
                                      now_ms + 1u);
    CHECK(wdc_admin_take_terminal(&harness->core, out_terminal, NULL, 0u,
                                  &response_bytes) == WDC_OK);
    CHECK(response_bytes == 0u);
    return status;
}

static int32_t execute_command(Harness *harness,
                               WdcAdminCommand command,
                               const uint8_t *payload,
                               uint32_t payload_bytes,
                               uint64_t now_ms,
                               WdcAdminTerminalRecord *out_terminal)
{
    WdcAdminRequest request =
        make_request(harness, command, payload_bytes, now_ms);
    return execute_request(harness, &request, payload, now_ms, out_terminal);
}

static int32_t begin(Harness *harness,
                     uint64_t now_ms,
                     WdcAdminTerminalRecord *terminal)
{
    return execute_command(harness, WDC_ADMIN_COMMAND_BEGIN_UPDATE,
                           NULL, 0u, now_ms, terminal);
}

static int32_t stream_artifact(Harness *harness,
                               uint64_t *now_ms,
                               WdcAdminTerminalRecord *terminal)
{
    uint32_t offset = 0u;
    while (offset < s_artifact_bytes) {
        uint32_t remaining = s_artifact_bytes - offset;
        uint32_t chunk = remaining < 512u ? remaining : 512u;
        int32_t status = execute_command(
            harness, WDC_ADMIN_COMMAND_WRITE_CHUNK, s_artifact + offset,
            chunk, *now_ms, terminal);
        if (status != WDC_OK) {
            return status;
        }
        offset += chunk;
        *now_ms += 2u;
    }
    return WDC_OK;
}

static bool confirmed_a_preserved(const Harness *harness)
{
    return harness->metadata.active_slot == WDC_BUNDLE_SLOT_A &&
           harness->metadata.last_good_slot == WDC_BUNDLE_SLOT_A &&
           harness->metadata.slot_a.state == WDC_SLOT_CONFIRMED &&
           harness->metadata.slot_a.bundle_version == 7u &&
           harness->metadata.slot_a.security_counter == 7u;
}

static void case_fixed_bounds_and_init(void)
{
    Harness harness;
    WdcControlAdmissionDecision decision;
    WdcControlHeapSnapshot heap;
    uint32_t before = s_failures;
    init_harness(&harness, 0u);
    CHECK(WDC_ADMIN_HP42_COMMAND_MASK == 0x5fu);
    CHECK(wdc_admin_update_state(&harness.update) ==
          WDC_ADMIN_UPDATE_STATE_IDLE);
    CHECK(wdc_admin_update_static_bytes() == sizeof(WdcAdminUpdateEngine));
    heap = harness.lifecycle.heap;
    CHECK(wdc_control_admit_exclusive_update(
              wdc_control_profile_c6_minimum(), &heap, &decision) == WDC_OK);
    CHECK(decision.fixed_control_reserve_bytes == 98304u);
    CHECK(decision.exclusive_update_required_bytes == 163840u);
    CHECK(decision.required_largest_block_bytes == 98304u);
    record_case("fixed-c6-exclusive-admission", before);
}

static void case_positive_quiesce_begin(void)
{
    Harness harness;
    WdcAdminTerminalRecord terminal;
    uint32_t before = s_failures;
    init_harness(&harness, 0u);
    CHECK(begin(&harness, 200u, &terminal) == WDC_OK);
    CHECK(harness.lifecycle.quiesce_calls == 1u);
    CHECK(harness.lifecycle.heap_calls == 1u);
    CHECK(wdc_admin_mode(&harness.core) == WDC_ADMIN_MODE_UPDATE);
    CHECK(wdc_admin_update_state(&harness.update) ==
          WDC_ADMIN_UPDATE_STATE_STREAMING);
    CHECK(harness.update.target_slot == WDC_BUNDLE_SLOT_B);
    CHECK(terminal.result == WDC_ADMIN_TERMINAL_SUCCEEDED);
    CHECK(confirmed_a_preserved(&harness));
    record_case("positive-quiesce-unload-before-update", before);
}

static void case_active_slot_denied(void)
{
    Harness harness;
    WdcAdminRequest request;
    WdcAdminTerminalRecord terminal;
    uint32_t before = s_failures;
    init_harness(&harness, 0u);
    request = make_request(&harness, WDC_ADMIN_COMMAND_BEGIN_UPDATE, 0u, 200u);
    request.slot = WDC_BUNDLE_SLOT_A;
    CHECK(execute_request(&harness, &request, NULL, 200u, &terminal) ==
          WDC_ERR_INVALID_STATE);
    CHECK(terminal.result == WDC_ADMIN_TERMINAL_FAILED);
    CHECK(wdc_admin_mode(&harness.core) == WDC_ADMIN_MODE_NORMAL);
    CHECK(confirmed_a_preserved(&harness));
    record_case("active-slot-never-staged", before);
}

static void case_quiesce_failure(void)
{
    Harness harness;
    WdcAdminTerminalRecord terminal;
    uint32_t before = s_failures;
    init_harness(&harness, 0u);
    harness.lifecycle.quiesce_status = WDC_ERR_TIMEOUT;
    CHECK(begin(&harness, 200u, &terminal) == WDC_ERR_TIMEOUT);
    CHECK(terminal.result == WDC_ADMIN_TERMINAL_TIMED_OUT);
    CHECK(wdc_admin_mode(&harness.core) == WDC_ADMIN_MODE_NORMAL);
    CHECK(confirmed_a_preserved(&harness));
    record_case("quiesce-failure-preserves-authority", before);
}

static void case_internal_free_denied(void)
{
    Harness harness;
    WdcAdminTerminalRecord terminal;
    uint32_t before = s_failures;
    init_harness(&harness, 0u);
    harness.lifecycle.heap.internal_free_bytes = 163839u;
    harness.lifecycle.heap.internal_largest_block_bytes = 131072u;
    CHECK(begin(&harness, 200u, &terminal) == WDC_ERR_NO_MEMORY);
    CHECK(wdc_admin_mode(&harness.core) == WDC_ADMIN_MODE_NORMAL);
    CHECK(confirmed_a_preserved(&harness));
    record_case("exclusive-free-byte-denial", before);
}

static void case_largest_block_denied(void)
{
    Harness harness;
    WdcAdminTerminalRecord terminal;
    uint32_t before = s_failures;
    init_harness(&harness, 0u);
    harness.lifecycle.heap.internal_free_bytes = 196608u;
    harness.lifecycle.heap.internal_largest_block_bytes = 98303u;
    CHECK(begin(&harness, 200u, &terminal) == WDC_ERR_NO_MEMORY);
    CHECK(wdc_admin_mode(&harness.core) == WDC_ADMIN_MODE_NORMAL);
    CHECK(confirmed_a_preserved(&harness));
    record_case("exclusive-largest-block-denial", before);
}

static void case_chunk_bound_preaccept(void)
{
    Harness harness;
    WdcAdminPreacceptResult rejection;
    WdcAdminRequest request;
    uint8_t oversized[WDC_ADMIN_UPDATE_MAX_CHUNK_BYTES + 1u];
    uint64_t sequence;
    uint32_t before = s_failures;
    init_harness(&harness, 0u);
    CHECK(begin(&harness, 200u, &(WdcAdminTerminalRecord){0}) == WDC_OK);
    sequence = wdc_admin_next_command_sequence(&harness.core);
    request = make_request(&harness, WDC_ADMIN_COMMAND_WRITE_CHUNK,
                           sizeof(oversized), 210u);
    memset(oversized, 0x5au, sizeof(oversized));
    CHECK(wdc_admin_submit(&harness.core, &request, oversized,
                           sizeof(oversized), 210u, &rejection) ==
          WDC_ERR_BAD_LENGTH);
    CHECK(rejection.rejection == WDC_ADMIN_REJECTION_BOUNDS);
    CHECK(wdc_admin_next_command_sequence(&harness.core) == sequence);
    CHECK(harness.update.streamed_bytes == 0u);
    record_case("chunk-bound-rejects-before-replay", before);
}

static void case_explicit_abort(void)
{
    Harness harness;
    WdcAdminTerminalRecord terminal;
    uint32_t before = s_failures;
    init_harness(&harness, 0u);
    CHECK(begin(&harness, 200u, &terminal) == WDC_OK);
    CHECK(execute_command(&harness, WDC_ADMIN_COMMAND_WRITE_CHUNK,
                          s_artifact, 128u, 210u, &terminal) == WDC_OK);
    CHECK(execute_command(&harness, WDC_ADMIN_COMMAND_ABORT,
                          NULL, 0u, 212u, &terminal) == WDC_OK);
    CHECK(terminal.result == WDC_ADMIN_TERMINAL_SUCCEEDED);
    CHECK(wdc_admin_mode(&harness.core) == WDC_ADMIN_MODE_NORMAL);
    CHECK(wdc_admin_update_state(&harness.update) ==
          WDC_ADMIN_UPDATE_STATE_IDLE);
    CHECK(confirmed_a_preserved(&harness));
    record_case("explicit-abort-preserves-authority", before);
}

static void case_stream_idle_timeout(void)
{
    Harness harness;
    WdcAdminTerminalRecord terminal;
    uint32_t before = s_failures;
    init_harness(&harness, 0u);
    CHECK(begin(&harness, 200u, &terminal) == WDC_OK);
    CHECK(wdc_admin_update_poll(&harness.update, 30201u) == WDC_ERR_TIMEOUT);
    CHECK(wdc_admin_mode(&harness.core) == WDC_ADMIN_MODE_NORMAL);
    CHECK(confirmed_a_preserved(&harness));
    record_case("stream-idle-timeout-aborts", before);
}

static void case_stream_rate_limit(void)
{
    Harness harness;
    WdcAdminTerminalRecord terminal;
    uint8_t byte = 0x5au;
    uint32_t index;
    uint32_t before = s_failures;
    init_harness(&harness, 0u);
    CHECK(begin(&harness, 200u, &terminal) == WDC_OK);
    for (index = 0u; index < 64u; ++index) {
        CHECK(execute_command(&harness, WDC_ADMIN_COMMAND_WRITE_CHUNK,
                              &byte, 1u, 210u + (2u * index),
                              &terminal) == WDC_OK);
    }
    CHECK(execute_command(&harness, WDC_ADMIN_COMMAND_WRITE_CHUNK,
                          &byte, 1u, 338u, &terminal) ==
          WDC_ERR_RATE_LIMITED);
    CHECK(terminal.result == WDC_ADMIN_TERMINAL_FAILED);
    CHECK(wdc_admin_mode(&harness.core) == WDC_ADMIN_MODE_NORMAL);
    CHECK(confirmed_a_preserved(&harness));
    record_case("bounded-stream-rate-window", before);
}

static void case_hash_mismatch(void)
{
    Harness harness;
    WdcAdminTerminalRecord terminal;
    uint64_t now_ms = 210u;
    uint32_t before = s_failures;
    init_harness(&harness, 0u);
    harness.request_hash[0] ^= 0xffu;
    CHECK(begin(&harness, 200u, &terminal) == WDC_OK);
    CHECK(stream_artifact(&harness, &now_ms, &terminal) == WDC_OK);
    CHECK(execute_command(&harness, WDC_ADMIN_COMMAND_FINISH_UPDATE,
                          NULL, 0u, now_ms, &terminal) ==
          WDC_ERR_CONTRACT_VIOLATION);
    CHECK(wdc_admin_mode(&harness.core) == WDC_ADMIN_MODE_NORMAL);
    CHECK(confirmed_a_preserved(&harness));
    record_case("complete-artifact-hash-mismatch-aborts", before);
}

static void case_security_rollback(void)
{
    Harness harness;
    WdcAdminTerminalRecord terminal;
    uint64_t now_ms = 210u;
    uint32_t before = s_failures;
    init_harness(&harness, 9u);
    CHECK(begin(&harness, 200u, &terminal) == WDC_OK);
    CHECK(stream_artifact(&harness, &now_ms, &terminal) == WDC_OK);
    CHECK(execute_command(&harness, WDC_ADMIN_COMMAND_FINISH_UPDATE,
                          NULL, 0u, now_ms, &terminal) ==
          WDC_ERR_CONTRACT_VIOLATION);
    CHECK(wdc_admin_mode(&harness.core) == WDC_ADMIN_MODE_NORMAL);
    CHECK(confirmed_a_preserved(&harness));
    record_case("security-floor-rollback-aborts", before);
}

static void case_replaceable_verifier_denial(void)
{
    Harness harness;
    WdcAdminTerminalRecord terminal;
    uint64_t now_ms = 210u;
    uint32_t before = s_failures;
    init_harness(&harness, 0u);
    CHECK(begin(&harness, 200u, &terminal) == WDC_OK);
    CHECK(stream_artifact(&harness, &now_ms, &terminal) == WDC_OK);
    harness.verifier.allow = false;
    CHECK(execute_command(&harness, WDC_ADMIN_COMMAND_FINISH_UPDATE,
                          NULL, 0u, now_ms, &terminal) ==
          WDC_ERR_CAPABILITY_DENIED);
    CHECK(harness.verifier.calls == 1u);
    CHECK(wdc_admin_mode(&harness.core) == WDC_ADMIN_MODE_NORMAL);
    CHECK(confirmed_a_preserved(&harness));
    record_case("replaceable-verifier-denial-aborts", before);
}

static void finish_verified(Harness *harness,
                            uint64_t *now_ms,
                            WdcAdminTerminalRecord *terminal)
{
    CHECK(begin(harness, 200u, terminal) == WDC_OK);
    CHECK(stream_artifact(harness, now_ms, terminal) == WDC_OK);
    CHECK(execute_command(harness, WDC_ADMIN_COMMAND_FINISH_UPDATE,
                          NULL, 0u, *now_ms, terminal) == WDC_OK);
    *now_ms += 2u;
    CHECK(wdc_admin_update_state(&harness->update) ==
          WDC_ADMIN_UPDATE_STATE_VERIFIED);
}

static void case_trial_journal_interruption(void)
{
    Harness harness;
    WdcAdminTerminalRecord terminal;
    WdcOtaHostFaultPlan fault;
    uint64_t now_ms = 210u;
    uint32_t before = s_failures;
    init_harness(&harness, 0u);
    finish_verified(&harness, &now_ms, &terminal);
    memset(&fault, 0, sizeof(fault));
    fault.operation = WDC_OTA_HOST_FAULT_METADATA_MARKER_WRITE;
    fault.trigger_index = 1u;
    CHECK(wdc_ota_host_fault_arm(&fault) == WDC_OK);
    CHECK(execute_command(&harness, WDC_ADMIN_COMMAND_ACTIVATE_TRIAL,
                          NULL, 0u, now_ms, &terminal) == WDC_ERR_IO);
    CHECK(terminal.result == WDC_ADMIN_TERMINAL_FAILED);
    CHECK(wdc_admin_mode(&harness.core) == WDC_ADMIN_MODE_NORMAL);
    CHECK(confirmed_a_preserved(&harness));
    CHECK(harness.metadata.slot_b.state == WDC_SLOT_VERIFIED);
    wdc_ota_host_fault_clear();
    record_case("trial-journal-interruption-preserves-boot", before);
}

static void case_complete_trial_handoff(void)
{
    Harness harness;
    WdcAdminTerminalRecord terminal;
    WdcBundleMetadataV1 durable;
    uint64_t now_ms = 210u;
    uint32_t before = s_failures;
    init_harness(&harness, 0u);
    finish_verified(&harness, &now_ms, &terminal);
    CHECK(execute_command(&harness, WDC_ADMIN_COMMAND_ACTIVATE_TRIAL,
                          NULL, 0u, now_ms, &terminal) == WDC_OK);
    CHECK(terminal.result == WDC_ADMIN_TERMINAL_REBOOT_HANDOFF);
    CHECK(terminal.metadata_commits == 3u);
    CHECK(terminal.bytes_received == s_artifact_bytes);
    CHECK(terminal.final_state == WDC_ADMIN_MODE_REBOOT_HANDOFF);
    CHECK(wdc_admin_mode(&harness.core) == WDC_ADMIN_MODE_REBOOT_HANDOFF);
    CHECK(wdc_admin_update_state(&harness.update) ==
          WDC_ADMIN_UPDATE_STATE_REBOOT_HANDOFF);
    CHECK(harness.verifier.calls == 2u);
    CHECK(wdc_ota_read_metadata(&durable) == WDC_OK);
    CHECK(durable.slot_b.state == WDC_SLOT_TRIAL);
    CHECK(durable.active_slot == WDC_BUNDLE_SLOT_B);
    CHECK(durable.last_good_slot == WDC_BUNDLE_SLOT_A);
    CHECK(harness.metadata.last_good_slot == WDC_BUNDLE_SLOT_A);
    CHECK(harness.metadata.slot_a.state == WDC_SLOT_CONFIRMED);
    record_case("verified-trial-durable-reboot-handoff", before);
}

int main(int argc, char **argv)
{
    uint32_t index;
    if (argc != 2 || !load_bundle(argv[1])) {
        (void)fprintf(stderr, "usage: hp4_2-smoke BUNDLE\n");
        return 2;
    }
    build_artifact();
    case_fixed_bounds_and_init();
    case_positive_quiesce_begin();
    case_active_slot_denied();
    case_quiesce_failure();
    case_internal_free_denied();
    case_largest_block_denied();
    case_chunk_bound_preaccept();
    case_explicit_abort();
    case_stream_idle_timeout();
    case_stream_rate_limit();
    case_hash_mismatch();
    case_security_rollback();
    case_replaceable_verifier_denial();
    case_trial_journal_interruption();
    case_complete_trial_handoff();
    (void)printf("{\"schema\":\"pulse.esp32.hp4_2-admin-update-smoke.v1\","
                 "\"status\":\"%s\",\"case_count\":%" PRIu32
                 ",\"failures\":%" PRIu32
                 ",\"engine_static_bytes\":%" PRIu32
                 ",\"working_bytes\":%u,\"chunk_bytes\":%u,"
                 "\"cases\":[",
                 s_failures == 0u && s_case_count == HP42_CASE_COUNT
                     ? "PASS" : "FAIL",
                 s_case_count, s_failures,
                 wdc_admin_update_static_bytes(),
                 WDC_ADMIN_UPDATE_WORKING_BYTES,
                 WDC_ADMIN_UPDATE_MAX_CHUNK_BYTES);
    for (index = 0u; index < s_case_count; ++index) {
        (void)printf("%s{\"name\":\"%s\",\"status\":\"%s\"}",
                     index == 0u ? "" : ",", s_cases[index].name,
                     s_cases[index].passed ? "PASS" : "FAIL");
    }
    (void)printf("]}\n");
    return s_failures == 0u && s_case_count == HP42_CASE_COUNT ? 0 : 1;
}
