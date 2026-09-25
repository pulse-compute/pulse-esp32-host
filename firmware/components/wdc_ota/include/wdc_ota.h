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
#define WDC_OTA_HOST_SLOT_CAPACITY_BYTES (2u * 1024u * 1024u)

typedef struct WdcOtaStageSession {
    WdcBundleSlotId slot;
    uint32_t expected_bytes;
    uint32_t written_bytes;
    uint32_t active;
} WdcOtaStageSession;

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
int32_t wdc_ota_read_slot_range(WdcBundleSlotId slot,
                                uint32_t offset,
                                uint8_t *buffer,
                                uint32_t length);
int32_t wdc_ota_slot_capacity_bytes(WdcBundleSlotId slot,
                                    uint32_t *out_capacity);
int32_t wdc_ota_stage_begin(WdcOtaStageSession *session,
                            WdcBundleSlotId slot,
                            uint32_t expected_bytes);
int32_t wdc_ota_stage_write(WdcOtaStageSession *session,
                            const uint8_t *bytes,
                            uint32_t length);
int32_t wdc_ota_stage_finish(WdcOtaStageSession *session);
int32_t wdc_ota_stage_abort(WdcOtaStageSession *session);

int32_t wdc_ota_read_metadata(WdcBundleMetadataV1 *out_metadata);
int32_t wdc_ota_write_metadata(const WdcBundleMetadataV1 *metadata);
int32_t wdc_ota_metadata_journal_record_validate(const WdcOtaMetadataJournalRecord *record);

#ifndef ESP_PLATFORM
typedef enum WdcOtaHostFaultOperation {
    WDC_OTA_HOST_FAULT_NONE = 0,
    WDC_OTA_HOST_FAULT_SLOT_ERASE = 1,
    WDC_OTA_HOST_FAULT_SLOT_WRITE = 2,
    WDC_OTA_HOST_FAULT_METADATA_ERASE = 3,
    WDC_OTA_HOST_FAULT_METADATA_BODY_WRITE = 4,
    WDC_OTA_HOST_FAULT_METADATA_MARKER_WRITE = 5
} WdcOtaHostFaultOperation;

typedef struct WdcOtaHostFaultPlan {
    WdcOtaHostFaultOperation operation;
    uint32_t trigger_index;
    uint32_t tear_after_bytes;
} WdcOtaHostFaultPlan;

int32_t wdc_ota_host_set_metadata(const WdcBundleMetadataV1 *metadata);
void wdc_ota_host_clear_metadata(void);
uint32_t wdc_ota_host_metadata_write_count(void);
uint32_t wdc_ota_host_metadata_valid_record_count(void);
int32_t wdc_ota_host_corrupt_metadata_record(uint32_t index);
int32_t wdc_ota_host_clear_metadata_record(uint32_t index);
int32_t wdc_ota_host_set_slot_image(WdcBundleSlotId slot, const uint8_t *image, uint32_t image_len);
void wdc_ota_host_clear_slots(void);
int32_t wdc_ota_host_fault_arm(const WdcOtaHostFaultPlan *plan);
void wdc_ota_host_fault_clear(void);
void wdc_ota_host_power_cycle(void);
uint32_t wdc_ota_host_fault_observation_count(void);
uint32_t wdc_ota_host_fault_trigger_count(void);
uint32_t wdc_ota_host_metadata_record_bytes(void);
uint32_t wdc_ota_host_metadata_body_bytes(void);
uint32_t wdc_ota_host_metadata_marker_bytes(void);
#endif

#ifdef __cplusplus
}
#endif
