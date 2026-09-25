#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

#include "esp_heap_caps.h"
#include "wdc_elf_allocator.h"

static uint32_t s_observed_size;
static uint32_t s_observed_alignment;
static uint32_t s_observed_capabilities;
static void *s_observed_free;
static uint8_t s_text_allocation;
static uint8_t s_writable_allocation[8192] __attribute__((aligned(4096)));

void *heap_caps_malloc(size_t size, uint32_t capabilities)
{
    s_observed_size = (uint32_t)size;
    s_observed_capabilities = capabilities;
    return &s_text_allocation;
}

void *heap_caps_aligned_alloc(size_t alignment, size_t size,
                              uint32_t capabilities)
{
    s_observed_alignment = (uint32_t)alignment;
    s_observed_size = (uint32_t)size;
    s_observed_capabilities = capabilities;
    return s_writable_allocation;
}

void heap_caps_free(void *pointer)
{
    s_observed_free = pointer;
}

extern void *__wrap_esp_elf_malloc(uint32_t size, bool executable);
extern void __wrap_esp_elf_free(void *pointer);

static uint8_t *read_file(const char *path, uint32_t *out_size)
{
    FILE *file;
    long size;
    uint8_t *bytes;

    file = fopen(path, "rb");
    if (file == NULL || fseek(file, 0, SEEK_END) != 0) {
        return NULL;
    }
    size = ftell(file);
    if (size <= 0 || size > (long)UINT32_MAX ||
        fseek(file, 0, SEEK_SET) != 0) {
        fclose(file);
        return NULL;
    }
    bytes = malloc((size_t)size);
    if (bytes == NULL || fread(bytes, 1u, (size_t)size, file) != (size_t)size) {
        free(bytes);
        fclose(file);
        return NULL;
    }
    fclose(file);
    *out_size = (uint32_t)size;
    return bytes;
}

int main(int argc, char **argv)
{
    uint8_t *elf_bytes;
    uint8_t *writable;
    uint32_t elf_size;

    if (argc != 2) {
        return 1;
    }
    elf_bytes = read_file(argv[1], &elf_size);
    if (elf_bytes == NULL ||
        wdc_elf_allocator_prepare(elf_bytes, elf_size) != 0) {
        return 2;
    }
    writable = __wrap_esp_elf_malloc(6978u, false);
    if (writable != s_writable_allocation + 14u ||
        s_observed_alignment != 16u || s_observed_size != 6993u ||
        s_observed_capabilities !=
            (MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT)) {
        return 3;
    }
    if (((uintptr_t)writable + 34u) % 4u != 0u ||
        ((uintptr_t)writable + 194u) % 16u != 0u ||
        wdc_elf_allocator_finish() != 0) {
        return 4;
    }
    __wrap_esp_elf_free(writable);
    if (s_observed_free != s_writable_allocation) {
        return 5;
    }
    free(elf_bytes);
    return 0;
}
