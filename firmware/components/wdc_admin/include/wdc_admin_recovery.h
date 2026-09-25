#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "wdc_admin_update.h"

#ifdef __cplusplus
extern "C" {
#endif

#define WDC_ADMIN_RECOVERY_STATUS_BYTES 64u
#define WDC_ADMIN_RECOVERY_RESERVE_BYTES 16384u

typedef enum WdcAdminRecoveryReason {
    WDC_ADMIN_RECOVERY_REASON_NONE = 0,
    WDC_ADMIN_RECOVERY_REASON_NO_VIABLE_APPLICATION = 1,
    WDC_ADMIN_RECOVERY_REASON_ADMINISTRATIVE_TRIGGER = 2,
} WdcAdminRecoveryReason;

/* Fixed, secret-free STATUS payload. */
typedef struct WdcAdminRecoveryStatus {
    uint32_t struct_size;
    uint16_t version_major;
    uint16_t version_minor;
    uint32_t mode;
    uint32_t recovery_reason;
    uint32_t update_state;
    uint32_t active_slot;
    uint32_t last_good_slot;
    uint32_t slot_a_state;
    uint32_t slot_b_state;
    uint32_t application_loaded;
    uint32_t native_refinements_loaded;
    uint32_t recovery_required;
    uint32_t audit_loss_count;
    uint32_t metadata_generation;
    uint32_t enabled_commands_mask;
    uint32_t flags;
} WdcAdminRecoveryStatus;

typedef struct WdcAdminRecoveryConfig {
    WdcAdminUpdateConfig update;
    /* Required only when the administration core starts in RECOVERY. */
    const WdcAppSlotBootResult *boot_result;
    uint32_t application_loaded;
    uint32_t native_refinements_loaded;
} WdcAdminRecoveryConfig;

typedef struct WdcAdminRecoveryEngine {
    WdcAdminUpdateEngine update;
    WdcAdminRecoveryReason reason;
    uint32_t application_loaded;
    uint32_t native_refinements_loaded;
    bool initialized;
} WdcAdminRecoveryEngine;

int32_t wdc_admin_recovery_init(WdcAdminRecoveryEngine *engine,
                                const WdcAdminRecoveryConfig *config,
                                uint64_t now_ms);

/* Executes one already accepted HP4.3 command and writes one terminal. */
int32_t wdc_admin_recovery_execute(WdcAdminRecoveryEngine *engine,
                                   const WdcAdminAcceptedCommand *command,
                                   uint64_t now_ms);

int32_t wdc_admin_recovery_poll(WdcAdminRecoveryEngine *engine,
                                uint64_t now_ms);

WdcAdminRecoveryReason wdc_admin_recovery_reason(
    const WdcAdminRecoveryEngine *engine);
uint32_t wdc_admin_recovery_static_bytes(void);

/* Side-effect-free firmware link anchor. */
uint32_t wdc_admin_recovery_link_anchor(void);

#ifdef __cplusplus
}
#endif
