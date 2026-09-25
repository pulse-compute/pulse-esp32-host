#include "wdc_events.h"

#include <stdbool.h>
#include <string.h>

int32_t wdc_event_encode_cbor(const WdcEvent *event, uint8_t *out, uint32_t out_cap, uint32_t *out_len)
{
    if (out_len != NULL) { *out_len = 0u; }
    if (event == NULL || out == NULL) { return WDC_ERR_BAD_POINTER; }
    if (event->payload_len > WDC_EVENT_PAYLOAD_MAX) { return WDC_ERR_BAD_LENGTH; }
    WdcCborBuilder b;
    wdc_cbor_builder_init(&b, out, out_cap);
    const bool has_resource = event->resource_id != WDC_EVENT_RESOURCE_NONE;
    const bool has_payload = event->payload_len != 0u;
    const bool has_causation = event->causation_id != 0u;
    const uint32_t pairs = 4u + (has_resource ? 1u : 0u) +
                           (has_payload ? 1u : 0u) + (has_causation ? 1u : 0u);
    int32_t status = wdc_cbor_begin_map(&b, pairs);
    if (status == WDC_OK) { status = wdc_cbor_put_key_u32(&b, WDC_CBOR_KEY_ABI_VERSION, WDC_R4_EVENT_ABI_VERSION); }
    if (status == WDC_OK) { status = wdc_cbor_put_key_u32(&b, WDC_CBOR_KEY_EVENT_TYPE, event->event_type); }
    if (status == WDC_OK) { status = wdc_cbor_put_key_u32(&b, WDC_CBOR_KEY_EVENT_ID, event->event_id); }
    if (status == WDC_OK) { status = wdc_cbor_put_key_u64(&b, WDC_CBOR_KEY_TIMESTAMP_MS, event->timestamp_ms); }
    if (status == WDC_OK && has_causation) { status = wdc_cbor_put_key_u64(&b, WDC_CBOR_KEY_CAUSATION_ID, event->causation_id); }
    if (status == WDC_OK && has_resource) { status = wdc_cbor_put_key_u32(&b, WDC_CBOR_KEY_RESOURCE_ID, event->resource_id); }
    if (status == WDC_OK && has_payload) { status = wdc_cbor_put_key_bytes(&b, WDC_CBOR_KEY_PAYLOAD, event->payload, event->payload_len); }
    if (status != WDC_OK) { return status; }
    if (out_len != NULL) { *out_len = wdc_cbor_len(&b); }
    return WDC_OK;
}

int32_t wdc_event_encode_envelope(const WdcEvent *event, uint8_t *out, uint32_t out_cap, uint32_t *out_len)
{
    return wdc_event_encode_cbor(event, out, out_cap, out_len);
}

int32_t wdc_event_decode_envelope(const uint8_t *buf, uint32_t len, WdcEvent *out_event)
{
    if (buf == NULL || out_event == NULL) { return WDC_ERR_BAD_POINTER; }
    if (!wdc_cbor_is_empty_or_map(buf, len)) { return WDC_ERR_BAD_ENCODING; }
    memset(out_event, 0, sizeof(*out_event));
    uint32_t abi_version = 0u;
    int32_t status = wdc_cbor_map_find_u32(buf, len, WDC_CBOR_KEY_ABI_VERSION, &abi_version);
    if (status != WDC_OK) { return WDC_ERR_BAD_ENCODING; }
    if (abi_version != WDC_R4_EVENT_ABI_VERSION) { return WDC_ERR_UNSUPPORTED_ABI; }
    out_event->abi_major = WDC_ABI_MAJOR;
    status = wdc_cbor_map_find_u32(buf, len, WDC_CBOR_KEY_EVENT_TYPE, &out_event->event_type);
    if (status != WDC_OK) { return WDC_ERR_BAD_ENCODING; }
    status = wdc_cbor_map_find_u32(buf, len, WDC_CBOR_KEY_EVENT_ID, &out_event->event_id);
    if (status != WDC_OK) { return WDC_ERR_BAD_ENCODING; }
    status = wdc_cbor_map_find_u64(buf, len, WDC_CBOR_KEY_TIMESTAMP_MS, &out_event->timestamp_ms);
    if (status != WDC_OK) { return WDC_ERR_BAD_ENCODING; }
    status = wdc_cbor_map_find_u64(buf, len, WDC_CBOR_KEY_CAUSATION_ID, &out_event->causation_id);
    if (status != WDC_OK && status != WDC_ERR_NOT_AVAILABLE) { return WDC_ERR_BAD_ENCODING; }
    uint32_t resource_id = 0u;
    status = wdc_cbor_map_find_u32(buf, len, WDC_CBOR_KEY_RESOURCE_ID, &resource_id);
    if (status == WDC_OK) { out_event->resource_id = resource_id; }
    else if (status != WDC_ERR_NOT_AVAILABLE) { return WDC_ERR_BAD_ENCODING; }
    WdcCborBytes payload;
    status = wdc_cbor_map_find_bytes(buf, len, WDC_CBOR_KEY_PAYLOAD, &payload);
    if (status == WDC_OK) {
        if (payload.len > WDC_EVENT_PAYLOAD_MAX) { return WDC_ERR_BAD_LENGTH; }
        out_event->payload_len = (uint16_t)payload.len;
        if (payload.len != 0u) { memcpy(out_event->payload, payload.ptr, payload.len); }
    } else if (status != WDC_ERR_NOT_AVAILABLE) { return WDC_ERR_BAD_ENCODING; }
    return WDC_OK;
}

int32_t wdc_event_decode_cbor(const uint8_t *buf, uint32_t len, WdcEvent *out_event)
{
    return wdc_event_decode_envelope(buf, len, out_event);
}
