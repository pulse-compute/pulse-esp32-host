#include "wdc_extension_sha256.h"

static const uint32_t s_round_constants[64] = {
    0x428a2f98u, 0x71374491u, 0xb5c0fbcfu, 0xe9b5dba5u, 0x3956c25bu, 0x59f111f1u,
    0x923f82a4u, 0xab1c5ed5u, 0xd807aa98u, 0x12835b01u, 0x243185beu, 0x550c7dc3u,
    0x72be5d74u, 0x80deb1feu, 0x9bdc06a7u, 0xc19bf174u, 0xe49b69c1u, 0xefbe4786u,
    0x0fc19dc6u, 0x240ca1ccu, 0x2de92c6fu, 0x4a7484aau, 0x5cb0a9dcu, 0x76f988dau,
    0x983e5152u, 0xa831c66du, 0xb00327c8u, 0xbf597fc7u, 0xc6e00bf3u, 0xd5a79147u,
    0x06ca6351u, 0x14292967u, 0x27b70a85u, 0x2e1b2138u, 0x4d2c6dfcu, 0x53380d13u,
    0x650a7354u, 0x766a0abbu, 0x81c2c92eu, 0x92722c85u, 0xa2bfe8a1u, 0xa81a664bu,
    0xc24b8b70u, 0xc76c51a3u, 0xd192e819u, 0xd6990624u, 0xf40e3585u, 0x106aa070u,
    0x19a4c116u, 0x1e376c08u, 0x2748774cu, 0x34b0bcb5u, 0x391c0cb3u, 0x4ed8aa4au,
    0x5b9cca4fu, 0x682e6ff3u, 0x748f82eeu, 0x78a5636fu, 0x84c87814u, 0x8cc70208u,
    0x90befffau, 0xa4506cebu, 0xbef9a3f7u, 0xc67178f2u,
};

static uint32_t rotate_right(uint32_t value, uint32_t count)
{
    return (value >> count) | (value << (32u - count));
}

static uint32_t read_be32(const uint8_t *bytes)
{
    return ((uint32_t)bytes[0] << 24) |
           ((uint32_t)bytes[1] << 16) |
           ((uint32_t)bytes[2] << 8) |
           (uint32_t)bytes[3];
}

static void transform(WdcExtensionSha256 *context, const uint8_t block[64])
{
    uint32_t words[64];
    uint32_t a;
    uint32_t b;
    uint32_t c;
    uint32_t d;
    uint32_t e;
    uint32_t f;
    uint32_t g;
    uint32_t h;
    uint32_t index;
    for (index = 0u; index < 16u; ++index) {
        words[index] = read_be32(block + index * 4u);
    }
    for (index = 16u; index < 64u; ++index) {
        uint32_t s0 = rotate_right(words[index - 15u], 7u) ^
                      rotate_right(words[index - 15u], 18u) ^
                      (words[index - 15u] >> 3u);
        uint32_t s1 = rotate_right(words[index - 2u], 17u) ^
                      rotate_right(words[index - 2u], 19u) ^
                      (words[index - 2u] >> 10u);
        words[index] = words[index - 16u] + s0 + words[index - 7u] + s1;
    }
    a = context->state[0];
    b = context->state[1];
    c = context->state[2];
    d = context->state[3];
    e = context->state[4];
    f = context->state[5];
    g = context->state[6];
    h = context->state[7];
    for (index = 0u; index < 64u; ++index) {
        uint32_t sum1 = rotate_right(e, 6u) ^ rotate_right(e, 11u) ^ rotate_right(e, 25u);
        uint32_t choice = (e & f) ^ ((~e) & g);
        uint32_t temporary1 = h + sum1 + choice + s_round_constants[index] + words[index];
        uint32_t sum0 = rotate_right(a, 2u) ^ rotate_right(a, 13u) ^ rotate_right(a, 22u);
        uint32_t majority = (a & b) ^ (a & c) ^ (b & c);
        uint32_t temporary2 = sum0 + majority;
        h = g;
        g = f;
        f = e;
        e = d + temporary1;
        d = c;
        c = b;
        b = a;
        a = temporary1 + temporary2;
    }
    context->state[0] += a;
    context->state[1] += b;
    context->state[2] += c;
    context->state[3] += d;
    context->state[4] += e;
    context->state[5] += f;
    context->state[6] += g;
    context->state[7] += h;
}

void wdc_extension_sha256_init(WdcExtensionSha256 *context)
{
    context->state[0] = 0x6a09e667u;
    context->state[1] = 0xbb67ae85u;
    context->state[2] = 0x3c6ef372u;
    context->state[3] = 0xa54ff53au;
    context->state[4] = 0x510e527fu;
    context->state[5] = 0x9b05688cu;
    context->state[6] = 0x1f83d9abu;
    context->state[7] = 0x5be0cd19u;
    context->bit_count = 0u;
    context->block_size = 0u;
}

void wdc_extension_sha256_update(WdcExtensionSha256 *context,
                                 const uint8_t *bytes,
                                 uint32_t size)
{
    uint32_t index;
    context->bit_count += (uint64_t)size * 8u;
    for (index = 0u; index < size; ++index) {
        context->block[context->block_size++] = bytes[index];
        if (context->block_size == sizeof(context->block)) {
            transform(context, context->block);
            context->block_size = 0u;
        }
    }
}

void wdc_extension_sha256_finish(WdcExtensionSha256 *context, uint8_t output[32])
{
    uint64_t original_bit_count = context->bit_count;
    uint8_t padding = 0x80u;
    uint8_t zero = 0u;
    uint8_t length[8];
    uint32_t index;
    wdc_extension_sha256_update(context, &padding, 1u);
    while (context->block_size != 56u) {
        wdc_extension_sha256_update(context, &zero, 1u);
    }
    for (index = 0u; index < 8u; ++index) {
        length[7u - index] = (uint8_t)(original_bit_count >> (index * 8u));
    }
    wdc_extension_sha256_update(context, length, sizeof(length));
    for (index = 0u; index < 8u; ++index) {
        output[index * 4u + 0u] = (uint8_t)(context->state[index] >> 24);
        output[index * 4u + 1u] = (uint8_t)(context->state[index] >> 16);
        output[index * 4u + 2u] = (uint8_t)(context->state[index] >> 8);
        output[index * 4u + 3u] = (uint8_t)context->state[index];
    }
}

void wdc_extension_sha256(const uint8_t *bytes, uint32_t size, uint8_t output[32])
{
    WdcExtensionSha256 context;
    wdc_extension_sha256_init(&context);
    wdc_extension_sha256_update(&context, bytes, size);
    wdc_extension_sha256_finish(&context, output);
}
