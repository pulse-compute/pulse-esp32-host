#include "wdc_http_platform.h"

#include <limits.h>
#include <string.h>

#include "wdc_net.h"

#ifdef ESP_PLATFORM

#include "esp_err.h"
#include "esp_event.h"
#include "esp_http_server.h"
#include "esp_https_server.h"
#include "esp_netif.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"

#define WDC_HTTP_WIFI_CONNECTED_BIT BIT0
#define WDC_HTTP_WIFI_FAILED_BIT BIT1
#define WDC_HTTP_APP_CTRL_PORT 32768u
#define WDC_HTTP_ADMIN_CTRL_PORT 32769u
#define WDC_HTTP_LISTENER_URI_HANDLERS 3u
#define WDC_HTTP_LISTENER_STACK_BYTES 6144u

typedef struct WdcHttpPlatformLane {
    WdcHttpLane lane;
    httpd_handle_t server;
    WdcHttpParser parser;
} WdcHttpPlatformLane;

typedef struct WdcHttpPlatformState {
    WdcHttpPlatformConfig config;
    WdcHttpPlatformStatus status;
    WdcHttpPlatformLane app;
    WdcHttpPlatformLane admin;
    StaticEventGroup_t event_group_storage;
    EventGroupHandle_t event_group;
    esp_event_handler_instance_t wifi_event_handler;
    esp_event_handler_instance_t ip_event_handler;
    bool wifi_handler_registered;
    bool ip_handler_registered;
} WdcHttpPlatformState;

static WdcHttpPlatformState s_platform;

static bool binding_is_zero(const uint8_t binding[32])
{
    uint8_t aggregate = 0u;
    uint32_t index;
    for (index = 0u; index < 32u; ++index) {
        aggregate |= binding[index];
    }
    return aggregate == 0u;
}

static uint64_t platform_now_ms(void)
{
    int64_t microseconds = esp_timer_get_time();
    return microseconds > 0 ? (uint64_t)microseconds / 1000u : 0u;
}

static void wifi_event(void *argument, esp_event_base_t base,
                       int32_t event_id, void *event_data)
{
    (void)argument;
    (void)event_data;
    if (base == WIFI_EVENT && event_id == WIFI_EVENT_STA_START) {
        (void)esp_wifi_connect();
        return;
    }
    if (base == WIFI_EVENT && event_id == WIFI_EVENT_STA_DISCONNECTED) {
        s_platform.status.wifi_connected = false;
        (void)wdc_net_set_state(WDC_NET_STATE_DISCONNECTED,
                                "HP5 Wi-Fi disconnected");
        if (s_platform.status.reconnect_count <
            s_platform.config.reconnect_attempts) {
            s_platform.status.reconnect_count += 1u;
            (void)esp_wifi_connect();
        } else if (s_platform.event_group != NULL) {
            (void)xEventGroupSetBits(s_platform.event_group,
                                     WDC_HTTP_WIFI_FAILED_BIT);
        }
        return;
    }
    if (base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP) {
        s_platform.status.wifi_connected = true;
        s_platform.status.reconnect_count = 0u;
        (void)wdc_net_set_state(WDC_NET_STATE_CONNECTED,
                                "HP5 Wi-Fi connected");
        if (s_platform.event_group != NULL) {
            (void)xEventGroupSetBits(s_platform.event_group,
                                     WDC_HTTP_WIFI_CONNECTED_BIT);
        }
    }
}

static const char *request_method(httpd_method_t method)
{
    switch (method) {
    case HTTP_GET: return "GET";
    case HTTP_POST: return "POST";
    case HTTP_DELETE: return "DELETE";
    default: return "";
    }
}

static const char *http_status_line(uint16_t status)
{
    switch (status) {
    case 200u: return "200 OK";
    case 202u: return "202 Accepted";
    case 204u: return "204 No Content";
    case 400u: return "400 Bad Request";
    case 401u: return "401 Unauthorized";
    case 404u: return "404 Not Found";
    case 408u: return "408 Request Timeout";
    case 409u: return "409 Conflict";
    case 413u: return "413 Content Too Large";
    case 429u: return "429 Too Many Requests";
    case 499u: return "499 Client Closed Request";
    case 500u: return "500 Internal Server Error";
    case 503u: return "503 Service Unavailable";
    case 504u: return "504 Gateway Timeout";
    default: return "500 Internal Server Error";
    }
}

static esp_err_t send_simple_error(httpd_req_t *request, uint16_t status)
{
    const char *line = http_status_line(status);
    (void)httpd_resp_set_status(request, line);
    (void)httpd_resp_set_type(request, "text/plain");
    return httpd_resp_send(request, line, HTTPD_RESP_USE_STRLEN);
}

static esp_err_t listener_handler(httpd_req_t *native_request)
{
    WdcHttpPlatformLane *lane =
        (WdcHttpPlatformLane *)native_request->user_ctx;
    WdcHttpRequest request;
    WdcHttpResponse response;
    uint64_t now_ms;
    uint64_t deadline_ms;
    uint32_t timeout_ms;
    uint32_t consumed = 0u;
    uint32_t remaining;
    int32_t status;
    esp_err_t send_status;
    if (lane == NULL || s_platform.config.service == NULL ||
        native_request->content_len > WDC_HTTP_REQUEST_BODY_MAX_BYTES) {
        return send_simple_error(native_request, 413u);
    }
    if (lane->lane == WDC_HTTP_LANE_APPLICATION &&
        strncmp(native_request->uri, WDC_HTTP_ADMIN_NAMESPACE,
                strlen(WDC_HTTP_ADMIN_NAMESPACE)) == 0) {
        return send_simple_error(native_request, 404u);
    }
    if (lane->lane == WDC_HTTP_LANE_ADMINISTRATION &&
        strncmp(native_request->uri, WDC_HTTP_ADMIN_NAMESPACE,
                strlen(WDC_HTTP_ADMIN_NAMESPACE)) != 0) {
        return send_simple_error(native_request, 404u);
    }
    now_ms = platform_now_ms();
    timeout_ms = lane->lane == WDC_HTTP_LANE_ADMINISTRATION ?
        s_platform.config.service->config.admin_request_deadline_ms :
        s_platform.config.service->config.app_request_deadline_ms;
    if (now_ms > UINT64_MAX - (uint64_t)timeout_ms) {
        return send_simple_error(native_request, 408u);
    }
    deadline_ms = now_ms + (uint64_t)timeout_ms;
    status = wdc_http_parser_begin(
        &lane->parser, request_method(native_request->method),
        native_request->uri, (uint32_t)native_request->content_len, true,
        true, s_platform.config.boot_channel_binding_sha256, now_ms,
        deadline_ms);
    if (status != WDC_OK) {
        return send_simple_error(native_request,
                                 status == WDC_ERR_TIMEOUT ? 408u : 400u);
    }
    remaining = (uint32_t)native_request->content_len;
    while (remaining != 0u) {
        int received = httpd_req_recv(
            native_request,
            (char *)(lane->parser.body + lane->parser.received_body_bytes),
            remaining);
        if (received == HTTPD_SOCK_ERR_TIMEOUT) {
            wdc_http_parser_reset(&lane->parser);
            return send_simple_error(native_request, 408u);
        }
        if (received <= 0) {
            wdc_http_parser_reset(&lane->parser);
            return ESP_FAIL;
        }
        /* The HTTPS server read directly into the parser's fixed body buffer;
         * account for those bytes without a second request-controlled copy. */
        lane->parser.received_body_bytes += (uint32_t)received;
        consumed += (uint32_t)received;
        remaining -= (uint32_t)received;
        if (platform_now_ms() >= deadline_ms) {
            wdc_http_parser_reset(&lane->parser);
            return send_simple_error(native_request, 408u);
        }
    }
    (void)consumed;
    lane->parser.state = WDC_HTTP_PARSER_COMPLETE;
    status = wdc_http_parser_take(&lane->parser, &request);
    if (status == WDC_OK) {
        status = wdc_http_service_handle(s_platform.config.service, &request,
                                         &response);
    }
    if (status != WDC_OK) {
        wdc_http_parser_reset(&lane->parser);
        return send_simple_error(native_request, 500u);
    }
    (void)httpd_resp_set_status(native_request,
                                http_status_line(response.status_code));
    (void)httpd_resp_set_type(native_request, response.content_type);
    send_status = httpd_resp_send(native_request, (const char *)response.body,
                                  response.body_bytes);
    wdc_http_service_note_send_result(
        s_platform.config.service, &response,
        send_status == ESP_OK ? WDC_OK : WDC_ERR_NOT_SYNCHRONIZED);
    wdc_http_parser_reset(&lane->parser);
    return send_status;
}

static esp_err_t register_lane_handlers(WdcHttpPlatformLane *lane)
{
    static const httpd_method_t methods[WDC_HTTP_LISTENER_URI_HANDLERS] = {
        HTTP_GET, HTTP_POST, HTTP_DELETE,
    };
    uint32_t index;
    for (index = 0u; index < WDC_HTTP_LISTENER_URI_HANDLERS; ++index) {
        httpd_uri_t route = {
            .uri = "/*",
            .method = methods[index],
            .handler = listener_handler,
            .user_ctx = lane,
        };
        esp_err_t status = httpd_register_uri_handler(lane->server, &route);
        if (status != ESP_OK) {
            return status;
        }
    }
    return ESP_OK;
}

static esp_err_t start_lane(WdcHttpPlatformLane *lane, uint16_t port,
                            uint16_t control_port)
{
    httpd_ssl_config_t listener = HTTPD_SSL_CONFIG_DEFAULT();
    listener.httpd.max_open_sockets =
        WDC_HTTP_PLATFORM_MAX_OPEN_SOCKETS_PER_LANE;
    listener.httpd.max_uri_handlers = WDC_HTTP_LISTENER_URI_HANDLERS;
    listener.httpd.stack_size = WDC_HTTP_LISTENER_STACK_BYTES;
    listener.httpd.ctrl_port = control_port;
    listener.httpd.lru_purge_enable = false;
    listener.httpd.uri_match_fn = httpd_uri_match_wildcard;
    listener.port_secure = port;
    listener.servercert = s_platform.config.server_certificate_pem;
    listener.servercert_len = s_platform.config.server_certificate_bytes;
    listener.prvtkey_pem = s_platform.config.server_private_key_pem;
    listener.prvtkey_len = s_platform.config.server_private_key_bytes;
    esp_err_t status = httpd_ssl_start(&lane->server, &listener);
    if (status != ESP_OK) {
        lane->server = NULL;
        return status;
    }
    status = register_lane_handlers(lane);
    if (status != ESP_OK) {
        (void)httpd_ssl_stop(lane->server);
        lane->server = NULL;
    }
    return status;
}

static esp_err_t start_wifi(void)
{
    wifi_init_config_t init = WIFI_INIT_CONFIG_DEFAULT();
    wifi_config_t station;
    esp_err_t status;
    EventBits_t bits;
    memset(&station, 0, sizeof(station));
    memcpy(station.sta.ssid, s_platform.config.wifi_ssid,
           strlen(s_platform.config.wifi_ssid) + 1u);
    memcpy(station.sta.password, s_platform.config.wifi_password,
           strlen(s_platform.config.wifi_password) + 1u);
    station.sta.threshold.authmode = WIFI_AUTH_WPA2_PSK;
    status = esp_netif_init();
    if (status != ESP_OK && status != ESP_ERR_INVALID_STATE) {
        return status;
    }
    status = esp_event_loop_create_default();
    if (status != ESP_OK && status != ESP_ERR_INVALID_STATE) {
        return status;
    }
    if (esp_netif_create_default_wifi_sta() == NULL) {
        return ESP_FAIL;
    }
    status = esp_wifi_init(&init);
    if (status != ESP_OK) {
        return status;
    }
    status = esp_event_handler_instance_register(
        WIFI_EVENT, ESP_EVENT_ANY_ID, wifi_event, NULL,
        &s_platform.wifi_event_handler);
    if (status != ESP_OK) {
        return status;
    }
    s_platform.wifi_handler_registered = true;
    status = esp_event_handler_instance_register(
        IP_EVENT, IP_EVENT_STA_GOT_IP, wifi_event, NULL,
        &s_platform.ip_event_handler);
    if (status != ESP_OK) {
        return status;
    }
    s_platform.ip_handler_registered = true;
    status = esp_wifi_set_mode(WIFI_MODE_STA);
    if (status == ESP_OK) {
        status = esp_wifi_set_config(WIFI_IF_STA, &station);
    }
    memset(&station, 0, sizeof(station));
    if (status == ESP_OK) {
        status = esp_wifi_start();
    }
    if (status != ESP_OK) {
        return status;
    }
    bits = xEventGroupWaitBits(
        s_platform.event_group,
        WDC_HTTP_WIFI_CONNECTED_BIT | WDC_HTTP_WIFI_FAILED_BIT, pdFALSE,
        pdFALSE, pdMS_TO_TICKS(s_platform.config.connect_timeout_ms));
    return (bits & WDC_HTTP_WIFI_CONNECTED_BIT) != 0u ? ESP_OK : ESP_ERR_TIMEOUT;
}

int32_t wdc_http_platform_start(const WdcHttpPlatformConfig *config)
{
    size_t ssid_bytes;
    size_t password_bytes;
    esp_err_t status;
    if (config == NULL || config->service == NULL ||
        config->wifi_ssid == NULL || config->wifi_password == NULL ||
        config->server_certificate_pem == NULL ||
        config->server_private_key_pem == NULL ||
        !config->service->started) {
        return WDC_ERR_BAD_POINTER;
    }
    if (s_platform.status.initialized) {
        return WDC_ERR_INVALID_STATE;
    }
    ssid_bytes = strlen(config->wifi_ssid);
    password_bytes = strlen(config->wifi_password);
    if (ssid_bytes == 0u || ssid_bytes >= WDC_HTTP_PLATFORM_SSID_MAX_BYTES ||
        password_bytes >= WDC_HTTP_PLATFORM_PASSWORD_MAX_BYTES ||
        config->server_certificate_bytes == 0u ||
        config->server_certificate_bytes >
            WDC_HTTP_PLATFORM_CERTIFICATE_MAX_BYTES ||
        config->server_private_key_bytes == 0u ||
        config->server_private_key_bytes >
            WDC_HTTP_PLATFORM_PRIVATE_KEY_MAX_BYTES ||
        config->reconnect_attempts >
            WDC_HTTP_PLATFORM_MAX_RECONNECT_ATTEMPTS ||
        config->connect_timeout_ms > WDC_HTTP_PLATFORM_CONNECT_TIMEOUT_MS) {
        return WDC_ERR_BAD_LENGTH;
    }
    memset(&s_platform, 0, sizeof(s_platform));
    s_platform.config = *config;
    if (s_platform.config.app_port == 0u) {
        s_platform.config.app_port = WDC_HTTP_PLATFORM_APP_PORT_DEFAULT;
    }
    if (s_platform.config.admin_port == 0u) {
        s_platform.config.admin_port = WDC_HTTP_PLATFORM_ADMIN_PORT_DEFAULT;
    }
    if (s_platform.config.reconnect_attempts == 0u) {
        s_platform.config.reconnect_attempts =
            WDC_HTTP_PLATFORM_MAX_RECONNECT_ATTEMPTS;
    }
    if (s_platform.config.connect_timeout_ms == 0u) {
        s_platform.config.connect_timeout_ms =
            WDC_HTTP_PLATFORM_CONNECT_TIMEOUT_MS;
    }
    if (s_platform.config.app_port == s_platform.config.admin_port ||
        binding_is_zero(s_platform.config.boot_channel_binding_sha256)) {
        memset(&s_platform, 0, sizeof(s_platform));
        return WDC_ERR_BAD_LENGTH;
    }
    s_platform.app.lane = WDC_HTTP_LANE_APPLICATION;
    s_platform.admin.lane = WDC_HTTP_LANE_ADMINISTRATION;
    s_platform.event_group =
        xEventGroupCreateStatic(&s_platform.event_group_storage);
    if (s_platform.event_group == NULL) {
        return WDC_ERR_NO_MEMORY;
    }
    status = start_wifi();
    if (status == ESP_OK) {
        status = start_lane(&s_platform.admin, s_platform.config.admin_port,
                            WDC_HTTP_ADMIN_CTRL_PORT);
    }
    if (status == ESP_OK) {
        s_platform.status.admin_listener_started = true;
        status = start_lane(&s_platform.app, s_platform.config.app_port,
                            WDC_HTTP_APP_CTRL_PORT);
    }
    if (status != ESP_OK) {
        s_platform.status.last_status = WDC_ERR_IO;
        wdc_http_platform_stop();
        return WDC_ERR_IO;
    }
    s_platform.status.app_listener_started = true;
    s_platform.status.initialized = true;
    s_platform.status.last_status = WDC_OK;
    return WDC_OK;
}

void wdc_http_platform_stop(void)
{
    if (s_platform.app.server != NULL) {
        (void)httpd_ssl_stop(s_platform.app.server);
        s_platform.app.server = NULL;
    }
    if (s_platform.admin.server != NULL) {
        (void)httpd_ssl_stop(s_platform.admin.server);
        s_platform.admin.server = NULL;
    }
    (void)esp_wifi_disconnect();
    (void)esp_wifi_stop();
    if (s_platform.ip_handler_registered) {
        (void)esp_event_handler_instance_unregister(
            IP_EVENT, IP_EVENT_STA_GOT_IP, s_platform.ip_event_handler);
    }
    if (s_platform.wifi_handler_registered) {
        (void)esp_event_handler_instance_unregister(
            WIFI_EVENT, ESP_EVENT_ANY_ID, s_platform.wifi_event_handler);
    }
    memset(&s_platform, 0, sizeof(s_platform));
}

void wdc_http_platform_get_status(WdcHttpPlatformStatus *out_status)
{
    if (out_status != NULL) {
        *out_status = s_platform.status;
    }
}

#else

static WdcHttpPlatformStatus s_host_status;

int32_t wdc_http_platform_start(const WdcHttpPlatformConfig *config)
{
    (void)config;
    memset(&s_host_status, 0, sizeof(s_host_status));
    s_host_status.last_status = WDC_ERR_NOT_AVAILABLE;
    return WDC_ERR_NOT_AVAILABLE;
}

void wdc_http_platform_stop(void)
{
    memset(&s_host_status, 0, sizeof(s_host_status));
}

void wdc_http_platform_get_status(WdcHttpPlatformStatus *out_status)
{
    if (out_status != NULL) {
        *out_status = s_host_status;
    }
}

#endif

uint32_t wdc_http_platform_link_anchor(void)
{
    return 1u;
}
