#include "wdc_diag.h"

#include <stdbool.h>
#include <stdio.h>
#include <string.h>

#ifdef ESP_PLATFORM
#include "esp_log.h"
#include "esp_system.h"
#include "esp_timer.h"
#endif

static WdcDiagRecord s_ring[WDC_DIAG_RING_CAPACITY];
static size_t s_head;
static size_t s_count;
static uint32_t s_next_seq;
static uint32_t s_dropped;
static uint32_t s_boot_count;
static uint32_t s_fault_count;
static uint32_t s_last_reset_reason;
static WdcDiagResetClass s_last_reset_class;
static WdcDiagBreadcrumb s_breadcrumb;
static bool s_breadcrumb_present;
static bool s_initialized;

#ifdef ESP_PLATFORM
static const char *TAG = "wdc_diag";
#endif

static uint64_t wdc_diag_now_ms(void)
{
#ifdef ESP_PLATFORM
    return (uint64_t)(esp_timer_get_time() / 1000LL);
#else
    return 0u;
#endif
}

static const char *wdc_log_level_name(int32_t level)
{
    switch (level) {
    case WDC_LOG_DEBUG: return "debug";
    case WDC_LOG_INFO: return "info";
    case WDC_LOG_WARN: return "warn";
    case WDC_LOG_ERROR: return "error";
    default: return "unknown";
    }
}

int32_t wdc_diag_init(void)
{
    memset(s_ring, 0, sizeof(s_ring));
    s_head = 0u;
    s_count = 0u;
    s_next_seq = 1u;
    s_dropped = 0u;
    s_boot_count = 0u;
    s_fault_count = 0u;
    s_last_reset_reason = 0u;
    s_last_reset_class = WDC_DIAG_RESET_UNKNOWN;
    memset(&s_breadcrumb, 0, sizeof(s_breadcrumb));
    s_breadcrumb_present = false;
    s_initialized = true;
    return WDC_OK;
}

int32_t wdc_diag_log(int32_t level, const char *message)
{
    if (!s_initialized) {
        (void)wdc_diag_init();
    }
    if (message == NULL) {
        message = "";
    }

    size_t slot;
    if (s_count < WDC_DIAG_RING_CAPACITY) {
        slot = (s_head + s_count) % WDC_DIAG_RING_CAPACITY;
        s_count++;
    } else {
        slot = s_head;
        s_head = (s_head + 1u) % WDC_DIAG_RING_CAPACITY;
        s_dropped++;
    }

    WdcDiagRecord *record = &s_ring[slot];
    record->seq = s_next_seq++;
    record->timestamp_ms = wdc_diag_now_ms();
    record->level = level;
    (void)snprintf(record->message, sizeof(record->message), "%s", message);

    if (level == WDC_LOG_ERROR) {
        s_fault_count++;
    }

    const char *level_name = wdc_log_level_name(level);
    (void)level_name;

#ifdef ESP_PLATFORM
    switch (level) {
    case WDC_LOG_DEBUG:
        ESP_LOGD(TAG, "%s", record->message);
        break;
    case WDC_LOG_WARN:
        ESP_LOGW(TAG, "%s", record->message);
        break;
    case WDC_LOG_ERROR:
        ESP_LOGE(TAG, "%s", record->message);
        break;
    case WDC_LOG_INFO:
    default:
        ESP_LOGI(TAG, "%s", record->message);
        break;
    }
#else
    (void)level_name;
#endif

    return WDC_OK;
}

void wdc_diag_note_boot(uint32_t reset_reason, const char *reset_name)
{
    if (!s_initialized) {
        (void)wdc_diag_init();
    }
    s_boot_count++;
    s_last_reset_reason = reset_reason;
    s_last_reset_class = wdc_diag_classify_reset(reset_reason);

    char msg[WDC_DIAG_MESSAGE_MAX];
    if (reset_name == NULL) {
        reset_name = "unknown";
    }
    (void)snprintf(msg, sizeof(msg), "boot #%lu reset=%s(%lu)",
                   (unsigned long)s_boot_count,
                   reset_name,
                   (unsigned long)reset_reason);
    (void)wdc_diag_log(WDC_LOG_INFO, msg);
}

size_t wdc_diag_count(void)
{
    return s_count;
}

int32_t wdc_diag_get(size_t index, WdcDiagRecord *out)
{
    if (out == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    if (index >= s_count) {
        return WDC_ERR_BAD_LENGTH;
    }
    size_t slot = (s_head + index) % WDC_DIAG_RING_CAPACITY;
    *out = s_ring[slot];
    return WDC_OK;
}

void wdc_diag_get_metrics(WdcDiagMetrics *out)
{
    if (out == NULL) {
        return;
    }
    out->boot_count = s_boot_count;
    out->fault_count = s_fault_count;
    out->ring_count = (uint32_t)s_count;
    out->ring_capacity = WDC_DIAG_RING_CAPACITY;
    out->dropped_logs = s_dropped;
    out->last_reset_reason = s_last_reset_reason;
    out->last_reset_class = s_last_reset_class;
    out->breadcrumb_present = s_breadcrumb_present;
    out->breadcrumb_generation = s_breadcrumb.generation;
}

WdcDiagResetClass wdc_diag_classify_reset(uint32_t reason)
{
#ifdef ESP_PLATFORM
    switch (reason) {
    case 1u: return WDC_DIAG_RESET_POWER;
    case 3u: return WDC_DIAG_RESET_SOFTWARE;
    case 4u: return WDC_DIAG_RESET_PANIC;
    case 7u:
    case 8u:
    case 9u: return WDC_DIAG_RESET_WATCHDOG;
    case 10u: return WDC_DIAG_RESET_BROWNOUT;
    default: return WDC_DIAG_RESET_UNKNOWN;
    }
#else
    switch (reason) {
    case 1u: return WDC_DIAG_RESET_POWER;
    case 3u: return WDC_DIAG_RESET_SOFTWARE;
    case 7u:
    case 8u:
    case 9u:
    case 100u: return WDC_DIAG_RESET_WATCHDOG;
    default: return WDC_DIAG_RESET_UNKNOWN;
    }
#endif
}

const char *wdc_diag_reset_class_name(WdcDiagResetClass reset_class)
{
    switch (reset_class) {
    case WDC_DIAG_RESET_POWER: return "power";
    case WDC_DIAG_RESET_SOFTWARE: return "software";
    case WDC_DIAG_RESET_WATCHDOG: return "watchdog";
    case WDC_DIAG_RESET_PANIC: return "panic";
    case WDC_DIAG_RESET_BROWNOUT: return "brownout";
    case WDC_DIAG_RESET_UNKNOWN:
    default: return "unknown";
    }
}

void wdc_diag_record_breadcrumb(int32_t safety_state,
                                int32_t fault_kind,
                                int32_t fault_status,
                                int32_t runtime_outcome,
                                const char *bundle,
                                uint32_t bundle_version,
                                const char *reason)
{
    if (!s_initialized) {
        (void)wdc_diag_init();
    }
    uint32_t next_generation = s_breadcrumb.generation + 1u;
    memset(&s_breadcrumb, 0, sizeof(s_breadcrumb));
    s_breadcrumb.magic = WDC_DIAG_BREADCRUMB_MAGIC;
    s_breadcrumb.generation = next_generation == 0u ? 1u : next_generation;
    s_breadcrumb.reset_reason = s_last_reset_reason;
    s_breadcrumb.reset_class = s_last_reset_class;
    s_breadcrumb.safety_state = safety_state;
    s_breadcrumb.fault_kind = fault_kind;
    s_breadcrumb.fault_status = fault_status;
    s_breadcrumb.runtime_outcome = runtime_outcome;
    s_breadcrumb.bundle_version = bundle_version;
    (void)snprintf(s_breadcrumb.bundle, sizeof(s_breadcrumb.bundle), "%s", bundle != NULL ? bundle : "");
    (void)snprintf(s_breadcrumb.reason, sizeof(s_breadcrumb.reason), "%s", reason != NULL ? reason : "");
    s_breadcrumb_present = true;
}

bool wdc_diag_get_breadcrumb(WdcDiagBreadcrumb *out)
{
    if (!s_breadcrumb_present) {
        return false;
    }
    if (out != NULL) {
        *out = s_breadcrumb;
    }
    return true;
}

int32_t wdc_diag_export_json(char *out, uint32_t out_cap, uint32_t *out_len)
{
    if (out_len != NULL) { *out_len = 0u; }
    if (out == NULL || out_cap == 0u) { return WDC_ERR_BAD_POINTER; }
    WdcDiagMetrics metrics;
    wdc_diag_get_metrics(&metrics);
    int written = snprintf(out, out_cap,
                           "{\"boot_count\":%lu,\"fault_count\":%lu,\"dropped_logs\":%lu,\"last_reset_class\":\"%s\",\"breadcrumb_present\":%s,\"breadcrumb_generation\":%lu}",
                           (unsigned long)metrics.boot_count,
                           (unsigned long)metrics.fault_count,
                           (unsigned long)metrics.dropped_logs,
                           wdc_diag_reset_class_name(metrics.last_reset_class),
                           metrics.breadcrumb_present ? "true" : "false",
                           (unsigned long)metrics.breadcrumb_generation);
    if (written < 0) { return WDC_ERR_BAD_ENCODING; }
    if ((uint32_t)written >= out_cap) { return WDC_ERR_RESPONSE_TOO_SMALL; }
    if (out_len != NULL) { *out_len = (uint32_t)written; }
    return WDC_OK;
}

const char *wdc_reset_reason_name(int32_t reason)
{
#ifdef ESP_PLATFORM
    switch ((esp_reset_reason_t)reason) {
    case ESP_RST_POWERON: return "poweron";
    case ESP_RST_EXT: return "external";
    case ESP_RST_SW: return "software";
    case ESP_RST_PANIC: return "panic";
    case ESP_RST_INT_WDT: return "interrupt_wdt";
    case ESP_RST_TASK_WDT: return "task_wdt";
    case ESP_RST_WDT: return "watchdog";
    case ESP_RST_DEEPSLEEP: return "deepsleep";
    case ESP_RST_BROWNOUT: return "brownout";
    case ESP_RST_SDIO: return "sdio";
    default: return "unknown";
    }
#else
    switch (reason) {
    case 0: return "unknown";
    case 1: return "poweron";
    case 2: return "external";
    case 3: return "software";
    default: return "unknown";
    }
#endif
}
