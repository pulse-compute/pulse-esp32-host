#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "esp_heap_caps.h"

static uint32_t s_observed_size;
static uint32_t s_observed_capabilities;
static void *s_observed_free;
static uint8_t s_allocation;

void *heap_caps_malloc(size_t size, uint32_t capabilities)
{
    s_observed_size = (uint32_t)size;
    s_observed_capabilities = capabilities;
    return &s_allocation;
}

void *heap_caps_aligned_alloc(size_t alignment, size_t size,
                              uint32_t capabilities)
{
    (void)alignment;
    return heap_caps_malloc(size, capabilities);
}

void heap_caps_free(void *pointer)
{
    s_observed_free = pointer;
}

extern void *__wrap_esp_elf_malloc(uint32_t size, bool executable);
extern void __wrap_esp_elf_free(void *pointer);

int main(void)
{
    void *pointer = __wrap_esp_elf_malloc(11248u, true);

    if (pointer != &s_allocation || s_observed_size != 11248u ||
        s_observed_capabilities !=
            (MALLOC_CAP_EXEC | MALLOC_CAP_INTERNAL |
             MALLOC_CAP_CACHE_ALIGNED)) {
        return 1;
    }
    pointer = __wrap_esp_elf_malloc(8008u, false);
    if (pointer != &s_allocation || s_observed_size != 8008u ||
        s_observed_capabilities !=
            (MALLOC_CAP_8BIT | MALLOC_CAP_INTERNAL |
             MALLOC_CAP_CACHE_ALIGNED)) {
        return 2;
    }
    __wrap_esp_elf_free(pointer);
    return s_observed_free == &s_allocation ? 0 : 3;
}
