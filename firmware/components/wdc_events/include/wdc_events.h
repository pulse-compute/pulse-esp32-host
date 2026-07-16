#pragma once

#include <stddef.h>
#include <stdint.h>

#include "wdc_abi.h"

#ifdef __cplusplus
extern "C" {
#endif

#define WDC_EVENT_QUEUE_CAPACITY_DEFAULT 16u
#define WDC_EVENT_PAYLOAD_MAX            128u
#define WDC_EVENT_RESOURCE_NONE          0u

typedef struct WdcEvent {
    uint32_t abi_major;
    uint32_t event_type;
    uint32_t event_id;
    uint32_t resource_id;
    uint64_t timestamp_ms;
    uint16_t payload_len;
    uint8_t payload[WDC_EVENT_PAYLOAD_MAX];
} WdcEvent;

typedef enum WdcEventOverflowPolicy {
    WDC_EVENT_OVERFLOW_DROP_NEWEST = 0,
} WdcEventOverflowPolicy;

typedef struct WdcEventQueueStats {
    size_t pending;
    uint32_t dropped;
    uint32_t capacity;
    WdcEventOverflowPolicy overflow_policy;
} WdcEventQueueStats;

typedef struct WdcEventQueue {
    WdcEvent items[WDC_EVENT_QUEUE_CAPACITY_DEFAULT];
    size_t head;
    size_t count;
    uint32_t dropped;
    uint32_t next_event_id;
} WdcEventQueue;

int32_t wdc_event_make(WdcEvent *event,
                       uint32_t event_type,
                       uint32_t resource_id,
                       uint64_t timestamp_ms,
                       const uint8_t *payload,
                       uint16_t payload_len);

int32_t wdc_event_encode_cbor(const WdcEvent *event,
                              uint8_t *out,
                              uint32_t out_cap,
                              uint32_t *out_len);

int32_t wdc_event_decode_cbor(const uint8_t *buf, uint32_t len, WdcEvent *out_event);

int32_t wdc_event_encode_envelope(const WdcEvent *event,
                                  uint8_t *out,
                                  uint32_t out_cap,
                                  uint32_t *out_len);

int32_t wdc_event_decode_envelope(const uint8_t *buf,
                                  uint32_t len,
                                  WdcEvent *out_event);

int32_t wdc_event_queue_init(WdcEventQueue *queue);
int32_t wdc_event_queue_push(WdcEventQueue *queue, const WdcEvent *event);
int32_t wdc_event_queue_pop(WdcEventQueue *queue, WdcEvent *out);
size_t wdc_event_queue_count(const WdcEventQueue *queue);
uint32_t wdc_event_queue_dropped(const WdcEventQueue *queue);

int32_t wdc_events_init(void);
int32_t wdc_events_post(const WdcEvent *event);
int32_t wdc_events_next(WdcEvent *out);
size_t wdc_events_pending(void);
uint32_t wdc_events_dropped(void);
void wdc_events_get_stats(WdcEventQueueStats *out_stats);

#ifdef __cplusplus
}
#endif
