#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "wdc_admin.h"
#include "wdc_caps.h"
#include "wdc_control.h"
#include "wdc_http_service.h"
#include "wdc_net.h"
#include "wdc_profile.h"
#include "wdc_runtime.h"
#include "wdc_static_wasm.h"

#define HP5_NATIVE_CASES 35u

static uint32_t s_cases;
static uint32_t s_failures;
static uint64_t s_now_ms = 1000u;

#define CHECK(expression)                                                     \
    do {                                                                      \
        s_cases += 1u;                                                        \
        if (!(expression)) {                                                  \
            s_failures += 1u;                                                 \
            (void)fprintf(stderr, "check failed at %s:%d: %s\n", __FILE__,  \
                          __LINE__, #expression);                             \
        }                                                                     \
    } while (0)

typedef enum AppMode {
    APP_MODE_RESPOND = 0,
    APP_MODE_DUPLICATE = 1,
    APP_MODE_NO_RESPONSE = 2,
    APP_MODE_TRAP = 3,
    APP_MODE_TIMEOUT = 4,
    APP_MODE_CANCEL = 5,
} AppMode;

typedef struct AppHarness {
    WdcHttpService *service;
    AppMode mode;
    int32_t first_guest_status;
    int32_t second_guest_status;
    uint32_t observed_request_id;
    uint32_t observed_event_type;
    uint32_t observed_body_bytes;
} AppHarness;

static uint64_t clock_now(void *context)
{
    (void)context;
    return s_now_ms;
}

static int32_t cbor_status(const uint8_t *response, uint32_t response_bytes)
{
    int32_t status = WDC_ERR_BAD_ENCODING;
    if (wdc_cbor_map_find_i32(response, response_bytes, WDC_CBOR_KEY_STATUS,
                              &status) != WDC_OK) {
        return WDC_ERR_BAD_ENCODING;
    }
    return status;
}

static int32_t guest_respond(uint32_t request_id, uint32_t http_status,
                             const uint8_t *body, uint32_t body_bytes)
{
    uint8_t request[128];
    uint8_t response[32];
    uint32_t response_bytes = 0u;
    WdcCborBuilder builder;
    int32_t status;
    wdc_cbor_builder_init(&builder, request, sizeof(request));
    status = wdc_cbor_begin_map(&builder, 4u);
    if (status == WDC_OK) {
        status = wdc_cbor_put_key_u32(&builder, WDC_CBOR_KEY_RESOURCE_ID,
                                      WDC_R8_RESOURCE_HTTP_API);
    }
    if (status == WDC_OK) {
        status = wdc_cbor_put_key_u32(&builder, WDC_CBOR_KEY_REQUEST_ID,
                                      request_id);
    }
    if (status == WDC_OK) {
        status = wdc_cbor_put_key_u32(&builder, WDC_CBOR_KEY_HTTP_STATUS,
                                      http_status);
    }
    if (status == WDC_OK) {
        status = wdc_cbor_put_key_bytes(&builder, WDC_CBOR_KEY_DATA, body,
                                        body_bytes);
    }
    if (status != WDC_OK) {
        return status;
    }
    status = wdc_host_call_dispatch(WDC_OP_HTTP_RESPOND, request,
                                    wdc_cbor_len(&builder), response,
                                    sizeof(response), &response_bytes);
    return status == WDC_OK ? cbor_status(response, response_bytes) : status;
}

static int32_t app_event_hook(void *context, const uint8_t *event_cbor,
                              uint32_t event_bytes)
{
    AppHarness *app = (AppHarness *)context;
    WdcCborBytes body = {0};
    uint32_t request_id = 0u;
    uint32_t event_type = 0u;
    uint64_t deadline_ms = 0u;
    if (app == NULL ||
        wdc_cbor_map_find_u32(event_cbor, event_bytes,
                              WDC_CBOR_KEY_REQUEST_ID,
                              &request_id) != WDC_OK ||
        wdc_cbor_map_find_u32(event_cbor, event_bytes,
                              WDC_CBOR_KEY_EVENT_TYPE,
                              &event_type) != WDC_OK ||
        wdc_cbor_map_find_u64(event_cbor, event_bytes,
                              WDC_CBOR_KEY_DEADLINE_MS,
                              &deadline_ms) != WDC_OK ||
        wdc_cbor_map_find_bytes(event_cbor, event_bytes,
                                WDC_CBOR_KEY_DATA, &body) != WDC_OK) {
        return WDC_ERR_BAD_ENCODING;
    }
    app->observed_request_id = request_id;
    app->observed_event_type = event_type;
    app->observed_body_bytes = body.len;
    if (app->mode == APP_MODE_TRAP) {
        return WDC_ERR_CONTRACT_VIOLATION;
    }
    if (app->mode == APP_MODE_NO_RESPONSE) {
        return WDC_OK;
    }
    if (app->mode == APP_MODE_TIMEOUT) {
        s_now_ms = deadline_ms;
    }
    if (app->mode == APP_MODE_CANCEL) {
        (void)wdc_http_service_cancel_app(app->service, request_id);
    }
    app->first_guest_status = guest_respond(
        request_id, app->mode == APP_MODE_DUPLICATE ? 201u : 200u,
        (const uint8_t *)"pong", 4u);
    if (app->mode == APP_MODE_DUPLICATE) {
        app->second_guest_status = guest_respond(
            request_id, 202u, (const uint8_t *)"late", 4u);
    }
    return WDC_OK;
}

static int32_t admin_authorize(
    void *context, const WdcAdminAuthorizationChallenge *challenge,
    const uint8_t *proof, uint32_t proof_bytes,
    WdcAdminAuthenticatedEntry *out_entry)
{
    uint64_t *epoch = (uint64_t *)context;
    if (challenge == NULL || out_entry == NULL || epoch == NULL ||
        proof_bytes != 5u || proof == NULL ||
        memcmp(proof, "proof", 5u) != 0) {
        return WDC_ERR_CAPABILITY_DENIED;
    }
    memset(out_entry, 0, sizeof(*out_entry));
    out_entry->struct_size = sizeof(*out_entry);
    out_entry->version_major = WDC_ADMIN_VERSION_MAJOR;
    out_entry->version_minor = WDC_ADMIN_VERSION_MINOR;
    out_entry->transport_kind = challenge->start.transport_kind;
    out_entry->authorization_method = challenge->start.authorization_method;
    out_entry->privilege_mask = WDC_ADMIN_PRIVILEGE_ALL;
    out_entry->authorization_epoch = ++(*epoch);
    out_entry->issued_monotonic_ms = s_now_ms;
    out_entry->expires_monotonic_ms = s_now_ms + 60000u;
    out_entry->session_nonce = 0x5a5a0000u + *epoch;
    memset(out_entry->principal_sha256, 0x31, 32u);
    memcpy(out_entry->channel_binding_sha256,
           challenge->start.channel_binding_sha256, 32u);
    return WDC_OK;
}

static int32_t artifact_verify(void *context,
                               const WdcAdminArtifactCandidate *candidate,
                               WdcAdminArtifactVerification *out_verification)
{
    (void)context;
    (void)candidate;
    if (out_verification == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    memset(out_verification, 0, sizeof(*out_verification));
    out_verification->struct_size = sizeof(*out_verification);
    out_verification->version_major = WDC_ADMIN_VERSION_MAJOR;
    out_verification->version_minor = WDC_ADMIN_VERSION_MINOR;
    out_verification->status = WDC_OK;
    out_verification->complete_artifact_valid = 1u;
    out_verification->host_compatible = 1u;
    out_verification->security_floor_valid = 1u;
    out_verification->artifact_authority_valid = 1u;
    return WDC_OK;
}

static void put_u16_le(uint8_t *bytes, uint16_t value)
{
    bytes[0] = (uint8_t)(value & 0xffu);
    bytes[1] = (uint8_t)((value >> 8u) & 0xffu);
}

static void put_u32_le(uint8_t *bytes, uint32_t value)
{
    bytes[0] = (uint8_t)(value & 0xffu);
    bytes[1] = (uint8_t)((value >> 8u) & 0xffu);
    bytes[2] = (uint8_t)((value >> 16u) & 0xffu);
    bytes[3] = (uint8_t)((value >> 24u) & 0xffu);
}

static void put_u64_le(uint8_t *bytes, uint64_t value)
{
    put_u32_le(bytes, (uint32_t)value);
    put_u32_le(bytes + 4u, (uint32_t)(value >> 32u));
}

static uint32_t make_status_frame(uint8_t *frame, uint64_t request_id,
                                  uint64_t epoch, uint64_t nonce,
                                  uint64_t sequence)
{
    uint8_t *request = frame + 4u;
    memset(frame, 0, 4u + WDC_ADMIN_REQUEST_BYTES);
    put_u32_le(frame, WDC_ADMIN_REQUEST_BYTES);
    put_u32_le(request + 0u, WDC_ADMIN_REQUEST_BYTES);
    put_u16_le(request + 4u, WDC_ADMIN_VERSION_MAJOR);
    put_u16_le(request + 6u, WDC_ADMIN_VERSION_MINOR);
    put_u32_le(request + 8u, WDC_ADMIN_COMMAND_STATUS);
    put_u32_le(request + 20u, WDC_ADMIN_SLOT_NONE);
    put_u64_le(request + 32u, request_id);
    put_u64_le(request + 40u, s_now_ms + 1000u);
    put_u64_le(request + 48u, epoch);
    put_u64_le(request + 56u, nonce);
    put_u64_le(request + 64u, sequence);
    return 4u + WDC_ADMIN_REQUEST_BYTES;
}

static int32_t make_request(WdcHttpParser *parser, const char *method,
                            const char *path, const uint8_t *body,
                            uint32_t body_bytes,
                            const uint8_t binding[32],
                            uint32_t deadline_delta,
                            WdcHttpRequest *out_request)
{
    uint32_t consumed = 0u;
    int32_t status = wdc_http_parser_begin(
        parser, method, path, body_bytes, true, true, binding, s_now_ms,
        s_now_ms + deadline_delta);
    if (status == WDC_OK && body_bytes != 0u) {
        status = wdc_http_parser_feed(parser, body, body_bytes, s_now_ms,
                                      &consumed);
        if (status == WDC_OK && consumed != body_bytes) {
            status = WDC_ERR_CONTRACT_VIOLATION;
        }
    }
    return status == WDC_OK ? wdc_http_parser_take(parser, out_request) :
                              status;
}

static void run_parser_cases(const uint8_t binding[32])
{
    WdcHttpParser parser;
    WdcHttpRequest request;
    uint8_t body[4] = {1u, 2u, 3u, 4u};
    uint32_t consumed = 0u;
    CHECK(sizeof(parser) <= WDC_HTTP_PARSER_STATIC_BUDGET_BYTES);
    CHECK(wdc_http_parser_begin(&parser, "POST", "/pulse/v1/app/echo",
                                WDC_HTTP_REQUEST_BODY_MAX_BYTES + 1u, true,
                                true, binding, 1u, 2u) == WDC_ERR_BAD_LENGTH);
    CHECK(wdc_http_parser_begin(&parser, "POST", "/pulse/v1/app/echo", 0u,
                                false, true, binding, 1u, 2u) ==
          WDC_ERR_CAPABILITY_DENIED);
    CHECK(wdc_http_parser_begin(&parser, "POST", "/pulse/v1/app/%65cho", 0u,
                                true, true, binding, 1u, 2u) ==
          WDC_ERR_BAD_ENCODING);
    CHECK(wdc_http_parser_begin(&parser, "POST", "/pulse/v1/app/echo", 4u,
                                true, true, binding, 10u, 11u) == WDC_OK &&
          wdc_http_parser_feed(&parser, body, 1u, 11u, &consumed) ==
              WDC_ERR_TIMEOUT);
    CHECK(wdc_http_parser_begin(&parser, "POST", "/pulse/v1/app/echo", 4u,
                                true, true, binding, 10u, 20u) == WDC_OK &&
          wdc_http_parser_feed(&parser, body, 4u, 10u, &consumed) == WDC_OK &&
          consumed == 4u &&
          wdc_http_parser_take(&parser, &request) == WDC_OK &&
          request.body_bytes == 4u);
}

static void complete_status_command(WdcAdminCore *core,
                                    WdcControlKernel *kernel)
{
    WdcControlWorkItem work;
    WdcAdminAcceptedCommand command;
    WdcAdminTerminalMetadata metadata;
    uint8_t response[4] = {'o', 'k', 0u, 0u};
    memset(&work, 0, sizeof(work));
    memset(&command, 0, sizeof(command));
    memset(&metadata, 0, sizeof(metadata));
    if (wdc_control_next(kernel, &work) != WDC_OK ||
        wdc_admin_begin_command(core, &work, s_now_ms, &command) != WDC_OK ||
        wdc_admin_write_response(core, response, 2u) != WDC_OK) {
        s_failures += 1u;
        return;
    }
    metadata.final_state = (uint32_t)wdc_admin_mode(core);
    metadata.slot = WDC_ADMIN_SLOT_NONE;
    if (wdc_admin_complete(core, WDC_ADMIN_TERMINAL_SUCCEEDED, WDC_OK,
                           &metadata, s_now_ms) != WDC_OK) {
        s_failures += 1u;
    }
}

int main(void)
{
    WdcControlKernel kernel;
    WdcAdminCore core;
    WdcAdminCoreConfig core_config;
    WdcHttpService service;
    WdcHttpServiceConfig service_config;
    WdcHttpParser parser;
    WdcHttpRequest request;
    WdcHttpResponse response;
    WdcHttpServiceStats stats;
    AppHarness app;
    WdcRuntime runtime;
    WdcRuntimeConfig runtime_config;
    uint8_t binding[32];
    uint8_t wrong_binding[32];
    uint8_t frame[4u + WDC_ADMIN_REQUEST_BYTES];
    uint64_t epoch_counter = 40u;
    uint64_t session_epoch;
    uint64_t session_nonce;
    uint32_t frame_bytes;
    uint64_t sequence_before;
    int32_t status;

    memset(binding, 0x42, sizeof(binding));
    memset(wrong_binding, 0x24, sizeof(wrong_binding));
    run_parser_cases(binding);

    memset(&kernel, 0, sizeof(kernel));
    CHECK(wdc_control_kernel_init(&kernel,
                                  wdc_control_profile_c6_minimum()) == WDC_OK);
    memset(&core_config, 0, sizeof(core_config));
    core_config.control_kernel = &kernel;
    core_config.authorizer.authorize = admin_authorize;
    core_config.authorizer.context = &epoch_counter;
    core_config.artifact_verifier.verify = artifact_verify;
    core_config.initial_mode = WDC_ADMIN_MODE_NORMAL;
    core_config.enabled_commands_mask = WDC_ADMIN_HP43_COMMAND_MASK;
    memcpy(core_config.boot_channel_binding_sha256, binding, sizeof(binding));
    CHECK(wdc_admin_core_init(&core, &core_config) == WDC_OK);

    memset(&app, 0, sizeof(app));
    memset(&runtime, 0, sizeof(runtime));
    runtime_config = wdc_runtime_default_config();
    CHECK(wdc_runtime_init(&runtime, &runtime_config) == WDC_OK &&
          wdc_runtime_load_static(&runtime, wdc_static_hello_wasm,
                                  wdc_static_hello_wasm_len) == WDC_OK &&
          wdc_runtime_lookup_exports(&runtime) == WDC_OK &&
          wdc_runtime_call_init(&runtime) == WDC_OK);
    wdc_runtime_set_host_stub_event_hook(&runtime, app_event_hook, &app);
    memset(&service_config, 0, sizeof(service_config));
    service_config.admin_core = &core;
    service_config.app_dispatch = wdc_http_runtime_dispatch;
    service_config.app_context = &runtime;
    service_config.clock = clock_now;
    CHECK(wdc_http_service_init(&service, &service_config) == WDC_OK &&
          sizeof(service) <= WDC_HTTP_SERVICE_STATIC_BUDGET_BYTES);
    app.service = &service;
    CHECK(wdc_http_service_register_app_route(
              &service, WDC_HTTP_METHOD_POST, "/pulse/v1/admin/shadow",
              WDC_R8_RESOURCE_HTTP_API) == WDC_ERR_CAPABILITY_DENIED);
    CHECK(wdc_http_service_register_app_route(
              &service, WDC_HTTP_METHOD_POST, "/pulse/v1/app/echo",
              WDC_R8_RESOURCE_HTTP_API) == WDC_OK &&
          wdc_http_service_register_app_route(
              &service, WDC_HTTP_METHOD_POST, "/pulse/v1/app/echo",
              WDC_R8_RESOURCE_HTTP_API) == WDC_ERR_CONTRACT_VIOLATION &&
          wdc_http_service_start(&service) == WDC_OK);

    CHECK(wdc_net_init(wdc_profile_builtin()) == WDC_OK &&
          wdc_caps_install_host_authorizer(
              wdc_profile_builtin(), wdc_caps_builtin_relay_full()) == WDC_OK);

    app.mode = APP_MODE_RESPOND;
    CHECK(make_request(&parser, "POST", "/pulse/v1/app/echo",
                       (const uint8_t *)"ping", 4u, binding, 1000u,
                       &request) == WDC_OK &&
          wdc_http_service_handle(&service, &request, &response) == WDC_OK &&
          response.status_code == 200u && response.body_bytes == 4u &&
          memcmp(response.body, "pong", 4u) == 0 &&
          app.first_guest_status == WDC_OK &&
          app.observed_event_type == WDC_EVENT_HTTP_REQUEST);

    app.mode = APP_MODE_DUPLICATE;
    CHECK(make_request(&parser, "POST", "/pulse/v1/app/echo", NULL, 0u,
                       binding, 1000u, &request) == WDC_OK &&
          wdc_http_service_handle(&service, &request, &response) == WDC_OK &&
          response.status_code == 201u && app.first_guest_status == WDC_OK &&
          app.second_guest_status == WDC_ERR_CONTRACT_VIOLATION);

    app.mode = APP_MODE_NO_RESPONSE;
    CHECK(make_request(&parser, "POST", "/pulse/v1/app/echo", NULL, 0u,
                       binding, 1000u, &request) == WDC_OK &&
          wdc_http_service_handle(&service, &request, &response) == WDC_OK &&
          response.status_code == 204u && response.terminal);

    app.mode = APP_MODE_TRAP;
    CHECK(make_request(&parser, "POST", "/pulse/v1/app/echo", NULL, 0u,
                       binding, 1000u, &request) == WDC_OK &&
          wdc_http_service_handle(&service, &request, &response) == WDC_OK &&
          response.status_code == 500u && response.terminal);

    app.mode = APP_MODE_CANCEL;
    CHECK(make_request(&parser, "POST", "/pulse/v1/app/echo", NULL, 0u,
                       binding, 1000u, &request) == WDC_OK &&
          wdc_http_service_handle(&service, &request, &response) == WDC_OK &&
          response.status_code == 499u &&
          app.first_guest_status == WDC_ERR_NOT_SYNCHRONIZED);

    app.mode = APP_MODE_TIMEOUT;
    s_now_ms = 2000u;
    CHECK(make_request(&parser, "POST", "/pulse/v1/app/echo", NULL, 0u,
                       binding, 10u, &request) == WDC_OK &&
          wdc_http_service_handle(&service, &request, &response) == WDC_OK &&
          response.status_code == 504u &&
          app.first_guest_status == WDC_ERR_TIMEOUT);
    s_now_ms = 3000u;

    CHECK(make_request(&parser, "POST", WDC_HTTP_ADMIN_SESSION_BEGIN_PATH,
                       NULL, 0u, wrong_binding, 1000u, &request) == WDC_OK &&
          wdc_http_service_handle(&service, &request, &response) == WDC_OK &&
          response.status_code == 401u &&
          wdc_admin_authorization_state(&core) ==
              WDC_ADMIN_AUTH_UNAUTHENTICATED);

    service.app_active = true;
    CHECK(make_request(&parser, "POST", WDC_HTTP_ADMIN_SESSION_BEGIN_PATH,
                       NULL, 0u, binding, 1000u, &request) == WDC_OK &&
          wdc_http_service_handle(&service, &request, &response) == WDC_OK &&
          response.status_code == 200u &&
          wdc_admin_authorization_state(&core) ==
              WDC_ADMIN_AUTH_CHALLENGE_ISSUED);
    service.app_active = false;

    CHECK(make_request(&parser, "POST", WDC_HTTP_ADMIN_SESSION_FINISH_PATH,
                       (const uint8_t *)"wrong", 5u, binding, 1000u,
                       &request) == WDC_OK &&
          wdc_http_service_handle(&service, &request, &response) == WDC_OK &&
          response.status_code == 401u &&
          wdc_admin_authorization_state(&core) ==
              WDC_ADMIN_AUTH_UNAUTHENTICATED);

    CHECK(make_request(&parser, "POST", WDC_HTTP_ADMIN_SESSION_BEGIN_PATH,
                       NULL, 0u, binding, 1000u, &request) == WDC_OK &&
          wdc_http_service_handle(&service, &request, &response) == WDC_OK &&
          response.status_code == 200u &&
          make_request(&parser, "POST", WDC_HTTP_ADMIN_SESSION_FINISH_PATH,
                       (const uint8_t *)"proof", 5u, binding, 1000u,
                       &request) == WDC_OK &&
          wdc_http_service_handle(&service, &request, &response) == WDC_OK &&
          response.status_code == 200u &&
          wdc_admin_authorization_state(&core) == WDC_ADMIN_AUTH_AUTHORIZED &&
          core.session.transport_kind ==
              WDC_ADMIN_TRANSPORT_AUTHENTICATED_EXTERNAL_V1);
    session_epoch = core.session.authorization_epoch;
    session_nonce = core.session.session_nonce;

    frame_bytes = make_status_frame(frame, 0x101u, session_epoch,
                                    session_nonce, 1u);
    CHECK(make_request(&parser, "POST", WDC_HTTP_ADMIN_COMMAND_PATH, frame,
                       frame_bytes, binding, 1000u, &request) == WDC_OK &&
          wdc_http_service_handle(&service, &request, &response) == WDC_OK &&
          response.status_code == 202u && response.accepted &&
          wdc_admin_command_lifecycle(&core) ==
              WDC_ADMIN_LIFECYCLE_ACCEPTED);

    complete_status_command(&core, &kernel);
    CHECK(make_request(&parser, "GET", WDC_HTTP_ADMIN_TERMINAL_PATH, NULL, 0u,
                       binding, 1000u, &request) == WDC_OK &&
          wdc_http_service_handle(&service, &request, &response) == WDC_OK &&
          response.status_code == 200u && response.terminal &&
          wdc_admin_command_lifecycle(&core) == WDC_ADMIN_LIFECYCLE_NONE);
    wdc_http_service_note_send_result(&service, &response,
                                      WDC_ERR_NOT_SYNCHRONIZED);
    CHECK(make_request(&parser, "GET", WDC_HTTP_ADMIN_TERMINAL_PATH, NULL, 0u,
                       binding, 1000u, &request) == WDC_OK &&
          wdc_http_service_handle(&service, &request, &response) == WDC_OK &&
          response.status_code == 404u);

    sequence_before = wdc_admin_next_command_sequence(&core);
    CHECK(make_request(&parser, "POST", WDC_HTTP_ADMIN_COMMAND_PATH, frame,
                       frame_bytes, binding, 1000u, &request) == WDC_OK &&
          wdc_http_service_handle(&service, &request, &response) == WDC_OK &&
          response.status_code == 409u &&
          wdc_admin_next_command_sequence(&core) == sequence_before &&
          wdc_admin_command_lifecycle(&core) == WDC_ADMIN_LIFECYCLE_NONE);

    frame_bytes = make_status_frame(frame, 0x102u, session_epoch,
                                    session_nonce, 2u);
    CHECK(make_request(&parser, "POST", WDC_HTTP_ADMIN_COMMAND_PATH, frame,
                       frame_bytes, binding, 1000u, &request) == WDC_OK);
    request.client_connected = false;
    CHECK(wdc_http_service_handle(&service, &request, &response) == WDC_OK &&
          response.status_code == 499u &&
          wdc_admin_next_command_sequence(&core) == sequence_before);

    CHECK(make_request(&parser, "POST", WDC_HTTP_ADMIN_COMMAND_PATH, frame,
                       frame_bytes, binding, 1000u, &request) == WDC_OK &&
          wdc_http_service_handle(&service, &request, &response) == WDC_OK &&
          response.status_code == 202u);
    wdc_http_service_note_send_result(&service, &response,
                                      WDC_ERR_NOT_SYNCHRONIZED);
    CHECK(wdc_admin_command_lifecycle(&core) ==
          WDC_ADMIN_LIFECYCLE_ACCEPTED);
    complete_status_command(&core, &kernel);
    CHECK(make_request(&parser, "GET", WDC_HTTP_ADMIN_TERMINAL_PATH, NULL, 0u,
                       binding, 1000u, &request) == WDC_OK &&
          wdc_http_service_handle(&service, &request, &response) == WDC_OK &&
          response.status_code == 200u && wdc_admin_mode(&core) ==
                                               WDC_ADMIN_MODE_NORMAL);

    status = guest_respond(77u, 200u, NULL, 0u);
    CHECK(status == WDC_ERR_INVALID_STATE);
    wdc_http_service_get_stats(&service, &stats);
    CHECK(stats.app_accepted == 6u && stats.app_completed == 3u &&
          stats.app_cancelled == 1u && stats.app_timed_out == 1u &&
          stats.app_trapped == 1u &&
          stats.duplicate_response_rejections == 1u);
    CHECK(stats.admin_commands_accepted == 2u &&
          stats.admin_terminal_losses == 1u &&
          stats.admin_response_losses == 2u &&
          stats.disconnected_rejections == 1u);

    wdc_caps_clear_host_authorizer();
    wdc_net_reset_for_test();
    wdc_runtime_teardown(&runtime);
    (void)printf(
        "{\"schema\":\"pulse.esp32.hp5-http-service-smoke.v1\","
        "\"status\":\"%s\",\"case_count\":%u,\"failures\":%u,"
        "\"fixed_parser\":true,\"separate_admin_lane\":true,"
        "\"external_entry_reuses_hp4\":true,"
        "\"first_response_wins\":true,"
        "\"network_loss_does_not_rollback\":true}\n",
        s_failures == 0u && s_cases == HP5_NATIVE_CASES ? "PASS" : "FAIL",
        s_cases, s_failures);
    return s_failures == 0u && s_cases == HP5_NATIVE_CASES ? 0 : 1;
}
