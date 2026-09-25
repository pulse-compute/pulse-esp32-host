#include "wdc_extension_internal.h"

#include <stdint.h>

#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/idf_additions.h"
#include "freertos/queue.h"
#include "freertos/task.h"

#define PULSE_HX3_STATIC_TASK_CONTROL_BYTES 2048u
#define PULSE_HX3_STATIC_QUEUE_CONTROL_BYTES 256u

_Static_assert(configSUPPORT_STATIC_ALLOCATION == 1,
               "HX3 requires FreeRTOS static allocation support");
_Static_assert(CONFIG_FREERTOS_TLSP_DELETION_CALLBACKS == 1,
               "HX3 requires confirmation when the static task is reaped");
_Static_assert(CONFIG_FREERTOS_THREAD_LOCAL_STORAGE_POINTERS >= 1,
               "HX3 requires one task-local deletion callback slot");
_Static_assert(sizeof(StackType_t) == 1u,
               "HX3's declared task-stack budget is expressed in ESP-IDF bytes");
_Static_assert(sizeof(StaticTask_t) <= PULSE_HX3_STATIC_TASK_CONTROL_BYTES,
               "HX3 synthetic StaticTask_t storage is too small");
_Static_assert(sizeof(StaticQueue_t) <= PULSE_HX3_STATIC_QUEUE_CONTROL_BYTES,
               "HX3 synthetic StaticQueue_t storage is too small");

static const char *const s_hx3_import_names[] = {
    "pulse_host_complete_effect_v1",
    "pulse_host_emit_event_v1",
    "pulse_host_monotonic_ms_v1",
    "pulse_host_report_health_v1",
    "uxTaskGetStackHighWaterMark",
    "vQueueDelete",
    "vTaskDelay",
    "vTaskDelete",
    "vTaskSetThreadLocalStoragePointerAndDelCallback",
    "xQueueGenericCreateStatic",
    "xQueueGenericSend",
    "xQueueReceive",
    "xTaskCreateStatic",
};

static const uint32_t s_hx3_import_addresses[] = {
    (uint32_t)(uintptr_t)&pulse_host_complete_effect_v1,
    (uint32_t)(uintptr_t)&pulse_host_emit_event_v1,
    (uint32_t)(uintptr_t)&pulse_host_monotonic_ms_v1,
    (uint32_t)(uintptr_t)&pulse_host_report_health_v1,
    (uint32_t)(uintptr_t)&uxTaskGetStackHighWaterMark,
    (uint32_t)(uintptr_t)&vQueueDelete,
    (uint32_t)(uintptr_t)&vTaskDelay,
    (uint32_t)(uintptr_t)&vTaskDelete,
    (uint32_t)(uintptr_t)&vTaskSetThreadLocalStoragePointerAndDelCallback,
    (uint32_t)(uintptr_t)&xQueueGenericCreateStatic,
    (uint32_t)(uintptr_t)&xQueueGenericSend,
    (uint32_t)(uintptr_t)&xQueueReceive,
    (uint32_t)(uintptr_t)&xTaskCreateStatic,
};

_Static_assert(sizeof(s_hx3_import_names) / sizeof(s_hx3_import_names[0]) ==
                   sizeof(s_hx3_import_addresses) / sizeof(s_hx3_import_addresses[0]),
               "HX3 import name/address table mismatch");
_Static_assert(sizeof(s_hx3_import_names) / sizeof(s_hx3_import_names[0]) <=
                   WDC_EXTENSION_IMPORT_CAPACITY,
               "HX3 import table exceeds inspector capacity");

void wdc_extension_platform_profile_imports(WdcExtensionProfile *profile)
{
    if (profile != NULL) {
        profile->allowed_imports = s_hx3_import_names;
        profile->allowed_import_addresses = s_hx3_import_addresses;
        profile->allowed_import_count =
            (uint32_t)(sizeof(s_hx3_import_names) / sizeof(s_hx3_import_names[0]));
    }
}

uint64_t wdc_extension_platform_monotonic_ms(void)
{
    int64_t microseconds = esp_timer_get_time();
    return microseconds <= 0 ? 0u : (uint64_t)microseconds / 1000u;
}
