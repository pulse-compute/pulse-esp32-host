#include "wdc_ota.h"

#include <stddef.h>
#include <string.h>
#include <stdbool.h>

#ifdef ESP_PLATFORM
#include "esp_partition.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#endif

typedef WdcOtaMetadataJournalRecord WdcOtaMetadataRecord;

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
    WdcOtaMetadataRecord copy;
    if (record == NULL) {
        return 0u;
    }
    /*
     * The CRC covers the complete persisted object representation, including
     * the alignment bytes before metadata. A C structure assignment need not
     * preserve padding bytes, so this copy must remain byte-for-byte.
     */
    memcpy(&copy, record, sizeof(copy));
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
    memcpy(&record->metadata, metadata, sizeof(record->metadata));
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

static bool metadata_record_erased(const WdcOtaMetadataRecord *record)
{
    const uint8_t *bytes = (const uint8_t *)record;
    uint32_t index;
    if (record == NULL) {
        return false;
    }
    for (index = 0u; index < (uint32_t)sizeof(*record); ++index) {
        if (bytes[index] != 0xffu) {
            return false;
        }
    }
    return true;
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
        if (!metadata_record_erased(r0) || !metadata_record_erased(r1)) {
            return WDC_ERR_CONTRACT_VIOLATION;
        }
        if (out_metadata != NULL) {
            wdc_bundle_metadata_init(out_metadata);
        }
        if (out_best_index != NULL) {
            *out_best_index = 0u;
        }
        return WDC_OK;
    }
    if (v0 && v1 && r0->generation == r1->generation &&
        !metadata_equal(&r0->metadata, &r1->metadata)) {
        return WDC_ERR_CONTRACT_VIOLATION;
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
        memcpy(out_metadata, &best->metadata, sizeof(*out_metadata));
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

int32_t wdc_ota_read_slot_range(WdcBundleSlotId slot,
                                uint32_t offset,
                                uint8_t *buffer,
                                uint32_t length)
{
    const esp_partition_t *partition;
    if (buffer == NULL || length == 0u) {
        return WDC_ERR_BAD_POINTER;
    }
    partition = find_slot_partition(slot);
    if (partition == NULL) {
        return WDC_ERR_NOT_AVAILABLE;
    }
    if (offset > partition->size || length > partition->size - offset) {
        return WDC_ERR_BAD_LENGTH;
    }
    return esp_partition_read(partition, offset, buffer, length) == ESP_OK
               ? WDC_OK
               : WDC_ERR_IO;
}

int32_t wdc_ota_slot_capacity_bytes(WdcBundleSlotId slot,
                                    uint32_t *out_capacity)
{
    const esp_partition_t *partition;
    if (out_capacity == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    partition = find_slot_partition(slot);
    if (partition == NULL) {
        *out_capacity = 0u;
        return WDC_ERR_NOT_AVAILABLE;
    }
    *out_capacity = partition->size;
    return WDC_OK;
}

int32_t wdc_ota_stage_begin(WdcOtaStageSession *session,
                            WdcBundleSlotId slot,
                            uint32_t expected_bytes)
{
    const esp_partition_t *partition;
    uint32_t erase_offset;
    if (session == NULL || expected_bytes == 0u) {
        return WDC_ERR_BAD_POINTER;
    }
    memset(session, 0, sizeof(*session));
    partition = find_slot_partition(slot);
    if (partition == NULL) {
        return WDC_ERR_NOT_AVAILABLE;
    }
    if (expected_bytes > partition->size) {
        return WDC_ERR_BAD_LENGTH;
    }
    /*
     * Retain the HP3 full-inactive-slot erase invariant, but do not issue one
     * multi-megabyte blocking erase. Both supported targets run a three-second
     * task watchdog; bounded chunks plus a one-tick delay let the idle task
     * service it without making partially erased bytes authoritative.
     */
    for (erase_offset = 0u; erase_offset < partition->size;) {
        uint32_t remaining = partition->size - erase_offset;
        uint32_t erase_bytes =
            remaining < (16u * 1024u) ? remaining : (16u * 1024u);
        if (esp_partition_erase_range(partition,
                                      erase_offset,
                                      erase_bytes) != ESP_OK) {
            return WDC_ERR_IO;
        }
        erase_offset += erase_bytes;
        if (erase_offset < partition->size) {
            vTaskDelay(1u);
        }
    }
    session->slot = slot;
    session->expected_bytes = expected_bytes;
    session->active = 1u;
    return WDC_OK;
}

int32_t wdc_ota_stage_write(WdcOtaStageSession *session,
                            const uint8_t *bytes,
                            uint32_t length)
{
    const esp_partition_t *partition;
    if (session == NULL || bytes == NULL || length == 0u) {
        return WDC_ERR_BAD_POINTER;
    }
    if (session->active != 1u ||
        session->written_bytes > session->expected_bytes ||
        length > session->expected_bytes - session->written_bytes) {
        return WDC_ERR_INVALID_STATE;
    }
    partition = find_slot_partition(session->slot);
    if (partition == NULL) {
        return WDC_ERR_NOT_AVAILABLE;
    }
    if (esp_partition_write(partition, session->written_bytes, bytes, length) !=
        ESP_OK) {
        return WDC_ERR_IO;
    }
    session->written_bytes += length;
    return WDC_OK;
}

int32_t wdc_ota_stage_finish(WdcOtaStageSession *session)
{
    if (session == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    if (session->active != 1u ||
        session->written_bytes != session->expected_bytes) {
        return WDC_ERR_INVALID_STATE;
    }
    session->active = 0u;
    return WDC_OK;
}

int32_t wdc_ota_stage_abort(WdcOtaStageSession *session)
{
    if (session == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    session->active = 0u;
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
    uint32_t offset = index * WDC_OTA_METADATA_RECORD_STRIDE_BYTES;
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
    if (partition == NULL || partition->size < (2u * WDC_OTA_METADATA_RECORD_STRIDE_BYTES)) {
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
    WdcBundleMetadataV1 copy;
    memcpy(&copy, metadata, sizeof(copy));
    if (wdc_bundle_metadata_seal(&copy) != WDC_OK) {
        return WDC_ERR_BAD_POINTER;
    }
    const esp_partition_t *partition = find_metadata_partition();
    if (partition == NULL || partition->size < (2u * WDC_OTA_METADATA_RECORD_STRIDE_BYTES)) {
        return WDC_ERR_NOT_AVAILABLE;
    }
    WdcOtaMetadataRecord r0;
    WdcOtaMetadataRecord r1;
    if (read_metadata_record(partition, 0u, &r0) != WDC_OK || read_metadata_record(partition, 1u, &r1) != WDC_OK) {
        return WDC_ERR_IO;
    }
    WdcBundleMetadataV1 current;
    uint32_t best_index = 0u;
    int32_t select_status = select_best_metadata_record(&r0, &r1, &current, &best_index);
    if (select_status != WDC_OK) {
        return select_status;
    }
    if (metadata_equal(&current, &copy)) {
        return WDC_OK;
    }
    WdcOtaMetadataRecord next;
    metadata_record_from_metadata(&next, &copy);
    bool have_valid_record = metadata_record_valid(&r0) || metadata_record_valid(&r1);
    uint32_t target_index = have_valid_record ? (best_index == 0u ? 1u : 0u) : 0u;
    uint32_t offset = target_index * WDC_OTA_METADATA_RECORD_STRIDE_BYTES;
    if (esp_partition_erase_range(partition, offset, WDC_OTA_METADATA_RECORD_STRIDE_BYTES) != ESP_OK) {
        return WDC_ERR_IO;
    }
    if (esp_partition_write(partition,
                            offset,
                            &next,
                            offsetof(WdcOtaMetadataRecord, commit_marker)) != ESP_OK) {
        return WDC_ERR_IO;
    }
    if (esp_partition_write(partition,
                            offset + offsetof(WdcOtaMetadataRecord, commit_marker),
                            &next.commit_marker,
                            sizeof(next.commit_marker)) != ESP_OK) {
        return WDC_ERR_IO;
    }
    return WDC_OK;
}

#else
static uint8_t s_slot_a[WDC_OTA_HOST_SLOT_CAPACITY_BYTES];
static uint32_t s_slot_a_len;
static uint8_t s_slot_b[WDC_OTA_HOST_SLOT_CAPACITY_BYTES];
static uint32_t s_slot_b_len;
static bool s_slot_a_present;
static bool s_slot_b_present;

static WdcOtaMetadataRecord s_metadata_records[2];
static bool s_metadata_record_present[2];
static uint32_t s_metadata_write_count;

typedef struct WdcOtaHostFaultState {
    WdcOtaHostFaultPlan plan;
    uint32_t observation_count;
    uint32_t trigger_count;
    bool armed;
} WdcOtaHostFaultState;

static WdcOtaHostFaultState s_host_fault;

static uint32_t host_fault_operation_bytes(WdcOtaHostFaultOperation operation)
{
    switch (operation) {
    case WDC_OTA_HOST_FAULT_SLOT_ERASE:
    case WDC_OTA_HOST_FAULT_SLOT_WRITE:
        return WDC_OTA_HOST_SLOT_CAPACITY_BYTES;
    case WDC_OTA_HOST_FAULT_METADATA_ERASE:
        return (uint32_t)sizeof(WdcOtaMetadataRecord);
    case WDC_OTA_HOST_FAULT_METADATA_BODY_WRITE:
        return (uint32_t)offsetof(WdcOtaMetadataRecord, commit_marker);
    case WDC_OTA_HOST_FAULT_METADATA_MARKER_WRITE:
        return (uint32_t)sizeof(((WdcOtaMetadataRecord *)0)->commit_marker);
    case WDC_OTA_HOST_FAULT_NONE:
    default:
        return 0u;
    }
}

static bool host_fault_take(WdcOtaHostFaultOperation operation,
                            uint32_t operation_bytes,
                            uint32_t *out_tear_after_bytes)
{
    if (!s_host_fault.armed || s_host_fault.plan.operation != operation) {
        return false;
    }
    s_host_fault.observation_count++;
    if (s_host_fault.observation_count != s_host_fault.plan.trigger_index) {
        return false;
    }
    s_host_fault.armed = false;
    s_host_fault.trigger_count++;
    if (out_tear_after_bytes != NULL) {
        *out_tear_after_bytes =
            s_host_fault.plan.tear_after_bytes < operation_bytes
                ? s_host_fault.plan.tear_after_bytes
                : operation_bytes;
    }
    return true;
}

int32_t wdc_ota_host_fault_arm(const WdcOtaHostFaultPlan *plan)
{
    uint32_t maximum;
    if (plan == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    maximum = host_fault_operation_bytes(plan->operation);
    if (maximum == 0u || plan->trigger_index == 0u ||
        plan->tear_after_bytes > maximum) {
        return WDC_ERR_BAD_LENGTH;
    }
    memset(&s_host_fault, 0, sizeof(s_host_fault));
    s_host_fault.plan = *plan;
    s_host_fault.armed = true;
    return WDC_OK;
}

void wdc_ota_host_fault_clear(void)
{
    memset(&s_host_fault, 0, sizeof(s_host_fault));
}

void wdc_ota_host_power_cycle(void)
{
    wdc_ota_host_fault_clear();
}

uint32_t wdc_ota_host_fault_observation_count(void)
{
    return s_host_fault.observation_count;
}

uint32_t wdc_ota_host_fault_trigger_count(void)
{
    return s_host_fault.trigger_count;
}

uint32_t wdc_ota_host_metadata_record_bytes(void)
{
    return (uint32_t)sizeof(WdcOtaMetadataRecord);
}

uint32_t wdc_ota_host_metadata_body_bytes(void)
{
    return (uint32_t)offsetof(WdcOtaMetadataRecord, commit_marker);
}

uint32_t wdc_ota_host_metadata_marker_bytes(void)
{
    return (uint32_t)sizeof(((WdcOtaMetadataRecord *)0)->commit_marker);
}

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
    WdcBundleMetadataV1 copy;
    memcpy(&copy, metadata, sizeof(copy));
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
    if (s_metadata_record_present[0]) {
        memcpy(&r0, &s_metadata_records[0], sizeof(r0));
    }
    if (s_metadata_record_present[1]) {
        memcpy(&r1, &s_metadata_records[1], sizeof(r1));
    }
    return select_best_metadata_record(&r0, &r1, out_metadata, NULL);
}

int32_t wdc_ota_write_metadata(const WdcBundleMetadataV1 *metadata)
{
    if (metadata == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    WdcBundleMetadataV1 copy;
    memcpy(&copy, metadata, sizeof(copy));
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
    if (s_metadata_record_present[0]) {
        memcpy(&r0, &s_metadata_records[0], sizeof(r0));
    }
    if (s_metadata_record_present[1]) {
        memcpy(&r1, &s_metadata_records[1], sizeof(r1));
    }
    status = select_best_metadata_record(&r0, &r1, &current, &best_index);
    if (status != WDC_OK) {
        return status;
    }
    if (metadata_equal(&current, &copy)) {
        return WDC_OK;
    }
    bool have_valid_record = metadata_record_valid(&r0) || metadata_record_valid(&r1);
    uint32_t target_index = have_valid_record ? (best_index == 0u ? 1u : 0u) : 0u;
    WdcOtaMetadataRecord next;
    uint32_t tear_after = 0u;
    uint8_t *target_bytes = (uint8_t *)&s_metadata_records[target_index];
    const uint8_t *next_bytes = (const uint8_t *)&next;
    uint32_t body_bytes = (uint32_t)offsetof(WdcOtaMetadataRecord,
                                               commit_marker);
    uint32_t marker_bytes = (uint32_t)sizeof(next.commit_marker);
    metadata_record_from_metadata(&next, &copy);

    if (host_fault_take(WDC_OTA_HOST_FAULT_METADATA_ERASE,
                        (uint32_t)sizeof(WdcOtaMetadataRecord),
                        &tear_after)) {
        memset(target_bytes, 0xff, tear_after);
        if (tear_after == (uint32_t)sizeof(WdcOtaMetadataRecord)) {
            s_metadata_record_present[target_index] = false;
        }
        return WDC_ERR_IO;
    }
    memset(target_bytes, 0xff, sizeof(WdcOtaMetadataRecord));
    s_metadata_record_present[target_index] = false;

    if (host_fault_take(WDC_OTA_HOST_FAULT_METADATA_BODY_WRITE,
                        body_bytes,
                        &tear_after)) {
        memcpy(target_bytes, next_bytes, tear_after);
        s_metadata_record_present[target_index] = tear_after != 0u;
        return WDC_ERR_IO;
    }
    memcpy(target_bytes, next_bytes, body_bytes);
    s_metadata_record_present[target_index] = true;

    if (host_fault_take(WDC_OTA_HOST_FAULT_METADATA_MARKER_WRITE,
                        marker_bytes,
                        &tear_after)) {
        memcpy(target_bytes + body_bytes,
               next_bytes + body_bytes,
               tear_after);
        if (tear_after == marker_bytes) {
            s_metadata_write_count++;
        }
        return WDC_ERR_IO;
    }
    memcpy(target_bytes + body_bytes,
           next_bytes + body_bytes,
           marker_bytes);
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
    if (image_len > WDC_OTA_HOST_SLOT_CAPACITY_BYTES) {
        return WDC_ERR_BAD_LENGTH;
    }
    if (slot == WDC_BUNDLE_SLOT_A) {
        memcpy(s_slot_a, image, image_len);
        s_slot_a_len = image_len;
        s_slot_a_present = true;
        return WDC_OK;
    }
    if (slot == WDC_BUNDLE_SLOT_B) {
        memcpy(s_slot_b, image, image_len);
        s_slot_b_len = image_len;
        s_slot_b_present = true;
        return WDC_OK;
    }
    return WDC_ERR_INVALID_RESOURCE;
}

void wdc_ota_host_clear_slots(void)
{
    memset(s_slot_a, 0xff, sizeof(s_slot_a));
    s_slot_a_len = 0u;
    s_slot_a_present = false;
    memset(s_slot_b, 0xff, sizeof(s_slot_b));
    s_slot_b_len = 0u;
    s_slot_b_present = false;
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
    return ((slot == WDC_BUNDLE_SLOT_A && s_slot_a_present) ||
            (slot == WDC_BUNDLE_SLOT_B && s_slot_b_present)) &&
                   *image_len > 0u
               ? WDC_OK
               : WDC_ERR_NOT_AVAILABLE;
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

int32_t wdc_ota_read_slot_range(WdcBundleSlotId slot,
                                uint32_t offset,
                                uint8_t *buffer,
                                uint32_t length)
{
    const uint8_t *image = NULL;
    uint32_t image_len = 0u;
    int32_t status;
    if (buffer == NULL || length == 0u) {
        return WDC_ERR_BAD_POINTER;
    }
    status = slot_image(slot, &image, &image_len);
    if (status != WDC_OK) {
        return status;
    }
    if (offset > image_len || length > image_len - offset) {
        return WDC_ERR_BAD_LENGTH;
    }
    memcpy(buffer, image + offset, length);
    return WDC_OK;
}

int32_t wdc_ota_slot_capacity_bytes(WdcBundleSlotId slot,
                                    uint32_t *out_capacity)
{
    if (out_capacity == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    if (slot != WDC_BUNDLE_SLOT_A && slot != WDC_BUNDLE_SLOT_B) {
        *out_capacity = 0u;
        return WDC_ERR_INVALID_RESOURCE;
    }
    *out_capacity = WDC_OTA_HOST_SLOT_CAPACITY_BYTES;
    return WDC_OK;
}

int32_t wdc_ota_stage_begin(WdcOtaStageSession *session,
                            WdcBundleSlotId slot,
                            uint32_t expected_bytes)
{
    uint8_t *target;
    uint32_t tear_after = 0u;
    if (session == NULL || expected_bytes == 0u) {
        return WDC_ERR_BAD_POINTER;
    }
    if ((slot != WDC_BUNDLE_SLOT_A && slot != WDC_BUNDLE_SLOT_B) ||
        expected_bytes > WDC_OTA_HOST_SLOT_CAPACITY_BYTES) {
        return WDC_ERR_BAD_LENGTH;
    }
    memset(session, 0, sizeof(*session));
    target = slot == WDC_BUNDLE_SLOT_A ? s_slot_a : s_slot_b;
    if (host_fault_take(WDC_OTA_HOST_FAULT_SLOT_ERASE,
                        WDC_OTA_HOST_SLOT_CAPACITY_BYTES,
                        &tear_after)) {
        memset(target, 0xff, tear_after);
        return WDC_ERR_IO;
    }
    memset(target, 0xff, WDC_OTA_HOST_SLOT_CAPACITY_BYTES);
    if (slot == WDC_BUNDLE_SLOT_A) {
        s_slot_a_len = 0u;
        s_slot_a_present = false;
    } else {
        s_slot_b_len = 0u;
        s_slot_b_present = false;
    }
    session->slot = slot;
    session->expected_bytes = expected_bytes;
    session->active = 1u;
    return WDC_OK;
}

int32_t wdc_ota_stage_write(WdcOtaStageSession *session,
                            const uint8_t *bytes,
                            uint32_t length)
{
    uint8_t *target;
    uint32_t tear_after = 0u;
    if (session == NULL || bytes == NULL || length == 0u) {
        return WDC_ERR_BAD_POINTER;
    }
    if (session->active != 1u ||
        session->written_bytes > session->expected_bytes ||
        length > session->expected_bytes - session->written_bytes) {
        return WDC_ERR_INVALID_STATE;
    }
    target = session->slot == WDC_BUNDLE_SLOT_A ? s_slot_a : s_slot_b;
    if (host_fault_take(WDC_OTA_HOST_FAULT_SLOT_WRITE,
                        length,
                        &tear_after)) {
        memcpy(target + session->written_bytes, bytes, tear_after);
        session->written_bytes += tear_after;
        if (session->slot == WDC_BUNDLE_SLOT_A) {
            s_slot_a_len = session->written_bytes;
            s_slot_a_present = session->written_bytes != 0u;
        } else {
            s_slot_b_len = session->written_bytes;
            s_slot_b_present = session->written_bytes != 0u;
        }
        session->active = 0u;
        return WDC_ERR_IO;
    }
    memcpy(target + session->written_bytes, bytes, length);
    session->written_bytes += length;
    if (session->slot == WDC_BUNDLE_SLOT_A) {
        s_slot_a_len = session->written_bytes;
        s_slot_a_present = true;
    } else {
        s_slot_b_len = session->written_bytes;
        s_slot_b_present = true;
    }
    return WDC_OK;
}

int32_t wdc_ota_stage_finish(WdcOtaStageSession *session)
{
    if (session == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    if (session->active != 1u ||
        session->written_bytes != session->expected_bytes) {
        return WDC_ERR_INVALID_STATE;
    }
    if (session->slot == WDC_BUNDLE_SLOT_A) {
        s_slot_a_len = session->expected_bytes;
        s_slot_a_present = true;
    } else if (session->slot == WDC_BUNDLE_SLOT_B) {
        s_slot_b_len = session->expected_bytes;
        s_slot_b_present = true;
    } else {
        return WDC_ERR_INVALID_RESOURCE;
    }
    session->active = 0u;
    return WDC_OK;
}

int32_t wdc_ota_stage_abort(WdcOtaStageSession *session)
{
    if (session == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    if (session->slot == WDC_BUNDLE_SLOT_A) {
        s_slot_a_len = 0u;
        s_slot_a_present = false;
    } else if (session->slot == WDC_BUNDLE_SLOT_B) {
        s_slot_b_len = 0u;
        s_slot_b_present = false;
    }
    session->active = 0u;
    return WDC_OK;
}
#endif
