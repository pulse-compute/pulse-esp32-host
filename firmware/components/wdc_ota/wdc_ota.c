#include "wdc_ota.h"

#include <string.h>
#include <stdbool.h>

#ifdef ESP_PLATFORM
#include "esp_partition.h"
#endif

#define WDC_OTA_METADATA_RECORD_MAGIC 0x57444a52u /* WDJR */
#define WDC_OTA_METADATA_RECORD_VERSION 1u
#define WDC_OTA_METADATA_COMMIT_MARKER 0xc0defaceu
#define WDC_OTA_METADATA_RECORD_STRIDE 4096u

typedef struct WdcOtaMetadataRecord {
    uint32_t magic;
    uint16_t version;
    uint16_t reserved;
    uint32_t generation;
    WdcBundleMetadataV1 metadata;
    uint32_t record_crc;
    uint32_t commit_marker;
} WdcOtaMetadataRecord;

const char *wdc_ota_slot_partition_label(WdcBundleSlotId slot)
{
    switch (slot) {
    case WDC_BUNDLE_SLOT_A:
        return "wasm_a";
    case WDC_BUNDLE_SLOT_B:
        return "wasm_b";
    case WDC_BUNDLE_SLOT_NONE:
    default:
        return NULL;
    }
}

static uint32_t ota_crc32_update(uint32_t crc, const uint8_t *data, uint32_t len)
{
    crc = ~crc;
    for (uint32_t i = 0u; i < len; ++i) {
        crc ^= data[i];
        for (uint32_t j = 0u; j < 8u; ++j) {
            uint32_t mask = 0u - (crc & 1u);
            crc = (crc >> 1u) ^ (0xedb88320u & mask);
        }
    }
    return ~crc;
}

static uint32_t metadata_record_crc32(const WdcOtaMetadataRecord *record)
{
    if (record == NULL) {
        return 0u;
    }
    WdcOtaMetadataRecord copy = *record;
    copy.record_crc = 0u;
    copy.commit_marker = 0u;
    return ota_crc32_update(0u, (const uint8_t *)&copy, (uint32_t)sizeof(copy));
}

static void metadata_record_from_metadata(WdcOtaMetadataRecord *record, const WdcBundleMetadataV1 *metadata)
{
    if (record == NULL || metadata == NULL) {
        return;
    }
    memset(record, 0xff, sizeof(*record));
    record->magic = WDC_OTA_METADATA_RECORD_MAGIC;
    record->version = WDC_OTA_METADATA_RECORD_VERSION;
    record->reserved = 0u;
    record->generation = metadata->metadata_generation;
    record->metadata = *metadata;
    (void)wdc_bundle_metadata_seal(&record->metadata);
    record->commit_marker = 0u;
    record->record_crc = metadata_record_crc32(record);
    record->commit_marker = WDC_OTA_METADATA_COMMIT_MARKER;
}

static bool metadata_record_valid(const WdcOtaMetadataRecord *record)
{
    if (record == NULL) {
        return false;
    }
    if (record->magic != WDC_OTA_METADATA_RECORD_MAGIC ||
        record->version != WDC_OTA_METADATA_RECORD_VERSION ||
        record->commit_marker != WDC_OTA_METADATA_COMMIT_MARKER) {
        return false;
    }
    if (record->record_crc != metadata_record_crc32(record)) {
        return false;
    }
    if (wdc_bundle_metadata_validate(&record->metadata) != WDC_OK) {
        return false;
    }
    return record->generation == record->metadata.metadata_generation;
}

int32_t wdc_ota_metadata_journal_record_validate(const WdcOtaMetadataJournalRecord *record)
{
    if (record == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    return metadata_record_valid((const WdcOtaMetadataRecord *)record) ? WDC_OK : WDC_ERR_CONTRACT_VIOLATION;
}

static bool metadata_equal(const WdcBundleMetadataV1 *a, const WdcBundleMetadataV1 *b)
{
    return a != NULL && b != NULL && memcmp(a, b, sizeof(*a)) == 0;
}

static int32_t select_best_metadata_record(const WdcOtaMetadataRecord *r0,
                                           const WdcOtaMetadataRecord *r1,
                                           WdcBundleMetadataV1 *out_metadata,
                                           uint32_t *out_best_index)
{
    bool v0 = metadata_record_valid(r0);
    bool v1 = metadata_record_valid(r1);
    if (!v0 && !v1) {
        if (out_metadata != NULL) {
            wdc_bundle_metadata_init(out_metadata);
        }
        if (out_best_index != NULL) {
            *out_best_index = 0u;
        }
        return WDC_OK;
    }
    const WdcOtaMetadataRecord *best = NULL;
    uint32_t index = 0u;
    if (v0 && (!v1 || r0->generation >= r1->generation)) {
        best = r0;
        index = 0u;
    } else {
        best = r1;
        index = 1u;
    }
    if (out_metadata != NULL) {
        *out_metadata = best->metadata;
    }
    if (out_best_index != NULL) {
        *out_best_index = index;
    }
    return WDC_OK;
}

#ifdef ESP_PLATFORM
static const esp_partition_t *find_slot_partition(WdcBundleSlotId slot)
{
    const char *label = wdc_ota_slot_partition_label(slot);
    if (label == NULL) {
        return NULL;
    }
    esp_partition_subtype_t subtype = slot == WDC_BUNDLE_SLOT_A ? (esp_partition_subtype_t)0x00 : (esp_partition_subtype_t)0x01;
    return esp_partition_find_first((esp_partition_type_t)0x40, subtype, label);
}

int32_t wdc_ota_read_slot_header(WdcBundleSlotId slot, WdcBundleParsedHeader *out_header)
{
    if (out_header == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    const esp_partition_t *partition = find_slot_partition(slot);
    if (partition == NULL || partition->size < WDC_BUNDLE_HEADER_LEN_V1) {
        return WDC_ERR_NOT_AVAILABLE;
    }
    uint8_t header[WDC_BUNDLE_HEADER_LEN_V1];
    if (esp_partition_read(partition, 0, header, sizeof(header)) != ESP_OK) {
        return WDC_ERR_IO;
    }
    return wdc_bundle_parse_header(header, sizeof(header), out_header);
}

int32_t wdc_ota_read_slot_to_buffer(WdcBundleSlotId slot,
                                    uint8_t *buffer,
                                    uint32_t buffer_cap,
                                    uint32_t *out_len)
{
    if (buffer == NULL || out_len == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    *out_len = 0u;
    const esp_partition_t *partition = find_slot_partition(slot);
    if (partition == NULL || partition->size < WDC_BUNDLE_HEADER_LEN_V1) {
        return WDC_ERR_NOT_AVAILABLE;
    }
    if (esp_partition_read(partition, 0, buffer, WDC_BUNDLE_HEADER_LEN_V1) != ESP_OK) {
        return WDC_ERR_IO;
    }
    WdcBundleParsedHeader header;
    int32_t status = wdc_bundle_parse_header(buffer, WDC_BUNDLE_HEADER_LEN_V1, &header);
    if (status != WDC_OK) {
        return status;
    }
    if (header.total_len > buffer_cap || header.total_len > partition->size) {
        return WDC_ERR_BAD_LENGTH;
    }
    if (esp_partition_read(partition, WDC_BUNDLE_HEADER_LEN_V1, buffer + WDC_BUNDLE_HEADER_LEN_V1, header.total_len - WDC_BUNDLE_HEADER_LEN_V1) != ESP_OK) {
        return WDC_ERR_IO;
    }
    *out_len = header.total_len;
    return WDC_OK;
}

static const esp_partition_t *find_metadata_partition(void)
{
    return esp_partition_find_first((esp_partition_type_t)0x40, (esp_partition_subtype_t)0x02, "wasm_meta");
}

static int32_t read_metadata_record(const esp_partition_t *partition, uint32_t index, WdcOtaMetadataRecord *out_record)
{
    if (partition == NULL || out_record == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    uint32_t offset = index * WDC_OTA_METADATA_RECORD_STRIDE;
    if (partition->size < offset + sizeof(*out_record)) {
        return WDC_ERR_BAD_LENGTH;
    }
    if (esp_partition_read(partition, offset, out_record, sizeof(*out_record)) != ESP_OK) {
        return WDC_ERR_IO;
    }
    return WDC_OK;
}

int32_t wdc_ota_read_metadata(WdcBundleMetadataV1 *out_metadata)
{
    if (out_metadata == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    const esp_partition_t *partition = find_metadata_partition();
    if (partition == NULL || partition->size < (2u * WDC_OTA_METADATA_RECORD_STRIDE)) {
        wdc_bundle_metadata_init(out_metadata);
        return WDC_OK;
    }
    WdcOtaMetadataRecord r0;
    WdcOtaMetadataRecord r1;
    if (read_metadata_record(partition, 0u, &r0) != WDC_OK || read_metadata_record(partition, 1u, &r1) != WDC_OK) {
        return WDC_ERR_IO;
    }
    return select_best_metadata_record(&r0, &r1, out_metadata, NULL);
}

int32_t wdc_ota_write_metadata(const WdcBundleMetadataV1 *metadata)
{
    if (metadata == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    WdcBundleMetadataV1 copy = *metadata;
    if (wdc_bundle_metadata_seal(&copy) != WDC_OK) {
        return WDC_ERR_BAD_POINTER;
    }
    const esp_partition_t *partition = find_metadata_partition();
    if (partition == NULL || partition->size < (2u * WDC_OTA_METADATA_RECORD_STRIDE)) {
        return WDC_ERR_NOT_AVAILABLE;
    }
    WdcOtaMetadataRecord r0;
    WdcOtaMetadataRecord r1;
    if (read_metadata_record(partition, 0u, &r0) != WDC_OK || read_metadata_record(partition, 1u, &r1) != WDC_OK) {
        return WDC_ERR_IO;
    }
    WdcBundleMetadataV1 current;
    uint32_t best_index = 0u;
    (void)select_best_metadata_record(&r0, &r1, &current, &best_index);
    if (metadata_equal(&current, &copy)) {
        return WDC_OK;
    }
    WdcOtaMetadataRecord next;
    metadata_record_from_metadata(&next, &copy);
    bool have_valid_record = metadata_record_valid(&r0) || metadata_record_valid(&r1);
    uint32_t target_index = have_valid_record ? (best_index == 0u ? 1u : 0u) : 0u;
    uint32_t offset = target_index * WDC_OTA_METADATA_RECORD_STRIDE;
    if (esp_partition_erase_range(partition, offset, WDC_OTA_METADATA_RECORD_STRIDE) != ESP_OK) {
        return WDC_ERR_IO;
    }
    if (esp_partition_write(partition, offset, &next, sizeof(next)) != ESP_OK) {
        return WDC_ERR_IO;
    }
    return WDC_OK;
}

#else
static const uint8_t *s_slot_a;
static uint32_t s_slot_a_len;
static const uint8_t *s_slot_b;
static uint32_t s_slot_b_len;

static WdcOtaMetadataRecord s_metadata_records[2];
static bool s_metadata_record_present[2];
static uint32_t s_metadata_write_count;

static void host_clear_metadata_records(void)
{
    memset(s_metadata_records, 0xff, sizeof(s_metadata_records));
    memset(s_metadata_record_present, 0, sizeof(s_metadata_record_present));
    s_metadata_write_count = 0u;
}

int32_t wdc_ota_host_set_metadata(const WdcBundleMetadataV1 *metadata)
{
    if (metadata == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    WdcBundleMetadataV1 copy = *metadata;
    int32_t status = wdc_bundle_metadata_seal(&copy);
    if (status != WDC_OK) {
        return status;
    }
    host_clear_metadata_records();
    metadata_record_from_metadata(&s_metadata_records[0], &copy);
    s_metadata_record_present[0] = true;
    return WDC_OK;
}

void wdc_ota_host_clear_metadata(void)
{
    host_clear_metadata_records();
}

int32_t wdc_ota_read_metadata(WdcBundleMetadataV1 *out_metadata)
{
    if (out_metadata == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    WdcOtaMetadataRecord r0;
    WdcOtaMetadataRecord r1;
    memset(&r0, 0xff, sizeof(r0));
    memset(&r1, 0xff, sizeof(r1));
    if (s_metadata_record_present[0]) { r0 = s_metadata_records[0]; }
    if (s_metadata_record_present[1]) { r1 = s_metadata_records[1]; }
    return select_best_metadata_record(&r0, &r1, out_metadata, NULL);
}

int32_t wdc_ota_write_metadata(const WdcBundleMetadataV1 *metadata)
{
    if (metadata == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    WdcBundleMetadataV1 copy = *metadata;
    int32_t status = wdc_bundle_metadata_seal(&copy);
    if (status != WDC_OK) {
        return status;
    }
    WdcBundleMetadataV1 current;
    uint32_t best_index = 0u;
    status = wdc_ota_read_metadata(&current);
    if (status != WDC_OK) {
        return status;
    }
    WdcOtaMetadataRecord r0;
    WdcOtaMetadataRecord r1;
    memset(&r0, 0xff, sizeof(r0));
    memset(&r1, 0xff, sizeof(r1));
    if (s_metadata_record_present[0]) { r0 = s_metadata_records[0]; }
    if (s_metadata_record_present[1]) { r1 = s_metadata_records[1]; }
    (void)select_best_metadata_record(&r0, &r1, &current, &best_index);
    if (metadata_equal(&current, &copy)) {
        return WDC_OK;
    }
    bool have_valid_record = metadata_record_valid(&r0) || metadata_record_valid(&r1);
    uint32_t target_index = have_valid_record ? (best_index == 0u ? 1u : 0u) : 0u;
    metadata_record_from_metadata(&s_metadata_records[target_index], &copy);
    s_metadata_record_present[target_index] = true;
    s_metadata_write_count++;
    return WDC_OK;
}

uint32_t wdc_ota_host_metadata_write_count(void)
{
    return s_metadata_write_count;
}

uint32_t wdc_ota_host_metadata_valid_record_count(void)
{
    uint32_t count = 0u;
    if (s_metadata_record_present[0] && metadata_record_valid(&s_metadata_records[0])) { count++; }
    if (s_metadata_record_present[1] && metadata_record_valid(&s_metadata_records[1])) { count++; }
    return count;
}

int32_t wdc_ota_host_corrupt_metadata_record(uint32_t index)
{
    if (index >= 2u) {
        return WDC_ERR_INVALID_RESOURCE;
    }
    if (!s_metadata_record_present[index]) {
        return WDC_ERR_NOT_AVAILABLE;
    }
    s_metadata_records[index].record_crc ^= 0x55aa55aau;
    return WDC_OK;
}

int32_t wdc_ota_host_clear_metadata_record(uint32_t index)
{
    if (index >= 2u) {
        return WDC_ERR_INVALID_RESOURCE;
    }
    memset(&s_metadata_records[index], 0xff, sizeof(s_metadata_records[index]));
    s_metadata_record_present[index] = false;
    return WDC_OK;
}

int32_t wdc_ota_host_set_slot_image(WdcBundleSlotId slot, const uint8_t *image, uint32_t image_len)
{
    if (image == NULL || image_len == 0u) {
        return WDC_ERR_BAD_POINTER;
    }
    if (slot == WDC_BUNDLE_SLOT_A) {
        s_slot_a = image;
        s_slot_a_len = image_len;
        return WDC_OK;
    }
    if (slot == WDC_BUNDLE_SLOT_B) {
        s_slot_b = image;
        s_slot_b_len = image_len;
        return WDC_OK;
    }
    return WDC_ERR_INVALID_RESOURCE;
}

void wdc_ota_host_clear_slots(void)
{
    s_slot_a = NULL;
    s_slot_a_len = 0u;
    s_slot_b = NULL;
    s_slot_b_len = 0u;
}

static int32_t slot_image(WdcBundleSlotId slot, const uint8_t **image, uint32_t *image_len)
{
    if (image == NULL || image_len == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    if (slot == WDC_BUNDLE_SLOT_A) {
        *image = s_slot_a;
        *image_len = s_slot_a_len;
    } else if (slot == WDC_BUNDLE_SLOT_B) {
        *image = s_slot_b;
        *image_len = s_slot_b_len;
    } else {
        return WDC_ERR_INVALID_RESOURCE;
    }
    return *image != NULL && *image_len > 0u ? WDC_OK : WDC_ERR_NOT_AVAILABLE;
}

int32_t wdc_ota_read_slot_header(WdcBundleSlotId slot, WdcBundleParsedHeader *out_header)
{
    const uint8_t *image = NULL;
    uint32_t image_len = 0u;
    int32_t status = slot_image(slot, &image, &image_len);
    if (status != WDC_OK) {
        return status;
    }
    return wdc_bundle_parse_header(image, image_len, out_header);
}

int32_t wdc_ota_read_slot_to_buffer(WdcBundleSlotId slot,
                                    uint8_t *buffer,
                                    uint32_t buffer_cap,
                                    uint32_t *out_len)
{
    if (buffer == NULL || out_len == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    const uint8_t *image = NULL;
    uint32_t image_len = 0u;
    int32_t status = slot_image(slot, &image, &image_len);
    if (status != WDC_OK) {
        return status;
    }
    if (image_len > buffer_cap) {
        return WDC_ERR_RESPONSE_TOO_SMALL;
    }
    memcpy(buffer, image, image_len);
    *out_len = image_len;
    return WDC_OK;
}
#endif
