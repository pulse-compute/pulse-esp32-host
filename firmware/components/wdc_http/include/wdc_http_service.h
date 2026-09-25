#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "wdc_admin.h"
#include "wdc_abi.h"

#ifdef __cplusplus
extern "C" {
#endif

/*
 * HP5 is deliberately small and fixed.  The HTTPS platform adapter owns
 * sockets, TLS material, Wi-Fi policy, and parser storage.  This service owns
 * route normalization and the one synchronous application response effect.
 */
#define WDC_HTTP_METHOD_MAX_BYTES 8u
#define WDC_HTTP_PATH_MAX_BYTES 96u
#define WDC_HTTP_REQUEST_BODY_MAX_BYTES 2048u
#define WDC_HTTP_APP_BODY_MAX_BYTES 1024u
#define WDC_HTTP_RESPONSE_BODY_MAX_BYTES 1280u
#define WDC_HTTP_APP_EVENT_MAX_BYTES 1536u
#define WDC_HTTP_APP_ROUTE_CAPACITY 4u
#define WDC_HTTP_APP_REQUEST_DEADLINE_MS 5000u
#define WDC_HTTP_ADMIN_REQUEST_DEADLINE_MS 30000u
#define WDC_HTTP_PARSER_STATIC_BUDGET_BYTES 2304u
#define WDC_HTTP_SERVICE_STATIC_BUDGET_BYTES 8192u

#define WDC_HTTP_APP_NAMESPACE "/pulse/v1/app/"
#define WDC_HTTP_ADMIN_NAMESPACE "/pulse/v1/admin/"
#define WDC_HTTP_ADMIN_SESSION_BEGIN_PATH \
    "/pulse/v1/admin/session/begin"
#define WDC_HTTP_ADMIN_SESSION_FINISH_PATH \
    "/pulse/v1/admin/session/finish"
#define WDC_HTTP_ADMIN_SESSION_PATH "/pulse/v1/admin/session"
#define WDC_HTTP_ADMIN_COMMAND_PATH "/pulse/v1/admin/command"
#define WDC_HTTP_ADMIN_TERMINAL_PATH "/pulse/v1/admin/terminal"

typedef enum WdcHttpMethod {
    WDC_HTTP_METHOD_NONE = 0,
    WDC_HTTP_METHOD_GET = 1,
    WDC_HTTP_METHOD_POST = 2,
    WDC_HTTP_METHOD_DELETE = 3,
} WdcHttpMethod;

typedef enum WdcHttpLane {
    WDC_HTTP_LANE_NONE = 0,
    WDC_HTTP_LANE_APPLICATION = 1,
    WDC_HTTP_LANE_ADMINISTRATION = 2,
} WdcHttpLane;

typedef enum WdcHttpParserState {
    WDC_HTTP_PARSER_EMPTY = 0,
    WDC_HTTP_PARSER_RECEIVING = 1,
    WDC_HTTP_PARSER_COMPLETE = 2,
    WDC_HTTP_PARSER_REJECTED = 3,
} WdcHttpParserState;

typedef struct WdcHttpRequest {
    WdcHttpMethod method;
    const char *path;
    uint32_t path_bytes;
    const uint8_t *body;
    uint32_t body_bytes;
    uint32_t declared_body_bytes;
    uint64_t received_monotonic_ms;
    uint64_t deadline_ms;
    uint8_t channel_binding_sha256[32];
    bool tls_established;
    bool client_connected;
    bool complete;
} WdcHttpRequest;

/* One fixed request normalizer.  Callers provide one instance per reserved
 * listener lane; no request-controlled allocation is performed. */
typedef struct WdcHttpParser {
    char method[WDC_HTTP_METHOD_MAX_BYTES];
    char path[WDC_HTTP_PATH_MAX_BYTES];
    uint8_t body[WDC_HTTP_REQUEST_BODY_MAX_BYTES];
    uint8_t channel_binding_sha256[32];
    WdcHttpParserState state;
    WdcHttpMethod method_id;
    uint32_t path_bytes;
    uint32_t declared_body_bytes;
    uint32_t received_body_bytes;
    uint64_t started_monotonic_ms;
    uint64_t deadline_ms;
    bool tls_established;
    bool client_connected;
} WdcHttpParser;

typedef struct WdcHttpResponse {
    uint16_t status_code;
    WdcHttpLane lane;
    uint32_t request_id;
    uint32_t body_bytes;
    bool accepted;
    bool terminal;
    char content_type[32];
    uint8_t body[WDC_HTTP_RESPONSE_BODY_MAX_BYTES];
} WdcHttpResponse;

typedef struct WdcHttpAppRoute {
    WdcHttpMethod method;
    uint32_t resource_id;
    char path[WDC_HTTP_PATH_MAX_BYTES];
} WdcHttpAppRoute;

typedef int32_t (*WdcHttpAppDispatchFn)(
    void *context,
    const uint8_t *event_cbor,
    uint32_t event_bytes,
    uint64_t deadline_ms);

typedef uint64_t (*WdcHttpClockFn)(void *context);

typedef struct WdcHttpServiceConfig {
    WdcAdminCore *admin_core;
    WdcHttpAppDispatchFn app_dispatch;
    void *app_context;
    WdcHttpClockFn clock;
    void *clock_context;
    uint32_t app_request_deadline_ms;
    uint32_t admin_request_deadline_ms;
} WdcHttpServiceConfig;

typedef struct WdcHttpServiceStats {
    uint32_t app_accepted;
    uint32_t app_completed;
    uint32_t app_cancelled;
    uint32_t app_timed_out;
    uint32_t app_trapped;
    uint32_t app_response_losses;
    uint32_t admin_requests;
    uint32_t admin_commands_accepted;
    uint32_t admin_preaccept_rejections;
    uint32_t admin_response_losses;
    uint32_t admin_terminal_losses;
    uint32_t malformed_rejections;
    uint32_t oversized_rejections;
    uint32_t slow_rejections;
    uint32_t disconnected_rejections;
    uint32_t saturated_rejections;
    uint32_t unauthorized_rejections;
    uint32_t duplicate_response_rejections;
} WdcHttpServiceStats;

typedef struct WdcHttpService {
    WdcHttpServiceConfig config;
    WdcHttpAppRoute routes[WDC_HTTP_APP_ROUTE_CAPACITY];
    WdcHttpServiceStats stats;
    WdcAdminSerialAdapter admin_frame_adapter;
    uint8_t app_event[WDC_HTTP_APP_EVENT_MAX_BYTES];
    uint8_t app_response[WDC_HTTP_APP_BODY_MAX_BYTES];
    uint32_t route_count;
    uint32_t next_request_id;
    uint64_t next_challenge_id;
    uint64_t active_app_deadline_ms;
    uint32_t active_app_request_id;
    uint32_t app_response_bytes;
    uint16_t app_response_status;
    bool initialized;
    bool started;
    bool app_active;
    bool admin_active;
    bool app_response_ready;
    bool app_cancelled;
} WdcHttpService;

const char *wdc_http_method_name(WdcHttpMethod method);
WdcHttpMethod wdc_http_method_from_text(const char *method);

int32_t wdc_http_parser_begin(WdcHttpParser *parser,
                              const char *method,
                              const char *path,
                              uint32_t declared_body_bytes,
                              bool tls_established,
                              bool client_connected,
                              const uint8_t channel_binding_sha256[32],
                              uint64_t now_ms,
                              uint64_t deadline_ms);
int32_t wdc_http_parser_feed(WdcHttpParser *parser,
                             const uint8_t *bytes,
                             uint32_t bytes_len,
                             uint64_t now_ms,
                             uint32_t *out_consumed);
int32_t wdc_http_parser_take(const WdcHttpParser *parser,
                             WdcHttpRequest *out_request);
void wdc_http_parser_reset(WdcHttpParser *parser);

int32_t wdc_http_service_init(WdcHttpService *service,
                              const WdcHttpServiceConfig *config);
int32_t wdc_http_service_register_app_route(WdcHttpService *service,
                                            WdcHttpMethod method,
                                            const char *path,
                                            uint32_t resource_id);
int32_t wdc_http_service_start(WdcHttpService *service);
void wdc_http_service_stop(WdcHttpService *service);
int32_t wdc_http_service_handle(WdcHttpService *service,
                                const WdcHttpRequest *request,
                                WdcHttpResponse *out_response);
int32_t wdc_http_service_cancel_app(WdcHttpService *service,
                                    uint32_t request_id);
void wdc_http_service_note_send_result(WdcHttpService *service,
                                       const WdcHttpResponse *response,
                                       int32_t send_status);
void wdc_http_service_get_stats(const WdcHttpService *service,
                                WdcHttpServiceStats *out_stats);

/* Used only while the common Wasm event handler is active. */
int32_t wdc_http_service_guest_response_host_call(
    void *context,
    const uint8_t *request,
    uint32_t request_len,
    uint8_t *response,
    uint32_t response_cap,
    uint32_t *out_response_len);

/* WdcHttpAppDispatchFn adapter for WdcRuntime. */
int32_t wdc_http_runtime_dispatch(void *context,
                                  const uint8_t *event_cbor,
                                  uint32_t event_bytes,
                                  uint64_t deadline_ms);

uint32_t wdc_http_service_link_anchor(void);

#ifdef __cplusplus
}
#endif
