#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "wdc_abi.h"
#include "wdc_caps.h"
#include "wdc_profile.h"
#include "wdc_runtime.h"

#ifdef __cplusplus
extern "C" {
#endif

#define WDC_SAFETY_REASON_MAX 80u
#define WDC_SAFETY_BUNDLE_MAX 80u

typedef enum WdcSafetyState {
    WDC_SAFETY_STATE_UNINITIALIZED = 0,
    WDC_SAFETY_STATE_BOOT_SAFE = 1,
    WDC_SAFETY_STATE_NO_BUNDLE = 2,
    WDC_SAFETY_STATE_APP_RUNNING = 3,
    WDC_SAFETY_STATE_APP_FAULT_STOPPED = 4,
} WdcSafetyState;

typedef enum WdcSafetyFaultKind {
    WDC_SAFETY_FAULT_NONE = 0,
    WDC_SAFETY_FAULT_NO_BUNDLE = 1,
    WDC_SAFETY_FAULT_RUNTIME_TRAP = 2,
    WDC_SAFETY_FAULT_RUNTIME_NON_OK = 3,
    WDC_SAFETY_FAULT_CONTRACT_VIOLATION = 4,
    WDC_SAFETY_FAULT_HOST_IO = 5,
    WDC_SAFETY_FAULT_MANUAL = 6,
} WdcSafetyFaultKind;

typedef struct WdcSafetyStatus {
    WdcSafetyState state;
    WdcSafetyFaultKind last_fault_kind;
    int32_t last_fault_status;
    WdcRuntimeOutcome last_runtime_outcome;
    uint32_t safe_defaults_applied;
    uint32_t safe_force_count;
    uint32_t fault_count;
    uint32_t denied_while_stopped_count;
    uint32_t denied_by_capability_count;
    uint32_t denied_by_rate_limit_count;
    uint32_t last_fault_event_id;
    bool physical_outputs_safe;
    char active_bundle[WDC_SAFETY_BUNDLE_MAX];
    uint32_t active_bundle_version;
    char last_fault_reason[WDC_SAFETY_REASON_MAX];
} WdcSafetyStatus;

const char *wdc_safety_state_name(WdcSafetyState state);
const char *wdc_safety_fault_name(WdcSafetyFaultKind fault);

int32_t wdc_safety_init(const WdcDeviceProfile *profile);
int32_t wdc_safety_install_guarded_authorizer(const WdcDeviceProfile *profile,
                                              const WdcCapabilitySet *set);
void wdc_safety_clear_guarded_authorizer(void);

int32_t wdc_safety_mark_app_running(const char *bundle_id, uint32_t bundle_version);
int32_t wdc_safety_enter_no_bundle_mode(const char *reason);
int32_t wdc_safety_force_safe_outputs(const char *reason);
int32_t wdc_safety_stop_app(WdcSafetyFaultKind fault,
                            int32_t status,
                            const char *reason,
                            const WdcRuntimeReport *runtime_report);

bool wdc_safety_physical_outputs_safe(void);
void wdc_safety_get_status(WdcSafetyStatus *out_status);
void wdc_safety_reset_for_test(void);

int32_t wdc_safety_authorize_host_call(void *ctx,
                                       uint32_t opcode,
                                       const uint8_t *request,
                                       uint32_t request_len,
                                       int32_t *out_decision_status);

#ifdef __cplusplus
}
#endif
