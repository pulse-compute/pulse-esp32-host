#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "wdc_profile.h"

#ifdef __cplusplus
extern "C" {
#endif

int32_t wdc_hal_apply_safe_gpio_defaults(const WdcDeviceProfile *profile);
uint32_t wdc_hal_safe_gpio_defaults_applied(void);

int32_t wdc_hal_gpio_set_level_by_resource(const WdcDeviceProfile *profile,
                                           uint32_t resource_id,
                                           uint32_t value);
int32_t wdc_hal_gpio_get_level_by_resource(const WdcDeviceProfile *profile,
                                           uint32_t resource_id,
                                           uint32_t *out_value);
bool wdc_hal_gpio_outputs_match_safe_levels(const WdcDeviceProfile *profile);

int32_t wdc_hal_install_host_gpio_bridge(const WdcDeviceProfile *profile);
void wdc_hal_clear_host_gpio_bridge(void);
void wdc_hal_gpio_reset_state_for_test(void);

#ifdef __cplusplus
}
#endif
