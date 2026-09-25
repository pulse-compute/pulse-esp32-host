#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "wdc_abi.h"
#include "wdc_caps.h"
#include "wdc_profile.h"

#ifdef __cplusplus
extern "C" {
#endif

#define WDC_BUNDLE_MAGIC_V1 "WDCBNDL\0"
#define WDC_BUNDLE_MAGIC_V1_LEN 8u
#define WDC_BUNDLE_CONTAINER_VERSION_V1 1u
#define WDC_BUNDLE_HEADER_LEN_V1 120u
#define WDC_BUNDLE_RESERVED_BYTES 32u

#define WDC_BUNDLE_SHA256_BYTES 32u
#define WDC_BUNDLE_SHA256_HEX_BYTES 65u
#define WDC_BUNDLE_MAX_ID_BYTES 96u
#define WDC_BUNDLE_MAX_TEXT_BYTES 96u
#define WDC_BUNDLE_MAX_REASON_BYTES 160u

#define WDC_BUNDLE_SIG_NONE 0u
#define WDC_BUNDLE_SIG_HMAC_SHA256_DEV 1u
#define WDC_BUNDLE_SIG_ED25519_RESERVED 2u
#define WDC_BUNDLE_SIG_ED25519 WDC_BUNDLE_SIG_ED25519_RESERVED
#define WDC_BUNDLE_ED25519_SIGNATURE_BYTES 64u
#define WDC_BUNDLE_ED25519_SIG_BYTES WDC_BUNDLE_ED25519_SIGNATURE_BYTES

#define WDC_BUNDLE_DEFAULT_MAX_LINEAR_MEMORY_BYTES (256u * 1024u)
#define WDC_BUNDLE_DEFAULT_MAX_STACK_BYTES (32u * 1024u)
#define WDC_BUNDLE_DEFAULT_MAX_PAYLOAD_BYTES (2u * 1024u * 1024u)
#define WDC_BUNDLE_DEFAULT_MAX_EVENT_BYTES WDC_MAX_EVENT_BYTES_DEFAULT
#define WDC_BUNDLE_DEFAULT_MAX_REQUEST_BYTES WDC_MAX_REQUEST_BYTES_DEFAULT
#define WDC_BUNDLE_DEFAULT_MAX_RESPONSE_BYTES WDC_MAX_RESPONSE_BYTES_DEFAULT

#define WDC_BUNDLE_METADATA_MAGIC 0x5744434du /* WDCM */
#define WDC_BUNDLE_METADATA_VERSION 1u

typedef enum WdcBundleSlotId {
    WDC_BUNDLE_SLOT_NONE = 0,
    WDC_BUNDLE_SLOT_A = 1,
    WDC_BUNDLE_SLOT_B = 2,
} WdcBundleSlotId;

typedef struct WdcBundleParsedHeader {
    uint16_t container_version;
    uint16_t header_len;
    uint32_t manifest_len;
    uint32_t payload_len;
    uint16_t signature_alg;
    uint16_t signature_len;
    uint32_t manifest_offset;
    uint32_t payload_offset;
    uint32_t signature_offset;
    uint32_t total_len;
    uint8_t manifest_sha256[WDC_BUNDLE_SHA256_BYTES];
    uint8_t payload_sha256[WDC_BUNDLE_SHA256_BYTES];
} WdcBundleParsedHeader;

typedef struct WdcBundleManifestSummary {
    char bundle_id[WDC_BUNDLE_MAX_ID_BYTES];
    uint32_t bundle_version;
    uint64_t security_counter;
    uint32_t abi_major;
    uint32_t abi_min_minor;
    uint32_t abi_max_minor;
    char target_soc[WDC_BUNDLE_MAX_TEXT_BYTES];
    char target_device_class[WDC_BUNDLE_MAX_TEXT_BYTES];
    char board_rev_min[16];
    char runtime_engine[32];
    char payload_kind[32];
    bool wasm_threads;
    bool wasm_shared_memory;
    bool wasm_wasi;
    uint32_t linear_memory_max_bytes;
    uint32_t stack_bytes;
    uint32_t max_event_bytes;
    uint32_t max_request_bytes;
    uint32_t max_response_bytes;
    uint32_t payload_size_bytes;
    char payload_sha256_hex[WDC_BUNDLE_SHA256_HEX_BYTES];
    char signature_alg[32];
    char signature_key_id[64];
} WdcBundleManifestSummary;

typedef int32_t (*WdcBundleSignatureVerifyFn)(void *ctx,
                                              const WdcBundleManifestSummary *manifest,
                                              uint16_t signature_alg,
                                              const uint8_t *header,
                                              uint32_t header_len,
                                              const uint8_t *manifest_bytes,
                                              uint32_t manifest_len,
                                              const uint8_t *payload,
                                              uint32_t payload_len,
                                              const uint8_t *signature,
                                              uint32_t signature_len);

typedef struct WdcBundleVerifyPolicy {
    const WdcDeviceProfile *profile;
    uint64_t min_security_counter;
    uint32_t max_linear_memory_bytes;
    uint32_t max_stack_bytes;
    uint32_t max_payload_bytes;
    uint32_t max_event_bytes;
    uint32_t max_request_bytes;
    uint32_t max_response_bytes;
    bool production_mode;
    bool allow_unsigned_dev;
    const uint8_t *dev_hmac_key;
    uint32_t dev_hmac_key_len;
    WdcBundleSignatureVerifyFn signature_verify;
    void *signature_verify_ctx;
    const char *required_signature_alg;
    const char *trusted_signature_key_id;
} WdcBundleVerifyPolicy;

typedef struct WdcBundleVerifyResult {
    int32_t status;
    char reason[WDC_BUNDLE_MAX_REASON_BYTES];
    WdcBundleParsedHeader header;
    WdcBundleManifestSummary manifest;
    WdcCapabilityParseArena capability_arena;
    WdcCapabilitySet capability_set;
    bool header_ok;
    bool manifest_hash_ok;
    bool payload_hash_ok;
    bool manifest_payload_binding_ok;
    bool signature_ok;
    bool abi_ok;
    bool target_ok;
    bool limits_ok;
    bool capabilities_ok;
    bool exports_ok;
    bool anti_rollback_ok;
} WdcBundleVerifyResult;

typedef struct WdcBundleSlotRecord {
    WdcSlotState state;
    uint32_t bundle_version;
    uint64_t security_counter;
    uint8_t payload_sha256[WDC_BUNDLE_SHA256_BYTES];
    uint32_t artifact_format_version;
    uint32_t artifact_bytes;
    uint8_t artifact_sha256[WDC_BUNDLE_SHA256_BYTES];
} WdcBundleSlotRecord;

typedef struct WdcBundleMetadataV1 {
    uint32_t magic;
    uint16_t version;
    uint16_t reserved;
    WdcBundleSlotId active_slot;
    WdcBundleSlotId last_good_slot;
    WdcBundleSlotRecord slot_a;
    WdcBundleSlotRecord slot_b;
    uint32_t candidate_boot_count;
    uint32_t candidate_fault_count;
    int32_t last_failure_reason;
    uint32_t trial_boot_in_progress;
    uint32_t trial_boot_generation;
    uint32_t last_reset_attribution;
    WdcBundleSlotId last_rejected_slot;
    uint32_t metadata_generation;
    uint32_t metadata_crc;
} WdcBundleMetadataV1;

typedef struct WdcSha256Context {
    uint8_t data[64];
    uint32_t datalen;
    uint64_t bitlen;
    uint32_t state[8];
} WdcSha256Context;

const WdcBundleVerifyPolicy *wdc_bundle_default_dev_policy(void);
WdcBundleVerifyPolicy wdc_bundle_make_default_dev_policy(const WdcDeviceProfile *profile);
WdcBundleVerifyPolicy wdc_bundle_make_default_production_policy(const WdcDeviceProfile *profile);

const char *wdc_bundle_signature_alg_name(uint16_t alg);
const char *wdc_bundle_slot_name(WdcBundleSlotId slot);
const char *wdc_bundle_slot_state_name(WdcSlotState state);

void wdc_sha256(const uint8_t *data, uint32_t len, uint8_t out_hash[WDC_BUNDLE_SHA256_BYTES]);
void wdc_sha256_init(WdcSha256Context *ctx);
void wdc_sha256_update(WdcSha256Context *ctx, const uint8_t *data, uint32_t len);
void wdc_sha256_final(WdcSha256Context *ctx, uint8_t hash[WDC_BUNDLE_SHA256_BYTES]);
void wdc_hmac_sha256(const uint8_t *key,
                     uint32_t key_len,
                     const uint8_t *part0,
                     uint32_t part0_len,
                     const uint8_t *part1,
                     uint32_t part1_len,
                     const uint8_t *part2,
                     uint32_t part2_len,
                     uint8_t out_hash[WDC_BUNDLE_SHA256_BYTES]);
void wdc_bundle_sha256_hex(const uint8_t hash[WDC_BUNDLE_SHA256_BYTES], char out_hex[WDC_BUNDLE_SHA256_HEX_BYTES]);

int32_t wdc_bundle_parse_header(const uint8_t *bundle,
                                uint32_t bundle_len,
                                WdcBundleParsedHeader *out_header);

int32_t wdc_bundle_parse_manifest_summary(const char *json,
                                          uint32_t json_len,
                                          WdcBundleManifestSummary *out_summary);

int32_t wdc_bundle_verify(const uint8_t *bundle,
                          uint32_t bundle_len,
                          const WdcBundleVerifyPolicy *policy,
                          WdcBundleVerifyResult *out_result);

int32_t wdc_bundle_get_payload(const uint8_t *bundle,
                               uint32_t bundle_len,
                               const WdcBundleParsedHeader *header,
                               const uint8_t **out_payload,
                               uint32_t *out_payload_len);

void wdc_bundle_metadata_init(WdcBundleMetadataV1 *metadata);
uint32_t wdc_bundle_metadata_crc32(const WdcBundleMetadataV1 *metadata);
int32_t wdc_bundle_metadata_seal(WdcBundleMetadataV1 *metadata);
int32_t wdc_bundle_metadata_validate(const WdcBundleMetadataV1 *metadata);
int32_t wdc_bundle_metadata_mark_verified(WdcBundleMetadataV1 *metadata,
                                          WdcBundleSlotId slot,
                                          const WdcBundleVerifyResult *verify_result);

#ifdef __cplusplus
}
#endif
