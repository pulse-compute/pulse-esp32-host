#include <stdint.h>
#include <string.h>

#include "wdc_extension.h"

static int fail_if(int condition, int code)
{
    return condition ? code : 0;
}

int main(void)
{
    uint8_t source_bytes[sizeof(pulse_extension_descriptor_v1) + 4u];
    uintptr_t base = (uintptr_t)source_bytes;
    uint32_t offset = (uint32_t)((2u + 4u - (base & 3u)) & 3u);
    pulse_extension_descriptor_v1 source;
    pulse_extension_descriptor_v1 normalized;
    pulse_extension_descriptor_v1 *misaligned;
    WdcExtensionInspection inspection;
    WdcElfMemoryLayout memory;
    uint32_t index;
    int code;

    memset(&source, 0, sizeof(source));
    memset(&normalized, 0, sizeof(normalized));
    memset(&inspection, 0, sizeof(inspection));
    memset(&memory, 0, sizeof(memory));

    source.magic = PULSE_EXTENSION_DESCRIPTOR_MAGIC_V1;
    source.struct_size = PULSE_EXTENSION_DESCRIPTOR_SIZE_V1;
    source.abi_major = PULSE_EXTENSION_ABI_MAJOR_V1;
    source.abi_minor = PULSE_EXTENSION_ABI_MINOR_V1;
    source.event_count = 1u;
    source.operation_count = 1u;
    source.event_ids[0] = 0x5449434bu;
    source.operation_ids[0] = 0x4543484fu;
    source.init_fn = (pulse_extension_init_fn_v1)(uintptr_t)0x1010u;
    source.start_fn = (pulse_extension_start_fn_v1)(uintptr_t)0x1020u;
    source.invoke_fn = (pulse_extension_invoke_fn_v1)(uintptr_t)0x1030u;
    source.health_fn = (pulse_extension_health_fn_v1)(uintptr_t)0x1040u;
    source.quiesce_fn = (pulse_extension_quiesce_fn_v1)(uintptr_t)0x1050u;
    source.deinit_fn = (pulse_extension_deinit_fn_v1)(uintptr_t)0x1060u;
    for (index = 0u; index < 16u; ++index) {
        source.extension_id[index] = (uint8_t)(index + 1u);
        inspection.metadata.extension_id[index] = source.extension_id[index];
    }
    for (index = 0u; index < 32u; ++index) {
        source.metadata_sha256[index] = (uint8_t)(0xa0u + index);
        inspection.normalized_metadata_sha256[index] = source.metadata_sha256[index];
    }
    inspection.metadata.event_count = source.event_count;
    inspection.metadata.operation_count = source.operation_count;
    memcpy(inspection.metadata.event_ids, source.event_ids, sizeof(source.event_ids));
    memcpy(inspection.metadata.operation_ids,
           source.operation_ids,
           sizeof(source.operation_ids));

    misaligned = (pulse_extension_descriptor_v1 *)(void *)(source_bytes + offset);
    memcpy(misaligned, &source, sizeof(source));
    memory.executable_address = 0x1000u;
    memory.executable_size = 0x100u;
    memory.writable_address = (uint32_t)(uintptr_t)misaligned;
    memory.writable_size = sizeof(*misaligned);

    code = fail_if(((uintptr_t)misaligned & 3u) != 2u, 1);
    if (code != 0) {
        return code;
    }
    code = fail_if(wdc_extension_test_normalize_descriptor(
                       misaligned, &inspection, &memory, &normalized) != WDC_EXTENSION_OK,
                   2);
    if (code != 0) {
        return code;
    }
    code = fail_if(((uintptr_t)&normalized & 3u) != 0u, 3);
    if (code != 0) {
        return code;
    }
    code = fail_if(memcmp(&normalized, &source, sizeof(source)) != 0, 4);
    if (code != 0) {
        return code;
    }

    memory.writable_size = sizeof(*misaligned) - 1u;
    return fail_if(wdc_extension_test_normalize_descriptor(
                       misaligned, &inspection, &memory, &normalized) !=
                       WDC_EXTENSION_ERR_DESCRIPTOR,
                   5);
}
