#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "wdc_abi.h"

#ifdef __cplusplus
extern "C" {
#endif

#define WDC_DIAG_RING_CAPACITY 32u
#define WDC_DIAG_MESSAGE_MAX   96u
#define WDC_DIAG_EXPORT_JSON_MAX 512u
#define WDC_DIAG_BREADCRUMB_MAGIC 0x57444642u /* WDFB */

typedef struct WdcDiagRecord {
    uint32_t seq;
    uint64_t timestamp_ms;
    int32_t level;
    char message[WDC_DIAG_MESSAGE_MAX];
} WdcDiagRecord;

typedef enum WdcDiagResetClass {
    WDC_DIAG_RESET_UNKNOWN = 0,
    WDC_DIAG_RESET_POWER = 1,
    WDC_DIAG_RESET_SOFTWARE = 2,
    WDC_DIAG_RESET_WATCHDOG = 3,
    WDC_DIAG_RESET_PANIC = 4,
    WDC_DIAG_RESET_BROWNOUT = 5,
} WdcDiagResetClass;

typedef struct WdcDiagBreadcrumb {
    uint32_t magic;
    uint32_t generation;
    uint32_t reset_reason;
    WdcDiagResetClass reset_class;
    int32_t safety_state;
    int32_t fault_kind;
    int32_t fault_status;
    int32_t runtime_outcome;
    uint32_t bundle_version;
    char bundle[80];
    char reason[WDC_DIAG_MESSAGE_MAX];
} WdcDiagBreadcrumb;

typedef struct WdcDiagMetrics {
    uint32_t boot_count;
    uint32_t fault_count;
    uint32_t ring_count;
    uint32_t ring_capacity;
    uint32_t dropped_logs;
    uint32_t last_reset_reason;
    WdcDiagResetClass last_reset_class;
    uint32_t breadcrumb_generation;
    bool breadcrumb_present;
} WdcDiagMetrics;

int32_t wdc_diag_init(void);
void wdc_diag_note_boot(uint32_t reset_reason, const char *reset_name);
int32_t wdc_diag_log(int32_t level, const char *message);
size_t wdc_diag_count(void);
int32_t wdc_diag_get(size_t index, WdcDiagRecord *out);
void wdc_diag_get_metrics(WdcDiagMetrics *out);
WdcDiagResetClass wdc_diag_classify_reset(uint32_t reason);
const char *wdc_diag_reset_class_name(WdcDiagResetClass reset_class);
void wdc_diag_record_breadcrumb(int32_t safety_state,
                                int32_t fault_kind,
                                int32_t fault_status,
                                int32_t runtime_outcome,
                                const char *bundle,
                                uint32_t bundle_version,
                                const char *reason);
bool wdc_diag_get_breadcrumb(WdcDiagBreadcrumb *out);
int32_t wdc_diag_export_json(char *out, uint32_t out_cap, uint32_t *out_len);
const char *wdc_reset_reason_name(int32_t reason);

#ifdef __cplusplus
}
#endif
