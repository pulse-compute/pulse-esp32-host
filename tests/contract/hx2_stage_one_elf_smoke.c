#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

#include "wdc_extension.h"

static const char *const s_import_names[] = {
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

static const uint32_t s_import_addresses[] = {
    1u, 1u, 1u, 1u, 1u, 1u, 1u, 1u, 1u, 1u, 1u, 1u, 1u,
};

static int read_file(const char *path, uint8_t **out_bytes, uint32_t *out_size)
{
    FILE *handle;
    long length;
    uint8_t *bytes;

    handle = fopen(path, "rb");
    if (handle == NULL || fseek(handle, 0, SEEK_END) != 0) {
        return 0;
    }
    length = ftell(handle);
    if (length <= 0 || (unsigned long)length > UINT32_MAX ||
        fseek(handle, 0, SEEK_SET) != 0) {
        fclose(handle);
        return 0;
    }
    bytes = malloc((size_t)length);
    if (bytes == NULL || fread(bytes, 1u, (size_t)length, handle) != (size_t)length) {
        free(bytes);
        fclose(handle);
        return 0;
    }
    fclose(handle);
    *out_bytes = bytes;
    *out_size = (uint32_t)length;
    return 1;
}

int main(int argc, char **argv)
{
    WdcExtensionInspection inspection;
    WdcExtensionProfile profile = {0};
    uint8_t *bytes = NULL;
    uint32_t size = 0u;
    int32_t status;

    if (argc != 2 || !read_file(argv[1], &bytes, &size)) {
        return 2;
    }
    profile.elf_machine = 94u;
    profile.architecture_id = 1u;
    profile.soc_id = 1u;
    profile.host_abi_major = PULSE_HOST_ABI_MAJOR_V1;
    profile.host_abi_minor = PULSE_HOST_ABI_MINOR_V1;
    profile.max_task_stack_bytes = 8192u;
    profile.max_static_memory_bytes = 16384u;
    profile.max_queue_depth = 16u;
    profile.max_queue_item_bytes = 512u;
    profile.max_queue_storage_bytes = 4096u;
    profile.max_event_payload_bytes = 128u;
    profile.max_effect_request_bytes = 256u;
    profile.max_effect_completion_bytes = 256u;
    profile.allowed_imports = s_import_names;
    profile.allowed_import_addresses = s_import_addresses;
    profile.allowed_import_count =
        (uint32_t)(sizeof(s_import_names) / sizeof(s_import_names[0]));

    status = wdc_extension_inspect(bytes, size, &profile, &inspection);
    free(bytes);
    if (status != WDC_EXTENSION_OK) {
        fprintf(stderr, "sealed ELF target inspection failed: %d\n", status);
        return 1;
    }
    if (inspection.entry_virtual_address == 0u) {
        fprintf(stderr, "sealed ELF entry address was not captured\n");
        return 1;
    }
    return 0;
}
