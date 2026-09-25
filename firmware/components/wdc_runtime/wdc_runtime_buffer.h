#pragma once

#include <stdint.h>

uint8_t *wdc_runtime_buffer_copy(const uint8_t *source, uint32_t size);
void wdc_runtime_buffer_release(uint8_t *buffer);
