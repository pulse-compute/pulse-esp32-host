#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "wdc_http_service.h"

#ifdef __cplusplus
extern "C" {
#endif

#define WDC_HTTP_PLATFORM_SSID_MAX_BYTES 32u
#define WDC_HTTP_PLATFORM_PASSWORD_MAX_BYTES 64u
#define WDC_HTTP_PLATFORM_APP_PORT_DEFAULT 443u
#define WDC_HTTP_PLATFORM_ADMIN_PORT_DEFAULT 8443u
#define WDC_HTTP_PLATFORM_MAX_OPEN_SOCKETS_PER_LANE 3u
#define WDC_HTTP_PLATFORM_MAX_RECONNECT_ATTEMPTS 8u
#define WDC_HTTP_PLATFORM_CONNECT_TIMEOUT_MS 30000u
#define WDC_HTTP_PLATFORM_CERTIFICATE_MAX_BYTES 8192u
#define WDC_HTTP_PLATFORM_PRIVATE_KEY_MAX_BYTES 4096u

/*
 * Host-private production adapter inputs.  The caller must keep certificate
 * and private-key buffers valid for the listener lifetime.  They are never
 * copied into an application event or portable artifact.
 */
typedef struct WdcHttpPlatformConfig {
    WdcHttpService *service;
    const char *wifi_ssid;
    const char *wifi_password;
    const uint8_t *server_certificate_pem;
    size_t server_certificate_bytes;
    const uint8_t *server_private_key_pem;
    size_t server_private_key_bytes;
    uint8_t boot_channel_binding_sha256[32];
    uint16_t app_port;
    uint16_t admin_port;
    uint32_t connect_timeout_ms;
    uint32_t reconnect_attempts;
} WdcHttpPlatformConfig;

typedef struct WdcHttpPlatformStatus {
    bool initialized;
    bool wifi_connected;
    bool app_listener_started;
    bool admin_listener_started;
    uint32_t reconnect_count;
    int32_t last_status;
} WdcHttpPlatformStatus;

int32_t wdc_http_platform_start(const WdcHttpPlatformConfig *config);
void wdc_http_platform_stop(void);
void wdc_http_platform_get_status(WdcHttpPlatformStatus *out_status);
uint32_t wdc_http_platform_link_anchor(void);

#ifdef __cplusplus
}
#endif
