#pragma once

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Experimental HX0-HX7 ABI. This is not yet a permanent public Pulse ABI. */
#define PULSE_EXTENSION_METADATA_MAGIC "PULSEXT1"
#define PULSE_EXTENSION_METADATA_SIZE_V1 192u
#define PULSE_EXTENSION_DESCRIPTOR_MAGIC_V1 0x31545845u
#define PULSE_EXTENSION_DESCRIPTOR_SIZE_V1 160u
#define PULSE_EXTENSION_ABI_MAJOR_V1 1u
#define PULSE_EXTENSION_ABI_MINOR_V1 0u
#define PULSE_HOST_ABI_MAJOR_V1 1u
#define PULSE_HOST_ABI_MINOR_V1 0u
#define PULSE_EXTENSION_CATALOG_CAPACITY_V1 4u

#define PULSE_EXT_OK 0
#define PULSE_EXT_ERR_ARGUMENT (-1)
#define PULSE_EXT_ERR_STATE (-2)
#define PULSE_EXT_ERR_UNSUPPORTED (-3)
#define PULSE_EXT_ERR_BUSY (-4)
#define PULSE_EXT_ERR_TIMEOUT (-5)
#define PULSE_EXT_ERR_BOUNDS (-6)
#define PULSE_EXT_ERR_DUPLICATE (-7)
#define PULSE_EXT_ERR_STALE (-8)
#define PULSE_EXT_ERR_FAULT (-9)

#define PULSE_EXT_HEALTH_INITIALIZED 1u
#define PULSE_EXT_HEALTH_RUNNING 2u
#define PULSE_EXT_HEALTH_QUIESCING 3u
#define PULSE_EXT_HEALTH_QUIESCED 4u
#define PULSE_EXT_HEALTH_FAULTED 5u

#if defined(__GNUC__)
#define PULSE_EXTENSION_EXPORT __attribute__((visibility("default")))
#define PULSE_EXTENSION_METADATA_V1 \
    __attribute__((section(".pulse_ext_meta"), used, aligned(4), visibility("default")))
#else
#define PULSE_EXTENSION_EXPORT
#define PULSE_EXTENSION_METADATA_V1
#endif

typedef struct pulse_u64_parts_v1 {
    uint32_t lo;
    uint32_t hi;
} pulse_u64_parts_v1;

typedef struct pulse_byte_span_v1 {
    const uint8_t *ptr;
    uint32_t len;
} pulse_byte_span_v1;

typedef struct pulse_extension_metadata_v1 {
    uint8_t magic[8];
    uint16_t format_major;
    uint16_t format_minor;
    uint32_t record_size;
    uint16_t architecture_id;
    uint16_t soc_id;
    uint32_t flags;
    uint16_t required_host_abi_major;
    uint16_t required_host_abi_min_minor;
    uint16_t extension_abi_major;
    uint16_t extension_abi_minor;
    uint8_t extension_id[16];
    uint32_t descriptor_size;
    uint32_t descriptor_alignment;
    uint16_t event_count;
    uint16_t operation_count;
    uint32_t reserved0;
    uint32_t event_ids[PULSE_EXTENSION_CATALOG_CAPACITY_V1];
    uint32_t operation_ids[PULSE_EXTENSION_CATALOG_CAPACITY_V1];
    uint32_t task_count;
    uint32_t task_stack_bytes;
    uint32_t static_memory_bytes;
    uint32_t queue_depth;
    uint32_t queue_item_bytes;
    uint32_t max_event_payload_bytes;
    uint32_t max_effect_request_bytes;
    uint32_t max_effect_completion_bytes;
    uint8_t artifact_sha256[32];
    uint8_t reserved1[32];
} pulse_extension_metadata_v1;

typedef struct pulse_extension_init_args_v1 {
    uint32_t struct_size;
    uint32_t flags;
    pulse_u64_parts_v1 activation_epoch;
    pulse_u64_parts_v1 boot_monotonic_ms;
    uint32_t host_event_queue_capacity;
    uint32_t host_max_event_payload_bytes;
    uint32_t host_max_effect_completion_bytes;
    uint32_t host_max_inflight_effects;
    uint8_t extension_id[16];
    uint32_t reserved[2];
} pulse_extension_init_args_v1;

typedef struct pulse_extension_invoke_v1 {
    uint32_t struct_size;
    uint32_t operation_id;
    pulse_u64_parts_v1 correlation_id;
    pulse_u64_parts_v1 deadline_ms;
    const uint8_t *payload_ptr;
    uint32_t payload_len;
    uint32_t flags;
    uint32_t reserved[3];
} pulse_extension_invoke_v1;

typedef struct pulse_extension_health_v1 {
    uint32_t struct_size;
    uint32_t state;
    int32_t fault_status;
    uint32_t pending_count;
    uint32_t queue_high_water;
    uint32_t task_stack_high_water_bytes;
    pulse_u64_parts_v1 last_progress_ms;
    uint32_t flags;
    uint32_t reserved[3];
} pulse_extension_health_v1;

typedef struct pulse_extension_quiesce_v1 {
    uint32_t struct_size;
    uint32_t reason;
    pulse_u64_parts_v1 deadline_ms;
    uint32_t flags;
    uint32_t reserved[3];
} pulse_extension_quiesce_v1;

typedef struct pulse_extension_event_v1 {
    uint32_t struct_size;
    uint32_t event_id;
    pulse_u64_parts_v1 causation_id;
    const uint8_t *payload_ptr;
    uint32_t payload_len;
    uint32_t flags;
    uint32_t reserved[3];
} pulse_extension_event_v1;

typedef struct pulse_extension_completion_v1 {
    uint32_t struct_size;
    int32_t status;
    pulse_u64_parts_v1 correlation_id;
    const uint8_t *payload_ptr;
    uint32_t payload_len;
    uint32_t flags;
    uint32_t reserved[3];
} pulse_extension_completion_v1;

typedef struct pulse_extension_log_v1 {
    uint32_t struct_size;
    uint32_t level;
    uint32_t diagnostic_code;
    const uint8_t *message_ptr;
    uint32_t message_len;
    uint32_t flags;
} pulse_extension_log_v1;

typedef struct pulse_extension_fault_v1 {
    uint32_t struct_size;
    int32_t status;
    uint32_t fault_code;
    pulse_u64_parts_v1 correlation_id;
    uint32_t flags;
    uint32_t reserved[2];
} pulse_extension_fault_v1;

typedef int32_t (*pulse_extension_init_fn_v1)(const pulse_extension_init_args_v1 *args);
typedef int32_t (*pulse_extension_start_fn_v1)(void);
typedef int32_t (*pulse_extension_invoke_fn_v1)(const pulse_extension_invoke_v1 *request);
typedef int32_t (*pulse_extension_health_fn_v1)(pulse_extension_health_v1 *out_health);
typedef int32_t (*pulse_extension_quiesce_fn_v1)(const pulse_extension_quiesce_v1 *request);
typedef int32_t (*pulse_extension_deinit_fn_v1)(void);

typedef struct pulse_extension_descriptor_v1 {
    uint32_t magic;
    uint32_t struct_size;
    uint16_t abi_major;
    uint16_t abi_minor;
    uint32_t flags;
    uint8_t extension_id[16];
    uint8_t metadata_sha256[32];
    uint16_t event_count;
    uint16_t operation_count;
    uint32_t reserved0;
    uint32_t event_ids[PULSE_EXTENSION_CATALOG_CAPACITY_V1];
    uint32_t operation_ids[PULSE_EXTENSION_CATALOG_CAPACITY_V1];
    pulse_extension_init_fn_v1 init_fn;
    pulse_extension_start_fn_v1 start_fn;
    pulse_extension_invoke_fn_v1 invoke_fn;
    pulse_extension_health_fn_v1 health_fn;
    pulse_extension_quiesce_fn_v1 quiesce_fn;
    pulse_extension_deinit_fn_v1 deinit_fn;
    uint8_t reserved1[32];
} pulse_extension_descriptor_v1;

PULSE_EXTENSION_EXPORT
const pulse_extension_descriptor_v1 *pulse_extension_entry_v1(void);

int32_t pulse_host_emit_event_v1(const pulse_extension_event_v1 *event);
int32_t pulse_host_complete_effect_v1(const pulse_extension_completion_v1 *completion);
int32_t pulse_host_monotonic_ms_v1(pulse_u64_parts_v1 *out_time);
int32_t pulse_host_log_v1(const pulse_extension_log_v1 *record);
int32_t pulse_host_report_health_v1(const pulse_extension_health_v1 *health);
int32_t pulse_host_report_fault_v1(const pulse_extension_fault_v1 *fault);

#ifdef __cplusplus
}
#define PULSE_EXT_STATIC_ASSERT(condition, message) static_assert(condition, message)
#define PULSE_EXT_ALIGNOF(type) alignof(type)
#else
#define PULSE_EXT_STATIC_ASSERT(condition, message) _Static_assert(condition, message)
#define PULSE_EXT_ALIGNOF(type) _Alignof(type)
#endif

PULSE_EXT_STATIC_ASSERT(sizeof(pulse_u64_parts_v1) == 8u, "pulse_u64_parts_v1 size");
PULSE_EXT_STATIC_ASSERT(sizeof(pulse_extension_metadata_v1) == 192u, "metadata size");
PULSE_EXT_STATIC_ASSERT(PULSE_EXT_ALIGNOF(pulse_extension_metadata_v1) == 4u, "metadata alignment");
PULSE_EXT_STATIC_ASSERT(offsetof(pulse_extension_metadata_v1, artifact_sha256) == 128u,
                        "metadata artifact digest offset");

/*
 * Target builds always enforce the exact 32-bit ABI. HX3's lifecycle smoke
 * harness may define PULSE_EXTENSION_HOST_TEST to exercise control flow on a
 * 64-bit development host; it never serializes or admits a host descriptor.
 */
#ifndef PULSE_EXTENSION_HOST_TEST
PULSE_EXT_STATIC_ASSERT(sizeof(void *) == 4u, "Pulse extension ABI requires 32-bit pointers");
PULSE_EXT_STATIC_ASSERT(sizeof(pulse_extension_init_fn_v1) == 4u,
                        "Pulse extension ABI requires 32-bit function pointers");
PULSE_EXT_STATIC_ASSERT(sizeof(pulse_byte_span_v1) == 8u, "pulse_byte_span_v1 size");
PULSE_EXT_STATIC_ASSERT(sizeof(pulse_extension_init_args_v1) == 64u, "init args size");
PULSE_EXT_STATIC_ASSERT(sizeof(pulse_extension_invoke_v1) == 48u, "invoke size");
PULSE_EXT_STATIC_ASSERT(sizeof(pulse_extension_health_v1) == 48u, "health size");
PULSE_EXT_STATIC_ASSERT(sizeof(pulse_extension_quiesce_v1) == 32u, "quiesce size");
PULSE_EXT_STATIC_ASSERT(sizeof(pulse_extension_event_v1) == 40u, "event size");
PULSE_EXT_STATIC_ASSERT(sizeof(pulse_extension_completion_v1) == 40u, "completion size");
PULSE_EXT_STATIC_ASSERT(sizeof(pulse_extension_log_v1) == 24u, "log size");
PULSE_EXT_STATIC_ASSERT(sizeof(pulse_extension_fault_v1) == 32u, "fault size");
PULSE_EXT_STATIC_ASSERT(sizeof(pulse_extension_descriptor_v1) == 160u, "descriptor size");
PULSE_EXT_STATIC_ASSERT(PULSE_EXT_ALIGNOF(pulse_extension_descriptor_v1) == 4u, "descriptor alignment");
PULSE_EXT_STATIC_ASSERT(offsetof(pulse_extension_descriptor_v1, init_fn) == 104u,
                        "descriptor init offset");
PULSE_EXT_STATIC_ASSERT(offsetof(pulse_extension_descriptor_v1, start_fn) == 108u,
                        "descriptor start offset");
PULSE_EXT_STATIC_ASSERT(offsetof(pulse_extension_descriptor_v1, invoke_fn) == 112u,
                        "descriptor invoke offset");
PULSE_EXT_STATIC_ASSERT(offsetof(pulse_extension_descriptor_v1, health_fn) == 116u,
                        "descriptor health offset");
PULSE_EXT_STATIC_ASSERT(offsetof(pulse_extension_descriptor_v1, quiesce_fn) == 120u,
                        "descriptor quiesce offset");
PULSE_EXT_STATIC_ASSERT(offsetof(pulse_extension_descriptor_v1, deinit_fn) == 124u,
                        "descriptor deinit offset");
#endif

#undef PULSE_EXT_STATIC_ASSERT
#undef PULSE_EXT_ALIGNOF
