#include "pulse_extension.h"

#ifndef PULSE_EXTENSION_TARGET_ARCHITECTURE_ID
#error "PULSE_EXTENSION_TARGET_ARCHITECTURE_ID must be supplied by the exact target build"
#endif

#ifndef PULSE_EXTENSION_TARGET_SOC_ID
#error "PULSE_EXTENSION_TARGET_SOC_ID must be supplied by the exact target build"
#endif

#ifndef PULSE_EXTENSION_METADATA_SHA256_BYTES
#error "PULSE_EXTENSION_METADATA_SHA256_BYTES must be supplied by the deterministic builder"
#endif

#define PULSE_SYNTHETIC_EVENT_TICK 0x5449434bu
#define PULSE_SYNTHETIC_OPERATION_ECHO 0x4543484fu
#define PULSE_SYNTHETIC_TASK_STACK_BYTES 4096u
#define PULSE_SYNTHETIC_STATIC_MEMORY_BYTES 3072u
#define PULSE_SYNTHETIC_QUEUE_DEPTH 4u
#define PULSE_SYNTHETIC_QUEUE_ITEM_BYTES 64u
#define PULSE_SYNTHETIC_TASK_CONTROL_BYTES 2048u
#define PULSE_SYNTHETIC_QUEUE_CONTROL_BYTES 256u
#define PULSE_SYNTHETIC_QUEUE_TYPE_BASE 0u
#define PULSE_SYNTHETIC_QUEUE_SEND_BACK 0
#define PULSE_SYNTHETIC_TASK_PRIORITY 5u
#define PULSE_SYNTHETIC_WORK_TICK 1u
#define PULSE_SYNTHETIC_WORK_ECHO 2u
#define PULSE_SYNTHETIC_EFFECT_PAYLOAD_MAX 32u

typedef int32_t pulse_freertos_base_type;
typedef uint32_t pulse_freertos_ubase_type;
typedef uint32_t pulse_freertos_tick_type;
typedef void *pulse_freertos_queue_handle;
typedef void *pulse_freertos_task_handle;
typedef void (*pulse_freertos_tls_delete_callback)(int, void *);

extern pulse_freertos_queue_handle xQueueGenericCreateStatic(
    pulse_freertos_ubase_type queue_length,
    pulse_freertos_ubase_type item_size,
    uint8_t *queue_storage,
    void *queue_control,
    uint8_t queue_type);
extern pulse_freertos_base_type xQueueGenericSend(
    pulse_freertos_queue_handle queue,
    const void *item,
    pulse_freertos_tick_type ticks_to_wait,
    pulse_freertos_base_type copy_position);
extern pulse_freertos_base_type xQueueReceive(
    pulse_freertos_queue_handle queue,
    void *item,
    pulse_freertos_tick_type ticks_to_wait);
extern void vQueueDelete(pulse_freertos_queue_handle queue);
extern pulse_freertos_task_handle xTaskCreateStatic(
    void (*task_code)(void *),
    const char *name,
    uint32_t stack_depth_bytes,
    void *parameter,
    pulse_freertos_ubase_type priority,
    uint8_t *stack_buffer,
    void *task_control);
extern void vTaskSetThreadLocalStoragePointerAndDelCallback(
    pulse_freertos_task_handle task,
    pulse_freertos_base_type index,
    void *value,
    pulse_freertos_tls_delete_callback callback);
extern void vTaskDelay(pulse_freertos_tick_type ticks);
extern void vTaskDelete(pulse_freertos_task_handle task);
extern pulse_freertos_ubase_type uxTaskGetStackHighWaterMark(
    pulse_freertos_task_handle task);

typedef struct synthetic_queue_item {
    uint32_t kind;
    pulse_u64_parts_v1 correlation_id;
    pulse_u64_parts_v1 deadline_ms;
    uint32_t payload_len;
    uint8_t payload[PULSE_SYNTHETIC_EFFECT_PAYLOAD_MAX];
    uint8_t reserved[8];
} synthetic_queue_item;

_Static_assert(sizeof(synthetic_queue_item) == PULSE_SYNTHETIC_QUEUE_ITEM_BYTES,
               "synthetic queue item size");

static const uint8_t s_extension_id[16] = {
    'P', 'U', 'L', 'S', 'E', '-', 'H', 'X', '3', '-', 'L', 'O', 'O', 'P', '0', '1',
};

PULSE_EXTENSION_METADATA_V1
const pulse_extension_metadata_v1 pulse_extension_metadata = {
    .magic = {'P', 'U', 'L', 'S', 'E', 'X', 'T', '1'},
    .format_major = 1u,
    .format_minor = 0u,
    .record_size = PULSE_EXTENSION_METADATA_SIZE_V1,
    .architecture_id = PULSE_EXTENSION_TARGET_ARCHITECTURE_ID,
    .soc_id = PULSE_EXTENSION_TARGET_SOC_ID,
    .flags = 0u,
    .required_host_abi_major = PULSE_HOST_ABI_MAJOR_V1,
    .required_host_abi_min_minor = PULSE_HOST_ABI_MINOR_V1,
    .extension_abi_major = PULSE_EXTENSION_ABI_MAJOR_V1,
    .extension_abi_minor = PULSE_EXTENSION_ABI_MINOR_V1,
    .extension_id = {
        'P', 'U', 'L', 'S', 'E', '-', 'H', 'X', '3', '-', 'L', 'O', 'O', 'P', '0', '1',
    },
    .descriptor_size = PULSE_EXTENSION_DESCRIPTOR_SIZE_V1,
    .descriptor_alignment = 4u,
    .event_count = 1u,
    .operation_count = 1u,
    .reserved0 = 0u,
    .event_ids = {PULSE_SYNTHETIC_EVENT_TICK, 0u, 0u, 0u},
    .operation_ids = {PULSE_SYNTHETIC_OPERATION_ECHO, 0u, 0u, 0u},
    .task_count = 1u,
    .task_stack_bytes = PULSE_SYNTHETIC_TASK_STACK_BYTES,
    .static_memory_bytes = PULSE_SYNTHETIC_STATIC_MEMORY_BYTES,
    .queue_depth = PULSE_SYNTHETIC_QUEUE_DEPTH,
    .queue_item_bytes = PULSE_SYNTHETIC_QUEUE_ITEM_BYTES,
    .max_event_payload_bytes = 64u,
    .max_effect_request_bytes = PULSE_SYNTHETIC_EFFECT_PAYLOAD_MAX,
    .max_effect_completion_bytes = PULSE_SYNTHETIC_EFFECT_PAYLOAD_MAX,
    .artifact_sha256 = {0u},
    .reserved1 = {0u},
};

static uint8_t s_task_stack[PULSE_SYNTHETIC_TASK_STACK_BYTES]
    __attribute__((aligned(16)));
static uint8_t s_task_control[PULSE_SYNTHETIC_TASK_CONTROL_BYTES]
    __attribute__((aligned(16)));
static uint8_t s_queue_storage[PULSE_SYNTHETIC_QUEUE_DEPTH *
                               PULSE_SYNTHETIC_QUEUE_ITEM_BYTES]
    __attribute__((aligned(16)));
static uint8_t s_queue_control[PULSE_SYNTHETIC_QUEUE_CONTROL_BYTES]
    __attribute__((aligned(16)));

static volatile uint32_t s_state;
static volatile int32_t s_fault_status;
static volatile uint32_t s_pending_count;
static volatile uint32_t s_queue_high_water;
static volatile uint32_t s_task_stack_high_water_bytes;
static volatile uint32_t s_accepting_work;
static volatile uint32_t s_quiesce_requested;
static volatile uint32_t s_task_exited;
static volatile uint32_t s_start_entered;
static pulse_freertos_queue_handle s_queue;
static pulse_freertos_task_handle s_task;
static pulse_u64_parts_v1 s_last_progress_ms;
static pulse_u64_parts_v1 s_service_time;
static pulse_u64_parts_v1 s_activation_epoch;
static pulse_extension_health_v1 s_service_health;

static void zero_bytes(void *value, uint32_t size)
{
    uint8_t *bytes = (uint8_t *)value;
    uint32_t index;
    for (index = 0u; index < size; ++index) {
        bytes[index] = 0u;
    }
}

static int words_zero(const uint32_t *words, uint32_t count)
{
    uint32_t index;
    for (index = 0u; index < count; ++index) {
        if (words[index] != 0u) {
            return 0;
        }
    }
    return 1;
}

static uint64_t time_value(pulse_u64_parts_v1 value)
{
    return ((uint64_t)value.hi << 32u) | value.lo;
}

static void update_progress(void)
{
    if (pulse_host_monotonic_ms_v1(&s_service_time) == PULSE_EXT_OK) {
        s_last_progress_ms = s_service_time;
    } else {
        s_fault_status = PULSE_EXT_ERR_FAULT;
        s_state = PULSE_EXT_HEALTH_FAULTED;
        s_quiesce_requested = 1u;
    }
}

static void write_health(pulse_extension_health_v1 *health)
{
    zero_bytes(health, sizeof(*health));
    health->struct_size = sizeof(*health);
    health->state = s_state == 0u ? PULSE_EXT_HEALTH_INITIALIZED : s_state;
    health->fault_status = s_fault_status;
    health->pending_count = s_pending_count;
    health->queue_high_water = s_queue_high_water;
    health->task_stack_high_water_bytes = s_task_stack_high_water_bytes;
    health->last_progress_ms = s_last_progress_ms;
}

static void report_health(void)
{
    write_health(&s_service_health);
    if (pulse_host_report_health_v1(&s_service_health) != PULSE_EXT_OK) {
        s_fault_status = PULSE_EXT_ERR_FAULT;
        s_state = PULSE_EXT_HEALTH_FAULTED;
        s_quiesce_requested = 1u;
    }
}

static void synthetic_task_deleted(int index, void *value)
{
    if (index == 0 && value == (void *)&s_task) {
        s_task = 0;
        s_task_exited = 1u;
    }
}

static void synthetic_task(void *parameter)
{
    synthetic_queue_item item;
    pulse_extension_event_v1 event;
    pulse_extension_completion_v1 completion;
    static const uint8_t tick_payload[] = {'h', 'x', '4', '-', 't', 'i', 'c', 'k'};
    uint32_t idle_polls = 0u;
    (void)parameter;
    update_progress();
    s_task_stack_high_water_bytes = uxTaskGetStackHighWaterMark(0);
    report_health();
    while (s_quiesce_requested == 0u) {
        if (xQueueReceive(s_queue, &item, 1u) != 0) {
            if (s_pending_count != 0u) {
                s_pending_count -= 1u;
            }
            if (item.kind == PULSE_SYNTHETIC_WORK_TICK) {
                zero_bytes(&event, sizeof(event));
                event.struct_size = sizeof(event);
                event.event_id = PULSE_SYNTHETIC_EVENT_TICK;
                event.causation_id = s_activation_epoch;
                if (time_value(event.causation_id) == 0u) {
                    event.causation_id.lo = 1u;
                }
                event.payload_ptr = tick_payload;
                event.payload_len = sizeof(tick_payload);
                if (pulse_host_emit_event_v1(&event) != PULSE_EXT_OK) {
                    s_accepting_work = 0u;
                    s_fault_status = PULSE_EXT_ERR_FAULT;
                    s_state = PULSE_EXT_HEALTH_FAULTED;
                }
            } else if (item.kind == PULSE_SYNTHETIC_WORK_ECHO) {
                zero_bytes(&completion, sizeof(completion));
                completion.struct_size = sizeof(completion);
                completion.status = PULSE_EXT_OK;
                completion.correlation_id = item.correlation_id;
                completion.payload_ptr = item.payload_len != 0u ? item.payload : 0;
                completion.payload_len = item.payload_len;
                if (pulse_host_complete_effect_v1(&completion) != PULSE_EXT_OK) {
                    s_accepting_work = 0u;
                    s_fault_status = PULSE_EXT_ERR_FAULT;
                    s_state = PULSE_EXT_HEALTH_FAULTED;
                }
            } else {
                s_accepting_work = 0u;
                s_fault_status = PULSE_EXT_ERR_FAULT;
                s_state = PULSE_EXT_HEALTH_FAULTED;
            }
            update_progress();
            report_health();
            idle_polls = 0u;
        } else {
            idle_polls += 1u;
            if ((idle_polls & 15u) == 0u) {
                s_task_stack_high_water_bytes = uxTaskGetStackHighWaterMark(0);
                update_progress();
                report_health();
            }
        }
    }
    while (xQueueReceive(s_queue, &item, 0u) != 0) {
        if (s_pending_count != 0u) {
            s_pending_count -= 1u;
        }
    }
    s_accepting_work = 0u;
    s_pending_count = 0u;
    s_state = PULSE_EXT_HEALTH_QUIESCED;
    update_progress();
    report_health();
    vTaskDelete(0);
}

static int32_t synthetic_init(const pulse_extension_init_args_v1 *args)
{
    uint32_t index;
    if (args == 0 || args->struct_size != sizeof(*args) || args->flags != 0u ||
        !words_zero(args->reserved, 2u)) {
        return PULSE_EXT_ERR_ARGUMENT;
    }
    for (index = 0u; index < sizeof(s_extension_id); ++index) {
        if (args->extension_id[index] != s_extension_id[index]) {
            return PULSE_EXT_ERR_ARGUMENT;
        }
    }
    if (s_state != 0u) {
        return PULSE_EXT_ERR_STATE;
    }
    zero_bytes(s_task_stack, sizeof(s_task_stack));
    zero_bytes(s_task_control, sizeof(s_task_control));
    zero_bytes(s_queue_storage, sizeof(s_queue_storage));
    zero_bytes(s_queue_control, sizeof(s_queue_control));
    zero_bytes(&s_service_health, sizeof(s_service_health));
    s_fault_status = PULSE_EXT_OK;
    s_pending_count = 0u;
    s_queue_high_water = 0u;
    s_task_stack_high_water_bytes = 0u;
    s_accepting_work = 0u;
    s_quiesce_requested = 0u;
    s_task_exited = 0u;
    s_start_entered = 0u;
    s_queue = 0;
    s_task = 0;
    s_last_progress_ms.lo = 0u;
    s_last_progress_ms.hi = 0u;
    s_activation_epoch = args->activation_epoch;
    s_state = PULSE_EXT_HEALTH_INITIALIZED;
    return PULSE_EXT_OK;
}

static int32_t synthetic_start(void)
{
    synthetic_queue_item initial_work;
    if (s_state != PULSE_EXT_HEALTH_INITIALIZED || s_start_entered != 0u) {
        return PULSE_EXT_ERR_STATE;
    }
    s_start_entered = 1u;
    s_queue = xQueueGenericCreateStatic(
        PULSE_SYNTHETIC_QUEUE_DEPTH,
        PULSE_SYNTHETIC_QUEUE_ITEM_BYTES,
        s_queue_storage,
        s_queue_control,
        PULSE_SYNTHETIC_QUEUE_TYPE_BASE);
    if (s_queue == 0) {
        s_fault_status = PULSE_EXT_ERR_FAULT;
        s_state = PULSE_EXT_HEALTH_FAULTED;
        return PULSE_EXT_ERR_FAULT;
    }
    zero_bytes(&initial_work, sizeof(initial_work));
    initial_work.kind = PULSE_SYNTHETIC_WORK_TICK;
    s_pending_count = 1u;
    if (xQueueGenericSend(s_queue, &initial_work, 0u,
                          PULSE_SYNTHETIC_QUEUE_SEND_BACK) == 0) {
        s_pending_count = 0u;
        s_fault_status = PULSE_EXT_ERR_FAULT;
        s_state = PULSE_EXT_HEALTH_FAULTED;
        return PULSE_EXT_ERR_FAULT;
    }
    s_queue_high_water = 1u;
    s_accepting_work = 1u;
    s_state = PULSE_EXT_HEALTH_RUNNING;
    s_task = xTaskCreateStatic(
        synthetic_task,
        "pulse-hx4",
        PULSE_SYNTHETIC_TASK_STACK_BYTES,
        0,
        PULSE_SYNTHETIC_TASK_PRIORITY,
        s_task_stack,
        s_task_control);
    if (s_task == 0) {
        s_accepting_work = 0u;
        s_fault_status = PULSE_EXT_ERR_FAULT;
        s_state = PULSE_EXT_HEALTH_FAULTED;
        return PULSE_EXT_ERR_FAULT;
    }
    /* Slot zero is safe for this direct FreeRTOS task; it is not a pthread. */
    vTaskSetThreadLocalStoragePointerAndDelCallback(
        s_task, 0, (void *)&s_task, synthetic_task_deleted);
    return PULSE_EXT_OK;
}

static int32_t synthetic_invoke(const pulse_extension_invoke_v1 *request)
{
    synthetic_queue_item item;
    if (request == 0 || request->struct_size != sizeof(*request) ||
        request->flags != 0u || !words_zero(request->reserved, 3u)) {
        return PULSE_EXT_ERR_ARGUMENT;
    }
    if (s_state != PULSE_EXT_HEALTH_RUNNING || s_accepting_work == 0u) {
        return PULSE_EXT_ERR_STATE;
    }
    if (request->operation_id != PULSE_SYNTHETIC_OPERATION_ECHO) {
        return PULSE_EXT_ERR_UNSUPPORTED;
    }
    if (request->payload_len > PULSE_SYNTHETIC_EFFECT_PAYLOAD_MAX ||
        ((request->payload_len == 0u) != (request->payload_ptr == 0))) {
        return PULSE_EXT_ERR_BOUNDS;
    }
    zero_bytes(&item, sizeof(item));
    item.kind = PULSE_SYNTHETIC_WORK_ECHO;
    item.correlation_id = request->correlation_id;
    item.deadline_ms = request->deadline_ms;
    item.payload_len = request->payload_len;
    if (request->payload_len != 0u) {
        uint32_t index;
        for (index = 0u; index < request->payload_len; ++index) {
            item.payload[index] = request->payload_ptr[index];
        }
    }
    s_pending_count += 1u;
    if (s_pending_count > s_queue_high_water) {
        s_queue_high_water = s_pending_count;
    }
    if (xQueueGenericSend(s_queue, &item, 0u,
                          PULSE_SYNTHETIC_QUEUE_SEND_BACK) == 0) {
        s_pending_count -= 1u;
        return PULSE_EXT_ERR_BUSY;
    }
    return PULSE_EXT_OK;
}

static int32_t synthetic_health(pulse_extension_health_v1 *out_health)
{
    if (out_health == 0 || out_health->struct_size != sizeof(*out_health)) {
        return PULSE_EXT_ERR_ARGUMENT;
    }
    write_health(out_health);
    return PULSE_EXT_OK;
}

static int32_t synthetic_quiesce(const pulse_extension_quiesce_v1 *request)
{
    uint64_t deadline;
    if (request == 0 || request->struct_size != sizeof(*request) ||
        request->flags != 0u || !words_zero(request->reserved, 3u)) {
        return PULSE_EXT_ERR_ARGUMENT;
    }
    if (s_start_entered == 0u ||
        (s_state != PULSE_EXT_HEALTH_RUNNING &&
         s_state != PULSE_EXT_HEALTH_FAULTED)) {
        return PULSE_EXT_ERR_STATE;
    }
    deadline = time_value(request->deadline_ms);
    if (deadline == 0u) {
        return PULSE_EXT_ERR_ARGUMENT;
    }
    s_accepting_work = 0u;
    s_quiesce_requested = 1u;
    s_state = PULSE_EXT_HEALTH_QUIESCING;
    if (s_task == 0) {
        synthetic_queue_item item;
        while (s_queue != 0 && xQueueReceive(s_queue, &item, 0u) != 0) {
            if (s_pending_count != 0u) {
                s_pending_count -= 1u;
            }
        }
        s_pending_count = 0u;
        s_task_exited = 1u;
        s_state = PULSE_EXT_HEALTH_QUIESCED;
    }
    while (s_task_exited == 0u) {
        if (pulse_host_monotonic_ms_v1(&s_service_time) != PULSE_EXT_OK ||
            time_value(s_service_time) >= deadline) {
            s_fault_status = PULSE_EXT_ERR_TIMEOUT;
            s_state = PULSE_EXT_HEALTH_FAULTED;
            report_health();
            return PULSE_EXT_ERR_TIMEOUT;
        }
        vTaskDelay(1u);
    }
    if (s_queue != 0) {
        vQueueDelete(s_queue);
        s_queue = 0;
    }
    s_state = PULSE_EXT_HEALTH_QUIESCED;
    return PULSE_EXT_OK;
}

static int32_t synthetic_deinit(void)
{
    if ((s_state != PULSE_EXT_HEALTH_INITIALIZED &&
         s_state != PULSE_EXT_HEALTH_QUIESCED) ||
        s_task != 0 || s_queue != 0) {
        return PULSE_EXT_ERR_STATE;
    }
    zero_bytes(s_task_stack, sizeof(s_task_stack));
    zero_bytes(s_task_control, sizeof(s_task_control));
    zero_bytes(s_queue_storage, sizeof(s_queue_storage));
    zero_bytes(s_queue_control, sizeof(s_queue_control));
    zero_bytes(&s_service_health, sizeof(s_service_health));
    s_fault_status = PULSE_EXT_OK;
    s_pending_count = 0u;
    s_queue_high_water = 0u;
    s_task_stack_high_water_bytes = 0u;
    s_accepting_work = 0u;
    s_quiesce_requested = 0u;
    s_task_exited = 0u;
    s_start_entered = 0u;
    s_last_progress_ms.lo = 0u;
    s_last_progress_ms.hi = 0u;
    s_activation_epoch.lo = 0u;
    s_activation_epoch.hi = 0u;
    s_state = 0u;
    return PULSE_EXT_OK;
}

static const pulse_extension_descriptor_v1 s_descriptor = {
    .magic = PULSE_EXTENSION_DESCRIPTOR_MAGIC_V1,
    .struct_size = PULSE_EXTENSION_DESCRIPTOR_SIZE_V1,
    .abi_major = PULSE_EXTENSION_ABI_MAJOR_V1,
    .abi_minor = PULSE_EXTENSION_ABI_MINOR_V1,
    .flags = 0u,
    .extension_id = {
        'P', 'U', 'L', 'S', 'E', '-', 'H', 'X', '3', '-', 'L', 'O', 'O', 'P', '0', '1',
    },
    .metadata_sha256 = {PULSE_EXTENSION_METADATA_SHA256_BYTES},
    .event_count = 1u,
    .operation_count = 1u,
    .reserved0 = 0u,
    .event_ids = {PULSE_SYNTHETIC_EVENT_TICK, 0u, 0u, 0u},
    .operation_ids = {PULSE_SYNTHETIC_OPERATION_ECHO, 0u, 0u, 0u},
    .init_fn = synthetic_init,
    .start_fn = synthetic_start,
    .invoke_fn = synthetic_invoke,
    .health_fn = synthetic_health,
    .quiesce_fn = synthetic_quiesce,
    .deinit_fn = synthetic_deinit,
    .reserved1 = {0u},
};

PULSE_EXTENSION_EXPORT
const pulse_extension_descriptor_v1 *pulse_extension_entry_v1(void)
{
    return &s_descriptor;
}
