#include "wdc_http_service.h"

#include "wdc_net.h"

#include <limits.h>
#include <string.h>

_Static_assert(sizeof(WdcHttpParser) <= WDC_HTTP_PARSER_STATIC_BUDGET_BYTES,
               "HP5 request parser exceeds its fixed budget");
_Static_assert(sizeof(WdcHttpService) <= WDC_HTTP_SERVICE_STATIC_BUDGET_BYTES,
               "HP5 HTTP service exceeds its fixed budget");

static WdcHttpService *s_active_app_service;

static bool bytes_are_zero(const uint8_t *bytes, uint32_t count)
{
    uint8_t aggregate = 0u;
    uint32_t index;
    if (bytes == NULL) {
        return true;
    }
    for (index = 0u; index < count; ++index) {
        aggregate |= bytes[index];
    }
    return aggregate == 0u;
}

const char *wdc_http_method_name(WdcHttpMethod method)
{
    switch (method) {
    case WDC_HTTP_METHOD_GET: return "GET";
    case WDC_HTTP_METHOD_POST: return "POST";
    case WDC_HTTP_METHOD_DELETE: return "DELETE";
    default: return "";
    }
}

WdcHttpMethod wdc_http_method_from_text(const char *method)
{
    if (method == NULL) {
        return WDC_HTTP_METHOD_NONE;
    }
    if (strcmp(method, "GET") == 0) {
        return WDC_HTTP_METHOD_GET;
    }
    if (strcmp(method, "POST") == 0) {
        return WDC_HTTP_METHOD_POST;
    }
    if (strcmp(method, "DELETE") == 0) {
        return WDC_HTTP_METHOD_DELETE;
    }
    return WDC_HTTP_METHOD_NONE;
}

static bool path_is_canonical(const char *path, uint32_t path_bytes)
{
    uint32_t index;
    if (path == NULL || path_bytes < 2u ||
        path_bytes >= WDC_HTTP_PATH_MAX_BYTES || path[0] != '/' ||
        path[path_bytes] != '\0') {
        return false;
    }
    for (index = 0u; index < path_bytes; ++index) {
        unsigned char value = (unsigned char)path[index];
        if (value < 0x21u || value > 0x7eu || value == '\\' || value == '%' ||
            value == '?' || value == '#') {
            return false;
        }
        if (value == '/' && index != 0u && path[index - 1u] == '/') {
            return false;
        }
    }
    return true;
}

void wdc_http_parser_reset(WdcHttpParser *parser)
{
    if (parser != NULL) {
        memset(parser, 0, sizeof(*parser));
    }
}

int32_t wdc_http_parser_begin(WdcHttpParser *parser,
                              const char *method,
                              const char *path,
                              uint32_t declared_body_bytes,
                              bool tls_established,
                              bool client_connected,
                              const uint8_t channel_binding_sha256[32],
                              uint64_t now_ms,
                              uint64_t deadline_ms)
{
    size_t method_bytes;
    size_t path_bytes;
    WdcHttpMethod method_id;
    if (parser == NULL || method == NULL || path == NULL ||
        channel_binding_sha256 == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    wdc_http_parser_reset(parser);
    method_bytes = strlen(method);
    path_bytes = strlen(path);
    method_id = wdc_http_method_from_text(method);
    if (method_id == WDC_HTTP_METHOD_NONE || method_bytes == 0u ||
        method_bytes >= WDC_HTTP_METHOD_MAX_BYTES ||
        path_bytes >= WDC_HTTP_PATH_MAX_BYTES ||
        !path_is_canonical(path, (uint32_t)path_bytes)) {
        parser->state = WDC_HTTP_PARSER_REJECTED;
        return WDC_ERR_BAD_ENCODING;
    }
    if (declared_body_bytes > WDC_HTTP_REQUEST_BODY_MAX_BYTES) {
        parser->state = WDC_HTTP_PARSER_REJECTED;
        return WDC_ERR_BAD_LENGTH;
    }
    if (!tls_established || !client_connected || deadline_ms <= now_ms) {
        parser->state = WDC_HTTP_PARSER_REJECTED;
        return !client_connected ? WDC_ERR_NOT_SYNCHRONIZED :
               (!tls_established ? WDC_ERR_CAPABILITY_DENIED : WDC_ERR_TIMEOUT);
    }
    memcpy(parser->method, method, method_bytes + 1u);
    memcpy(parser->path, path, path_bytes + 1u);
    memcpy(parser->channel_binding_sha256, channel_binding_sha256,
           sizeof(parser->channel_binding_sha256));
    parser->method_id = method_id;
    parser->path_bytes = (uint32_t)path_bytes;
    parser->declared_body_bytes = declared_body_bytes;
    parser->started_monotonic_ms = now_ms;
    parser->deadline_ms = deadline_ms;
    parser->tls_established = tls_established;
    parser->client_connected = client_connected;
    parser->state = declared_body_bytes == 0u ?
        WDC_HTTP_PARSER_COMPLETE : WDC_HTTP_PARSER_RECEIVING;
    return WDC_OK;
}

int32_t wdc_http_parser_feed(WdcHttpParser *parser,
                             const uint8_t *bytes,
                             uint32_t bytes_len,
                             uint64_t now_ms,
                             uint32_t *out_consumed)
{
    uint32_t remaining;
    uint32_t consume;
    if (parser == NULL || out_consumed == NULL ||
        (bytes_len != 0u && bytes == NULL)) {
        return WDC_ERR_BAD_POINTER;
    }
    *out_consumed = 0u;
    if (parser->state != WDC_HTTP_PARSER_RECEIVING) {
        return WDC_ERR_INVALID_STATE;
    }
    if (!parser->client_connected) {
        parser->state = WDC_HTTP_PARSER_REJECTED;
        return WDC_ERR_NOT_SYNCHRONIZED;
    }
    if (now_ms >= parser->deadline_ms) {
        parser->state = WDC_HTTP_PARSER_REJECTED;
        return WDC_ERR_TIMEOUT;
    }
    remaining = parser->declared_body_bytes - parser->received_body_bytes;
    if (bytes_len > remaining) {
        parser->state = WDC_HTTP_PARSER_REJECTED;
        return WDC_ERR_BAD_LENGTH;
    }
    consume = bytes_len;
    if (consume != 0u) {
        memcpy(parser->body + parser->received_body_bytes, bytes, consume);
        parser->received_body_bytes += consume;
        *out_consumed = consume;
    }
    if (parser->received_body_bytes == parser->declared_body_bytes) {
        parser->state = WDC_HTTP_PARSER_COMPLETE;
    }
    return WDC_OK;
}

int32_t wdc_http_parser_take(const WdcHttpParser *parser,
                             WdcHttpRequest *out_request)
{
    if (parser == NULL || out_request == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    if (parser->state != WDC_HTTP_PARSER_COMPLETE ||
        parser->received_body_bytes != parser->declared_body_bytes) {
        return WDC_ERR_INVALID_STATE;
    }
    memset(out_request, 0, sizeof(*out_request));
    out_request->method = parser->method_id;
    out_request->path = parser->path;
    out_request->path_bytes = parser->path_bytes;
    out_request->body = parser->declared_body_bytes != 0u ? parser->body : NULL;
    out_request->body_bytes = parser->declared_body_bytes;
    out_request->declared_body_bytes = parser->declared_body_bytes;
    out_request->received_monotonic_ms = parser->started_monotonic_ms;
    out_request->deadline_ms = parser->deadline_ms;
    memcpy(out_request->channel_binding_sha256,
           parser->channel_binding_sha256,
           sizeof(out_request->channel_binding_sha256));
    out_request->tls_established = parser->tls_established;
    out_request->client_connected = parser->client_connected;
    out_request->complete = true;
    return WDC_OK;
}

static void response_init(WdcHttpResponse *response, WdcHttpLane lane,
                          uint16_t status_code)
{
    memset(response, 0, sizeof(*response));
    response->lane = lane;
    response->status_code = status_code;
    (void)memcpy(response->content_type, "application/cbor", 17u);
}

static int32_t finish_builder(WdcCborBuilder *builder,
                              WdcHttpResponse *response)
{
    response->body_bytes = wdc_cbor_len(builder);
    return WDC_OK;
}

static int32_t status_response(WdcHttpResponse *response,
                               WdcHttpLane lane,
                               uint16_t http_status,
                               int32_t status,
                               uint32_t request_id)
{
    WdcCborBuilder builder;
    int32_t result;
    response_init(response, lane, http_status);
    response->request_id = request_id;
    wdc_cbor_builder_init(&builder, response->body, sizeof(response->body));
    result = wdc_cbor_begin_map(&builder, request_id != 0u ? 2u : 1u);
    if (result == WDC_OK) {
        result = wdc_cbor_put_key_i32(&builder, WDC_CBOR_KEY_STATUS, status);
    }
    if (result == WDC_OK && request_id != 0u) {
        result = wdc_cbor_put_key_u32(&builder, WDC_CBOR_KEY_REQUEST_ID,
                                      request_id);
    }
    return result == WDC_OK ? finish_builder(&builder, response) : result;
}

static uint16_t http_status_for_error(int32_t status,
                                      WdcAdminPreacceptRejection rejection)
{
    if (rejection == WDC_ADMIN_REJECTION_UNAUTHORIZED ||
        rejection == WDC_ADMIN_REJECTION_EXPIRED ||
        status == WDC_ERR_CAPABILITY_DENIED) {
        return 401u;
    }
    if (rejection == WDC_ADMIN_REJECTION_RATE_LIMITED ||
        status == WDC_ERR_RATE_LIMITED) {
        return 429u;
    }
    if (rejection == WDC_ADMIN_REJECTION_BUSY || status == WDC_ERR_BUSY ||
        status == WDC_ERR_NO_MEMORY) {
        return 503u;
    }
    if (rejection == WDC_ADMIN_REJECTION_STALE_REPLAY ||
        rejection == WDC_ADMIN_REJECTION_OUT_OF_ORDER ||
        rejection == WDC_ADMIN_REJECTION_WRONG_STATE ||
        status == WDC_ERR_INVALID_STATE) {
        return 409u;
    }
    if (status == WDC_ERR_TIMEOUT) {
        return 408u;
    }
    if (status == WDC_ERR_NOT_AVAILABLE) {
        return 404u;
    }
    return 400u;
}

static bool has_prefix(const char *text, const char *prefix)
{
    size_t length;
    if (text == NULL || prefix == NULL) {
        return false;
    }
    length = strlen(prefix);
    return strncmp(text, prefix, length) == 0;
}

int32_t wdc_http_service_init(WdcHttpService *service,
                              const WdcHttpServiceConfig *config)
{
    if (service == NULL || config == NULL || config->admin_core == NULL ||
        !config->admin_core->initialized || config->clock == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    if ((config->app_request_deadline_ms != 0u &&
         config->app_request_deadline_ms >
             WDC_HTTP_APP_REQUEST_DEADLINE_MS) ||
        (config->admin_request_deadline_ms != 0u &&
         config->admin_request_deadline_ms >
             WDC_HTTP_ADMIN_REQUEST_DEADLINE_MS)) {
        return WDC_ERR_BAD_LENGTH;
    }
    memset(service, 0, sizeof(*service));
    service->config = *config;
    if (service->config.app_request_deadline_ms == 0u) {
        service->config.app_request_deadline_ms =
            WDC_HTTP_APP_REQUEST_DEADLINE_MS;
    }
    if (service->config.admin_request_deadline_ms == 0u) {
        service->config.admin_request_deadline_ms =
            WDC_HTTP_ADMIN_REQUEST_DEADLINE_MS;
    }
    service->next_request_id = 1u;
    service->next_challenge_id = 1u;
    if (wdc_admin_serial_init(&service->admin_frame_adapter,
                              config->admin_core) != WDC_OK) {
        memset(service, 0, sizeof(*service));
        return WDC_ERR_INVALID_STATE;
    }
    service->initialized = true;
    return WDC_OK;
}

int32_t wdc_http_service_register_app_route(WdcHttpService *service,
                                            WdcHttpMethod method,
                                            const char *path,
                                            uint32_t resource_id)
{
    size_t path_bytes;
    uint32_t index;
    if (service == NULL || path == NULL || !service->initialized) {
        return WDC_ERR_BAD_POINTER;
    }
    if (service->started) {
        return WDC_ERR_INVALID_STATE;
    }
    path_bytes = strlen(path);
    if ((method != WDC_HTTP_METHOD_GET && method != WDC_HTTP_METHOD_POST) ||
        resource_id != WDC_R8_RESOURCE_HTTP_API ||
        !path_is_canonical(path, (uint32_t)path_bytes) ||
        !has_prefix(path, WDC_HTTP_APP_NAMESPACE) ||
        has_prefix(path, WDC_HTTP_ADMIN_NAMESPACE)) {
        return WDC_ERR_CAPABILITY_DENIED;
    }
    if (service->route_count >= WDC_HTTP_APP_ROUTE_CAPACITY) {
        return WDC_ERR_NO_MEMORY;
    }
    for (index = 0u; index < service->route_count; ++index) {
        if (service->routes[index].method == method &&
            strcmp(service->routes[index].path, path) == 0) {
            return WDC_ERR_CONTRACT_VIOLATION;
        }
    }
    service->routes[service->route_count].method = method;
    service->routes[service->route_count].resource_id = resource_id;
    memcpy(service->routes[service->route_count].path, path, path_bytes + 1u);
    service->route_count += 1u;
    return WDC_OK;
}

int32_t wdc_http_service_start(WdcHttpService *service)
{
    int32_t status;
    if (service == NULL || !service->initialized) {
        return WDC_ERR_BAD_POINTER;
    }
    if (service->started) {
        return WDC_ERR_INVALID_STATE;
    }
    if (service->route_count != 0u && service->config.app_dispatch == NULL) {
        return WDC_ERR_INVALID_STATE;
    }
    status = wdc_net_set_http_response_hook(
        wdc_http_service_guest_response_host_call, service);
    if (status != WDC_OK) {
        return status;
    }
    service->started = true;
    return WDC_OK;
}

void wdc_http_service_stop(WdcHttpService *service)
{
    if (service == NULL || !service->initialized) {
        return;
    }
    if (s_active_app_service == service) {
        s_active_app_service = NULL;
    }
    wdc_net_clear_http_response_hook(
        wdc_http_service_guest_response_host_call, service);
    service->started = false;
    service->app_active = false;
    service->admin_active = false;
    service->app_response_ready = false;
    service->app_cancelled = false;
    memset(service->app_event, 0, sizeof(service->app_event));
    memset(service->app_response, 0, sizeof(service->app_response));
}

static const WdcHttpAppRoute *find_app_route(const WdcHttpService *service,
                                             const WdcHttpRequest *request)
{
    uint32_t index;
    for (index = 0u; index < service->route_count; ++index) {
        if (service->routes[index].method == request->method &&
            strcmp(service->routes[index].path, request->path) == 0) {
            return &service->routes[index];
        }
    }
    return NULL;
}

static int32_t next_request_id(WdcHttpService *service,
                               uint32_t *out_request_id)
{
    if (service->next_request_id == 0u || out_request_id == NULL) {
        return WDC_ERR_RATE_LIMITED;
    }
    *out_request_id = service->next_request_id;
    if (service->next_request_id == UINT32_MAX) {
        service->next_request_id = 0u;
    } else {
        service->next_request_id += 1u;
    }
    return WDC_OK;
}

static int32_t build_app_event(WdcHttpService *service,
                               const WdcHttpRequest *request,
                               const WdcHttpAppRoute *route,
                               uint32_t request_id,
                               uint32_t *out_event_bytes)
{
    WdcCborBuilder builder;
    int32_t status;
    wdc_cbor_builder_init(&builder, service->app_event,
                          sizeof(service->app_event));
    status = wdc_cbor_begin_map(&builder, 11u);
    if (status == WDC_OK) {
        status = wdc_cbor_put_key_u32(&builder, WDC_CBOR_KEY_ABI_MAJOR,
                                      WDC_ABI_MAJOR);
    }
    if (status == WDC_OK) {
        status = wdc_cbor_put_key_u32(&builder, WDC_CBOR_KEY_EVENT_TYPE,
                                      WDC_EVENT_HTTP_REQUEST);
    }
    if (status == WDC_OK) {
        status = wdc_cbor_put_key_u32(&builder, WDC_CBOR_KEY_EVENT_ID,
                                      request_id);
    }
    if (status == WDC_OK) {
        status = wdc_cbor_put_key_u64(&builder, WDC_CBOR_KEY_TIMESTAMP_MS,
                                      request->received_monotonic_ms);
    }
    if (status == WDC_OK) {
        status = wdc_cbor_put_key_u64(&builder, WDC_CBOR_KEY_CAUSATION_ID,
                                      (uint64_t)request_id);
    }
    if (status == WDC_OK) {
        status = wdc_cbor_put_key_u32(&builder, WDC_CBOR_KEY_RESOURCE_ID,
                                      route->resource_id);
    }
    if (status == WDC_OK) {
        status = wdc_cbor_put_key_u32(&builder, WDC_CBOR_KEY_REQUEST_ID,
                                      request_id);
    }
    if (status == WDC_OK) {
        status = wdc_cbor_put_key_text(&builder, WDC_CBOR_KEY_METHOD,
                                       wdc_http_method_name(request->method));
    }
    if (status == WDC_OK) {
        status = wdc_cbor_put_key_text(&builder, WDC_CBOR_KEY_URL,
                                       request->path);
    }
    if (status == WDC_OK) {
        status = wdc_cbor_put_key_bytes(&builder, WDC_CBOR_KEY_DATA,
                                        request->body,
                                        request->body_bytes);
    }
    if (status == WDC_OK) {
        status = wdc_cbor_put_key_u64(&builder, WDC_CBOR_KEY_DEADLINE_MS,
                                      request->deadline_ms);
    }
    if (status != WDC_OK) {
        return status;
    }
    *out_event_bytes = wdc_cbor_len(&builder);
    return WDC_OK;
}

static int32_t handle_app(WdcHttpService *service,
                          const WdcHttpRequest *request,
                          WdcHttpResponse *response)
{
    const WdcHttpAppRoute *route = find_app_route(service, request);
    uint32_t request_id = 0u;
    uint32_t event_bytes = 0u;
    uint64_t after_ms;
    int32_t status;
    if (route == NULL) {
        return status_response(response, WDC_HTTP_LANE_APPLICATION, 404u,
                               WDC_ERR_NOT_AVAILABLE, 0u);
    }
    if (request->body_bytes > WDC_HTTP_APP_BODY_MAX_BYTES) {
        service->stats.oversized_rejections += 1u;
        return status_response(response, WDC_HTTP_LANE_APPLICATION, 413u,
                               WDC_ERR_BAD_LENGTH, 0u);
    }
    if (service->config.app_dispatch == NULL) {
        service->stats.saturated_rejections += 1u;
        return status_response(response, WDC_HTTP_LANE_APPLICATION, 503u,
                               WDC_ERR_NOT_AVAILABLE, 0u);
    }
    if (service->app_active || s_active_app_service != NULL) {
        service->stats.saturated_rejections += 1u;
        return status_response(response, WDC_HTTP_LANE_APPLICATION, 503u,
                               WDC_ERR_BUSY, 0u);
    }
    status = next_request_id(service, &request_id);
    if (status != WDC_OK) {
        service->stats.saturated_rejections += 1u;
        return status_response(response, WDC_HTTP_LANE_APPLICATION, 503u,
                               status, 0u);
    }
    status = build_app_event(service, request, route, request_id,
                             &event_bytes);
    if (status != WDC_OK) {
        service->stats.oversized_rejections += 1u;
        return status_response(response, WDC_HTTP_LANE_APPLICATION, 413u,
                               status, request_id);
    }
    service->app_active = true;
    service->app_cancelled = false;
    service->app_response_ready = false;
    service->active_app_request_id = request_id;
    service->active_app_deadline_ms = request->deadline_ms;
    service->app_response_bytes = 0u;
    service->app_response_status = 0u;
    service->stats.app_accepted += 1u;
    s_active_app_service = service;
    status = service->config.app_dispatch(service->config.app_context,
                                          service->app_event, event_bytes,
                                          request->deadline_ms);
    s_active_app_service = NULL;
    after_ms = service->config.clock(service->config.clock_context);
    response_init(response, WDC_HTTP_LANE_APPLICATION, 204u);
    response->request_id = request_id;
    response->accepted = true;
    response->terminal = true;
    if (service->app_cancelled) {
        service->stats.app_cancelled += 1u;
        (void)status_response(response, WDC_HTTP_LANE_APPLICATION, 499u,
                              WDC_ERR_NOT_SYNCHRONIZED, request_id);
        response->accepted = true;
        response->terminal = true;
    } else if (after_ms >= request->deadline_ms) {
        service->stats.app_timed_out += 1u;
        (void)status_response(response, WDC_HTTP_LANE_APPLICATION, 504u,
                              WDC_ERR_TIMEOUT, request_id);
        response->accepted = true;
        response->terminal = true;
    } else if (status != WDC_OK) {
        service->stats.app_trapped += 1u;
        (void)status_response(response, WDC_HTTP_LANE_APPLICATION, 500u,
                              status, request_id);
        response->accepted = true;
        response->terminal = true;
    } else if (service->app_response_ready) {
        response->status_code = service->app_response_status;
        response->body_bytes = service->app_response_bytes;
        (void)memcpy(response->content_type, "application/octet-stream", 25u);
        if (response->body_bytes != 0u) {
            memcpy(response->body, service->app_response,
                   response->body_bytes);
        }
        service->stats.app_completed += 1u;
    } else {
        service->stats.app_completed += 1u;
    }
    service->app_active = false;
    service->app_cancelled = false;
    service->app_response_ready = false;
    service->active_app_request_id = 0u;
    service->active_app_deadline_ms = 0u;
    service->app_response_bytes = 0u;
    service->app_response_status = 0u;
    memset(service->app_event, 0, sizeof(service->app_event));
    memset(service->app_response, 0, sizeof(service->app_response));
    return WDC_OK;
}

static int32_t admin_result_response(WdcHttpService *service,
                                     WdcHttpResponse *response,
                                     int32_t status,
                                     const WdcAdminPreacceptResult *rejection)
{
    WdcCborBuilder builder;
    uint16_t http_status = status == WDC_OK ? 200u :
        http_status_for_error(status, rejection != NULL ?
            rejection->rejection : WDC_ADMIN_REJECTION_NONE);
    int32_t build;
    response_init(response, WDC_HTTP_LANE_ADMINISTRATION, http_status);
    if (status != WDC_OK) {
        service->stats.admin_preaccept_rejections += 1u;
        if (http_status == 401u) {
            service->stats.unauthorized_rejections += 1u;
        }
    }
    wdc_cbor_builder_init(&builder, response->body, sizeof(response->body));
    build = wdc_cbor_begin_map(&builder, 4u);
    if (build == WDC_OK) {
        build = wdc_cbor_put_key_i32(&builder, WDC_CBOR_KEY_STATUS, status);
    }
    if (build == WDC_OK) {
        build = wdc_cbor_put_key_u32(
            &builder, WDC_CBOR_KEY_DECISION,
            rejection != NULL ? (uint32_t)rejection->rejection : 0u);
    }
    if (build == WDC_OK) {
        build = wdc_cbor_put_key_u64(
            &builder, WDC_CBOR_KEY_REQUEST_ID,
            rejection != NULL ? rejection->request_id : 0u);
    }
    if (build == WDC_OK) {
        build = wdc_cbor_put_key_u64(
            &builder, WDC_CBOR_KEY_CORRELATION_ID,
            rejection != NULL ? rejection->command_sequence : 0u);
    }
    return build == WDC_OK ? finish_builder(&builder, response) : build;
}

static int32_t handle_admin_begin(WdcHttpService *service,
                                  const WdcHttpRequest *request,
                                  WdcHttpResponse *response,
                                  uint64_t now_ms)
{
    WdcAdminAuthorizationStart start;
    WdcAdminPreacceptResult rejection;
    WdcCborBuilder builder;
    uint64_t challenge_deadline = 0u;
    uint64_t challenge_id = service->next_challenge_id;
    int32_t status;
    int32_t build;
    if (request->method != WDC_HTTP_METHOD_POST || request->body_bytes != 0u) {
        service->stats.malformed_rejections += 1u;
        return status_response(response, WDC_HTTP_LANE_ADMINISTRATION, 400u,
                               WDC_ERR_BAD_ENCODING, 0u);
    }
    if (challenge_id == 0u) {
        service->stats.saturated_rejections += 1u;
        return status_response(response, WDC_HTTP_LANE_ADMINISTRATION, 503u,
                               WDC_ERR_RATE_LIMITED, 0u);
    }
    memset(&start, 0, sizeof(start));
    memset(&rejection, 0, sizeof(rejection));
    start.transport_kind = WDC_ADMIN_TRANSPORT_AUTHENTICATED_EXTERNAL_V1;
    start.authorization_method =
        WDC_ADMIN_AUTH_METHOD_REPLACEABLE_AUTHENTICATOR;
    start.attended_physical_entry = 0u;
    start.challenge_id = challenge_id;
    memcpy(start.channel_binding_sha256, request->channel_binding_sha256,
           sizeof(start.channel_binding_sha256));
    status = wdc_admin_authorization_begin(service->config.admin_core, &start,
                                           now_ms, &challenge_deadline,
                                           &rejection);
    if (status != WDC_OK) {
        return admin_result_response(service, response, status, &rejection);
    }
    if (service->next_challenge_id == UINT64_MAX) {
        service->next_challenge_id = 0u;
    } else {
        service->next_challenge_id += 1u;
    }
    response_init(response, WDC_HTTP_LANE_ADMINISTRATION, 200u);
    wdc_cbor_builder_init(&builder, response->body, sizeof(response->body));
    build = wdc_cbor_begin_map(&builder, 4u);
    if (build == WDC_OK) {
        build = wdc_cbor_put_key_i32(&builder, WDC_CBOR_KEY_STATUS, WDC_OK);
    }
    if (build == WDC_OK) {
        build = wdc_cbor_put_key_u64(&builder, WDC_CBOR_KEY_CORRELATION_ID,
                                     challenge_id);
    }
    if (build == WDC_OK) {
        build = wdc_cbor_put_key_u64(&builder, WDC_CBOR_KEY_DEADLINE_MS,
                                     challenge_deadline);
    }
    if (build == WDC_OK) {
        build = wdc_cbor_put_key_u32(
            &builder, WDC_CBOR_KEY_NETWORK_STATE,
            (uint32_t)wdc_admin_authorization_state(service->config.admin_core));
    }
    return build == WDC_OK ? finish_builder(&builder, response) : build;
}

static int32_t handle_admin_finish(WdcHttpService *service,
                                   const WdcHttpRequest *request,
                                   WdcHttpResponse *response,
                                   uint64_t now_ms)
{
    WdcAdminPreacceptResult rejection;
    WdcCborBuilder builder;
    int32_t status;
    int32_t build;
    if (request->method != WDC_HTTP_METHOD_POST || request->body_bytes == 0u ||
        request->body_bytes > WDC_ADMIN_MAX_PAYLOAD_BYTES) {
        service->stats.malformed_rejections += 1u;
        return status_response(response, WDC_HTTP_LANE_ADMINISTRATION, 400u,
                               WDC_ERR_BAD_LENGTH, 0u);
    }
    memset(&rejection, 0, sizeof(rejection));
    status = wdc_admin_authorization_finish(service->config.admin_core,
                                            request->body,
                                            request->body_bytes, now_ms,
                                            &rejection);
    if (status != WDC_OK) {
        return admin_result_response(service, response, status, &rejection);
    }
    response_init(response, WDC_HTTP_LANE_ADMINISTRATION, 200u);
    wdc_cbor_builder_init(&builder, response->body, sizeof(response->body));
    build = wdc_cbor_begin_map(&builder, 3u);
    if (build == WDC_OK) {
        build = wdc_cbor_put_key_i32(&builder, WDC_CBOR_KEY_STATUS, WDC_OK);
    }
    if (build == WDC_OK) {
        build = wdc_cbor_put_key_u32(
            &builder, WDC_CBOR_KEY_NETWORK_STATE,
            (uint32_t)wdc_admin_authorization_state(service->config.admin_core));
    }
    if (build == WDC_OK) {
        build = wdc_cbor_put_key_u64(
            &builder, WDC_CBOR_KEY_CORRELATION_ID,
            wdc_admin_next_command_sequence(service->config.admin_core));
    }
    return build == WDC_OK ? finish_builder(&builder, response) : build;
}

static int32_t handle_admin_close(WdcHttpService *service,
                                  const WdcHttpRequest *request,
                                  WdcHttpResponse *response,
                                  uint64_t now_ms)
{
    int32_t status;
    if (request->method != WDC_HTTP_METHOD_DELETE ||
        request->body_bytes != 0u) {
        service->stats.malformed_rejections += 1u;
        return status_response(response, WDC_HTTP_LANE_ADMINISTRATION, 400u,
                               WDC_ERR_BAD_ENCODING, 0u);
    }
    status = wdc_admin_session_close(service->config.admin_core, now_ms);
    return status_response(response, WDC_HTTP_LANE_ADMINISTRATION,
                           status == WDC_OK ? 204u :
                               http_status_for_error(
                                   status, WDC_ADMIN_REJECTION_NONE),
                           status, 0u);
}

static int32_t handle_admin_command(WdcHttpService *service,
                                    const WdcHttpRequest *request,
                                    WdcHttpResponse *response,
                                    uint64_t now_ms)
{
    WdcAdminPreacceptResult rejection;
    uint32_t consumed = 0u;
    bool complete = false;
    int32_t status;
    if (request->method != WDC_HTTP_METHOD_POST ||
        request->body_bytes < 4u + WDC_ADMIN_REQUEST_BYTES ||
        request->body_bytes > WDC_ADMIN_MAX_FRAME_BYTES) {
        service->stats.malformed_rejections += 1u;
        return status_response(response, WDC_HTTP_LANE_ADMINISTRATION, 400u,
                               WDC_ERR_BAD_LENGTH, 0u);
    }
    wdc_admin_serial_reset(&service->admin_frame_adapter);
    memset(&rejection, 0, sizeof(rejection));
    status = wdc_admin_serial_feed(&service->admin_frame_adapter,
                                   request->body, request->body_bytes, now_ms,
                                   &consumed, &complete, &rejection);
    if (status != WDC_OK || !complete || consumed != request->body_bytes) {
        if (status == WDC_OK) {
            status = WDC_ERR_BAD_ENCODING;
            rejection.rejection = WDC_ADMIN_REJECTION_BAD_FRAME;
            rejection.status = status;
        }
        return admin_result_response(service, response, status, &rejection);
    }
    service->stats.admin_commands_accepted += 1u;
    status = admin_result_response(service, response, WDC_OK, &rejection);
    response->status_code = 202u;
    response->request_id = (uint32_t)rejection.request_id;
    response->accepted = true;
    return status;
}

static int32_t handle_admin_terminal(WdcHttpService *service,
                                     const WdcHttpRequest *request,
                                     WdcHttpResponse *response)
{
    WdcAdminTerminalRecord terminal;
    uint8_t admin_response[WDC_ADMIN_MAX_STATUS_RESPONSE_BYTES];
    uint32_t admin_response_bytes = 0u;
    WdcCborBuilder builder;
    int32_t status;
    int32_t build;
    if (request->method != WDC_HTTP_METHOD_GET || request->body_bytes != 0u) {
        service->stats.malformed_rejections += 1u;
        return status_response(response, WDC_HTTP_LANE_ADMINISTRATION, 400u,
                               WDC_ERR_BAD_ENCODING, 0u);
    }
    memset(&terminal, 0, sizeof(terminal));
    memset(admin_response, 0, sizeof(admin_response));
    status = wdc_admin_take_terminal(service->config.admin_core, &terminal,
                                     admin_response, sizeof(admin_response),
                                     &admin_response_bytes);
    if (status != WDC_OK) {
        return status_response(response, WDC_HTTP_LANE_ADMINISTRATION,
                               http_status_for_error(
                                   status, WDC_ADMIN_REJECTION_NONE),
                               status, 0u);
    }
    response_init(response, WDC_HTTP_LANE_ADMINISTRATION, 200u);
    response->request_id = (uint32_t)terminal.request_id;
    response->terminal = true;
    wdc_cbor_builder_init(&builder, response->body, sizeof(response->body));
    build = wdc_cbor_begin_map(&builder, 10u);
    if (build == WDC_OK) {
        build = wdc_cbor_put_key_i32(&builder, WDC_CBOR_KEY_STATUS,
                                     terminal.status);
    }
    if (build == WDC_OK) {
        build = wdc_cbor_put_key_u32(&builder, WDC_CBOR_KEY_RESULT,
                                     terminal.result);
    }
    if (build == WDC_OK) {
        build = wdc_cbor_put_key_u64(&builder, WDC_CBOR_KEY_REQUEST_ID,
                                     terminal.request_id);
    }
    if (build == WDC_OK) {
        build = wdc_cbor_put_key_u64(&builder, WDC_CBOR_KEY_CORRELATION_ID,
                                     terminal.command_sequence);
    }
    if (build == WDC_OK) {
        build = wdc_cbor_put_key_u32(&builder, WDC_CBOR_KEY_PAYLOAD_LEN,
                                     terminal.bytes_received);
    }
    if (build == WDC_OK) {
        build = wdc_cbor_put_key_u32(&builder, WDC_CBOR_KEY_QUEUE_DROPPED,
                                     terminal.metadata_commits);
    }
    if (build == WDC_OK) {
        build = wdc_cbor_put_key_u32(&builder, WDC_CBOR_KEY_NETWORK_STATE,
                                     terminal.final_state);
    }
    if (build == WDC_OK) {
        build = wdc_cbor_put_key_u32(&builder, WDC_CBOR_KEY_SLOT,
                                     terminal.slot);
    }
    if (build == WDC_OK) {
        build = wdc_cbor_put_key_u32(&builder, WDC_CBOR_KEY_DECISION,
                                     terminal.flags);
    }
    if (build == WDC_OK) {
        build = wdc_cbor_put_key_bytes(&builder, WDC_CBOR_KEY_DATA,
                                       admin_response,
                                       admin_response_bytes);
    }
    memset(admin_response, 0, sizeof(admin_response));
    return build == WDC_OK ? finish_builder(&builder, response) : build;
}

static int32_t handle_admin(WdcHttpService *service,
                            const WdcHttpRequest *request,
                            WdcHttpResponse *response,
                            uint64_t now_ms)
{
    int32_t status;
    if (service->admin_active) {
        service->stats.saturated_rejections += 1u;
        return status_response(response, WDC_HTTP_LANE_ADMINISTRATION, 503u,
                               WDC_ERR_BUSY, 0u);
    }
    if (bytes_are_zero(request->channel_binding_sha256, 32u) ||
        memcmp(request->channel_binding_sha256,
               service->config.admin_core->boot_channel_binding_sha256,
               32u) != 0) {
        service->stats.unauthorized_rejections += 1u;
        return status_response(response, WDC_HTTP_LANE_ADMINISTRATION, 401u,
                               WDC_ERR_CAPABILITY_DENIED, 0u);
    }
    service->admin_active = true;
    service->stats.admin_requests += 1u;
    (void)wdc_admin_poll(service->config.admin_core, now_ms);
    if (strcmp(request->path, WDC_HTTP_ADMIN_SESSION_BEGIN_PATH) == 0) {
        status = handle_admin_begin(service, request, response, now_ms);
    } else if (strcmp(request->path,
                      WDC_HTTP_ADMIN_SESSION_FINISH_PATH) == 0) {
        status = handle_admin_finish(service, request, response, now_ms);
    } else if (strcmp(request->path, WDC_HTTP_ADMIN_SESSION_PATH) == 0) {
        status = handle_admin_close(service, request, response, now_ms);
    } else if (strcmp(request->path, WDC_HTTP_ADMIN_COMMAND_PATH) == 0) {
        status = handle_admin_command(service, request, response, now_ms);
    } else if (strcmp(request->path, WDC_HTTP_ADMIN_TERMINAL_PATH) == 0) {
        status = handle_admin_terminal(service, request, response);
    } else {
        status = status_response(response, WDC_HTTP_LANE_ADMINISTRATION,
                                 404u, WDC_ERR_NOT_AVAILABLE, 0u);
    }
    service->admin_active = false;
    return status;
}

int32_t wdc_http_service_handle(WdcHttpService *service,
                                const WdcHttpRequest *request,
                                WdcHttpResponse *out_response)
{
    WdcHttpLane lane;
    uint64_t now_ms;
    uint32_t maximum_deadline_ms;
    if (service == NULL || request == NULL || out_response == NULL ||
        !service->initialized) {
        return WDC_ERR_BAD_POINTER;
    }
    if (!service->started) {
        return status_response(out_response, WDC_HTTP_LANE_NONE, 503u,
                               WDC_ERR_INVALID_STATE, 0u);
    }
    if (!request->complete || request->method == WDC_HTTP_METHOD_NONE ||
        !path_is_canonical(request->path, request->path_bytes) ||
        request->body_bytes != request->declared_body_bytes ||
        request->body_bytes > WDC_HTTP_REQUEST_BODY_MAX_BYTES ||
        (request->body_bytes != 0u && request->body == NULL)) {
        service->stats.malformed_rejections += 1u;
        return status_response(out_response, WDC_HTTP_LANE_NONE, 400u,
                               WDC_ERR_BAD_ENCODING, 0u);
    }
    lane = has_prefix(request->path, WDC_HTTP_ADMIN_NAMESPACE) ?
        WDC_HTTP_LANE_ADMINISTRATION : WDC_HTTP_LANE_APPLICATION;
    if (!request->tls_established) {
        service->stats.unauthorized_rejections += 1u;
        return status_response(out_response, lane, 401u,
                               WDC_ERR_CAPABILITY_DENIED, 0u);
    }
    if (!request->client_connected) {
        service->stats.disconnected_rejections += 1u;
        return status_response(out_response, lane, 499u,
                               WDC_ERR_NOT_SYNCHRONIZED, 0u);
    }
    now_ms = service->config.clock(service->config.clock_context);
    maximum_deadline_ms = lane == WDC_HTTP_LANE_ADMINISTRATION ?
        service->config.admin_request_deadline_ms :
        service->config.app_request_deadline_ms;
    if (request->deadline_ms <= now_ms ||
        request->deadline_ms - now_ms > maximum_deadline_ms) {
        service->stats.slow_rejections += 1u;
        return status_response(out_response, lane, 408u,
                               WDC_ERR_TIMEOUT, 0u);
    }
    if (lane == WDC_HTTP_LANE_ADMINISTRATION) {
        return handle_admin(service, request, out_response, now_ms);
    }
    return handle_app(service, request, out_response);
}

int32_t wdc_http_service_cancel_app(WdcHttpService *service,
                                    uint32_t request_id)
{
    if (service == NULL || !service->initialized) {
        return WDC_ERR_BAD_POINTER;
    }
    if (!service->app_active || request_id == 0u ||
        request_id != service->active_app_request_id) {
        return WDC_ERR_NOT_AVAILABLE;
    }
    service->app_cancelled = true;
    return WDC_OK;
}

void wdc_http_service_note_send_result(WdcHttpService *service,
                                       const WdcHttpResponse *response,
                                       int32_t send_status)
{
    if (service == NULL || response == NULL || !service->initialized ||
        send_status == WDC_OK) {
        return;
    }
    if (response->lane == WDC_HTTP_LANE_APPLICATION) {
        service->stats.app_response_losses += 1u;
    } else if (response->lane == WDC_HTTP_LANE_ADMINISTRATION) {
        service->stats.admin_response_losses += 1u;
        if (response->terminal) {
            service->stats.admin_terminal_losses += 1u;
        }
    }
}

void wdc_http_service_get_stats(const WdcHttpService *service,
                                WdcHttpServiceStats *out_stats)
{
    if (service != NULL && out_stats != NULL) {
        *out_stats = service->stats;
    }
}

static int32_t write_guest_call_status(uint8_t *response,
                                       uint32_t response_cap,
                                       uint32_t *out_response_len,
                                       int32_t status)
{
    WdcCborBuilder builder;
    int32_t build;
    if (response == NULL || response_cap == 0u) {
        return WDC_ERR_RESPONSE_TOO_SMALL;
    }
    wdc_cbor_builder_init(&builder, response, response_cap);
    build = wdc_cbor_begin_map(&builder, 1u);
    if (build == WDC_OK) {
        build = wdc_cbor_put_key_i32(&builder, WDC_CBOR_KEY_STATUS, status);
    }
    if (build == WDC_OK && out_response_len != NULL) {
        *out_response_len = wdc_cbor_len(&builder);
    }
    return build;
}

int32_t wdc_http_service_guest_response_host_call(
    void *context,
    const uint8_t *request,
    uint32_t request_len,
    uint8_t *response,
    uint32_t response_cap,
    uint32_t *out_response_len)
{
    WdcHttpService *service = (WdcHttpService *)context;
    WdcCborBytes body = {0};
    uint32_t resource_id = 0u;
    uint32_t request_id = 0u;
    uint32_t http_status = 0u;
    uint64_t now_ms;
    int32_t status;
    if (out_response_len != NULL) {
        *out_response_len = 0u;
    }
    if (service == NULL || service != s_active_app_service ||
        !service->app_active) {
        return write_guest_call_status(response, response_cap,
                                       out_response_len,
                                       WDC_ERR_INVALID_STATE);
    }
    status = wdc_cbor_map_find_u32(request, request_len,
                                   WDC_CBOR_KEY_RESOURCE_ID, &resource_id);
    if (status == WDC_OK) {
        status = wdc_cbor_map_find_u32(request, request_len,
                                       WDC_CBOR_KEY_REQUEST_ID, &request_id);
    }
    if (status == WDC_OK) {
        status = wdc_cbor_map_find_u32(request, request_len,
                                       WDC_CBOR_KEY_HTTP_STATUS,
                                       &http_status);
    }
    if (status == WDC_OK) {
        status = wdc_cbor_map_find_bytes(request, request_len,
                                         WDC_CBOR_KEY_DATA, &body);
        if (status == WDC_ERR_NOT_AVAILABLE) {
            status = WDC_OK;
        }
    }
    if (status != WDC_OK || resource_id != WDC_R8_RESOURCE_HTTP_API ||
        request_id != service->active_app_request_id || http_status < 200u ||
        http_status > 599u || body.len > WDC_HTTP_APP_BODY_MAX_BYTES) {
        return write_guest_call_status(response, response_cap,
                                       out_response_len,
                                       status != WDC_OK ?
                                           WDC_ERR_BAD_ENCODING :
                                           WDC_ERR_CAPABILITY_DENIED);
    }
    if (service->app_response_ready) {
        service->stats.duplicate_response_rejections += 1u;
        return write_guest_call_status(response, response_cap,
                                       out_response_len,
                                       WDC_ERR_CONTRACT_VIOLATION);
    }
    now_ms = service->config.clock(service->config.clock_context);
    if (service->app_cancelled) {
        return write_guest_call_status(response, response_cap,
                                       out_response_len,
                                       WDC_ERR_NOT_SYNCHRONIZED);
    }
    if (now_ms >= service->active_app_deadline_ms) {
        return write_guest_call_status(response, response_cap,
                                       out_response_len, WDC_ERR_TIMEOUT);
    }
    if (body.len != 0u) {
        memcpy(service->app_response, body.ptr, body.len);
    }
    service->app_response_bytes = body.len;
    service->app_response_status = (uint16_t)http_status;
    service->app_response_ready = true;
    return write_guest_call_status(response, response_cap, out_response_len,
                                   WDC_OK);
}

uint32_t wdc_http_service_link_anchor(void)
{
    return 1u;
}
