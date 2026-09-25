#include "wdc_runtime_buffer.h"

#include <stddef.h>
#include <string.h>

#include "esp_heap_caps.h"

uint8_t *wdc_runtime_buffer_copy(const uint8_t *source, uint32_t size)
{
    uint8_t *copy;

    if (source == NULL || size == 0u) {
        return NULL;
    }
    copy = heap_caps_malloc(size, MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
    if (copy == NULL) {
        return NULL;
    }
    memcpy(copy, source, size);
    return copy;
}

void wdc_runtime_buffer_release(uint8_t *buffer)
{
    heap_caps_free(buffer);
}
