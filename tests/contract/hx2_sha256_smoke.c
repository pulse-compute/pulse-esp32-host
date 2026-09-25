#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "wdc_extension_sha256.h"

static int check(const char *input, const char *expected)
{
    static const char hex[] = "0123456789abcdef";
    uint8_t digest[32];
    char rendered[65];
    uint32_t index;
    wdc_extension_sha256((const uint8_t *)input, (uint32_t)strlen(input), digest);
    for (index = 0u; index < 32u; ++index) {
        rendered[index * 2u] = hex[digest[index] >> 4];
        rendered[index * 2u + 1u] = hex[digest[index] & 0x0fu];
    }
    rendered[64] = '\0';
    if (strcmp(rendered, expected) != 0) {
        fprintf(stderr, "%s\n", rendered);
        return 0;
    }
    return 1;
}

int main(void)
{
    return check("", "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855") &&
                   check("abc", "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad") &&
                   check("The quick brown fox jumps over the lazy dog",
                         "d7a8fbb307d7809469ca9abcb0082e4f8d5651e46d3cdb762d02d0bf37c9e592") &&
                   check("aaaaaaaaaaaaaaaaaaaa"
                         "aaaaaaaaaaaaaaaaaaaa"
                         "aaaaaaaaaaaaaaaaaaaa"
                         "aaaaaaaaaaaaaaaaaaaa"
                         "aaaaaaaaaaaaaaaaaaaa",
                         "2816597888e4a0d3a36b82b83316ab32680eb8f00f8cd3b904d681246d285a0e")
               ? 0
               : 1;
}
