#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#include "esp_heap_caps.h"
#include "platform_api_vmcore.h"

#define LINEAR_MEMORY_BYTES (128u * 1024u)

static uint8_t s_internal[LINEAR_MEMORY_BYTES + 32u]
    __attribute__((aligned(8)));
static uint8_t s_executable;
static size_t s_observed_size;
static uint32_t s_observed_capabilities;
static int s_real_mmap_calls;

void *heap_caps_malloc(size_t size, uint32_t capabilities)
{
    s_observed_size = size;
    s_observed_capabilities = capabilities;
    return s_internal;
}

void *__real_os_mmap(void *hint, size_t size, int prot, int flags,
                     os_file_handle file)
{
    (void)hint;
    (void)size;
    (void)prot;
    (void)flags;
    (void)file;
    s_real_mmap_calls++;
    return &s_executable;
}

extern void *__wrap_os_mmap(void *hint, size_t size, int prot, int flags,
                            os_file_handle file);

int main(void)
{
    uint8_t *linear;
    uint8_t *origin;
    void *executable;

    memset(s_internal, 0xa5, sizeof(s_internal));
    linear = __wrap_os_mmap(NULL, LINEAR_MEMORY_BYTES, MMAP_PROT_NONE, 0, 0);
    if (linear == NULL || ((uintptr_t)linear & 7u) != 0u ||
        s_observed_size != LINEAR_MEMORY_BYTES + 4u + sizeof(uintptr_t) ||
        s_observed_capabilities !=
            (MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT) ||
        s_real_mmap_calls != 0) {
        return 1;
    }
    for (size_t index = 0u; index < LINEAR_MEMORY_BYTES; ++index) {
        if (linear[index] != 0u) {
            return 2;
        }
    }
    memcpy(&origin, linear - sizeof(uintptr_t), sizeof(origin));
    if (origin != s_internal) {
        return 3;
    }
    executable = __wrap_os_mmap(NULL, 64u, MMAP_PROT_EXEC, 0, 0);
    if (executable != &s_executable || s_real_mmap_calls != 1) {
        return 4;
    }
    return 0;
}
