#include "wdc_abi.h"

#include <stddef.h>
#include <string.h>

#define MAJOR_UNSIGNED 0u
#define MAJOR_NEGATIVE 1u
#define MAJOR_BYTES    2u
#define MAJOR_TEXT     3u
#define MAJOR_ARRAY    4u
#define MAJOR_MAP      5u
#define MAJOR_TAG      6u
#define MAJOR_SIMPLE   7u

#define SIMPLE_FALSE 0xf4u
#define SIMPLE_TRUE  0xf5u

void wdc_cbor_builder_init(WdcCborBuilder *builder, uint8_t *buf, uint32_t cap)
{
    if (builder == NULL) {
        return;
    }
    builder->buf = buf;
    builder->cap = cap;
    builder->len = 0u;
}

uint32_t wdc_cbor_len(const WdcCborBuilder *builder)
{
    return builder != NULL ? builder->len : 0u;
}

static int32_t put_u8(WdcCborBuilder *builder, uint8_t value)
{
    if (builder == NULL || builder->buf == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    if (builder->len >= builder->cap) {
        return WDC_ERR_RESPONSE_TOO_SMALL;
    }
    builder->buf[builder->len++] = value;
    return WDC_OK;
}

static int32_t put_raw(WdcCborBuilder *builder, const uint8_t *value, uint32_t value_len)
{
    if (builder == NULL || builder->buf == NULL || (value_len != 0u && value == NULL)) {
        return WDC_ERR_BAD_POINTER;
    }
    if (value_len > builder->cap || builder->len > builder->cap - value_len) {
        return WDC_ERR_RESPONSE_TOO_SMALL;
    }
    if (value_len != 0u) {
        memcpy(&builder->buf[builder->len], value, value_len);
        builder->len += value_len;
    }
    return WDC_OK;
}

static int32_t put_type_value(WdcCborBuilder *builder, uint8_t major, uint64_t value)
{
    const uint8_t prefix = (uint8_t)(major << 5u);
    if (value <= 23u) {
        return put_u8(builder, (uint8_t)(prefix | (uint8_t)value));
    }
    if (value <= 0xffu) {
        int32_t status = put_u8(builder, (uint8_t)(prefix | 24u));
        if (status != WDC_OK) { return status; }
        return put_u8(builder, (uint8_t)value);
    }
    if (value <= 0xffffu) {
        int32_t status = put_u8(builder, (uint8_t)(prefix | 25u));
        if (status != WDC_OK) { return status; }
        status = put_u8(builder, (uint8_t)((value >> 8u) & 0xffu));
        if (status != WDC_OK) { return status; }
        return put_u8(builder, (uint8_t)(value & 0xffu));
    }
    if (value <= 0xffffffffu) {
        int32_t status = put_u8(builder, (uint8_t)(prefix | 26u));
        if (status != WDC_OK) { return status; }
        for (int shift = 24; shift >= 0; shift -= 8) {
            status = put_u8(builder, (uint8_t)((value >> (unsigned)shift) & 0xffu));
            if (status != WDC_OK) { return status; }
        }
        return WDC_OK;
    }
    int32_t status = put_u8(builder, (uint8_t)(prefix | 27u));
    if (status != WDC_OK) { return status; }
    for (int shift = 56; shift >= 0; shift -= 8) {
        status = put_u8(builder, (uint8_t)((value >> (unsigned)shift) & 0xffu));
        if (status != WDC_OK) { return status; }
    }
    return WDC_OK;
}

int32_t wdc_cbor_begin_map(WdcCborBuilder *builder, uint32_t pairs)
{
    return put_type_value(builder, MAJOR_MAP, pairs);
}

static int32_t put_key(WdcCborBuilder *builder, uint32_t key)
{
    return put_type_value(builder, MAJOR_UNSIGNED, key);
}

int32_t wdc_cbor_put_key_u32(WdcCborBuilder *builder, uint32_t key, uint32_t value)
{
    int32_t status = put_key(builder, key);
    if (status != WDC_OK) { return status; }
    return put_type_value(builder, MAJOR_UNSIGNED, value);
}

int32_t wdc_cbor_put_key_u64(WdcCborBuilder *builder, uint32_t key, uint64_t value)
{
    int32_t status = put_key(builder, key);
    if (status != WDC_OK) { return status; }
    return put_type_value(builder, MAJOR_UNSIGNED, value);
}

int32_t wdc_cbor_put_key_i32(WdcCborBuilder *builder, uint32_t key, int32_t value)
{
    int32_t status = put_key(builder, key);
    if (status != WDC_OK) { return status; }
    if (value >= 0) {
        return put_type_value(builder, MAJOR_UNSIGNED, (uint32_t)value);
    }
    return put_type_value(builder, MAJOR_NEGATIVE, (uint32_t)(-1 - value));
}

int32_t wdc_cbor_put_key_bool(WdcCborBuilder *builder, uint32_t key, bool value)
{
    int32_t status = put_key(builder, key);
    if (status != WDC_OK) { return status; }
    return put_u8(builder, value ? SIMPLE_TRUE : SIMPLE_FALSE);
}

int32_t wdc_cbor_put_key_bytes(WdcCborBuilder *builder, uint32_t key, const uint8_t *value, uint32_t value_len)
{
    int32_t status = put_key(builder, key);
    if (status != WDC_OK) { return status; }
    status = put_type_value(builder, MAJOR_BYTES, value_len);
    if (status != WDC_OK) { return status; }
    return put_raw(builder, value, value_len);
}

int32_t wdc_cbor_put_key_text(WdcCborBuilder *builder, uint32_t key, const char *value)
{
    if (value == NULL) { return WDC_ERR_BAD_POINTER; }
    uint32_t len = (uint32_t)strlen(value);
    int32_t status = put_key(builder, key);
    if (status != WDC_OK) { return status; }
    status = put_type_value(builder, MAJOR_TEXT, len);
    if (status != WDC_OK) { return status; }
    return put_raw(builder, (const uint8_t *)value, len);
}

typedef struct Item {
    uint8_t major;
    uint64_t value;
    const uint8_t *payload;
    uint32_t payload_len;
    uint32_t next;
    bool is_bool;
    bool bool_value;
} Item;

static int32_t read_type_value(const uint8_t *buf,
                               uint32_t len,
                               uint32_t offset,
                               uint8_t *out_major,
                               uint64_t *out_value,
                               uint32_t *out_next)
{
    if (buf == NULL || out_major == NULL || out_value == NULL || out_next == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    if (offset >= len) {
        return WDC_ERR_BAD_ENCODING;
    }
    const uint8_t initial = buf[offset++];
    *out_major = (uint8_t)(initial >> 5u);
    const uint8_t addl = (uint8_t)(initial & 0x1fu);
    if (addl <= 23u) {
        *out_value = addl;
        *out_next = offset;
        return WDC_OK;
    }
    if (addl == 24u) {
        if (offset >= len) { return WDC_ERR_BAD_ENCODING; }
        *out_value = buf[offset++];
        *out_next = offset;
        return WDC_OK;
    }
    if (addl == 25u) {
        if (len - offset < 2u) { return WDC_ERR_BAD_ENCODING; }
        *out_value = ((uint64_t)buf[offset] << 8u) | (uint64_t)buf[offset + 1u];
        *out_next = offset + 2u;
        return WDC_OK;
    }
    if (addl == 26u) {
        if (len - offset < 4u) { return WDC_ERR_BAD_ENCODING; }
        *out_value = ((uint64_t)buf[offset] << 24u) |
                     ((uint64_t)buf[offset + 1u] << 16u) |
                     ((uint64_t)buf[offset + 2u] << 8u) |
                     (uint64_t)buf[offset + 3u];
        *out_next = offset + 4u;
        return WDC_OK;
    }
    if (addl == 27u) {
        if (len - offset < 8u) { return WDC_ERR_BAD_ENCODING; }
        uint64_t value = 0u;
        for (uint32_t i = 0u; i < 8u; ++i) {
            value = (value << 8u) | (uint64_t)buf[offset + i];
        }
        *out_value = value;
        *out_next = offset + 8u;
        return WDC_OK;
    }
    return WDC_ERR_BAD_ENCODING;
}

static int32_t read_item(const uint8_t *buf, uint32_t len, uint32_t offset, Item *out_item);

static int32_t skip_item(const uint8_t *buf, uint32_t len, uint32_t offset, uint32_t *out_next)
{
    Item item;
    int32_t status = read_item(buf, len, offset, &item);
    if (status != WDC_OK) { return status; }
    *out_next = item.next;
    return WDC_OK;
}

static int32_t read_item(const uint8_t *buf, uint32_t len, uint32_t offset, Item *out_item)
{
    if (buf == NULL || out_item == NULL) { return WDC_ERR_BAD_POINTER; }
    memset(out_item, 0, sizeof(*out_item));
    if (offset >= len) { return WDC_ERR_BAD_ENCODING; }
    if (buf[offset] == SIMPLE_FALSE || buf[offset] == SIMPLE_TRUE) {
        out_item->major = MAJOR_SIMPLE;
        out_item->is_bool = true;
        out_item->bool_value = buf[offset] == SIMPLE_TRUE;
        out_item->next = offset + 1u;
        return WDC_OK;
    }

    uint8_t major = 0u;
    uint64_t value = 0u;
    uint32_t next = 0u;
    int32_t status = read_type_value(buf, len, offset, &major, &value, &next);
    if (status != WDC_OK) { return status; }
    out_item->major = major;
    out_item->value = value;
    out_item->next = next;

    if (major == MAJOR_BYTES || major == MAJOR_TEXT) {
        if (value > UINT32_MAX || next > len || (uint32_t)value > len - next) {
            return WDC_ERR_BAD_ENCODING;
        }
        out_item->payload = &buf[next];
        out_item->payload_len = (uint32_t)value;
        out_item->next = next + (uint32_t)value;
        return WDC_OK;
    }
    if (major == MAJOR_ARRAY) {
        if (value > 32u) { return WDC_ERR_BAD_ENCODING; }
        for (uint32_t i = 0u; i < (uint32_t)value; ++i) {
            status = skip_item(buf, len, out_item->next, &out_item->next);
            if (status != WDC_OK) { return status; }
        }
        return WDC_OK;
    }
    if (major == MAJOR_MAP) {
        if (value > 32u) { return WDC_ERR_BAD_ENCODING; }
        for (uint32_t i = 0u; i < (uint32_t)value; ++i) {
            status = skip_item(buf, len, out_item->next, &out_item->next);
            if (status != WDC_OK) { return status; }
            status = skip_item(buf, len, out_item->next, &out_item->next);
            if (status != WDC_OK) { return status; }
        }
        return WDC_OK;
    }
    if (major == MAJOR_TAG) { return WDC_ERR_BAD_ENCODING; }
    return WDC_OK;
}

bool wdc_cbor_is_empty_or_map(const uint8_t *buf, uint32_t len)
{
    if (len == 0u) { return true; }
    if (buf == NULL) { return false; }
    Item item;
    if (read_item(buf, len, 0u, &item) != WDC_OK) { return false; }
    return item.major == MAJOR_MAP && item.next == len;
}

static int32_t find_item(const uint8_t *buf, uint32_t len, uint32_t key, Item *out_item)
{
    if (buf == NULL || out_item == NULL) { return WDC_ERR_BAD_POINTER; }
    if (len == 0u) { return WDC_ERR_NOT_AVAILABLE; }
    uint8_t major = 0u;
    uint64_t pairs = 0u;
    uint32_t offset = 0u;
    int32_t status = read_type_value(buf, len, 0u, &major, &pairs, &offset);
    if (status != WDC_OK) { return status; }
    if (major != MAJOR_MAP || pairs > 32u) { return WDC_ERR_BAD_ENCODING; }

    for (uint32_t i = 0u; i < (uint32_t)pairs; ++i) {
        Item key_item;
        status = read_item(buf, len, offset, &key_item);
        if (status != WDC_OK) { return status; }
        offset = key_item.next;
        Item value_item;
        status = read_item(buf, len, offset, &value_item);
        if (status != WDC_OK) { return status; }
        offset = value_item.next;
        if (key_item.major == MAJOR_UNSIGNED && key_item.value == key) {
            *out_item = value_item;
            return WDC_OK;
        }
    }
    if (offset != len) { return WDC_ERR_BAD_ENCODING; }
    return WDC_ERR_NOT_AVAILABLE;
}

int32_t wdc_cbor_map_find_u32(const uint8_t *buf, uint32_t len, uint32_t key, uint32_t *out_value)
{
    if (out_value == NULL) { return WDC_ERR_BAD_POINTER; }
    Item item;
    int32_t status = find_item(buf, len, key, &item);
    if (status != WDC_OK) { return status; }
    if (item.major != MAJOR_UNSIGNED || item.value > UINT32_MAX) { return WDC_ERR_BAD_ENCODING; }
    *out_value = (uint32_t)item.value;
    return WDC_OK;
}

int32_t wdc_cbor_map_find_u64(const uint8_t *buf, uint32_t len, uint32_t key, uint64_t *out_value)
{
    if (out_value == NULL) { return WDC_ERR_BAD_POINTER; }
    Item item;
    int32_t status = find_item(buf, len, key, &item);
    if (status != WDC_OK) { return status; }
    if (item.major != MAJOR_UNSIGNED) { return WDC_ERR_BAD_ENCODING; }
    *out_value = item.value;
    return WDC_OK;
}

int32_t wdc_cbor_map_find_i32(const uint8_t *buf, uint32_t len, uint32_t key, int32_t *out_value)
{
    if (out_value == NULL) { return WDC_ERR_BAD_POINTER; }
    Item item;
    int32_t status = find_item(buf, len, key, &item);
    if (status != WDC_OK) { return status; }
    if (item.major == MAJOR_UNSIGNED && item.value <= INT32_MAX) {
        *out_value = (int32_t)item.value;
        return WDC_OK;
    }
    if (item.major == MAJOR_NEGATIVE && item.value <= (uint64_t)INT32_MAX) {
        *out_value = (int32_t)(-1 - (int32_t)item.value);
        return WDC_OK;
    }
    return WDC_ERR_BAD_ENCODING;
}

int32_t wdc_cbor_map_find_bool(const uint8_t *buf, uint32_t len, uint32_t key, bool *out_value)
{
    if (out_value == NULL) { return WDC_ERR_BAD_POINTER; }
    Item item;
    int32_t status = find_item(buf, len, key, &item);
    if (status != WDC_OK) { return status; }
    if (!item.is_bool) { return WDC_ERR_BAD_ENCODING; }
    *out_value = item.bool_value;
    return WDC_OK;
}

int32_t wdc_cbor_map_find_bytes(const uint8_t *buf, uint32_t len, uint32_t key, WdcCborBytes *out_value)
{
    if (out_value == NULL) { return WDC_ERR_BAD_POINTER; }
    Item item;
    int32_t status = find_item(buf, len, key, &item);
    if (status != WDC_OK) { return status; }
    if (item.major != MAJOR_BYTES) { return WDC_ERR_BAD_ENCODING; }
    out_value->ptr = item.payload;
    out_value->len = item.payload_len;
    return WDC_OK;
}

int32_t wdc_cbor_map_find_text(const uint8_t *buf, uint32_t len, uint32_t key, WdcCborText *out_value)
{
    if (out_value == NULL) { return WDC_ERR_BAD_POINTER; }
    Item item;
    int32_t status = find_item(buf, len, key, &item);
    if (status != WDC_OK) { return status; }
    if (item.major != MAJOR_TEXT) { return WDC_ERR_BAD_ENCODING; }
    out_value->ptr = (const char *)item.payload;
    out_value->len = item.payload_len;
    return WDC_OK;
}
