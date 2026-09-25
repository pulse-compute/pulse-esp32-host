#ifndef PULSE_TEST_ESP_HEAP_CAPS_H
#define PULSE_TEST_ESP_HEAP_CAPS_H

#include <stddef.h>
#include <stdint.h>

#define MALLOC_CAP_8BIT (1u << 0)
#define MALLOC_CAP_INTERNAL (1u << 1)
#define MALLOC_CAP_SPIRAM (1u << 2)
#define MALLOC_CAP_EXEC (1u << 3)
#define MALLOC_CAP_CACHE_ALIGNED (1u << 4)

void *heap_caps_malloc(size_t size, uint32_t capabilities);
void *heap_caps_aligned_alloc(size_t alignment, size_t size,
                              uint32_t capabilities);
void heap_caps_free(void *pointer);

#endif
