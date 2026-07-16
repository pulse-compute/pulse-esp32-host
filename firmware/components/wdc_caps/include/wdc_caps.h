#pragma once

#include <stddef.h>
#include <stdint.h>
#include <stdbool.h>

#include "wdc_abi.h"
#include "wdc_profile.h"

#ifdef __cplusplus
extern "C" {
#endif

#define WDC_CAPS_MAX_CAPABILITIES 16u
#define WDC_CAPS_STRING_ARENA_BYTES 512u
#define WDC_CAPS_AUDIT_TEXT_MAX 64u

typedef struct WdcCapability {
    uint32_t capability_id;
    WdcResourceKind kind;
    uint32_t resource_id;
    const char *resource_name;
    uint32_t ops;
    uint32_t max_payload_bytes;
    uint32_t max_rate_hz;
} WdcCapability;

typedef struct WdcCapabilitySet {
    const char *bundle_id;
    uint32_t bundle_version;
    const WdcCapability *capabilities;
    size_t capability_count;
} WdcCapabilitySet;

typedef struct WdcCapabilityParseArena {
    WdcCapability capabilities[WDC_CAPS_MAX_CAPABILITIES];
    char strings[WDC_CAPS_STRING_ARENA_BYTES];
    size_t string_len;
    char bundle_id[96];
} WdcCapabilityParseArena;

typedef struct WdcCapabilityAuditRecord {
    char bundle[WDC_CAPS_AUDIT_TEXT_MAX];
    uint32_t bundle_version;
    uint32_t opcode;
    char opcode_name[WDC_CAPS_AUDIT_TEXT_MAX];
    uint32_t resource_id;
    char resource_name[WDC_CAPS_AUDIT_TEXT_MAX];
    char capability[WDC_CAPS_AUDIT_TEXT_MAX];
    char decision[16];
    int32_t result;
    uint32_t payload_len;
    uint32_t payload_limit;
    uint32_t rate_limit_hz;
    uint64_t now_ms;
    uint64_t next_allowed_ms;
} WdcCapabilityAuditRecord;

typedef uint64_t (*WdcCapsClockFn)(void *ctx);

typedef struct WdcCapabilityAuthorizer {
    const WdcDeviceProfile *profile;
    const WdcCapabilitySet *capability_set;
    uint64_t last_allowed_ms[WDC_CAPS_MAX_CAPABILITIES];
    bool rate_seen[WDC_CAPS_MAX_CAPABILITIES];
} WdcCapabilityAuthorizer;

const char *wdc_resource_kind_name(WdcResourceKind kind);
const char *wdc_cap_op_name(uint32_t op);
WdcResourceKind wdc_resource_kind_from_string(const char *text, size_t len);
uint32_t wdc_cap_op_from_string(const char *text, size_t len);

const WdcCapabilitySet *wdc_caps_builtin_relay_limited(void);
const WdcCapabilitySet *wdc_caps_builtin_relay_full(void);

int32_t wdc_caps_parse_manifest_json(const char *json,
                                     size_t json_len,
                                     const WdcDeviceProfile *profile,
                                     WdcCapabilityParseArena *arena,
                                     WdcCapabilitySet *out_set);

int32_t wdc_caps_check_resource(const WdcCapabilitySet *set,
                                const WdcDeviceProfile *profile,
                                uint32_t opcode,
                                WdcResourceKind kind,
                                uint32_t op,
                                uint32_t resource_id,
                                WdcCapabilityAuditRecord *out_audit);

int32_t wdc_caps_check_config_key(const WdcCapabilitySet *set,
                                  uint32_t opcode,
                                  uint32_t op,
                                  const char *key,
                                  size_t key_len,
                                  WdcCapabilityAuditRecord *out_audit);

int32_t wdc_caps_authorize_host_call(void *ctx,
                                     uint32_t opcode,
                                     const uint8_t *request,
                                     uint32_t request_len,
                                     int32_t *out_decision_status);

int32_t wdc_caps_install_host_authorizer(const WdcDeviceProfile *profile,
                                         const WdcCapabilitySet *set);
void wdc_caps_clear_host_authorizer(void);
void wdc_caps_last_audit(WdcCapabilityAuditRecord *out_audit);

void wdc_caps_set_clock(WdcCapsClockFn fn, void *ctx);
void wdc_caps_clear_clock(void);
void wdc_caps_set_time_ms_for_test(uint64_t now_ms);

#ifdef __cplusplus
}
#endif
