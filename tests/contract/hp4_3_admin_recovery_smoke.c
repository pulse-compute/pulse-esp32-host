#include <inttypes.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "wdc_admin_recovery.h"
#include "wdc_ota.h"
#include "wdc_profile.h"

#define HP43_CASE_COUNT 12u
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
    WdcAdminRecoveryEngine recovery;
    WdcBundleMetadataV1 metadata;
    WdcHostFingerprintV1 fingerprint;
    WdcBundleVerifyPolicy bundle_policy;
    WdcAppSlotVerifyPolicy slot_policy;
    WdcActivationPolicy activation_policy;
    WdcAppSlotBootResult boot_result;
    FakeAuthorizer authorizer;
    FakeVerifier verifier;
    FakeLifecycle lifecycle;
    uint8_t binding[32];
    uint8_t working[WDC_ADMIN_UPDATE_WORKING_BYTES];
    uint64_t next_request_id;
} Harness;

static uint8_t s_bundle[MAX_BUNDLE_BYTES];
static uint8_t s_artifact[MAX_ARTIFACT_BYTES];
static uint32_t s_bundle_bytes;
static uint32_t s_artifact_bytes;
static uint8_t s_artifact_sha256[WDC_BUNDLE_SHA256_BYTES];
static CaseResult s_cases[HP43_CASE_COUNT];
static uint32_t s_case_count;
static uint32_t s_failures;

#define CHECK(condition)                                                       \
    do {                                                                       \
        if (!(condition)) {                                                    \
            s_failures += 1u;                                                  \
            (void)fprintf(stderr, "CHECK failed at %s:%d: %s\n",             \
                          __FILE__, __LINE__, #condition);                     \
        }                                                                      \
    } while (0)

static void record_case(const char *name, uint32_t before)
{
    CHECK(s_case_count < HP43_CASE_COUNT);
    if (s_case_count < HP43_CASE_COUNT) {
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
    out_entry->privilege_mask = WDC_ADMIN_PRIVILEGE_ALL;
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
    CHECK(candidate->stored_bytes == s_artifact_bytes);
    CHECK(memcmp(candidate->artifact_sha256, s_artifact_sha256,
                 WDC_BUNDLE_SHA256_BYTES) == 0);
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

static void configure_host(Harness *harness)
{
    const WdcHostFingerprintV1 *fingerprint =
        wdc_host_fingerprint_for_target(WDC_HOST_TARGET_ESP32C6);
    CHECK(fingerprint != NULL);
    harness->fingerprint = *fingerprint;
    harness->fingerprint.capability_mask |= WDC_HOST_CAP_APPLICATION_SLOTS;
    harness->fingerprint.crc32 =
        wdc_host_fingerprint_crc32(&harness->fingerprint);
    harness->bundle_policy =
        wdc_bundle_make_default_dev_policy(wdc_profile_builtin());
    memset(&harness->slot_policy, 0, sizeof(harness->slot_policy));
    harness->slot_policy.bundle_policy = &harness->bundle_policy;
    harness->activation_policy = wdc_activation_default_policy();
}

static void seed_empty(Harness *harness)
{
    wdc_bundle_metadata_init(&harness->metadata);
    CHECK(wdc_bundle_metadata_seal(&harness->metadata) == WDC_OK);
    CHECK(wdc_ota_host_set_metadata(&harness->metadata) == WDC_OK);
}

static void seed_confirmed_a(Harness *harness)
{
    WdcAppSlotStageSession stage;
    WdcAppSlotStageResult result;
    seed_empty(harness);
    CHECK(wdc_app_slots_stage_begin(&stage, &harness->metadata,
                                    WDC_BUNDLE_SLOT_A,
                                    s_artifact_bytes) == WDC_OK);
    CHECK(wdc_app_slots_stage_write(&stage, s_artifact,
                                    s_artifact_bytes) == WDC_OK);
    memset(&result, 0, sizeof(result));
    CHECK(wdc_app_slots_stage_finish(
              &stage, &harness->metadata, &harness->fingerprint,
              &harness->slot_policy, harness->working,
              sizeof(harness->working), &result) == WDC_OK);
    CHECK(result.terminal_state == WDC_SLOT_VERIFIED);
    harness->metadata.slot_a.state = WDC_SLOT_CONFIRMED;
    harness->metadata.active_slot = WDC_BUNDLE_SLOT_A;
    harness->metadata.last_good_slot = WDC_BUNDLE_SLOT_A;
    harness->metadata.metadata_generation += 1u;
    CHECK(wdc_bundle_metadata_seal(&harness->metadata) == WDC_OK);
    CHECK(wdc_ota_host_set_metadata(&harness->metadata) == WDC_OK);
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
    start.challenge_id = 0x4300u;
    memcpy(start.channel_binding_sha256, harness->binding,
           sizeof(start.channel_binding_sha256));
    CHECK(wdc_admin_authorization_begin(&harness->core, &start, 100u,
                                         &deadline, &rejection) == WDC_OK);
    CHECK(wdc_admin_authorization_finish(&harness->core,
                                          (const uint8_t *)"proof", 5u,
                                          101u, &rejection) == WDC_OK);
}

static void init_harness(Harness *harness,
                         WdcAdminMode initial_mode,
                         bool confirmed)
{
    WdcAdminCoreConfig core_config;
    WdcAdminRecoveryConfig recovery_config;
    uint32_t index;
    memset(harness, 0, sizeof(*harness));
    wdc_ota_host_clear_slots();
    wdc_ota_host_clear_metadata();
    configure_host(harness);
    if (confirmed) {
        seed_confirmed_a(harness);
    } else {
        seed_empty(harness);
    }
    for (index = 0u; index < sizeof(harness->binding); ++index) {
        harness->binding[index] = (uint8_t)(0xb0u + (index % 23u));
    }
    harness->authorizer.next_epoch = 1u;
    harness->verifier.allow = true;
    harness->lifecycle.quiesce_status = WDC_OK;
    harness->lifecycle.heap_status = WDC_OK;
    harness->lifecycle.heap.internal_free_bytes = 196608u;
    harness->lifecycle.heap.internal_largest_block_bytes = 131072u;
    harness->next_request_id = 1u;
    CHECK(wdc_control_kernel_init(&harness->kernel,
                                  wdc_control_profile_c6_minimum()) == WDC_OK);
    memset(&core_config, 0, sizeof(core_config));
    core_config.control_kernel = &harness->kernel;
    core_config.authorizer.authorize = fake_authorize;
    core_config.authorizer.context = &harness->authorizer;
    core_config.artifact_verifier.verify = fake_verify;
    core_config.artifact_verifier.context = &harness->verifier;
    core_config.initial_mode = initial_mode;
    core_config.enabled_commands_mask = WDC_ADMIN_HP43_COMMAND_MASK;
    memcpy(core_config.boot_channel_binding_sha256, harness->binding,
           sizeof(core_config.boot_channel_binding_sha256));
    CHECK(wdc_admin_core_init(&harness->core, &core_config) == WDC_OK);
    memset(&recovery_config, 0, sizeof(recovery_config));
    recovery_config.update.core = &harness->core;
    recovery_config.update.metadata = &harness->metadata;
    recovery_config.update.running_host_fingerprint = &harness->fingerprint;
    recovery_config.update.slot_verify_policy = &harness->slot_policy;
    recovery_config.update.activation_policy = &harness->activation_policy;
    recovery_config.update.lifecycle.quiesce_and_unload = fake_quiesce;
    recovery_config.update.lifecycle.heap_snapshot_after_unload = fake_heap;
    recovery_config.update.lifecycle.context = &harness->lifecycle;
    recovery_config.update.working_buffer = harness->working;
    recovery_config.update.working_buffer_bytes = sizeof(harness->working);
    if (initial_mode == WDC_ADMIN_MODE_RECOVERY) {
        memset(&harness->boot_result, 0, sizeof(harness->boot_result));
        harness->boot_result.status = WDC_ERR_NOT_AVAILABLE;
        harness->boot_result.outcome = WDC_APP_SLOT_BOOT_RECOVERY;
        harness->boot_result.selected_slot = WDC_BUNDLE_SLOT_NONE;
        harness->boot_result.fallback_slot = WDC_BUNDLE_SLOT_NONE;
        harness->boot_result.recovery = true;
        recovery_config.boot_result = &harness->boot_result;
    } else {
        recovery_config.application_loaded = 1u;
        recovery_config.native_refinements_loaded = 1u;
    }
    CHECK(wdc_admin_recovery_init(&harness->recovery, &recovery_config,
                                   90u) == WDC_OK);
    authorize(harness);
}

static WdcAdminRequest make_request(Harness *harness,
                                    WdcAdminCommand command,
                                    uint32_t payload_bytes,
                                    uint64_t now_ms)
{
    WdcAdminRequest request;
    bool bound = command == WDC_ADMIN_COMMAND_BEGIN_UPDATE ||
                 command == WDC_ADMIN_COMMAND_WRITE_CHUNK ||
                 command == WDC_ADMIN_COMMAND_FINISH_UPDATE ||
                 command == WDC_ADMIN_COMMAND_ACTIVATE_TRIAL ||
                 (command == WDC_ADMIN_COMMAND_ABORT &&
                  harness->core.mode == WDC_ADMIN_MODE_UPDATE);
    memset(&request, 0, sizeof(request));
    request.struct_size = WDC_ADMIN_REQUEST_BYTES;
    request.version_major = WDC_ADMIN_VERSION_MAJOR;
    request.version_minor = WDC_ADMIN_VERSION_MINOR;
    request.command = (uint32_t)command;
    request.payload_bytes = payload_bytes;
    request.slot = bound
                       ? (harness->metadata.active_slot == WDC_BUNDLE_SLOT_A
                              ? WDC_BUNDLE_SLOT_B
                              : WDC_BUNDLE_SLOT_A)
                       : WDC_ADMIN_SLOT_NONE;
    request.expected_total_bytes = bound ? s_artifact_bytes : 0u;
    request.request_id = harness->next_request_id++;
    request.deadline_ms = now_ms + 1000u;
    request.authorization_epoch = harness->core.session.authorization_epoch;
    request.session_nonce = harness->core.session.session_nonce;
    request.command_sequence = wdc_admin_next_command_sequence(&harness->core);
    if (bound) {
        memcpy(request.artifact_sha256, s_artifact_sha256,
               sizeof(request.artifact_sha256));
    }
    return request;
}

static int32_t execute_request(Harness *harness,
                               WdcAdminRequest *request,
                               const uint8_t *payload,
                               uint64_t now_ms,
                               WdcAdminTerminalRecord *out_terminal,
                               uint8_t *response,
                               uint32_t response_capacity,
                               uint32_t *out_response_bytes)
{
    WdcAdminPreacceptResult rejection;
    WdcControlWorkItem work;
    WdcAdminAcceptedCommand accepted;
    int32_t status;
    status = wdc_admin_submit(&harness->core, request, payload,
                              request->payload_bytes, now_ms, &rejection);
    if (status != WDC_OK) {
        return status;
    }
    CHECK(wdc_control_next(&harness->kernel, &work) == WDC_OK);
    CHECK(wdc_admin_begin_command(&harness->core, &work, now_ms + 1u,
                                  &accepted) == WDC_OK);
    status = wdc_admin_recovery_execute(&harness->recovery, &accepted,
                                        now_ms + 1u);
    CHECK(wdc_admin_take_terminal(&harness->core, out_terminal, response,
                                  response_capacity,
                                  out_response_bytes) == WDC_OK);
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
    uint32_t response_bytes = 0u;
    return execute_request(harness, &request, payload, now_ms, out_terminal,
                           NULL, 0u, &response_bytes);
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

static void case_automatic_recovery(void)
{
    Harness harness;
    uint32_t before = s_failures;
    init_harness(&harness, WDC_ADMIN_MODE_RECOVERY, false);
    CHECK(WDC_ADMIN_HP43_COMMAND_MASK == 0xffu);
    CHECK(wdc_admin_mode(&harness.core) == WDC_ADMIN_MODE_RECOVERY);
    CHECK(wdc_admin_recovery_reason(&harness.recovery) ==
          WDC_ADMIN_RECOVERY_REASON_NO_VIABLE_APPLICATION);
    CHECK(harness.recovery.application_loaded == 0u);
    CHECK(harness.lifecycle.quiesce_calls == 0u);
    record_case("no-viable-enters-host-only-recovery", before);
}

static void case_malformed_boot_evidence(void)
{
    Harness harness;
    WdcAdminCoreConfig core_config;
    WdcAdminRecoveryConfig recovery_config;
    uint32_t before = s_failures;
    memset(&harness, 0, sizeof(harness));
    wdc_ota_host_clear_slots();
    wdc_ota_host_clear_metadata();
    configure_host(&harness);
    seed_empty(&harness);
    memset(harness.binding, 0x5au, sizeof(harness.binding));
    CHECK(wdc_control_kernel_init(&harness.kernel,
                                  wdc_control_profile_c6_minimum()) == WDC_OK);
    memset(&core_config, 0, sizeof(core_config));
    core_config.control_kernel = &harness.kernel;
    core_config.authorizer.authorize = fake_authorize;
    core_config.authorizer.context = &harness.authorizer;
    core_config.artifact_verifier.verify = fake_verify;
    core_config.artifact_verifier.context = &harness.verifier;
    core_config.initial_mode = WDC_ADMIN_MODE_RECOVERY;
    core_config.enabled_commands_mask = WDC_ADMIN_HP43_COMMAND_MASK;
    memcpy(core_config.boot_channel_binding_sha256, harness.binding,
           sizeof(core_config.boot_channel_binding_sha256));
    CHECK(wdc_admin_core_init(&harness.core, &core_config) == WDC_OK);
    memset(&recovery_config, 0, sizeof(recovery_config));
    recovery_config.update.core = &harness.core;
    recovery_config.update.metadata = &harness.metadata;
    recovery_config.update.running_host_fingerprint = &harness.fingerprint;
    recovery_config.update.slot_verify_policy = &harness.slot_policy;
    recovery_config.update.activation_policy = &harness.activation_policy;
    recovery_config.update.lifecycle.quiesce_and_unload = fake_quiesce;
    recovery_config.update.lifecycle.heap_snapshot_after_unload = fake_heap;
    recovery_config.update.lifecycle.context = &harness.lifecycle;
    recovery_config.update.working_buffer = harness.working;
    recovery_config.update.working_buffer_bytes = sizeof(harness.working);
    memset(&harness.boot_result, 0, sizeof(harness.boot_result));
    harness.boot_result.status = WDC_ERR_NOT_AVAILABLE;
    harness.boot_result.outcome = WDC_APP_SLOT_BOOT_RECOVERY;
    harness.boot_result.selected_slot = WDC_BUNDLE_SLOT_A;
    harness.boot_result.recovery = true;
    recovery_config.boot_result = &harness.boot_result;
    CHECK(wdc_admin_recovery_init(&harness.recovery, &recovery_config,
                                   90u) == WDC_ERR_BAD_ENCODING);
    CHECK(harness.metadata.active_slot == WDC_BUNDLE_SLOT_NONE);
    record_case("malformed-boot-evidence-fails-closed", before);
}

static void case_recovery_status(void)
{
    Harness harness;
    WdcAdminRequest request;
    WdcAdminTerminalRecord terminal;
    WdcAdminRecoveryStatus response;
    uint32_t response_bytes = 0u;
    uint32_t before = s_failures;
    init_harness(&harness, WDC_ADMIN_MODE_RECOVERY, false);
    request = make_request(&harness, WDC_ADMIN_COMMAND_STATUS, 0u, 200u);
    memset(&response, 0, sizeof(response));
    CHECK(execute_request(&harness, &request, NULL, 200u, &terminal,
                          (uint8_t *)&response, sizeof(response),
                          &response_bytes) == WDC_OK);
    CHECK(response_bytes == WDC_ADMIN_RECOVERY_STATUS_BYTES);
    CHECK(response.struct_size == WDC_ADMIN_RECOVERY_STATUS_BYTES);
    CHECK(response.mode == WDC_ADMIN_MODE_RECOVERY);
    CHECK(response.recovery_reason ==
          WDC_ADMIN_RECOVERY_REASON_NO_VIABLE_APPLICATION);
    CHECK(response.enabled_commands_mask == WDC_ADMIN_HP43_COMMAND_MASK);
    CHECK(response.application_loaded == 0u);
    CHECK(terminal.result == WDC_ADMIN_TERMINAL_SUCCEEDED);
    record_case("fixed-secret-free-recovery-status", before);
}

static void case_recovery_abort(void)
{
    Harness harness;
    WdcAdminTerminalRecord terminal;
    uint32_t before = s_failures;
    init_harness(&harness, WDC_ADMIN_MODE_RECOVERY, false);
    CHECK(execute_command(&harness, WDC_ADMIN_COMMAND_ABORT, NULL, 0u,
                          200u, &terminal) == WDC_OK);
    CHECK(terminal.result == WDC_ADMIN_TERMINAL_SUCCEEDED);
    CHECK(terminal.final_state == WDC_ADMIN_MODE_RECOVERY);
    CHECK(harness.metadata.active_slot == WDC_BUNDLE_SLOT_NONE);
    record_case("idle-abort-retains-recovery", before);
}

static void case_no_viable_reboot_denied(void)
{
    Harness harness;
    WdcAdminTerminalRecord terminal;
    uint32_t before = s_failures;
    init_harness(&harness, WDC_ADMIN_MODE_RECOVERY, false);
    CHECK(execute_command(&harness, WDC_ADMIN_COMMAND_REBOOT, NULL, 0u,
                          200u, &terminal) == WDC_ERR_INVALID_STATE);
    CHECK(terminal.result == WDC_ADMIN_TERMINAL_FAILED);
    CHECK(wdc_admin_mode(&harness.core) == WDC_ADMIN_MODE_RECOVERY);
    CHECK(harness.metadata.active_slot == WDC_BUNDLE_SLOT_NONE);
    record_case("no-viable-reboot-loop-denied", before);
}

static void case_recovery_staging_and_abort(void)
{
    Harness harness;
    WdcAdminTerminalRecord terminal;
    uint32_t before = s_failures;
    init_harness(&harness, WDC_ADMIN_MODE_RECOVERY, false);
    CHECK(execute_command(&harness, WDC_ADMIN_COMMAND_BEGIN_UPDATE,
                          NULL, 0u, 200u, &terminal) == WDC_OK);
    CHECK(wdc_admin_mode(&harness.core) == WDC_ADMIN_MODE_UPDATE);
    CHECK(wdc_admin_update_state(&harness.recovery.update) ==
          WDC_ADMIN_UPDATE_STATE_STREAMING);
    CHECK(harness.recovery.update.target_slot == WDC_BUNDLE_SLOT_A);
    CHECK(harness.lifecycle.quiesce_calls == 0u);
    CHECK(execute_command(&harness, WDC_ADMIN_COMMAND_ABORT, NULL, 0u,
                          210u, &terminal) == WDC_OK);
    CHECK(wdc_admin_mode(&harness.core) == WDC_ADMIN_MODE_RECOVERY);
    CHECK(harness.metadata.active_slot == WDC_BUNDLE_SLOT_NONE);
    record_case("recovery-stage-abort-returns-recovery", before);
}

static void case_recovery_resource_denial(void)
{
    Harness harness;
    WdcAdminTerminalRecord terminal;
    uint32_t before = s_failures;
    init_harness(&harness, WDC_ADMIN_MODE_RECOVERY, false);
    harness.lifecycle.heap.internal_free_bytes = 160000u;
    CHECK(execute_command(&harness, WDC_ADMIN_COMMAND_BEGIN_UPDATE,
                          NULL, 0u, 200u, &terminal) ==
          WDC_ERR_NO_MEMORY);
    CHECK(terminal.result == WDC_ADMIN_TERMINAL_FAILED);
    CHECK(wdc_admin_mode(&harness.core) == WDC_ADMIN_MODE_RECOVERY);
    CHECK(harness.metadata.active_slot == WDC_BUNDLE_SLOT_NONE);
    record_case("hp1-denial-retains-recovery-authority", before);
}

static void case_recovery_activation(void)
{
    Harness harness;
    WdcAdminTerminalRecord terminal;
    uint64_t now_ms = 210u;
    uint32_t before = s_failures;
    init_harness(&harness, WDC_ADMIN_MODE_RECOVERY, false);
    CHECK(execute_command(&harness, WDC_ADMIN_COMMAND_BEGIN_UPDATE,
                          NULL, 0u, 200u, &terminal) == WDC_OK);
    CHECK(stream_artifact(&harness, &now_ms, &terminal) == WDC_OK);
    CHECK(execute_command(&harness, WDC_ADMIN_COMMAND_FINISH_UPDATE,
                          NULL, 0u, now_ms, &terminal) == WDC_OK);
    CHECK(harness.metadata.slot_a.state == WDC_SLOT_VERIFIED);
    CHECK(harness.metadata.active_slot == WDC_BUNDLE_SLOT_NONE);
    now_ms += 2u;
    CHECK(execute_command(&harness, WDC_ADMIN_COMMAND_ACTIVATE_TRIAL,
                          NULL, 0u, now_ms, &terminal) == WDC_OK);
    CHECK(terminal.result == WDC_ADMIN_TERMINAL_REBOOT_HANDOFF);
    CHECK(wdc_admin_mode(&harness.core) ==
          WDC_ADMIN_MODE_REBOOT_HANDOFF);
    CHECK(harness.metadata.active_slot == WDC_BUNDLE_SLOT_A);
    CHECK(harness.metadata.last_good_slot == WDC_BUNDLE_SLOT_NONE);
    CHECK(harness.metadata.slot_a.state == WDC_SLOT_TRIAL);
    CHECK(harness.verifier.calls == 2u);
    record_case("verified-recovery-candidate-trial-handoff", before);
}

static void case_administrative_entry(void)
{
    Harness harness;
    WdcAdminTerminalRecord terminal;
    uint32_t before = s_failures;
    init_harness(&harness, WDC_ADMIN_MODE_NORMAL, true);
    CHECK(execute_command(&harness, WDC_ADMIN_COMMAND_ENTER_RECOVERY,
                          NULL, 0u, 200u, &terminal) == WDC_OK);
    CHECK(terminal.result == WDC_ADMIN_TERMINAL_SUCCEEDED);
    CHECK(wdc_admin_mode(&harness.core) == WDC_ADMIN_MODE_RECOVERY);
    CHECK(wdc_admin_recovery_reason(&harness.recovery) ==
          WDC_ADMIN_RECOVERY_REASON_ADMINISTRATIVE_TRIGGER);
    CHECK(harness.lifecycle.quiesce_calls == 1u);
    CHECK(harness.recovery.application_loaded == 0u);
    CHECK(harness.metadata.active_slot == WDC_BUNDLE_SLOT_A);
    CHECK(harness.metadata.slot_a.state == WDC_SLOT_CONFIRMED);
    record_case("authorized-entry-unloads-before-recovery", before);
}

static void case_entry_evidence_failure(void)
{
    Harness harness;
    WdcAdminTerminalRecord terminal;
    uint32_t before = s_failures;
    init_harness(&harness, WDC_ADMIN_MODE_NORMAL, true);
    harness.lifecycle.malformed_evidence = true;
    CHECK(execute_command(&harness, WDC_ADMIN_COMMAND_ENTER_RECOVERY,
                          NULL, 0u, 200u, &terminal) ==
          WDC_ERR_CONTRACT_VIOLATION);
    CHECK(terminal.result == WDC_ADMIN_TERMINAL_FAILED);
    CHECK(wdc_admin_mode(&harness.core) == WDC_ADMIN_MODE_NORMAL);
    CHECK(harness.metadata.active_slot == WDC_BUNDLE_SLOT_A);
    CHECK(harness.metadata.slot_a.state == WDC_SLOT_CONFIRMED);
    record_case("malformed-unload-proof-preserves-normal", before);
}

static void case_safe_reboot_handoff(void)
{
    Harness harness;
    WdcAdminTerminalRecord terminal;
    uint32_t before = s_failures;
    init_harness(&harness, WDC_ADMIN_MODE_NORMAL, true);
    CHECK(execute_command(&harness, WDC_ADMIN_COMMAND_ENTER_RECOVERY,
                          NULL, 0u, 200u, &terminal) == WDC_OK);
    CHECK(execute_command(&harness, WDC_ADMIN_COMMAND_REBOOT,
                          NULL, 0u, 210u, &terminal) == WDC_OK);
    CHECK(terminal.result == WDC_ADMIN_TERMINAL_REBOOT_HANDOFF);
    CHECK(terminal.slot == WDC_BUNDLE_SLOT_A);
    CHECK(wdc_admin_mode(&harness.core) ==
          WDC_ADMIN_MODE_REBOOT_HANDOFF);
    CHECK(harness.metadata.slot_a.state == WDC_SLOT_CONFIRMED);
    record_case("read-only-viability-precedes-reboot", before);
}

static void case_recovery_request_shape(void)
{
    Harness harness;
    WdcAdminRequest request;
    WdcAdminPreacceptResult rejection;
    uint64_t sequence;
    uint32_t before = s_failures;
    init_harness(&harness, WDC_ADMIN_MODE_NORMAL, true);
    request = make_request(&harness, WDC_ADMIN_COMMAND_ENTER_RECOVERY,
                           0u, 200u);
    request.slot = WDC_BUNDLE_SLOT_B;
    request.expected_total_bytes = s_artifact_bytes;
    memcpy(request.artifact_sha256, s_artifact_sha256,
           sizeof(request.artifact_sha256));
    sequence = wdc_admin_next_command_sequence(&harness.core);
    CHECK(wdc_admin_submit(&harness.core, &request, NULL, 0u, 200u,
                           &rejection) == WDC_ERR_BAD_LENGTH);
    CHECK(rejection.rejection == WDC_ADMIN_REJECTION_BOUNDS);
    CHECK(wdc_admin_next_command_sequence(&harness.core) == sequence);
    CHECK(wdc_admin_mode(&harness.core) == WDC_ADMIN_MODE_NORMAL);
    CHECK(harness.metadata.slot_a.state == WDC_SLOT_CONFIRMED);
    record_case("recovery-control-shape-rejects-preaccept", before);
}

int main(int argc, char **argv)
{
    uint32_t index;
    if (argc != 2 || !load_bundle(argv[1])) {
        (void)fprintf(stderr, "usage: hp4_3-smoke BUNDLE\n");
        return 2;
    }
    build_artifact();
    case_automatic_recovery();
    case_malformed_boot_evidence();
    case_recovery_status();
    case_recovery_abort();
    case_no_viable_reboot_denied();
    case_recovery_staging_and_abort();
    case_recovery_resource_denial();
    case_recovery_activation();
    case_administrative_entry();
    case_entry_evidence_failure();
    case_safe_reboot_handoff();
    case_recovery_request_shape();
    (void)printf(
        "{\"schema\":\"pulse.esp32.hp4_3-admin-recovery-smoke.v1\"," 
        "\"status\":\"%s\",\"case_count\":%" PRIu32 ","
        "\"failures\":%" PRIu32 ",\"engine_static_bytes\":%" PRIu32 ","
        "\"recovery_status_bytes\":%u,\"working_bytes\":%u,"
        "\"recovery_reserve_bytes\":%u,\"cases\":[",
        s_failures == 0u && s_case_count == HP43_CASE_COUNT ? "PASS" : "FAIL",
        s_case_count, s_failures, wdc_admin_recovery_static_bytes(),
        WDC_ADMIN_RECOVERY_STATUS_BYTES, WDC_ADMIN_UPDATE_WORKING_BYTES,
        WDC_ADMIN_RECOVERY_RESERVE_BYTES);
    for (index = 0u; index < s_case_count; ++index) {
        (void)printf("%s{\"name\":\"%s\",\"status\":\"%s\"}",
                     index == 0u ? "" : ",", s_cases[index].name,
                     s_cases[index].passed != 0u ? "PASS" : "FAIL");
    }
    (void)printf("]}\n");
    return s_failures == 0u && s_case_count == HP43_CASE_COUNT ? 0 : 1;
}
