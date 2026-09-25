#pragma once

#include <stdint.h>

#include "wdc_extension.h"
#include "wdc_runtime.h"

#ifdef __cplusplus
extern "C" {
#endif

#define WDC_EXTENSION_BRIDGE_DEFAULT_EFFECT_TIMEOUT_MS 1000u
#define WDC_EXTENSION_BRIDGE_ENCODING_CBOR 1u

typedef struct WdcExtensionBridgeConfig {
    uint32_t effect_timeout_ms;
    uint32_t max_effect_request_bytes;
    uint32_t max_effect_completion_bytes;
    uint32_t expected_event_id;
    uint32_t expected_operation_id;
} WdcExtensionBridgeConfig;

typedef struct WdcExtensionBridgeReport {
    int32_t status;
    int32_t runtime_status;
    int32_t completion_status;
    uint32_t event_queue_depth_before;
    uint32_t event_queue_depth_after;
    uint32_t event_type;
    uint32_t event_id;
    uint64_t causation_id;
    uint32_t event_payload_len;
    uint32_t event_encoded_len;
    uint32_t operation_id;
    uint64_t correlation_id;
    uint64_t deadline_ms;
    uint32_t effect_request_len;
    uint32_t completion_payload_len;
    uint32_t completion_latency_ms;
    uint32_t encoding;
    uint32_t effect_invoked;
    uint32_t completion_accepted;
    uint8_t completion_payload[WDC_EXTENSION_EFFECT_PAYLOAD_MAX];
} WdcExtensionBridgeReport;

typedef struct WdcExtensionBridge {
    WdcExtensionRegistry *registry;
    WdcRuntime *runtime;
    WdcExtensionBridgeConfig config;
    WdcExtensionBridgeReport report;
    WdcEvent current_event;
    uint64_t next_correlation_id;
    uint32_t current_event_active;
    uint32_t initialized;
} WdcExtensionBridge;

WdcExtensionBridgeConfig wdc_extension_bridge_default_config(void);
int32_t wdc_extension_bridge_init(WdcExtensionBridge *bridge,
                                  WdcExtensionRegistry *registry,
                                  WdcRuntime *runtime,
                                  const WdcExtensionBridgeConfig *config);
int32_t wdc_extension_bridge_process_next(WdcExtensionBridge *bridge);
void wdc_extension_bridge_deinit(WdcExtensionBridge *bridge);
const WdcExtensionBridgeReport *wdc_extension_bridge_get_report(
    const WdcExtensionBridge *bridge);

#ifdef __cplusplus
}
#endif
