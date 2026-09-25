#include <stdbool.h>
#include <stdint.h>

#include "esp_heap_caps.h"

/*
 * elf_loader 1.3.2's unified-segment branch receives executable=true but
 * drops MALLOC_CAP_EXEC and allocates ordinary byte-addressable RAM.  With
 * ESP32-C6 PMP IRAM/DRAM splitting enabled that RAM is RW/NX, so the first
 * call through the relocated entry pointer raises an instruction-access
 * fault.  The C6 extension profiles disable that fixed split because a
 * dynamic ELF segment must be writable while loading and executable later.
 *
 * Retain the loader's cache-alignment requirement, but make executable
 * intent explicit and fail closed if the active memory policy cannot supply
 * it.  ESP32-C6 uses one shared D/IRAM address space, so the executable
 * allocation remains writable while the segment is copied and relocated.
 */
void *__wrap_esp_elf_malloc(uint32_t size, bool executable)
{
    uint32_t capabilities = MALLOC_CAP_INTERNAL | MALLOC_CAP_CACHE_ALIGNED;

    capabilities |= executable ? MALLOC_CAP_EXEC : MALLOC_CAP_8BIT;
    return heap_caps_malloc(size, capabilities);
}

void __wrap_esp_elf_free(void *pointer)
{
    heap_caps_free(pointer);
}
