#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "wdc_abi.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef enum WdcGpioMode {
    WDC_GPIO_MODE_DISABLED = 0,
    WDC_GPIO_MODE_INPUT = 1,
    WDC_GPIO_MODE_INPUT_PULLUP = 2,
    WDC_GPIO_MODE_OUTPUT = 3,
} WdcGpioMode;

typedef struct WdcProfileResource {
    uint32_t resource_id;
    WdcResourceKind kind;
    const char *name;
} WdcProfileResource;

typedef struct WdcGpioResource {
    uint32_t resource_id;
    const char *name;
    int pin;
    WdcGpioMode mode;
    int active_level;
    int safe_level;
    bool apply_safe_level;
} WdcGpioResource;

typedef struct WdcNetworkResource {
    uint32_t resource_id;
    const char *name;
    const char *mqtt_topic_prefix;
    const char *mqtt_subscribe_prefix;
    const char *http_url_prefix;
    const char *http_methods_csv;
    uint32_t max_payload_bytes;
} WdcNetworkResource;

typedef struct WdcDeviceProfile {
    const char *device_class;
    const char *hardware;
    const char *board_rev;
    const WdcProfileResource *resources;
    size_t resource_count;
    const WdcGpioResource *gpio;
    size_t gpio_count;
    const WdcNetworkResource *network;
    size_t network_count;
} WdcDeviceProfile;

const WdcDeviceProfile *wdc_profile_builtin(void);
int32_t wdc_profile_validate_basic(const WdcDeviceProfile *profile);
const WdcProfileResource *wdc_profile_find_resource_by_id(const WdcDeviceProfile *profile, uint32_t resource_id);
const WdcProfileResource *wdc_profile_find_resource_by_name(const WdcDeviceProfile *profile, WdcResourceKind kind, const char *name);
const WdcGpioResource *wdc_profile_find_gpio_by_id(const WdcDeviceProfile *profile, uint32_t resource_id);
const WdcGpioResource *wdc_profile_find_gpio_by_name(const WdcDeviceProfile *profile, const char *name);
const WdcNetworkResource *wdc_profile_find_network_by_id(const WdcDeviceProfile *profile, uint32_t resource_id);
const WdcNetworkResource *wdc_profile_find_network_by_name(const WdcDeviceProfile *profile, const char *name);

#ifdef __cplusplus
}
#endif
