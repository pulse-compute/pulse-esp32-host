#include "wdc_profile.h"

#include <string.h>

static const WdcProfileResource s_resources[] = {
    { WDC_R4_RESOURCE_RELAY_1, WDC_RESOURCE_KIND_GPIO, "relay_1" },
    { WDC_R4_RESOURCE_STATUS_LED, WDC_RESOURCE_KIND_GPIO, "status_led" },
    { WDC_R4_RESOURCE_BUTTON_1, WDC_RESOURCE_KIND_GPIO, "button_1" },
    { WDC_R4_RESOURCE_TEMP_AMBIENT, WDC_RESOURCE_KIND_SENSOR, "temp_ambient" },
    { WDC_R8_RESOURCE_MQTT_TELEMETRY, WDC_RESOURCE_KIND_NETWORK, "mqtt_telemetry" },
    { WDC_R8_RESOURCE_MQTT_COMMANDS, WDC_RESOURCE_KIND_NETWORK, "mqtt_commands" },
    { WDC_R8_RESOURCE_HTTP_API, WDC_RESOURCE_KIND_NETWORK, "http_api" },
    { WDC_R4_RESOURCE_APP_STATE, WDC_RESOURCE_KIND_STORAGE, "app_state" },
};

static const WdcGpioResource s_gpio[] = {
    {
        .resource_id = WDC_R4_RESOURCE_RELAY_1,
        .name = "relay_1",
        .pin = 12,
        .mode = WDC_GPIO_MODE_OUTPUT,
        .active_level = 1,
        .safe_level = 0,
        .apply_safe_level = true,
    },
    {
        .resource_id = WDC_R4_RESOURCE_STATUS_LED,
        .name = "status_led",
        .pin = 48,
        .mode = WDC_GPIO_MODE_OUTPUT,
        .active_level = 0,
        .safe_level = 1,
        .apply_safe_level = true,
    },
    {
        .resource_id = WDC_R4_RESOURCE_BUTTON_1,
        .name = "button_1",
        .pin = 0,
        .mode = WDC_GPIO_MODE_INPUT_PULLUP,
        .active_level = 0,
        .safe_level = 1,
        .apply_safe_level = false,
    },
};

static const WdcNetworkResource s_network[] = {
    {
        .resource_id = WDC_R8_RESOURCE_MQTT_TELEMETRY,
        .name = "mqtt_telemetry",
        .mqtt_topic_prefix = "devices/demo/telemetry",
        .mqtt_subscribe_prefix = NULL,
        .http_url_prefix = NULL,
        .http_methods_csv = NULL,
        .max_payload_bytes = 512u,
    },
    {
        .resource_id = WDC_R8_RESOURCE_MQTT_COMMANDS,
        .name = "mqtt_commands",
        .mqtt_topic_prefix = NULL,
        .mqtt_subscribe_prefix = "devices/demo/commands/",
        .http_url_prefix = NULL,
        .http_methods_csv = NULL,
        .max_payload_bytes = 256u,
    },
    {
        .resource_id = WDC_R8_RESOURCE_HTTP_API,
        .name = "http_api",
        .mqtt_topic_prefix = NULL,
        .mqtt_subscribe_prefix = NULL,
        .http_url_prefix = "https://api.example.invalid/devices/demo/",
        .http_methods_csv = "GET,POST",
        .max_payload_bytes = 1024u,
    },
};

static const WdcDeviceProfile s_builtin = {
    .device_class = "relay-node",
    .hardware = "esp32-s3",
    .board_rev = "c",
    .resources = s_resources,
    .resource_count = sizeof(s_resources) / sizeof(s_resources[0]),
    .gpio = s_gpio,
    .gpio_count = sizeof(s_gpio) / sizeof(s_gpio[0]),
    .network = s_network,
    .network_count = sizeof(s_network) / sizeof(s_network[0]),
};

const WdcDeviceProfile *wdc_profile_builtin(void)
{
    return &s_builtin;
}

static bool wdc_gpio_pin_valid(int pin)
{
    return pin >= 0 && pin <= 48;
}

static bool resource_id_seen(const WdcDeviceProfile *profile, uint32_t resource_id, size_t before_index)
{
    for (size_t i = 0; i < before_index; ++i) {
        if (profile->resources[i].resource_id == resource_id) {
            return true;
        }
    }
    return false;
}

int32_t wdc_profile_validate_basic(const WdcDeviceProfile *profile)
{
    if (profile == NULL || profile->device_class == NULL || profile->hardware == NULL ||
        profile->board_rev == NULL || profile->resources == NULL || profile->resource_count == 0u ||
        profile->gpio == NULL || profile->gpio_count == 0u ||
        profile->network == NULL || profile->network_count == 0u) {
        return WDC_ERR_BAD_POINTER;
    }

    for (size_t i = 0; i < profile->resource_count; ++i) {
        const WdcProfileResource *resource = &profile->resources[i];
        if (resource->resource_id == 0u || resource->kind == WDC_RESOURCE_KIND_NONE ||
            resource->name == NULL || resource->name[0] == '\0') {
            return WDC_ERR_BAD_ENCODING;
        }
        if (resource_id_seen(profile, resource->resource_id, i)) {
            return WDC_ERR_BAD_ENCODING;
        }
    }

    for (size_t i = 0; i < profile->gpio_count; ++i) {
        const WdcGpioResource *gpio = &profile->gpio[i];
        if (gpio->resource_id == 0u || gpio->name == NULL || gpio->name[0] == '\0') {
            return WDC_ERR_BAD_ENCODING;
        }
        if (wdc_profile_find_resource_by_id(profile, gpio->resource_id) == NULL) {
            return WDC_ERR_INVALID_RESOURCE;
        }
        if (!wdc_gpio_pin_valid(gpio->pin)) {
            return WDC_ERR_INVALID_RESOURCE;
        }
        if (gpio->safe_level != 0 && gpio->safe_level != 1) {
            return WDC_ERR_BAD_ENCODING;
        }
        if (gpio->active_level != 0 && gpio->active_level != 1) {
            return WDC_ERR_BAD_ENCODING;
        }
    }

    for (size_t i = 0; i < profile->network_count; ++i) {
        const WdcNetworkResource *net = &profile->network[i];
        if (net->resource_id == 0u || net->name == NULL || net->name[0] == '\0') {
            return WDC_ERR_BAD_ENCODING;
        }
        const WdcProfileResource *resource = wdc_profile_find_resource_by_id(profile, net->resource_id);
        if (resource == NULL || resource->kind != WDC_RESOURCE_KIND_NETWORK) {
            return WDC_ERR_INVALID_RESOURCE;
        }
        if (net->mqtt_topic_prefix == NULL && net->mqtt_subscribe_prefix == NULL && net->http_url_prefix == NULL) {
            return WDC_ERR_BAD_ENCODING;
        }
        if (net->max_payload_bytes == 0u) {
            return WDC_ERR_BAD_ENCODING;
        }
    }

    return WDC_OK;
}

const WdcProfileResource *wdc_profile_find_resource_by_id(const WdcDeviceProfile *profile, uint32_t resource_id)
{
    if (profile == NULL || profile->resources == NULL || resource_id == 0u) {
        return NULL;
    }
    for (size_t i = 0; i < profile->resource_count; ++i) {
        if (profile->resources[i].resource_id == resource_id) {
            return &profile->resources[i];
        }
    }
    return NULL;
}

const WdcProfileResource *wdc_profile_find_resource_by_name(const WdcDeviceProfile *profile, WdcResourceKind kind, const char *name)
{
    if (profile == NULL || profile->resources == NULL || name == NULL) {
        return NULL;
    }
    for (size_t i = 0; i < profile->resource_count; ++i) {
        if (profile->resources[i].kind == kind && profile->resources[i].name != NULL && strcmp(profile->resources[i].name, name) == 0) {
            return &profile->resources[i];
        }
    }
    return NULL;
}

const WdcGpioResource *wdc_profile_find_gpio_by_id(const WdcDeviceProfile *profile, uint32_t resource_id)
{
    if (profile == NULL || profile->gpio == NULL || resource_id == 0u) {
        return NULL;
    }
    for (size_t i = 0; i < profile->gpio_count; ++i) {
        if (profile->gpio[i].resource_id == resource_id) {
            return &profile->gpio[i];
        }
    }
    return NULL;
}

const WdcGpioResource *wdc_profile_find_gpio_by_name(const WdcDeviceProfile *profile, const char *name)
{
    if (profile == NULL || profile->gpio == NULL || name == NULL) {
        return NULL;
    }
    for (size_t i = 0; i < profile->gpio_count; ++i) {
        if (profile->gpio[i].name != NULL && strcmp(profile->gpio[i].name, name) == 0) {
            return &profile->gpio[i];
        }
    }
    return NULL;
}

const WdcNetworkResource *wdc_profile_find_network_by_id(const WdcDeviceProfile *profile, uint32_t resource_id)
{
    if (profile == NULL || profile->network == NULL || resource_id == 0u) {
        return NULL;
    }
    for (size_t i = 0; i < profile->network_count; ++i) {
        if (profile->network[i].resource_id == resource_id) {
            return &profile->network[i];
        }
    }
    return NULL;
}

const WdcNetworkResource *wdc_profile_find_network_by_name(const WdcDeviceProfile *profile, const char *name)
{
    if (profile == NULL || profile->network == NULL || name == NULL) {
        return NULL;
    }
    for (size_t i = 0; i < profile->network_count; ++i) {
        if (profile->network[i].name != NULL && strcmp(profile->network[i].name, name) == 0) {
            return &profile->network[i];
        }
    }
    return NULL;
}
