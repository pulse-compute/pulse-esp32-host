#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "wdc_abi.h"
#include "wdc_bundle.h"
#include "wdc_profile.h"

static uint8_t *read_file(const char *path, uint32_t *out_len) {
    FILE *f = fopen(path, "rb");
    assert(f != NULL);
    assert(fseek(f, 0, SEEK_END) == 0);
    long n = ftell(f);
    assert(n > 0 && n < 1000000);
    assert(fseek(f, 0, SEEK_SET) == 0);
    uint8_t *buf = (uint8_t *)malloc((size_t)n);
    assert(buf != NULL);
    assert(fread(buf, 1, (size_t)n, f) == (size_t)n);
    assert(fclose(f) == 0);
    *out_len = (uint32_t)n;
    return buf;
}

static int32_t r9_test_vector_verifier(void *user,
                                          const WdcBundleManifestSummary *summary,
                                          uint16_t alg,
                                          const uint8_t *header,
                                          uint32_t header_len,
                                          const uint8_t *manifest,
                                          uint32_t manifest_len,
                                          const uint8_t *payload,
                                          uint32_t payload_len,
                                          const uint8_t *signature,
                                          uint32_t signature_len) {
    (void)user;
    static const uint8_t context[] = "WDC-R9-ED25519-TEST-VECTOR";
    static const uint8_t context2[] = "WDC-R9-ED25519-TEST-VECTOR/2/";
    const char *key_id = summary != NULL ? summary->signature_key_id : NULL;
    if (alg != WDC_BUNDLE_SIG_ED25519 || key_id == NULL || strncmp(key_id, "prod-", 5u) != 0u || signature_len != WDC_BUNDLE_ED25519_SIG_BYTES) {
        return WDC_ERR_CONTRACT_VIOLATION;
    }
    uint32_t key_len = (uint32_t)strlen(key_id);
    uint32_t len1 = (uint32_t)(sizeof(context) - 1u) + key_len + header_len + manifest_len + payload_len;
    uint8_t *buf1 = (uint8_t *)malloc(len1);
    assert(buf1 != NULL);
    uint32_t off = 0u;
    memcpy(buf1 + off, context, sizeof(context) - 1u); off += (uint32_t)(sizeof(context) - 1u);
    memcpy(buf1 + off, key_id, key_len); off += key_len;
    memcpy(buf1 + off, header, header_len); off += header_len;
    memcpy(buf1 + off, manifest, manifest_len); off += manifest_len;
    memcpy(buf1 + off, payload, payload_len); off += payload_len;
    assert(off == len1);
    uint8_t first[WDC_BUNDLE_SHA256_BYTES];
    wdc_sha256(buf1, len1, first);
    free(buf1);

    uint8_t buf2[(sizeof(context2) - 1u) + WDC_BUNDLE_SHA256_BYTES];
    memcpy(buf2, context2, sizeof(context2) - 1u);
    memcpy(buf2 + (sizeof(context2) - 1u), first, WDC_BUNDLE_SHA256_BYTES);
    uint8_t second[WDC_BUNDLE_SHA256_BYTES];
    wdc_sha256(buf2, (uint32_t)sizeof(buf2), second);
    bool ok = memcmp(signature, first, WDC_BUNDLE_SHA256_BYTES) == 0 &&
              memcmp(signature + WDC_BUNDLE_SHA256_BYTES, second, WDC_BUNDLE_SHA256_BYTES) == 0;
    return ok ? WDC_OK : WDC_ERR_CONTRACT_VIOLATION;
}


int main(int argc, char **argv) {
    assert(argc == 3);
    uint32_t dev_len = 0u;
    uint32_t prod_len = 0u;
    uint8_t *dev_bundle = read_file(argv[1], &dev_len);
    uint8_t *prod_bundle = read_file(argv[2], &prod_len);
    WdcBundleVerifyResult result;

    WdcBundleVerifyPolicy dev_policy = wdc_bundle_make_default_dev_policy(wdc_profile_builtin());
    assert(dev_policy.production_mode == false);
    assert(wdc_bundle_verify(dev_bundle, dev_len, &dev_policy, &result) == WDC_OK);
    assert(result.signature_ok);
    assert(strcmp(result.manifest.signature_alg, "hmac-sha256-dev") == 0);
    assert(wdc_bundle_verify(prod_bundle, prod_len, &dev_policy, &result) == WDC_ERR_CONTRACT_VIOLATION);
    assert(!result.signature_ok);

    WdcBundleVerifyPolicy prod_policy = wdc_bundle_make_default_production_policy(wdc_profile_builtin());
    assert(prod_policy.production_mode == true);
    assert(prod_policy.dev_hmac_key == NULL);
    assert(prod_policy.allow_unsigned_dev == false);
    assert(prod_policy.signature_verify == NULL);
    assert(strcmp(prod_policy.trusted_signature_key_id, "prod-test-r9") == 0);
    assert(wdc_bundle_verify(dev_bundle, dev_len, &prod_policy, &result) == WDC_ERR_CONTRACT_VIOLATION);
    assert(!result.signature_ok);
    assert(wdc_bundle_verify(prod_bundle, prod_len, &prod_policy, &result) == WDC_ERR_CONTRACT_VIOLATION);
    assert(!result.signature_ok);

    prod_policy.signature_verify = r9_test_vector_verifier;
    assert(wdc_bundle_verify(prod_bundle, prod_len, &prod_policy, &result) == WDC_OK);
    assert(result.signature_ok);
    assert(result.header.signature_alg == WDC_BUNDLE_SIG_ED25519);
    assert(strcmp(result.manifest.signature_alg, "ed25519") == 0);
    assert(strncmp(result.manifest.signature_key_id, "prod-", 5u) == 0);

    prod_policy.trusted_signature_key_id = "real-prod-key";
    assert(wdc_bundle_verify(prod_bundle, prod_len, &prod_policy, &result) == WDC_ERR_CONTRACT_VIOLATION);
    assert(!result.signature_ok);

    free(dev_bundle);
    free(prod_bundle);
    return 0;
}
