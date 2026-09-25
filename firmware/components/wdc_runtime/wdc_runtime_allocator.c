#include <stddef.h>
#include <stdint.h>
#include <string.h>

#include "esp_heap_caps.h"
#include "platform_api_vmcore.h"

extern void *__real_os_mmap(void *hint, size_t size, int prot, int flags,
                            os_file_handle file);

/*
 * The pinned ESP-IDF WAMR port selects MALLOC_CAP_SPIRAM for every mmap when
 * ESP32-S3 PSRAM support is enabled, including writable interpreter linear
 * memory.  The HX4.5 named-board lane already consumes that cache-backed pool
 * for native executable text.  Keep executable mappings under WAMR's exact
 * policy, but give writable mappings an explicit internal, byte-accessible
 * allocation.  The prefix layout intentionally matches espidf_memmap.c so
 * the unmodified os_munmap/os_free path releases the original allocation.
 */
void *__wrap_os_mmap(void *hint, size_t size, int prot, int flags,
                     os_file_handle file)
{
    const size_t overhead = 4u + sizeof(uintptr_t);
    uint8_t *origin;
    uint8_t *fixed;
    uintptr_t aligned;

    if ((prot & MMAP_PROT_EXEC) != 0) {
        return __real_os_mmap(hint, size, prot, flags, file);
    }
    if (size > SIZE_MAX - overhead) {
        return NULL;
    }
    origin = heap_caps_malloc(size + overhead,
                              MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
    if (origin == NULL) {
        return NULL;
    }
    fixed = origin + sizeof(uintptr_t);
    aligned = ((uintptr_t)fixed + 7u) & ~(uintptr_t)7u;
    fixed = (uint8_t *)aligned;
    memcpy(fixed - sizeof(uintptr_t), &origin, sizeof(origin));
    memset(fixed, 0, size);
    return fixed;
}
