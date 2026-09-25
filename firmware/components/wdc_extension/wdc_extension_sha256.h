#pragma once

#include <stdint.h>

typedef struct WdcExtensionSha256 {
    uint32_t state[8];
    uint64_t bit_count;
    uint8_t block[64];
    uint32_t block_size;
} WdcExtensionSha256;

void wdc_extension_sha256_init(WdcExtensionSha256 *context);
void wdc_extension_sha256_update(WdcExtensionSha256 *context,
                                 const uint8_t *bytes,
                                 uint32_t size);
void wdc_extension_sha256_finish(WdcExtensionSha256 *context, uint8_t output[32]);
void wdc_extension_sha256(const uint8_t *bytes, uint32_t size, uint8_t output[32]);
