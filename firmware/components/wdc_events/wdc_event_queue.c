#include "wdc_events.h"

#include <string.h>

static WdcEventQueue s_default_queue;

int32_t wdc_event_make(WdcEvent *event,
                       uint32_t event_type,
                       uint32_t resource_id,
                       uint64_t timestamp_ms,
                       const uint8_t *payload,
                       uint16_t payload_len)
{
    if (event == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    if (payload_len > WDC_EVENT_PAYLOAD_MAX || (payload_len != 0u && payload == NULL)) {
        return payload_len > WDC_EVENT_PAYLOAD_MAX ? WDC_ERR_BAD_LENGTH : WDC_ERR_BAD_POINTER;
    }
    memset(event, 0, sizeof(*event));
    event->abi_major = WDC_ABI_MAJOR;
    event->event_type = event_type;
    event->resource_id = resource_id;
    event->timestamp_ms = timestamp_ms;
    event->payload_len = payload_len;
    if (payload_len != 0u) {
        memcpy(event->payload, payload, payload_len);
    }
    return WDC_OK;
}

int32_t wdc_event_queue_init(WdcEventQueue *queue)
{
    if (queue == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    memset(queue, 0, sizeof(*queue));
    queue->next_event_id = 1u;
    return WDC_OK;
}

int32_t wdc_event_queue_push(WdcEventQueue *queue, const WdcEvent *event)
{
    if (queue == NULL || event == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    if (event->payload_len > WDC_EVENT_PAYLOAD_MAX) {
        return WDC_ERR_BAD_LENGTH;
    }
    if (queue->count >= WDC_EVENT_QUEUE_CAPACITY_DEFAULT) {
        queue->dropped++;
        return WDC_ERR_BUSY;
    }

    size_t tail = (queue->head + queue->count) % WDC_EVENT_QUEUE_CAPACITY_DEFAULT;
    queue->items[tail] = *event;
    if (queue->items[tail].abi_major == 0u) {
        queue->items[tail].abi_major = WDC_ABI_MAJOR;
    }
    if (queue->items[tail].event_id == 0u) {
        queue->items[tail].event_id = queue->next_event_id++;
        if (queue->next_event_id == 0u) {
            queue->next_event_id = 1u;
        }
    }
    queue->count++;
    return WDC_OK;
}

int32_t wdc_event_queue_pop(WdcEventQueue *queue, WdcEvent *out)
{
    if (queue == NULL || out == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    if (queue->count == 0u) {
        return WDC_ERR_NOT_AVAILABLE;
    }

    *out = queue->items[queue->head];
    queue->head = (queue->head + 1u) % WDC_EVENT_QUEUE_CAPACITY_DEFAULT;
    queue->count--;
    return WDC_OK;
}

size_t wdc_event_queue_count(const WdcEventQueue *queue)
{
    if (queue == NULL) {
        return 0u;
    }
    return queue->count;
}

uint32_t wdc_event_queue_dropped(const WdcEventQueue *queue)
{
    if (queue == NULL) {
        return 0u;
    }
    return queue->dropped;
}

int32_t wdc_events_init(void)
{
    return wdc_event_queue_init(&s_default_queue);
}

int32_t wdc_events_post(const WdcEvent *event)
{
    return wdc_event_queue_push(&s_default_queue, event);
}

int32_t wdc_events_next(WdcEvent *out)
{
    return wdc_event_queue_pop(&s_default_queue, out);
}

size_t wdc_events_pending(void)
{
    return wdc_event_queue_count(&s_default_queue);
}

uint32_t wdc_events_dropped(void)
{
    return wdc_event_queue_dropped(&s_default_queue);
}


void wdc_events_get_stats(WdcEventQueueStats *out_stats)
{
    if (out_stats == NULL) {
        return;
    }
    out_stats->pending = s_default_queue.count;
    out_stats->dropped = s_default_queue.dropped;
    out_stats->capacity = WDC_EVENT_QUEUE_CAPACITY_DEFAULT;
    out_stats->overflow_policy = WDC_EVENT_OVERFLOW_DROP_NEWEST;
}
