#include <stddef.h>
#include <stdint.h>
#include <string.h>

#include "esp_heap_caps.h"
#include "wdc_runtime_buffer.h"

static uint8_t s_storage[512];
static size_t s_observed_size;
static uint32_t s_observed_capabilities;
static void *s_observed_free;

void *heap_caps_malloc(size_t size, uint32_t capabilities)
{
    s_observed_size = size;
    s_observed_capabilities = capabilities;
    return s_storage;
}

void heap_caps_free(void *pointer)
{
    s_observed_free = pointer;
}

int main(void)
{
    static const uint8_t source[] = {0x00u, 0x61u, 0x73u, 0x6du,
                                     0x01u, 0x00u, 0x00u, 0x00u};
    uint8_t *copy = wdc_runtime_buffer_copy(source, sizeof(source));

    if (copy != s_storage || s_observed_size != sizeof(source) ||
        s_observed_capabilities !=
            (MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT) ||
        memcmp(copy, source, sizeof(source)) != 0) {
        return 1;
    }
    copy[0] = 0xffu;
    if (source[0] != 0x00u) {
        return 2;
    }
    wdc_runtime_buffer_release(copy);
    if (s_observed_free != s_storage) {
        return 3;
    }
    return 0;
}
