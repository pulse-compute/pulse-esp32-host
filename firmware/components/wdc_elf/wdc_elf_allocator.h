#pragma once

#include <stdint.h>

int32_t wdc_elf_allocator_prepare(const uint8_t *elf_bytes, uint32_t elf_size);
int32_t wdc_elf_allocator_finish(void);
