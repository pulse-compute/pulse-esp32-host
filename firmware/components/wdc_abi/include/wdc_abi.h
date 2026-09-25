#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define WDC_ABI_MAJOR 1u
#define WDC_ABI_MINOR 0u

#define WDC_IMPORT_MODULE      "wdc"
#define WDC_IMPORT_LOG         "wdc_log"
#define WDC_IMPORT_MILLIS      "wdc_millis"
#define WDC_IMPORT_RANDOM      "wdc_random"
#define WDC_IMPORT_YIELD       "wdc_yield"
#define WDC_IMPORT_HOST_CALL   "wdc_host_call"

#define WDC_EXPORT_INIT        "wdc_module_init"
#define WDC_EXPORT_ON_EVENT    "wdc_module_on_event"
#define WDC_EXPORT_HEALTH      "wdc_module_health"
#define WDC_EXPORT_SHUTDOWN    "wdc_module_shutdown"

#define WDC_BUNDLE_MAGIC       "WDCB"
#define WDC_BUNDLE_MAGIC_V0    WDC_BUNDLE_MAGIC
#define WDC_BUNDLE_HEADER_VERSION 1u

#define WDC_MAX_REQUEST_BYTES_DEFAULT  2048u
#define WDC_MAX_RESPONSE_BYTES_DEFAULT 2048u
#define WDC_MAX_EVENT_BYTES_DEFAULT    2048u

/* R3 symbols are kept for regression tests and guest SDK compatibility. */
#define WDC_R3_SHELL_VERSION "0.1.0-r3"
#define WDC_R3_BUILD_STAGE   "R3"

#define WDC_R4_SHELL_VERSION "0.1.0-r4"
#define WDC_R4_BUILD_STAGE   "R4"
#define WDC_R5_SHELL_VERSION "0.1.0-r5"
#define WDC_R5_BUILD_STAGE   "R5"
#define WDC_R6_SHELL_VERSION "0.1.0-r6"
#define WDC_R6_BUILD_STAGE   "R6"
#define WDC_R7_SHELL_VERSION "0.1.0-r7"
#define WDC_R7_BUILD_STAGE   "R7"
#define WDC_R8_SHELL_VERSION "0.1.0-r8"
#define WDC_R8_BUILD_STAGE   "R8"
#define WDC_R8_1_SHELL_VERSION "0.1.0-r8.1"
#define WDC_R8_1_BUILD_STAGE   "R8.1"
#define WDC_R8_2_SHELL_VERSION "0.1.0-r8.2"
#define WDC_R8_2_BUILD_STAGE   "R8.2"
#define WDC_R9_SHELL_VERSION   "0.1.0-r9"
#define WDC_R9_BUILD_STAGE     "R9"
#define WDC_CURRENT_SHELL_VERSION WDC_R9_SHELL_VERSION
#define WDC_CURRENT_BUILD_STAGE   WDC_R9_BUILD_STAGE

#define WDC_CBOR_KEY_STATUS        0u
#define WDC_CBOR_KEY_ABI_MAJOR     1u
#define WDC_CBOR_KEY_ABI_MINOR     2u
#define WDC_CBOR_KEY_RESOURCE_ID   3u
#define WDC_CBOR_KEY_VALUE         4u
#define WDC_CBOR_KEY_TIMER_ID      5u
#define WDC_CBOR_KEY_DELAY_MS      6u
#define WDC_CBOR_KEY_REPEAT        7u
#define WDC_CBOR_KEY_KEY           8u
#define WDC_CBOR_KEY_DATA          9u
#define WDC_CBOR_KEY_BUILD_STAGE   10u
#define WDC_CBOR_KEY_SHELL_VERSION 11u

/* R4 event envelope and audit keys. */
#define WDC_CBOR_KEY_ABI_VERSION    12u
#define WDC_CBOR_KEY_EVENT_TYPE     13u
#define WDC_CBOR_KEY_EVENT_ID       14u
#define WDC_CBOR_KEY_TIMESTAMP_MS   15u
#define WDC_CBOR_KEY_PAYLOAD        16u
#define WDC_CBOR_KEY_EVENT_PAYLOAD  WDC_CBOR_KEY_PAYLOAD
#define WDC_CBOR_KEY_CAPABILITY     17u
#define WDC_CBOR_KEY_DECISION       18u
#define WDC_CBOR_KEY_RESULT         19u
#define WDC_CBOR_KEY_RESOURCE_NAME  20u
#define WDC_CBOR_KEY_BUNDLE_NAME    21u
#define WDC_CBOR_KEY_BUNDLE_VERSION 22u
#define WDC_CBOR_KEY_QUEUE_DROPPED  23u

/* R8 network and active-bundle response keys. */
#define WDC_CBOR_KEY_CONNECTED        24u
#define WDC_CBOR_KEY_TOPIC            25u
#define WDC_CBOR_KEY_QOS              26u
#define WDC_CBOR_KEY_RETAIN           27u
#define WDC_CBOR_KEY_REQUEST_ID       28u
#define WDC_CBOR_KEY_METHOD           29u
#define WDC_CBOR_KEY_URL              30u
#define WDC_CBOR_KEY_HTTP_STATUS      31u
#define WDC_CBOR_KEY_NETWORK_STATE    32u
#define WDC_CBOR_KEY_SLOT             33u
#define WDC_CBOR_KEY_SECURITY_COUNTER 34u
#define WDC_CBOR_KEY_PENDING_COUNT    35u
#define WDC_CBOR_KEY_PAYLOAD_LEN      36u
#define WDC_CBOR_KEY_CAUSATION_ID     37u
#define WDC_CBOR_KEY_OPERATION_ID     38u
#define WDC_CBOR_KEY_CORRELATION_ID   39u
#define WDC_CBOR_KEY_DEADLINE_MS      40u
#define WDC_CBOR_KEY_ENCODING         41u
#define WDC_CBOR_KEY_COMPLETION_LATENCY_MS 42u

#define WDC_R4_EVENT_ABI_VERSION ((WDC_ABI_MAJOR << 16u) | WDC_ABI_MINOR)

#define WDC_R3_RESOURCE_RELAY_1     1u
#define WDC_R3_RESOURCE_STATUS_LED  2u
#define WDC_R3_RESOURCE_BUTTON_1    3u

#define WDC_R4_RESOURCE_RELAY_1        WDC_R3_RESOURCE_RELAY_1
#define WDC_R4_RESOURCE_STATUS_LED     WDC_R3_RESOURCE_STATUS_LED
#define WDC_R4_RESOURCE_BUTTON_1       WDC_R3_RESOURCE_BUTTON_1
#define WDC_R4_RESOURCE_TEMP_AMBIENT   10u
#define WDC_R4_RESOURCE_MQTT_TELEMETRY 20u
#define WDC_R4_RESOURCE_APP_STATE      30u

#define WDC_R8_RESOURCE_MQTT_TELEMETRY WDC_R4_RESOURCE_MQTT_TELEMETRY
#define WDC_R8_RESOURCE_MQTT_COMMANDS  21u
#define WDC_R8_RESOURCE_HTTP_API       22u
#define WDC_R8_RESOURCE_APP_STATE      WDC_R4_RESOURCE_APP_STATE

typedef enum WdcStatus {
    WDC_OK = 0,
    WDC_ERR_UNKNOWN = -1,
    WDC_ERR_UNSUPPORTED_ABI = -2,
    WDC_ERR_BAD_POINTER = -3,
    WDC_ERR_BAD_LENGTH = -4,
    WDC_ERR_BAD_ENCODING = -5,
    WDC_ERR_UNSUPPORTED_OPCODE = -6,
    WDC_ERR_CAPABILITY_DENIED = -7,
    WDC_ERR_INVALID_RESOURCE = -8,
    WDC_ERR_INVALID_STATE = -9,
    WDC_ERR_BUSY = -10,
    WDC_ERR_TIMEOUT = -11,
    WDC_ERR_NO_MEMORY = -12,
    WDC_ERR_RESPONSE_TOO_SMALL = -13,
    WDC_ERR_RATE_LIMITED = -14,
    WDC_ERR_CONTRACT_VIOLATION = -15,
    WDC_ERR_IO = -16,
    WDC_ERR_NOT_AVAILABLE = -17,
    WDC_ERR_NOT_SYNCHRONIZED = -18,
} WdcStatus;

typedef enum WdcLogLevel {
    WDC_LOG_DEBUG = 0,
    WDC_LOG_INFO = 1,
    WDC_LOG_WARN = 2,
    WDC_LOG_ERROR = 3,
} WdcLogLevel;

typedef enum WdcResourceKind {
    WDC_RESOURCE_KIND_NONE = 0,
    WDC_RESOURCE_KIND_GPIO = 1,
    WDC_RESOURCE_KIND_SENSOR = 2,
    WDC_RESOURCE_KIND_I2C = 3,
    WDC_RESOURCE_KIND_NETWORK = 4,
    WDC_RESOURCE_KIND_BLE = 5,
    WDC_RESOURCE_KIND_CONFIG = 6,
    WDC_RESOURCE_KIND_STORAGE = 7,
    WDC_RESOURCE_KIND_DIAGNOSTICS = 8,
    WDC_RESOURCE_KIND_CLOCK = 9,
} WdcResourceKind;

typedef enum WdcCapabilityOp {
    WDC_CAP_OP_NONE = 0u,
    WDC_CAP_OP_READ = 1u << 0u,
    WDC_CAP_OP_WRITE = 1u << 1u,
    WDC_CAP_OP_SUBSCRIBE = 1u << 2u,
    WDC_CAP_OP_PUBLISH = 1u << 3u,
    WDC_CAP_OP_REQUEST = 1u << 4u,
    WDC_CAP_OP_NOTIFY = 1u << 5u,
} WdcCapabilityOp;

typedef enum WdcEventType {
    WDC_EVENT_SYSTEM_BOOT = 0x0001,
    WDC_EVENT_BOOT = WDC_EVENT_SYSTEM_BOOT,
    WDC_EVENT_SHUTDOWN_REQUEST = 0x0002,
    WDC_EVENT_CONFIG_CHANGED = 0x0003,
    WDC_EVENT_MODULE_PROBATION_STARTED = 0x0004,
    WDC_EVENT_MODULE_PROBATION_ENDING = 0x0005,
    WDC_EVENT_TIMER_FIRED = 0x0101,
    WDC_EVENT_GPIO_CHANGED = 0x0201,
    WDC_EVENT_FAULT = 0x0701,
    WDC_EVENT_SAFETY_STATE_CHANGED = 0x0702,
    WDC_EVENT_PHYSICAL_ACTION = 0x0703,
    WDC_EVENT_NET_STATE_CHANGED = 0x0801,
    WDC_EVENT_NETWORK_STATUS_CHANGED = WDC_EVENT_NET_STATE_CHANGED,
    WDC_EVENT_NET_CONNECTED = WDC_EVENT_NET_STATE_CHANGED,
    WDC_EVENT_NET_DISCONNECTED = 0x0802,
    WDC_EVENT_MQTT_MESSAGE = 0x0803,
    WDC_EVENT_HTTP_RESPONSE = 0x0804,
    WDC_EVENT_HTTP_REQUEST = 0x0805,
} WdcEventType;

typedef enum WdcHostOpcode {
    WDC_OP_SYS_GET_INFO = 0x0001,
    WDC_OP_SYS_GET_METRIC = 0x0002,
    WDC_OP_TIME_GET = 0x0003,
    WDC_OP_TIMER_SET = 0x0101,
    WDC_OP_TIMER_CANCEL = 0x0102,
    WDC_OP_CONFIG_GET = 0x0201,
    WDC_OP_CONFIG_SET = 0x0202,
    WDC_OP_CONFIG_DELETE = 0x0203,
    WDC_OP_GPIO_GET = 0x0301,
    WDC_OP_GPIO_SET = 0x0302,
    WDC_OP_GPIO_SUBSCRIBE = 0x0303,
    WDC_OP_SENSOR_READ = 0x0401,
    WDC_OP_SENSOR_SUBSCRIBE = 0x0402,
    WDC_OP_I2C_TRANSFER = 0x0410,
    WDC_OP_NET_STATUS = 0x0501,
    WDC_OP_MQTT_PUBLISH = 0x0502,
    WDC_OP_MQTT_SUBSCRIBE = 0x0503,
    WDC_OP_HTTP_REQUEST = 0x0504,
    WDC_OP_HTTP_RESPOND = 0x0505,
    WDC_OP_BLE_SET_VALUE = 0x0601,
    WDC_OP_BLE_NOTIFY = 0x0602,
    WDC_OP_BLE_ADVERTISE_SET = 0x0603,
    WDC_OP_KV_GET = 0x0701,
    WDC_OP_KV_SET = 0x0702,
    WDC_OP_KV_DELETE = 0x0703,
    WDC_OP_EFFECT_INVOKE = 0x0801,
} WdcHostOpcode;

typedef enum WdcSlotState {
    WDC_SLOT_EMPTY = 0,
    WDC_SLOT_STAGED = 1,
    WDC_SLOT_VERIFIED = 2,
    WDC_SLOT_TRIAL = 3,
    WDC_SLOT_TRIAL_RUNNING = 4,
    WDC_SLOT_CONFIRMED = 5,
    WDC_SLOT_REJECTED = 6,

    /* Pre-HP3 host-internal names remain source-compatible. */
    WDC_SLOT_DOWNLOADED = WDC_SLOT_STAGED,
    WDC_SLOT_PENDING = WDC_SLOT_TRIAL,
    WDC_SLOT_RUNNING_PENDING = WDC_SLOT_TRIAL_RUNNING,
    WDC_SLOT_FAILED = WDC_SLOT_REJECTED,
} WdcSlotState;

typedef enum WdcShutdownReason {
    WDC_SHUTDOWN_NORMAL = 0,
    WDC_SHUTDOWN_ROLLBACK = 1,
    WDC_SHUTDOWN_SHELL_OTA = 2,
    WDC_SHUTDOWN_REBOOT = 3,
    WDC_SHUTDOWN_FAULT = 4,
} WdcShutdownReason;

typedef struct WdcBundleHeaderV1 {
    char     magic[4];
    uint16_t header_version;
    uint16_t flags;
    uint32_t header_len;
    uint32_t manifest_offset;
    uint32_t manifest_len;
    uint32_t payload_offset;
    uint32_t payload_len;
    uint32_t signature_offset;
    uint32_t signature_len;
    uint8_t  manifest_sha256[32];
    uint8_t  payload_sha256[32];
} WdcBundleHeaderV1;

typedef struct WdcGuestMemory {
    uint8_t *base;
    uint32_t len;
    uint32_t max_request_bytes;
    uint32_t max_response_bytes;
} WdcGuestMemory;

typedef struct WdcHostCallLimits {
    uint32_t max_request_bytes;
    uint32_t max_response_bytes;
} WdcHostCallLimits;

typedef struct WdcCborBuilder {
    uint8_t *buf;
    uint32_t cap;
    uint32_t len;
} WdcCborBuilder;

typedef struct WdcCborBytes {
    const uint8_t *ptr;
    uint32_t len;
} WdcCborBytes;

typedef struct WdcCborText {
    const char *ptr;
    uint32_t len;
} WdcCborText;

typedef int32_t (*WdcHostAuthorizeFn)(void *ctx,
                                      uint32_t opcode,
                                      const uint8_t *request,
                                      uint32_t request_len,
                                      int32_t *out_decision_status);

typedef int32_t (*WdcHostEffectCallFn)(void *ctx,
                                      const uint8_t *request,
                                      uint32_t request_len,
                                      uint8_t *response,
                                      uint32_t response_cap,
                                      uint32_t *out_response_len);

const char *wdc_status_name(int32_t status);
const char *wdc_opcode_name(uint32_t opcode);
bool wdc_opcode_known(uint32_t opcode);
bool wdc_opcode_requires_resource(uint32_t opcode);
bool wdc_opcode_supported_r3(uint32_t opcode);
bool wdc_opcode_supported_r4(uint32_t opcode);
bool wdc_opcode_supported_r8(uint32_t opcode);

void wdc_cbor_builder_init(WdcCborBuilder *builder, uint8_t *buf, uint32_t cap);
int32_t wdc_cbor_begin_map(WdcCborBuilder *builder, uint32_t pairs);
int32_t wdc_cbor_put_key_u32(WdcCborBuilder *builder, uint32_t key, uint32_t value);
int32_t wdc_cbor_put_key_u64(WdcCborBuilder *builder, uint32_t key, uint64_t value);
int32_t wdc_cbor_put_key_i32(WdcCborBuilder *builder, uint32_t key, int32_t value);
int32_t wdc_cbor_put_key_bool(WdcCborBuilder *builder, uint32_t key, bool value);
int32_t wdc_cbor_put_key_bytes(WdcCborBuilder *builder, uint32_t key, const uint8_t *value, uint32_t value_len);
int32_t wdc_cbor_put_key_text(WdcCborBuilder *builder, uint32_t key, const char *value);
uint32_t wdc_cbor_len(const WdcCborBuilder *builder);

bool wdc_cbor_is_empty_or_map(const uint8_t *buf, uint32_t len);
int32_t wdc_cbor_map_find_u32(const uint8_t *buf, uint32_t len, uint32_t key, uint32_t *out_value);
int32_t wdc_cbor_map_find_u64(const uint8_t *buf, uint32_t len, uint32_t key, uint64_t *out_value);
int32_t wdc_cbor_map_find_i32(const uint8_t *buf, uint32_t len, uint32_t key, int32_t *out_value);
int32_t wdc_cbor_map_find_bool(const uint8_t *buf, uint32_t len, uint32_t key, bool *out_value);
int32_t wdc_cbor_map_find_bytes(const uint8_t *buf, uint32_t len, uint32_t key, WdcCborBytes *out_value);
int32_t wdc_cbor_map_find_text(const uint8_t *buf, uint32_t len, uint32_t key, WdcCborText *out_value);

int32_t wdc_guest_memory_validate_range(const WdcGuestMemory *memory,
                                        uint32_t ptr,
                                        uint32_t len,
                                        bool write,
                                        uint8_t **out_native);

void wdc_host_call_set_authorizer(WdcHostAuthorizeFn fn, void *ctx);
void wdc_host_call_clear_authorizer(void);

WdcHostCallLimits wdc_host_call_default_limits(void);
WdcHostCallLimits wdc_host_call_get_limits(void);
void wdc_host_call_set_limits(const WdcHostCallLimits *limits);
void wdc_host_call_reset_limits(void);

int32_t wdc_host_call_dispatch(uint32_t opcode,
                               const uint8_t *request,
                               uint32_t request_len,
                               uint8_t *response,
                               uint32_t response_cap,
                               uint32_t *out_response_len);

int32_t wdc_host_call_from_guest_memory(const WdcGuestMemory *memory,
                                        uint32_t opcode,
                                        uint32_t req_ptr,
                                        uint32_t req_len,
                                        uint32_t rsp_ptr,
                                        uint32_t rsp_cap,
                                        uint32_t *out_response_len);

int32_t wdc_host_call_dispatch_stub(uint32_t opcode,
                                    const uint8_t *request,
                                    uint32_t request_len,
                                    uint8_t *response,
                                    uint32_t response_cap);

typedef int32_t (*WdcHostGpioWriteFn)(void *ctx, uint32_t resource_id, uint32_t value);
typedef int32_t (*WdcHostGpioReadFn)(void *ctx, uint32_t resource_id, uint32_t *out_value);
typedef int32_t (*WdcHostNetCallFn)(void *ctx,
                                    uint32_t opcode,
                                    const uint8_t *request,
                                    uint32_t request_len,
                                    uint8_t *response,
                                    uint32_t response_cap,
                                    uint32_t *out_response_len);

void wdc_host_call_set_gpio_hooks(WdcHostGpioWriteFn write_fn,
                                  WdcHostGpioReadFn read_fn,
                                  void *ctx);
void wdc_host_call_clear_gpio_hooks(void);

void wdc_host_call_set_net_hook(WdcHostNetCallFn net_fn, void *ctx);
void wdc_host_call_clear_net_hook(void);

int32_t wdc_host_call_set_effect_hook(WdcHostEffectCallFn effect_fn, void *ctx);
void wdc_host_call_clear_effect_hook(void);

void wdc_host_call_reset_for_test(void);

#ifdef __cplusplus
}
#endif
