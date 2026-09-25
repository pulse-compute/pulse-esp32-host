#include "wdc_control.h"

#include <stdint.h>

#include "esp_attr.h"
#include "esp_heap_caps.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

_Static_assert(configMAX_PRIORITIES > 13,
               "HP1 requires its safety/recovery priority to exist");
_Static_assert(configUSE_TASK_NOTIFICATIONS == 1,
               "HP1 requires direct FreeRTOS task notifications");

static TaskHandle_t s_notification_task;

int32_t wdc_control_platform_bind_notification_task(void *host_task_handle)
{
    TaskHandle_t task = (TaskHandle_t)host_task_handle;
    if (task == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    if (s_notification_task != NULL && s_notification_task != task) {
        return WDC_ERR_INVALID_STATE;
    }
    s_notification_task = task;
    return WDC_OK;
}

void wdc_control_platform_unbind_notification_task(void)
{
    s_notification_task = NULL;
}

int32_t IRAM_ATTR wdc_control_platform_capture_from_isr(
    WdcControlKernel *kernel,
    const WdcControlIsrCapture *capture,
    int32_t *out_higher_priority_woken)
{
    BaseType_t higher_priority_woken = pdFALSE;
    int32_t status;
    if (out_higher_priority_woken == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    *out_higher_priority_woken = 0;
    if (s_notification_task == NULL) {
        return WDC_ERR_INVALID_STATE;
    }
    status = wdc_control_capture_isr(kernel, capture);
    if (status != WDC_OK) {
        return status;
    }
    vTaskNotifyGiveFromISR(s_notification_task, &higher_priority_woken);
    *out_higher_priority_woken = higher_priority_woken == pdTRUE ? 1 : 0;
    return WDC_OK;
}

int32_t wdc_control_platform_heap_snapshot(WdcControlHeapSnapshot *out_snapshot)
{
    uint32_t internal_caps = MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT;
    if (out_snapshot == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    out_snapshot->internal_free_bytes =
        (uint32_t)heap_caps_get_free_size(internal_caps);
    out_snapshot->internal_largest_block_bytes =
        (uint32_t)heap_caps_get_largest_free_block(internal_caps);
    out_snapshot->psram_free_bytes =
        (uint32_t)heap_caps_get_free_size(MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    return out_snapshot->internal_free_bytes != 0u &&
                   out_snapshot->internal_largest_block_bytes != 0u
               ? WDC_OK
               : WDC_ERR_NOT_AVAILABLE;
}
