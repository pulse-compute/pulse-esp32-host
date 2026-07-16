#pragma once

#include <stdint.h>
#include "wdc_bundle.h"

#ifdef __cplusplus
extern "C" {
#endif

#define WDC_OTA_SLOT_READ_MAX_BYTES WDC_BUNDLE_DEFAULT_MAX_PAYLOAD_BYTES
#define WDC_OTA_METADATA_RECORD_MAGIC 0x57444a52u /* WDJR */
#define WDC_OTA_METADATA_RECORD_VERSION 1u
#define WDC_OTA_METADATA_COMMIT_MARKER 0xc0defaceu
#define WDC_OTA_METADATA_RECORD_STRIDE_BYTES 4096u
#define WDC_OTA_METADATA_JOURNAL_RECORDS 2u

typedef struct WdcOtaMetadataJournalRecord {
    uint32_t magic;
    uint16_t version;
    uint16_t reserved;
    uint32_t generation;
    WdcBundleMetadataV1 metadata;
    uint32_t record_crc;
    uint32_t commit_marker;
} WdcOtaMetadataJournalRecord;

const char *wdc_ota_slot_partition_label(WdcBundleSlotId slot);
int32_t wdc_ota_read_slot_header(WdcBundleSlotId slot, WdcBundleParsedHeader *out_header);
int32_t wdc_ota_read_slot_to_buffer(WdcBundleSlotId slot,
                                    uint8_t *buffer,
                                    uint32_t buffer_cap,
                                    uint32_t *out_len);

int32_t wdc_ota_read_metadata(WdcBundleMetadataV1 *out_metadata);
int32_t wdc_ota_write_metadata(const WdcBundleMetadataV1 *metadata);
int32_t wdc_ota_metadata_journal_record_validate(const WdcOtaMetadataJournalRecord *record);

#ifndef ESP_PLATFORM
int32_t wdc_ota_host_set_metadata(const WdcBundleMetadataV1 *metadata);
void wdc_ota_host_clear_metadata(void);
uint32_t wdc_ota_host_metadata_write_count(void);
uint32_t wdc_ota_host_metadata_valid_record_count(void);
int32_t wdc_ota_host_corrupt_metadata_record(uint32_t index);
int32_t wdc_ota_host_clear_metadata_record(uint32_t index);
int32_t wdc_ota_host_set_slot_image(WdcBundleSlotId slot, const uint8_t *image, uint32_t image_len);
void wdc_ota_host_clear_slots(void);
#endif

#ifdef __cplusplus
}
#endif
