#include "wdc_bundle.h"

#include <ctype.h>
#include <stdio.h>
#include <string.h>

static const uint8_t WDC_DEV_HMAC_KEY[] = {
    'w','d','c','-','d','e','v','-','b','u','n','d','l','e','-','s','i','g','n','i','n','g','-','k','e','y','-','r','6'
};

static WdcBundleVerifyPolicy s_default_dev_policy;

static uint16_t read_u16_le(const uint8_t *p)
{
    return (uint16_t)((uint16_t)p[0] | ((uint16_t)p[1] << 8u));
}

static uint32_t read_u32_le(const uint8_t *p)
{
    return ((uint32_t)p[0]) |
           ((uint32_t)p[1] << 8u) |
           ((uint32_t)p[2] << 16u) |
           ((uint32_t)p[3] << 24u);
}

static void put_reason(WdcBundleVerifyResult *result, const char *reason)
{
    if (result != NULL && reason != NULL) {
        (void)snprintf(result->reason, sizeof(result->reason), "%s", reason);
    }
}

static int32_t set_fail(WdcBundleVerifyResult *result, int32_t status, const char *reason)
{
    if (result != NULL) {
        result->status = status;
        put_reason(result, reason);
    }
    return status;
}

const WdcBundleVerifyPolicy *wdc_bundle_default_dev_policy(void)
{
    s_default_dev_policy = wdc_bundle_make_default_dev_policy(NULL);
    return &s_default_dev_policy;
}

WdcBundleVerifyPolicy wdc_bundle_make_default_dev_policy(const WdcDeviceProfile *profile)
{
    WdcBundleVerifyPolicy policy;
    memset(&policy, 0, sizeof(policy));
    policy.profile = profile != NULL ? profile : wdc_profile_builtin();
    policy.min_security_counter = 0u;
    policy.max_linear_memory_bytes = WDC_BUNDLE_DEFAULT_MAX_LINEAR_MEMORY_BYTES;
    policy.max_stack_bytes = WDC_BUNDLE_DEFAULT_MAX_STACK_BYTES;
    policy.max_payload_bytes = WDC_BUNDLE_DEFAULT_MAX_PAYLOAD_BYTES;
    policy.max_event_bytes = WDC_BUNDLE_DEFAULT_MAX_EVENT_BYTES;
    policy.max_request_bytes = WDC_BUNDLE_DEFAULT_MAX_REQUEST_BYTES;
    policy.max_response_bytes = WDC_BUNDLE_DEFAULT_MAX_RESPONSE_BYTES;
    policy.production_mode = false;
    policy.allow_unsigned_dev = false;
    policy.dev_hmac_key = WDC_DEV_HMAC_KEY;
    policy.dev_hmac_key_len = (uint32_t)sizeof(WDC_DEV_HMAC_KEY);
    return policy;
}

WdcBundleVerifyPolicy wdc_bundle_make_default_production_policy(const WdcDeviceProfile *profile)
{
    WdcBundleVerifyPolicy policy = wdc_bundle_make_default_dev_policy(profile);
    policy.production_mode = true;
    policy.allow_unsigned_dev = false;
    policy.dev_hmac_key = NULL;
    policy.dev_hmac_key_len = 0u;
    policy.required_signature_alg = "ed25519";
    policy.trusted_signature_key_id = "prod-test-r9";
    policy.signature_verify = NULL;
    policy.signature_verify_ctx = NULL;
    return policy;
}

const char *wdc_bundle_signature_alg_name(uint16_t alg)
{
    switch (alg) {
    case WDC_BUNDLE_SIG_NONE:
        return "none";
    case WDC_BUNDLE_SIG_HMAC_SHA256_DEV:
        return "hmac-sha256-dev";
    case WDC_BUNDLE_SIG_ED25519_RESERVED:
        return "ed25519";
    default:
        return "unknown";
    }
}

const char *wdc_bundle_slot_name(WdcBundleSlotId slot)
{
    switch (slot) {
    case WDC_BUNDLE_SLOT_A:
        return "wasm_a";
    case WDC_BUNDLE_SLOT_B:
        return "wasm_b";
    case WDC_BUNDLE_SLOT_NONE:
    default:
        return "none";
    }
}

const char *wdc_bundle_slot_state_name(WdcSlotState state)
{
    switch (state) {
    case WDC_SLOT_EMPTY:
        return "empty";
    case WDC_SLOT_DOWNLOADED:
        return "downloaded";
    case WDC_SLOT_VERIFIED:
        return "verified";
    case WDC_SLOT_PENDING:
        return "pending";
    case WDC_SLOT_RUNNING_PENDING:
        return "running_pending";
    case WDC_SLOT_CONFIRMED:
        return "confirmed";
    case WDC_SLOT_FAILED:
        return "failed";
    default:
        return "unknown";
    }
}

typedef struct WdcSha256Ctx {
    uint8_t data[64];
    uint32_t datalen;
    uint64_t bitlen;
    uint32_t state[8];
} WdcSha256Ctx;

static const uint32_t s_k[64] = {
    0x428a2f98u, 0x71374491u, 0xb5c0fbcfu, 0xe9b5dba5u, 0x3956c25bu, 0x59f111f1u, 0x923f82a4u, 0xab1c5ed5u,
    0xd807aa98u, 0x12835b01u, 0x243185beu, 0x550c7dc3u, 0x72be5d74u, 0x80deb1feu, 0x9bdc06a7u, 0xc19bf174u,
    0xe49b69c1u, 0xefbe4786u, 0x0fc19dc6u, 0x240ca1ccu, 0x2de92c6fu, 0x4a7484aau, 0x5cb0a9dcu, 0x76f988dau,
    0x983e5152u, 0xa831c66du, 0xb00327c8u, 0xbf597fc7u, 0xc6e00bf3u, 0xd5a79147u, 0x06ca6351u, 0x14292967u,
    0x27b70a85u, 0x2e1b2138u, 0x4d2c6dfcu, 0x53380d13u, 0x650a7354u, 0x766a0abbu, 0x81c2c92eu, 0x92722c85u,
    0xa2bfe8a1u, 0xa81a664bu, 0xc24b8b70u, 0xc76c51a3u, 0xd192e819u, 0xd6990624u, 0xf40e3585u, 0x106aa070u,
    0x19a4c116u, 0x1e376c08u, 0x2748774cu, 0x34b0bcb5u, 0x391c0cb3u, 0x4ed8aa4au, 0x5b9cca4fu, 0x682e6ff3u,
    0x748f82eeu, 0x78a5636fu, 0x84c87814u, 0x8cc70208u, 0x90befffau, 0xa4506cebu, 0xbef9a3f7u, 0xc67178f2u,
};

static uint32_t rotr(uint32_t a, uint32_t b)
{
    return (a >> b) | (a << (32u - b));
}

static void sha256_transform(WdcSha256Ctx *ctx, const uint8_t data[64])
{
    uint32_t m[64];
    for (uint32_t i = 0u, j = 0u; i < 16u; ++i, j += 4u) {
        m[i] = ((uint32_t)data[j] << 24u) | ((uint32_t)data[j + 1u] << 16u) | ((uint32_t)data[j + 2u] << 8u) | ((uint32_t)data[j + 3u]);
    }
    for (uint32_t i = 16u; i < 64u; ++i) {
        uint32_t s0 = rotr(m[i - 15u], 7u) ^ rotr(m[i - 15u], 18u) ^ (m[i - 15u] >> 3u);
        uint32_t s1 = rotr(m[i - 2u], 17u) ^ rotr(m[i - 2u], 19u) ^ (m[i - 2u] >> 10u);
        m[i] = m[i - 16u] + s0 + m[i - 7u] + s1;
    }

    uint32_t a = ctx->state[0];
    uint32_t b = ctx->state[1];
    uint32_t c = ctx->state[2];
    uint32_t d = ctx->state[3];
    uint32_t e = ctx->state[4];
    uint32_t f = ctx->state[5];
    uint32_t g = ctx->state[6];
    uint32_t h = ctx->state[7];

    for (uint32_t i = 0u; i < 64u; ++i) {
        uint32_t s1 = rotr(e, 6u) ^ rotr(e, 11u) ^ rotr(e, 25u);
        uint32_t ch = (e & f) ^ ((~e) & g);
        uint32_t temp1 = h + s1 + ch + s_k[i] + m[i];
        uint32_t s0 = rotr(a, 2u) ^ rotr(a, 13u) ^ rotr(a, 22u);
        uint32_t maj = (a & b) ^ (a & c) ^ (b & c);
        uint32_t temp2 = s0 + maj;
        h = g;
        g = f;
        f = e;
        e = d + temp1;
        d = c;
        c = b;
        b = a;
        a = temp1 + temp2;
    }

    ctx->state[0] += a;
    ctx->state[1] += b;
    ctx->state[2] += c;
    ctx->state[3] += d;
    ctx->state[4] += e;
    ctx->state[5] += f;
    ctx->state[6] += g;
    ctx->state[7] += h;
}

static void sha256_init(WdcSha256Ctx *ctx)
{
    memset(ctx, 0, sizeof(*ctx));
    ctx->state[0] = 0x6a09e667u;
    ctx->state[1] = 0xbb67ae85u;
    ctx->state[2] = 0x3c6ef372u;
    ctx->state[3] = 0xa54ff53au;
    ctx->state[4] = 0x510e527fu;
    ctx->state[5] = 0x9b05688cu;
    ctx->state[6] = 0x1f83d9abu;
    ctx->state[7] = 0x5be0cd19u;
}

static void sha256_update(WdcSha256Ctx *ctx, const uint8_t *data, uint32_t len)
{
    if (data == NULL || len == 0u) {
        return;
    }
    for (uint32_t i = 0u; i < len; ++i) {
        ctx->data[ctx->datalen] = data[i];
        ctx->datalen++;
        if (ctx->datalen == 64u) {
            sha256_transform(ctx, ctx->data);
            ctx->bitlen += 512u;
            ctx->datalen = 0u;
        }
    }
}

static void sha256_final(WdcSha256Ctx *ctx, uint8_t hash[32])
{
    uint32_t i = ctx->datalen;

    if (ctx->datalen < 56u) {
        ctx->data[i++] = 0x80u;
        while (i < 56u) {
            ctx->data[i++] = 0x00u;
        }
    } else {
        ctx->data[i++] = 0x80u;
        while (i < 64u) {
            ctx->data[i++] = 0x00u;
        }
        sha256_transform(ctx, ctx->data);
        memset(ctx->data, 0, 56u);
    }

    ctx->bitlen += (uint64_t)ctx->datalen * 8u;
    ctx->data[63] = (uint8_t)(ctx->bitlen);
    ctx->data[62] = (uint8_t)(ctx->bitlen >> 8u);
    ctx->data[61] = (uint8_t)(ctx->bitlen >> 16u);
    ctx->data[60] = (uint8_t)(ctx->bitlen >> 24u);
    ctx->data[59] = (uint8_t)(ctx->bitlen >> 32u);
    ctx->data[58] = (uint8_t)(ctx->bitlen >> 40u);
    ctx->data[57] = (uint8_t)(ctx->bitlen >> 48u);
    ctx->data[56] = (uint8_t)(ctx->bitlen >> 56u);
    sha256_transform(ctx, ctx->data);

    for (i = 0u; i < 4u; ++i) {
        hash[i] = (uint8_t)((ctx->state[0] >> (24u - i * 8u)) & 0xffu);
        hash[i + 4u] = (uint8_t)((ctx->state[1] >> (24u - i * 8u)) & 0xffu);
        hash[i + 8u] = (uint8_t)((ctx->state[2] >> (24u - i * 8u)) & 0xffu);
        hash[i + 12u] = (uint8_t)((ctx->state[3] >> (24u - i * 8u)) & 0xffu);
        hash[i + 16u] = (uint8_t)((ctx->state[4] >> (24u - i * 8u)) & 0xffu);
        hash[i + 20u] = (uint8_t)((ctx->state[5] >> (24u - i * 8u)) & 0xffu);
        hash[i + 24u] = (uint8_t)((ctx->state[6] >> (24u - i * 8u)) & 0xffu);
        hash[i + 28u] = (uint8_t)((ctx->state[7] >> (24u - i * 8u)) & 0xffu);
    }
}

void wdc_sha256(const uint8_t *data, uint32_t len, uint8_t out_hash[WDC_BUNDLE_SHA256_BYTES])
{
    WdcSha256Ctx ctx;
    sha256_init(&ctx);
    sha256_update(&ctx, data, len);
    sha256_final(&ctx, out_hash);
}

void wdc_hmac_sha256(const uint8_t *key,
                     uint32_t key_len,
                     const uint8_t *part0,
                     uint32_t part0_len,
                     const uint8_t *part1,
                     uint32_t part1_len,
                     const uint8_t *part2,
                     uint32_t part2_len,
                     uint8_t out_hash[WDC_BUNDLE_SHA256_BYTES])
{
    uint8_t key_block[64];
    uint8_t key_hash[32];
    memset(key_block, 0, sizeof(key_block));
    if (key != NULL && key_len > 64u) {
        wdc_sha256(key, key_len, key_hash);
        memcpy(key_block, key_hash, sizeof(key_hash));
    } else if (key != NULL && key_len > 0u) {
        memcpy(key_block, key, key_len);
    }

    uint8_t ipad[64];
    uint8_t opad[64];
    for (uint32_t i = 0u; i < 64u; ++i) {
        ipad[i] = (uint8_t)(key_block[i] ^ 0x36u);
        opad[i] = (uint8_t)(key_block[i] ^ 0x5cu);
    }

    uint8_t inner[32];
    WdcSha256Ctx ctx;
    sha256_init(&ctx);
    sha256_update(&ctx, ipad, sizeof(ipad));
    sha256_update(&ctx, part0, part0_len);
    sha256_update(&ctx, part1, part1_len);
    sha256_update(&ctx, part2, part2_len);
    sha256_final(&ctx, inner);

    sha256_init(&ctx);
    sha256_update(&ctx, opad, sizeof(opad));
    sha256_update(&ctx, inner, sizeof(inner));
    sha256_final(&ctx, out_hash);
}

void wdc_bundle_sha256_hex(const uint8_t hash[WDC_BUNDLE_SHA256_BYTES], char out_hex[WDC_BUNDLE_SHA256_HEX_BYTES])
{
    static const char hex[] = "0123456789abcdef";
    if (out_hex == NULL) {
        return;
    }
    if (hash == NULL) {
        out_hex[0] = '\0';
        return;
    }
    for (uint32_t i = 0u; i < WDC_BUNDLE_SHA256_BYTES; ++i) {
        out_hex[i * 2u] = hex[(hash[i] >> 4u) & 0x0fu];
        out_hex[i * 2u + 1u] = hex[hash[i] & 0x0fu];
    }
    out_hex[64] = '\0';
}

int32_t wdc_bundle_parse_header(const uint8_t *bundle,
                                uint32_t bundle_len,
                                WdcBundleParsedHeader *out_header)
{
    if (bundle == NULL || out_header == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    memset(out_header, 0, sizeof(*out_header));
    if (bundle_len < WDC_BUNDLE_HEADER_LEN_V1) {
        return WDC_ERR_BAD_LENGTH;
    }
    if (memcmp(bundle, WDC_BUNDLE_MAGIC_V1, WDC_BUNDLE_MAGIC_V1_LEN) != 0) {
        return WDC_ERR_BAD_ENCODING;
    }
    out_header->container_version = read_u16_le(bundle + 8u);
    out_header->header_len = read_u16_le(bundle + 10u);
    out_header->manifest_len = read_u32_le(bundle + 12u);
    out_header->payload_len = read_u32_le(bundle + 16u);
    memcpy(out_header->manifest_sha256, bundle + 20u, WDC_BUNDLE_SHA256_BYTES);
    memcpy(out_header->payload_sha256, bundle + 52u, WDC_BUNDLE_SHA256_BYTES);
    out_header->signature_alg = read_u16_le(bundle + 84u);
    out_header->signature_len = read_u16_le(bundle + 86u);
    if (out_header->container_version != WDC_BUNDLE_CONTAINER_VERSION_V1 ||
        out_header->header_len != WDC_BUNDLE_HEADER_LEN_V1) {
        return WDC_ERR_UNSUPPORTED_ABI;
    }
    if (out_header->manifest_len == 0u || out_header->payload_len == 0u) {
        return WDC_ERR_BAD_LENGTH;
    }
    if (out_header->signature_alg == WDC_BUNDLE_SIG_HMAC_SHA256_DEV && out_header->signature_len != WDC_BUNDLE_SHA256_BYTES) {
        return WDC_ERR_BAD_LENGTH;
    }
    if (out_header->signature_alg == WDC_BUNDLE_SIG_ED25519 && out_header->signature_len != WDC_BUNDLE_ED25519_SIGNATURE_BYTES) {
        return WDC_ERR_BAD_LENGTH;
    }
    if (out_header->signature_alg == WDC_BUNDLE_SIG_NONE && out_header->signature_len != 0u) {
        return WDC_ERR_BAD_LENGTH;
    }
    out_header->manifest_offset = out_header->header_len;
    out_header->payload_offset = out_header->manifest_offset + out_header->manifest_len;
    out_header->signature_offset = out_header->payload_offset + out_header->payload_len;
    out_header->total_len = out_header->signature_offset + out_header->signature_len;
    if (out_header->payload_offset < out_header->manifest_offset ||
        out_header->signature_offset < out_header->payload_offset ||
        out_header->total_len < out_header->signature_offset) {
        return WDC_ERR_BAD_LENGTH;
    }
    if (bundle_len != WDC_BUNDLE_HEADER_LEN_V1 && out_header->total_len > bundle_len) {
        return WDC_ERR_BAD_LENGTH;
    }
    return WDC_OK;
}

static const char *skip_ws(const char *p, const char *end)
{
    while (p < end && isspace((unsigned char)*p)) {
        p++;
    }
    return p;
}

static const char *find_string_token(const char *json, const char *end, const char *token)
{
    size_t token_len = strlen(token);
    const char *p = json;
    while (p + token_len <= end) {
        if (*p == '"' && (size_t)(end - p) >= token_len + 2u &&
            p[1 + token_len] == '"' && memcmp(p + 1, token, token_len) == 0) {
            return p;
        }
        p++;
    }
    return NULL;
}

static const char *find_key_local(const char *json, const char *end, const char *key)
{
    const char *p = json;
    while (p < end) {
        const char *token = find_string_token(p, end, key);
        if (token == NULL) {
            return NULL;
        }
        const char *after = skip_ws(token + strlen(key) + 2u, end);
        if (after < end && *after == ':') {
            return skip_ws(after + 1, end);
        }
        p = token + 1;
    }
    return NULL;
}

static const char *find_matching_local(const char *p, const char *end, char open_ch, char close_ch)
{
    if (p == NULL || p >= end || *p != open_ch) {
        return NULL;
    }
    int depth = 0;
    bool in_string = false;
    bool escaped = false;
    for (const char *cur = p; cur < end; ++cur) {
        char c = *cur;
        if (in_string) {
            if (escaped) {
                escaped = false;
            } else if (c == '\\') {
                escaped = true;
            } else if (c == '"') {
                in_string = false;
            }
            continue;
        }
        if (c == '"') {
            in_string = true;
        } else if (c == open_ch) {
            depth++;
        } else if (c == close_ch) {
            depth--;
            if (depth == 0) {
                return cur;
            }
        }
    }
    return NULL;
}

static int32_t extract_string_value(const char *p, const char *end, char *out, size_t out_cap)
{
    if (p == NULL || out == NULL || out_cap == 0u) {
        return WDC_ERR_BAD_POINTER;
    }
    p = skip_ws(p, end);
    if (p >= end || *p != '"') {
        return WDC_ERR_BAD_ENCODING;
    }
    p++;
    size_t n = 0u;
    while (p < end && *p != '"') {
        if (*p == '\\') {
            return WDC_ERR_BAD_ENCODING;
        }
        if (n + 1u >= out_cap) {
            return WDC_ERR_NO_MEMORY;
        }
        out[n++] = *p++;
    }
    if (p >= end || *p != '"') {
        return WDC_ERR_BAD_ENCODING;
    }
    out[n] = '\0';
    return WDC_OK;
}

static int32_t extract_uint64_value(const char *p, const char *end, uint64_t *out)
{
    if (p == NULL || out == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    p = skip_ws(p, end);
    if (p >= end || !isdigit((unsigned char)*p)) {
        return WDC_ERR_BAD_ENCODING;
    }
    uint64_t value = 0u;
    while (p < end && isdigit((unsigned char)*p)) {
        value = value * 10u + (uint64_t)(*p - '0');
        p++;
    }
    *out = value;
    return WDC_OK;
}

static int32_t extract_u32_key(const char *json, const char *end, const char *key, uint32_t *out)
{
    uint64_t value = 0u;
    const char *p = find_key_local(json, end, key);
    if (p == NULL || extract_uint64_value(p, end, &value) != WDC_OK || value > 0xffffffffull) {
        return WDC_ERR_BAD_ENCODING;
    }
    *out = (uint32_t)value;
    return WDC_OK;
}

static int32_t extract_u64_key(const char *json, const char *end, const char *key, uint64_t *out)
{
    const char *p = find_key_local(json, end, key);
    return p == NULL ? WDC_ERR_BAD_ENCODING : extract_uint64_value(p, end, out);
}

static int32_t extract_string_key(const char *json, const char *end, const char *key, char *out, size_t out_cap)
{
    const char *p = find_key_local(json, end, key);
    return p == NULL ? WDC_ERR_BAD_ENCODING : extract_string_value(p, end, out, out_cap);
}

static bool array_contains_string(const char *array, const char *end, const char *needle)
{
    if (array == NULL || array >= end || *array != '[' || needle == NULL) {
        return false;
    }
    const char *array_end = find_matching_local(array, end, '[', ']');
    if (array_end == NULL) {
        return false;
    }
    const char *p = array + 1;
    char tmp[WDC_BUNDLE_MAX_TEXT_BYTES];
    while (p < array_end) {
        p = skip_ws(p, array_end);
        if (p >= array_end) {
            break;
        }
        if (*p == ',') {
            p++;
            continue;
        }
        if (*p == '"') {
            if (extract_string_value(p, array_end, tmp, sizeof(tmp)) == WDC_OK && strcmp(tmp, needle) == 0) {
                return true;
            }
            p++;
            while (p < array_end && *p != '"') {
                p++;
            }
            if (p < array_end) {
                p++;
            }
            continue;
        }
        p++;
    }
    return false;
}

static int32_t extract_bool_key(const char *json, const char *end, const char *key, bool *out)
{
    const char *p = find_key_local(json, end, key);
    if (p == NULL || out == NULL) {
        return WDC_ERR_BAD_ENCODING;
    }
    if ((size_t)(end - p) >= 4u && memcmp(p, "true", 4u) == 0) {
        *out = true;
        return WDC_OK;
    }
    if ((size_t)(end - p) >= 5u && memcmp(p, "false", 5u) == 0) {
        *out = false;
        return WDC_OK;
    }
    return WDC_ERR_BAD_ENCODING;
}

static int32_t extract_object_string(const char *json, const char *end, const char *object_key, const char *key, char *out, size_t out_cap)
{
    const char *obj = find_key_local(json, end, object_key);
    if (obj == NULL || *obj != '{') {
        return WDC_ERR_BAD_ENCODING;
    }
    const char *obj_end = find_matching_local(obj, end, '{', '}');
    if (obj_end == NULL) {
        return WDC_ERR_BAD_ENCODING;
    }
    return extract_string_key(obj, obj_end, key, out, out_cap);
}

static int32_t extract_object_u32(const char *json, const char *end, const char *object_key, const char *key, uint32_t *out)
{
    const char *obj = find_key_local(json, end, object_key);
    if (obj == NULL || *obj != '{') {
        return WDC_ERR_BAD_ENCODING;
    }
    const char *obj_end = find_matching_local(obj, end, '{', '}');
    if (obj_end == NULL) {
        return WDC_ERR_BAD_ENCODING;
    }
    return extract_u32_key(obj, obj_end, key, out);
}

static int32_t extract_first_array_string_under_object(const char *json,
                                                        const char *end,
                                                        const char *object_key,
                                                        const char *array_key,
                                                        char *out,
                                                        size_t out_cap)
{
    const char *obj = find_key_local(json, end, object_key);
    if (obj == NULL || *obj != '{') {
        return WDC_ERR_BAD_ENCODING;
    }
    const char *obj_end = find_matching_local(obj, end, '{', '}');
    if (obj_end == NULL) {
        return WDC_ERR_BAD_ENCODING;
    }
    const char *array = find_key_local(obj, obj_end, array_key);
    if (array == NULL || *array != '[') {
        return WDC_ERR_BAD_ENCODING;
    }
    const char *array_end = find_matching_local(array, obj_end, '[', ']');
    if (array_end == NULL) {
        return WDC_ERR_BAD_ENCODING;
    }
    const char *p = skip_ws(array + 1, array_end);
    return extract_string_value(p, array_end, out, out_cap);
}

static int32_t extract_u32_from_nested_object(const char *json,
                                               const char *end,
                                               const char *outer_key,
                                               const char *inner_key,
                                               uint32_t *out)
{
    const char *outer = find_key_local(json, end, outer_key);
    if (outer == NULL || *outer != '{') {
        return WDC_ERR_BAD_ENCODING;
    }
    const char *outer_end = find_matching_local(outer, end, '{', '}');
    if (outer_end == NULL) {
        return WDC_ERR_BAD_ENCODING;
    }
    return extract_u32_key(outer, outer_end, inner_key, out);
}

int32_t wdc_bundle_parse_manifest_summary(const char *json,
                                          uint32_t json_len,
                                          WdcBundleManifestSummary *out_summary)
{
    if (json == NULL || out_summary == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    memset(out_summary, 0, sizeof(*out_summary));
    const char *end = json + json_len;
    uint32_t format = 0u;
    if (extract_u32_key(json, end, "manifest_format", &format) != WDC_OK || format != 1u) {
        return WDC_ERR_BAD_ENCODING;
    }
    if (extract_string_key(json, end, "bundle_id", out_summary->bundle_id, sizeof(out_summary->bundle_id)) != WDC_OK ||
        extract_u32_key(json, end, "bundle_version", &out_summary->bundle_version) != WDC_OK ||
        extract_u64_key(json, end, "security_counter", &out_summary->security_counter) != WDC_OK) {
        return WDC_ERR_BAD_ENCODING;
    }

    const char *abi = find_key_local(json, end, "abi");
    if (abi == NULL || *abi != '{') {
        return WDC_ERR_BAD_ENCODING;
    }
    const char *abi_end = find_matching_local(abi, end, '{', '}');
    if (abi_end == NULL ||
        extract_u32_key(abi, abi_end, "major", &out_summary->abi_major) != WDC_OK ||
        extract_u32_key(abi, abi_end, "min_minor", &out_summary->abi_min_minor) != WDC_OK ||
        extract_u32_key(abi, abi_end, "max_minor", &out_summary->abi_max_minor) != WDC_OK) {
        return WDC_ERR_BAD_ENCODING;
    }

    if (extract_first_array_string_under_object(json, end, "target", "soc", out_summary->target_soc, sizeof(out_summary->target_soc)) != WDC_OK ||
        extract_first_array_string_under_object(json, end, "target", "device_class", out_summary->target_device_class, sizeof(out_summary->target_device_class)) != WDC_OK ||
        extract_object_string(json, end, "target", "board_rev_min", out_summary->board_rev_min, sizeof(out_summary->board_rev_min)) != WDC_OK) {
        return WDC_ERR_BAD_ENCODING;
    }

    if (extract_object_string(json, end, "runtime", "engine", out_summary->runtime_engine, sizeof(out_summary->runtime_engine)) != WDC_OK ||
        extract_object_string(json, end, "runtime", "payload_kind", out_summary->payload_kind, sizeof(out_summary->payload_kind)) != WDC_OK) {
        return WDC_ERR_BAD_ENCODING;
    }
    const char *features = find_key_local(json, end, "wasm_features");
    if (features == NULL || *features != '{') {
        return WDC_ERR_BAD_ENCODING;
    }
    const char *features_end = find_matching_local(features, end, '{', '}');
    if (features_end == NULL ||
        extract_bool_key(features, features_end, "threads", &out_summary->wasm_threads) != WDC_OK ||
        extract_bool_key(features, features_end, "shared_memory", &out_summary->wasm_shared_memory) != WDC_OK ||
        extract_bool_key(features, features_end, "wasi", &out_summary->wasm_wasi) != WDC_OK) {
        return WDC_ERR_BAD_ENCODING;
    }

    if (extract_u32_from_nested_object(json, end, "limits", "linear_memory_max_bytes", &out_summary->linear_memory_max_bytes) != WDC_OK ||
        extract_u32_from_nested_object(json, end, "limits", "stack_bytes", &out_summary->stack_bytes) != WDC_OK ||
        extract_u32_from_nested_object(json, end, "limits", "max_event_bytes", &out_summary->max_event_bytes) != WDC_OK ||
        extract_u32_from_nested_object(json, end, "limits", "max_request_bytes", &out_summary->max_request_bytes) != WDC_OK ||
        extract_u32_from_nested_object(json, end, "limits", "max_response_bytes", &out_summary->max_response_bytes) != WDC_OK) {
        return WDC_ERR_BAD_ENCODING;
    }

    if (extract_object_string(json, end, "payload", "sha256", out_summary->payload_sha256_hex, sizeof(out_summary->payload_sha256_hex)) != WDC_OK ||
        extract_object_u32(json, end, "payload", "size_bytes", &out_summary->payload_size_bytes) != WDC_OK ||
        extract_object_string(json, end, "signature", "alg", out_summary->signature_alg, sizeof(out_summary->signature_alg)) != WDC_OK ||
        extract_object_string(json, end, "signature", "key_id", out_summary->signature_key_id, sizeof(out_summary->signature_key_id)) != WDC_OK) {
        return WDC_ERR_BAD_ENCODING;
    }
    return WDC_OK;
}

static bool bytes_equal_constant_time(const uint8_t *a, const uint8_t *b, uint32_t len)
{
    uint8_t diff = 0u;
    for (uint32_t i = 0u; i < len; ++i) {
        diff = (uint8_t)(diff | (uint8_t)(a[i] ^ b[i]));
    }
    return diff == 0u;
}

static bool optional_text_matches(const char *required, const char *actual)
{
    return required == NULL || required[0] == '\0' || (actual != NULL && strcmp(required, actual) == 0);
}

static bool manifest_signature_alg_matches_header(const WdcBundleVerifyResult *result)
{
    return result != NULL && strcmp(result->manifest.signature_alg, wdc_bundle_signature_alg_name(result->header.signature_alg)) == 0;
}

static bool wasm_read_u32_leb(const uint8_t *payload, uint32_t payload_len, uint32_t *offset, uint32_t *out_value)
{
    if (payload == NULL || offset == NULL || out_value == NULL) {
        return false;
    }
    uint32_t result = 0u;
    uint32_t shift = 0u;
    for (uint32_t i = 0u; i < 5u; ++i) {
        if (*offset >= payload_len) {
            return false;
        }
        uint8_t byte = payload[(*offset)++];
        result |= ((uint32_t)(byte & 0x7fu)) << shift;
        if ((byte & 0x80u) == 0u) {
            *out_value = result;
            return true;
        }
        shift += 7u;
    }
    return false;
}

static bool wasm_skip_bytes(uint32_t payload_len, uint32_t *offset, uint32_t count)
{
    if (offset == NULL || count > payload_len - *offset) {
        return false;
    }
    *offset += count;
    return true;
}

static bool wasm_export_section_has_function(const uint8_t *section, uint32_t section_len, const char *name)
{
    if (section == NULL || name == NULL) {
        return false;
    }
    uint32_t offset = 0u;
    uint32_t export_count = 0u;
    if (!wasm_read_u32_leb(section, section_len, &offset, &export_count)) {
        return false;
    }
    const uint32_t wanted_len = (uint32_t)strlen(name);
    for (uint32_t i = 0u; i < export_count; ++i) {
        uint32_t name_len = 0u;
        if (!wasm_read_u32_leb(section, section_len, &offset, &name_len) || name_len > section_len - offset) {
            return false;
        }
        const uint8_t *export_name = section + offset;
        offset += name_len;
        if (offset >= section_len) {
            return false;
        }
        uint8_t kind = section[offset++];
        uint32_t index = 0u;
        if (!wasm_read_u32_leb(section, section_len, &offset, &index)) {
            return false;
        }
        (void)index;
        if (kind == 0u && name_len == wanted_len && memcmp(export_name, name, wanted_len) == 0) {
            return true;
        }
    }
    return false;
}

static bool wasm_payload_has_required_exports(const uint8_t *payload, uint32_t payload_len)
{
    if (payload == NULL || payload_len < 8u ||
        payload[0] != 0x00u || payload[1] != 0x61u || payload[2] != 0x73u || payload[3] != 0x6du ||
        payload[4] != 0x01u || payload[5] != 0x00u || payload[6] != 0x00u || payload[7] != 0x00u) {
        return false;
    }

    const char *required[] = {
        WDC_EXPORT_INIT,
        WDC_EXPORT_ON_EVENT,
        WDC_EXPORT_HEALTH,
        WDC_EXPORT_SHUTDOWN,
    };
    bool found[4] = { false, false, false, false };

    uint32_t offset = 8u;
    uint8_t previous_non_custom_section = 0u;
    while (offset < payload_len) {
        uint8_t section_id = payload[offset++];
        uint32_t section_len = 0u;
        if (!wasm_read_u32_leb(payload, payload_len, &offset, &section_len) || section_len > payload_len - offset) {
            return false;
        }
        const uint8_t *section = payload + offset;
        if (section_id != 0u) {
            if (section_id <= previous_non_custom_section) {
                return false;
            }
            previous_non_custom_section = section_id;
        }
        if (section_id == 7u) {
            for (size_t r = 0u; r < sizeof(required) / sizeof(required[0]); ++r) {
                if (!found[r] && wasm_export_section_has_function(section, section_len, required[r])) {
                    found[r] = true;
                }
            }
        }
        if (!wasm_skip_bytes(payload_len, &offset, section_len)) {
            return false;
        }
    }

    for (size_t r = 0u; r < sizeof(found) / sizeof(found[0]); ++r) {
        if (!found[r]) {
            return false;
        }
    }
    return true;
}

static bool target_array_contains(const char *json, const char *end, const char *array_key, const char *needle)
{
    const char *target = find_key_local(json, end, "target");
    if (target == NULL || *target != '{') {
        return false;
    }
    const char *target_end = find_matching_local(target, end, '{', '}');
    if (target_end == NULL) {
        return false;
    }
    const char *array = find_key_local(target, target_end, array_key);
    return array_contains_string(array, target_end, needle);
}

static bool board_rev_compatible(const char *actual, const char *minimum)
{
    if (actual == NULL || minimum == NULL || minimum[0] == '\0') {
        return false;
    }
    return strcmp(actual, minimum) >= 0;
}

int32_t wdc_bundle_verify(const uint8_t *bundle,
                          uint32_t bundle_len,
                          const WdcBundleVerifyPolicy *policy,
                          WdcBundleVerifyResult *out_result)
{
    if (bundle == NULL || out_result == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    memset(out_result, 0, sizeof(*out_result));
    out_result->status = WDC_ERR_UNKNOWN;

    WdcBundleVerifyPolicy local_policy = policy != NULL ? *policy : wdc_bundle_make_default_dev_policy(NULL);
    if (local_policy.profile == NULL) {
        local_policy.profile = wdc_profile_builtin();
    }
    if (local_policy.max_linear_memory_bytes == 0u) {
        local_policy.max_linear_memory_bytes = WDC_BUNDLE_DEFAULT_MAX_LINEAR_MEMORY_BYTES;
    }
    if (local_policy.max_stack_bytes == 0u) {
        local_policy.max_stack_bytes = WDC_BUNDLE_DEFAULT_MAX_STACK_BYTES;
    }
    if (local_policy.max_payload_bytes == 0u) {
        local_policy.max_payload_bytes = WDC_BUNDLE_DEFAULT_MAX_PAYLOAD_BYTES;
    }
    if (local_policy.max_event_bytes == 0u) {
        local_policy.max_event_bytes = WDC_BUNDLE_DEFAULT_MAX_EVENT_BYTES;
    }
    if (local_policy.max_request_bytes == 0u) {
        local_policy.max_request_bytes = WDC_BUNDLE_DEFAULT_MAX_REQUEST_BYTES;
    }
    if (local_policy.max_response_bytes == 0u) {
        local_policy.max_response_bytes = WDC_BUNDLE_DEFAULT_MAX_RESPONSE_BYTES;
    }

    int32_t status = wdc_bundle_parse_header(bundle, bundle_len, &out_result->header);
    if (status != WDC_OK) {
        return set_fail(out_result, status, "invalid bundle header");
    }
    out_result->header_ok = true;
    if (out_result->header.total_len != bundle_len) {
        return set_fail(out_result, WDC_ERR_BAD_LENGTH, "bundle has trailing unsigned bytes");
    }

    if (out_result->header.payload_len > local_policy.max_payload_bytes) {
        return set_fail(out_result, WDC_ERR_BAD_LENGTH, "payload exceeds policy maximum");
    }

    const uint8_t *manifest = bundle + out_result->header.manifest_offset;
    const uint8_t *payload = bundle + out_result->header.payload_offset;
    const uint8_t *signature = bundle + out_result->header.signature_offset;

    uint8_t hash[WDC_BUNDLE_SHA256_BYTES];
    wdc_sha256(manifest, out_result->header.manifest_len, hash);
    out_result->manifest_hash_ok = bytes_equal_constant_time(hash, out_result->header.manifest_sha256, WDC_BUNDLE_SHA256_BYTES);
    if (!out_result->manifest_hash_ok) {
        return set_fail(out_result, WDC_ERR_CONTRACT_VIOLATION, "manifest hash mismatch");
    }

    wdc_sha256(payload, out_result->header.payload_len, hash);
    out_result->payload_hash_ok = bytes_equal_constant_time(hash, out_result->header.payload_sha256, WDC_BUNDLE_SHA256_BYTES);
    if (!out_result->payload_hash_ok) {
        return set_fail(out_result, WDC_ERR_CONTRACT_VIOLATION, "payload hash mismatch");
    }

    status = wdc_bundle_parse_manifest_summary((const char *)manifest, out_result->header.manifest_len, &out_result->manifest);
    if (status != WDC_OK) {
        return set_fail(out_result, status, "manifest summary parse failed");
    }

    char payload_hex[WDC_BUNDLE_SHA256_HEX_BYTES];
    wdc_bundle_sha256_hex(out_result->header.payload_sha256, payload_hex);
    out_result->manifest_payload_binding_ok =
        strcmp(payload_hex, out_result->manifest.payload_sha256_hex) == 0 &&
        out_result->manifest.payload_size_bytes == out_result->header.payload_len;
    if (!out_result->manifest_payload_binding_ok) {
        return set_fail(out_result, WDC_ERR_CONTRACT_VIOLATION, "manifest payload binding mismatch");
    }

    if (!manifest_signature_alg_matches_header(out_result)) {
        return set_fail(out_result, WDC_ERR_CONTRACT_VIOLATION, "manifest signature algorithm does not match container header");
    }
    if (!optional_text_matches(local_policy.required_signature_alg, out_result->manifest.signature_alg)) {
        return set_fail(out_result, WDC_ERR_CONTRACT_VIOLATION, "manifest signature algorithm not allowed by policy");
    }
    if (!optional_text_matches(local_policy.trusted_signature_key_id, out_result->manifest.signature_key_id)) {
        return set_fail(out_result, WDC_ERR_CONTRACT_VIOLATION, "manifest signature key id not trusted by policy");
    }

    if (out_result->header.signature_alg == WDC_BUNDLE_SIG_NONE) {
        out_result->signature_ok = (!local_policy.production_mode && local_policy.allow_unsigned_dev);
    } else if (out_result->header.signature_alg == WDC_BUNDLE_SIG_HMAC_SHA256_DEV) {
        if (local_policy.production_mode || local_policy.dev_hmac_key == NULL || local_policy.dev_hmac_key_len == 0u) {
            out_result->signature_ok = false;
        } else {
            uint8_t expected[WDC_BUNDLE_SHA256_BYTES];
            wdc_hmac_sha256(local_policy.dev_hmac_key,
                            local_policy.dev_hmac_key_len,
                            bundle,
                            out_result->header.header_len,
                            manifest,
                            out_result->header.manifest_len,
                            payload,
                            out_result->header.payload_len,
                            expected);
            out_result->signature_ok = bytes_equal_constant_time(expected, signature, WDC_BUNDLE_SHA256_BYTES);
        }
    } else if (out_result->header.signature_alg == WDC_BUNDLE_SIG_ED25519) {
        out_result->signature_ok = false;
        if (local_policy.signature_verify != NULL && strcmp(out_result->manifest.signature_alg, "ed25519") == 0) {
            int32_t verify_status = local_policy.signature_verify(local_policy.signature_verify_ctx,
                                                                  &out_result->manifest,
                                                                  out_result->header.signature_alg,
                                                                  bundle,
                                                                  out_result->header.header_len,
                                                                  manifest,
                                                                  out_result->header.manifest_len,
                                                                  payload,
                                                                  out_result->header.payload_len,
                                                                  signature,
                                                                  out_result->header.signature_len);
            out_result->signature_ok = verify_status == WDC_OK;
        }
    } else {
        out_result->signature_ok = false;
    }
    if (!out_result->signature_ok) {
        return set_fail(out_result, WDC_ERR_CONTRACT_VIOLATION, "signature verification failed");
    }

    const uint32_t shell_abi_minor = WDC_ABI_MINOR;
    out_result->abi_ok = out_result->manifest.abi_major == WDC_ABI_MAJOR &&
                         out_result->manifest.abi_min_minor <= shell_abi_minor &&
                         out_result->manifest.abi_max_minor >= shell_abi_minor;
    if (!out_result->abi_ok) {
        return set_fail(out_result, WDC_ERR_UNSUPPORTED_ABI, "unsupported ABI range");
    }

    const char *json = (const char *)manifest;
    const char *json_end = json + out_result->header.manifest_len;
    out_result->target_ok = target_array_contains(json, json_end, "soc", local_policy.profile->hardware) &&
                            target_array_contains(json, json_end, "device_class", local_policy.profile->device_class) &&
                            board_rev_compatible(local_policy.profile->board_rev, out_result->manifest.board_rev_min);
    if (!out_result->target_ok) {
        return set_fail(out_result, WDC_ERR_INVALID_RESOURCE, "target hardware/device profile mismatch");
    }

    out_result->limits_ok = out_result->manifest.linear_memory_max_bytes <= local_policy.max_linear_memory_bytes &&
                            out_result->manifest.stack_bytes <= local_policy.max_stack_bytes &&
                            out_result->manifest.max_event_bytes <= local_policy.max_event_bytes &&
                            out_result->manifest.max_request_bytes <= local_policy.max_request_bytes &&
                            out_result->manifest.max_response_bytes <= local_policy.max_response_bytes &&
                            !out_result->manifest.wasm_threads &&
                            !out_result->manifest.wasm_shared_memory &&
                            !out_result->manifest.wasm_wasi &&
                            strcmp(out_result->manifest.runtime_engine, "wamr") == 0 &&
                            strcmp(out_result->manifest.payload_kind, "wasm") == 0;
    if (!out_result->limits_ok) {
        return set_fail(out_result, WDC_ERR_BAD_LENGTH, "manifest limits/features exceed policy");
    }

    out_result->anti_rollback_ok = out_result->manifest.security_counter >= local_policy.min_security_counter;
    if (!out_result->anti_rollback_ok) {
        return set_fail(out_result, WDC_ERR_CONTRACT_VIOLATION, "security counter violates anti-rollback policy");
    }

    status = wdc_caps_parse_manifest_json(json,
                                          out_result->header.manifest_len,
                                          local_policy.profile,
                                          &out_result->capability_arena,
                                          &out_result->capability_set);
    out_result->capabilities_ok = status == WDC_OK;
    if (!out_result->capabilities_ok) {
        return set_fail(out_result, status, "capability manifest incompatible with device profile");
    }

    out_result->exports_ok = wasm_payload_has_required_exports(payload, out_result->header.payload_len);
    if (!out_result->exports_ok) {
        return set_fail(out_result, WDC_ERR_NOT_AVAILABLE, "required WASM exports missing");
    }

    out_result->status = WDC_OK;
    put_reason(out_result, "bundle verified");
    return WDC_OK;
}

int32_t wdc_bundle_get_payload(const uint8_t *bundle,
                               uint32_t bundle_len,
                               const WdcBundleParsedHeader *header,
                               const uint8_t **out_payload,
                               uint32_t *out_payload_len)
{
    if (bundle == NULL || header == NULL || out_payload == NULL || out_payload_len == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    if (header->payload_offset + header->payload_len < header->payload_offset ||
        header->payload_offset + header->payload_len > bundle_len) {
        return WDC_ERR_BAD_LENGTH;
    }
    *out_payload = bundle + header->payload_offset;
    *out_payload_len = header->payload_len;
    return WDC_OK;
}

static uint32_t crc32_update(uint32_t crc, const uint8_t *data, uint32_t len)
{
    crc = ~crc;
    for (uint32_t i = 0u; i < len; ++i) {
        crc ^= data[i];
        for (uint32_t j = 0u; j < 8u; ++j) {
            uint32_t mask = 0u - (crc & 1u);
            crc = (crc >> 1u) ^ (0xedb88320u & mask);
        }
    }
    return ~crc;
}

void wdc_bundle_metadata_init(WdcBundleMetadataV1 *metadata)
{
    if (metadata == NULL) {
        return;
    }
    memset(metadata, 0, sizeof(*metadata));
    metadata->magic = WDC_BUNDLE_METADATA_MAGIC;
    metadata->version = WDC_BUNDLE_METADATA_VERSION;
    metadata->active_slot = WDC_BUNDLE_SLOT_NONE;
    metadata->last_good_slot = WDC_BUNDLE_SLOT_NONE;
    metadata->slot_a.state = WDC_SLOT_EMPTY;
    metadata->slot_b.state = WDC_SLOT_EMPTY;
    (void)wdc_bundle_metadata_seal(metadata);
}

uint32_t wdc_bundle_metadata_crc32(const WdcBundleMetadataV1 *metadata)
{
    if (metadata == NULL) {
        return 0u;
    }
    WdcBundleMetadataV1 copy = *metadata;
    copy.metadata_crc = 0u;
    return crc32_update(0u, (const uint8_t *)&copy, (uint32_t)sizeof(copy));
}

int32_t wdc_bundle_metadata_seal(WdcBundleMetadataV1 *metadata)
{
    if (metadata == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    metadata->metadata_crc = 0u;
    metadata->metadata_crc = wdc_bundle_metadata_crc32(metadata);
    return WDC_OK;
}

int32_t wdc_bundle_metadata_validate(const WdcBundleMetadataV1 *metadata)
{
    if (metadata == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    if (metadata->magic != WDC_BUNDLE_METADATA_MAGIC || metadata->version != WDC_BUNDLE_METADATA_VERSION) {
        return WDC_ERR_BAD_ENCODING;
    }
    return metadata->metadata_crc == wdc_bundle_metadata_crc32(metadata) ? WDC_OK : WDC_ERR_CONTRACT_VIOLATION;
}

int32_t wdc_bundle_metadata_mark_verified(WdcBundleMetadataV1 *metadata,
                                          WdcBundleSlotId slot,
                                          const WdcBundleVerifyResult *verify_result)
{
    if (metadata == NULL || verify_result == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    if (verify_result->status != WDC_OK || !verify_result->payload_hash_ok) {
        return WDC_ERR_INVALID_STATE;
    }
    WdcBundleSlotRecord *record = NULL;
    if (slot == WDC_BUNDLE_SLOT_A) {
        record = &metadata->slot_a;
    } else if (slot == WDC_BUNDLE_SLOT_B) {
        record = &metadata->slot_b;
    } else {
        return WDC_ERR_INVALID_RESOURCE;
    }
    record->state = WDC_SLOT_VERIFIED;
    record->bundle_version = verify_result->manifest.bundle_version;
    record->security_counter = verify_result->manifest.security_counter;
    memcpy(record->payload_sha256, verify_result->header.payload_sha256, WDC_BUNDLE_SHA256_BYTES);
    metadata->metadata_generation++;
    return wdc_bundle_metadata_seal(metadata);
}
