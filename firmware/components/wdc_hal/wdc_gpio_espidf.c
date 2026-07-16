#include "wdc_gpio.h"

#include <stddef.h>
#include <string.h>

#include "wdc_abi.h"

#ifdef ESP_PLATFORM
#include "driver/gpio.h"
#include "esp_err.h"
#endif

#define WDC_HAL_GPIO_STATE_SLOTS 8u

typedef struct WdcHalGpioState {
    bool used;
    uint32_t resource_id;
    uint32_t level;
} WdcHalGpioState;


#ifndef ESP_PLATFORM
__attribute__((weak)) void wdc_host_call_set_gpio_hooks(WdcHostGpioWriteFn write_fn, WdcHostGpioReadFn read_fn, void *ctx)
{
    (void)write_fn;
    (void)read_fn;
    (void)ctx;
}

__attribute__((weak)) void wdc_host_call_clear_gpio_hooks(void)
{
}
#endif

static uint32_t s_safe_defaults_applied;
static WdcHalGpioState s_gpio_state[WDC_HAL_GPIO_STATE_SLOTS];

static int32_t wdc_hal_find_state(uint32_t resource_id)
{
    for (uint32_t i = 0u; i < WDC_HAL_GPIO_STATE_SLOTS; ++i) {
        if (s_gpio_state[i].used && s_gpio_state[i].resource_id == resource_id) {
            return (int32_t)i;
        }
    }
    return -1;
}

static int32_t wdc_hal_set_state(uint32_t resource_id, uint32_t level)
{
    int32_t index = wdc_hal_find_state(resource_id);
    if (index < 0) {
        for (uint32_t i = 0u; i < WDC_HAL_GPIO_STATE_SLOTS; ++i) {
            if (!s_gpio_state[i].used) {
                index = (int32_t)i;
                break;
            }
        }
    }
    if (index < 0) {
        return WDC_ERR_NO_MEMORY;
    }
    s_gpio_state[index].used = true;
    s_gpio_state[index].resource_id = resource_id;
    s_gpio_state[index].level = level != 0u ? 1u : 0u;
    return WDC_OK;
}

static int32_t wdc_hal_configure_gpio(const WdcGpioResource *gpio)
{
    if (gpio == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    if (gpio->pin < 0 || gpio->pin > 48) {
        return WDC_ERR_INVALID_RESOURCE;
    }

#ifdef ESP_PLATFORM
    gpio_config_t cfg = {
        .pin_bit_mask = (1ULL << (uint32_t)gpio->pin),
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .pull_up_en = GPIO_PULLUP_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };

    switch (gpio->mode) {
    case WDC_GPIO_MODE_OUTPUT:
        cfg.mode = GPIO_MODE_OUTPUT;
        break;
    case WDC_GPIO_MODE_INPUT_PULLUP:
        cfg.mode = GPIO_MODE_INPUT;
        cfg.pull_up_en = GPIO_PULLUP_ENABLE;
        break;
    case WDC_GPIO_MODE_INPUT:
        cfg.mode = GPIO_MODE_INPUT;
        break;
    case WDC_GPIO_MODE_DISABLED:
    default:
        return WDC_OK;
    }

    esp_err_t err = gpio_config(&cfg);
    if (err != ESP_OK) {
        return WDC_ERR_IO;
    }

    if (gpio->mode == WDC_GPIO_MODE_OUTPUT && gpio->apply_safe_level) {
        err = gpio_set_level((gpio_num_t)gpio->pin, gpio->safe_level ? 1 : 0);
        if (err != ESP_OK) {
            return WDC_ERR_IO;
        }
    }
#endif

    if (gpio->mode == WDC_GPIO_MODE_OUTPUT && gpio->apply_safe_level) {
        return wdc_hal_set_state(gpio->resource_id, gpio->safe_level != 0 ? 1u : 0u);
    }
    if (gpio->mode == WDC_GPIO_MODE_INPUT_PULLUP) {
        return wdc_hal_set_state(gpio->resource_id, 1u);
    }
    if (gpio->mode == WDC_GPIO_MODE_INPUT) {
        return wdc_hal_set_state(gpio->resource_id, 0u);
    }
    return WDC_OK;
}

int32_t wdc_hal_apply_safe_gpio_defaults(const WdcDeviceProfile *profile)
{
    if (profile == NULL || profile->gpio == NULL) {
        return WDC_ERR_BAD_POINTER;
    }

    int32_t status = wdc_profile_validate_basic(profile);
    if (status != WDC_OK) {
        return status;
    }

    s_safe_defaults_applied = 0u;
    for (size_t i = 0; i < profile->gpio_count; ++i) {
        status = wdc_hal_configure_gpio(&profile->gpio[i]);
        if (status != WDC_OK) {
            return status;
        }
        if (profile->gpio[i].mode == WDC_GPIO_MODE_OUTPUT && profile->gpio[i].apply_safe_level) {
            s_safe_defaults_applied++;
        }
    }
    return WDC_OK;
}

uint32_t wdc_hal_safe_gpio_defaults_applied(void)
{
    return s_safe_defaults_applied;
}

int32_t wdc_hal_gpio_set_level_by_resource(const WdcDeviceProfile *profile,
                                           uint32_t resource_id,
                                           uint32_t value)
{
    const WdcGpioResource *gpio = wdc_profile_find_gpio_by_id(profile, resource_id);
    if (gpio == NULL) {
        return WDC_ERR_INVALID_RESOURCE;
    }
    if (gpio->mode != WDC_GPIO_MODE_OUTPUT) {
        return WDC_ERR_INVALID_RESOURCE;
    }
    if (value > 1u) {
        return WDC_ERR_BAD_ENCODING;
    }

#ifdef ESP_PLATFORM
    esp_err_t err = gpio_set_level((gpio_num_t)gpio->pin, value ? 1 : 0);
    if (err != ESP_OK) {
        return WDC_ERR_IO;
    }
#endif

    return wdc_hal_set_state(resource_id, value);
}

int32_t wdc_hal_gpio_get_level_by_resource(const WdcDeviceProfile *profile,
                                           uint32_t resource_id,
                                           uint32_t *out_value)
{
    if (out_value == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    const WdcGpioResource *gpio = wdc_profile_find_gpio_by_id(profile, resource_id);
    if (gpio == NULL) {
        return WDC_ERR_INVALID_RESOURCE;
    }

#ifdef ESP_PLATFORM
    if (gpio->mode == WDC_GPIO_MODE_INPUT || gpio->mode == WDC_GPIO_MODE_INPUT_PULLUP) {
        int level = gpio_get_level((gpio_num_t)gpio->pin);
        *out_value = level != 0 ? 1u : 0u;
        (void)wdc_hal_set_state(resource_id, *out_value);
        return WDC_OK;
    }
#endif

    int32_t index = wdc_hal_find_state(resource_id);
    if (index < 0) {
        return WDC_ERR_NOT_AVAILABLE;
    }
    *out_value = s_gpio_state[index].level;
    return WDC_OK;
}

bool wdc_hal_gpio_outputs_match_safe_levels(const WdcDeviceProfile *profile)
{
    if (profile == NULL || profile->gpio == NULL) {
        return false;
    }
    for (size_t i = 0; i < profile->gpio_count; ++i) {
        const WdcGpioResource *gpio = &profile->gpio[i];
        if (gpio->mode != WDC_GPIO_MODE_OUTPUT || !gpio->apply_safe_level) {
            continue;
        }
        uint32_t level = 0u;
        if (wdc_hal_gpio_get_level_by_resource(profile, gpio->resource_id, &level) != WDC_OK) {
            return false;
        }
        if (level != (gpio->safe_level != 0 ? 1u : 0u)) {
            return false;
        }
    }
    return true;
}

static int32_t wdc_hal_gpio_write_hook(void *ctx, uint32_t resource_id, uint32_t value)
{
    return wdc_hal_gpio_set_level_by_resource((const WdcDeviceProfile *)ctx, resource_id, value);
}

static int32_t wdc_hal_gpio_read_hook(void *ctx, uint32_t resource_id, uint32_t *out_value)
{
    return wdc_hal_gpio_get_level_by_resource((const WdcDeviceProfile *)ctx, resource_id, out_value);
}

int32_t wdc_hal_install_host_gpio_bridge(const WdcDeviceProfile *profile)
{
    if (profile == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    wdc_host_call_set_gpio_hooks(wdc_hal_gpio_write_hook, wdc_hal_gpio_read_hook, (void *)profile);
    return WDC_OK;
}

void wdc_hal_clear_host_gpio_bridge(void)
{
    wdc_host_call_clear_gpio_hooks();
}

void wdc_hal_gpio_reset_state_for_test(void)
{
    memset(s_gpio_state, 0, sizeof(s_gpio_state));
    s_safe_defaults_applied = 0u;
    wdc_hal_clear_host_gpio_bridge();
}
