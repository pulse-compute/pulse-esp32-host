#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "wdc_abi.h"
#include "wdc_events.h"
#include "wdc_profile.h"

#ifdef __cplusplus
extern "C" {
#endif

/* R8 network mediation deliberately keeps Wi-Fi/TLS/MQTT/HTTP ownership native.
 * WASM app logic can request publish/subscribe/request operations, but cannot
 * own credentials, sockets, radio state, or TLS material. */
#define WDC_NET_TOPIC_MAX_BYTES     96u
#define WDC_NET_METHOD_MAX_BYTES    8u
#define WDC_NET_URL_MAX_BYTES       160u
#define WDC_NET_PAYLOAD_MAX_BYTES   1024u

/* Compatibility aliases for older R8 smoke code. */
#define WDC_NET_TOPIC_MAX   WDC_NET_TOPIC_MAX_BYTES
#define WDC_NET_METHOD_MAX  WDC_NET_METHOD_MAX_BYTES
#define WDC_NET_URL_MAX     WDC_NET_URL_MAX_BYTES
#define WDC_NET_PAYLOAD_MAX WDC_NET_PAYLOAD_MAX_BYTES

typedef enum WdcNetState {
    WDC_NET_STATE_UNINITIALIZED = 0,
    WDC_NET_STATE_DISCONNECTED = 1,
    WDC_NET_STATE_CONNECTED = 2,
    WDC_NET_STATE_DEGRADED = 3,

    WDC_NET_STATE_DOWN = WDC_NET_STATE_DISCONNECTED,
    WDC_NET_STATE_WIFI_CONNECTED = WDC_NET_STATE_CONNECTED,
    WDC_NET_STATE_MQTT_CONNECTED = WDC_NET_STATE_CONNECTED,
} WdcNetState;

typedef struct WdcNetOperation {
    uint32_t resource_id;
    uint32_t request_id;
    uint32_t payload_len;
    uint32_t qos;
    char topic[WDC_NET_TOPIC_MAX_BYTES];
    char method[WDC_NET_METHOD_MAX_BYTES];
    char url[WDC_NET_URL_MAX_BYTES];
} WdcNetOperation;

typedef struct WdcNetStatus {
    WdcNetState state;
    bool initialized;
    bool connected;
    uint32_t next_request_id;
    uint32_t last_request_id;
    uint32_t publish_count;
    uint32_t subscribe_count;
    uint32_t http_request_count;
    uint32_t denied_disconnected_count;
    uint32_t rejected_count;
    int32_t last_status;
    WdcNetOperation last_publish;
    WdcNetOperation last_subscribe;
    WdcNetOperation last_http_request;
} WdcNetStatus;

/* Host-private paired response bridge.  The network mediator knows only that
 * an active host service may consume WDC_OP_HTTP_RESPOND; it does not depend
 * on HTTP listener or administration authority. */
typedef int32_t (*WdcNetHttpResponseHookFn)(
    void *context,
    const uint8_t *request,
    uint32_t request_len,
    uint8_t *response,
    uint32_t response_cap,
    uint32_t *out_response_len);

const char *wdc_net_state_name(WdcNetState state);
int32_t wdc_net_init(const WdcDeviceProfile *profile);
void wdc_net_reset_for_test(void);
void wdc_net_get_status(WdcNetStatus *out_status);
int32_t wdc_net_set_state(WdcNetState state, const char *reason);
WdcNetState wdc_net_get_state(void);
int32_t wdc_net_set_connected(bool connected, const char *reason);
int32_t wdc_net_install_host_bridge(const WdcDeviceProfile *profile);
int32_t wdc_net_install_host_hook(void);
void wdc_net_clear_host_bridge(void);
void wdc_net_clear_host_hook(void);
int32_t wdc_net_set_http_response_hook(WdcNetHttpResponseHookFn hook,
                                       void *context);
void wdc_net_clear_http_response_hook(WdcNetHttpResponseHookFn hook,
                                      void *context);

int32_t wdc_net_host_call(void *ctx,
                          uint32_t opcode,
                          const uint8_t *request,
                          uint32_t request_len,
                          uint8_t *response,
                          uint32_t response_cap,
                          uint32_t *out_response_len);

int32_t wdc_net_handle_host_call(void *ctx,
                                 uint32_t opcode,
                                 const uint8_t *request,
                                 uint32_t request_len,
                                 uint8_t *response,
                                 uint32_t response_cap,
                                 uint32_t *out_response_len);

#ifdef __cplusplus
}
#endif
