#pragma once

#include <stdint.h>

#include "wdc_extension.h"

/* Private HX3 seams. None of these symbols belongs to the Pulse ABI. */
void wdc_extension_platform_profile_imports(WdcExtensionProfile *profile);
uint64_t wdc_extension_platform_monotonic_ms(void);

int32_t wdc_extension_services_bind(WdcExtensionRegistry *registry);
void wdc_extension_services_unbind(WdcExtensionRegistry *registry);
WdcExtensionRegistry *wdc_extension_services_registry(void);

typedef struct WdcExtensionCompletionResult {
    int32_t status;
    uint64_t correlation_id;
    uint64_t started_ms;
    uint64_t completed_ms;
    uint32_t payload_len;
    uint8_t payload[WDC_EXTENSION_EFFECT_PAYLOAD_MAX];
} WdcExtensionCompletionResult;

int32_t wdc_extension_services_begin_effect(
    WdcExtensionCandidate *candidate,
    uint64_t correlation_id,
    uint64_t deadline_ms);
/* OK=completed, NOT_READY=active, TIMEOUT=expired, STATE=canceled/stale. */
int32_t wdc_extension_services_take_effect(
    WdcExtensionCandidate *candidate,
    uint64_t correlation_id,
    WdcExtensionCompletionResult *out_result);
int32_t wdc_extension_services_timeout_effect(
    WdcExtensionCandidate *candidate,
    uint64_t correlation_id);
int32_t wdc_extension_services_release_effect(
    WdcExtensionCandidate *candidate,
    uint64_t correlation_id);
void wdc_extension_services_cancel_candidate_effects(
    WdcExtensionCandidate *candidate);

#ifdef PULSE_EXTENSION_HOST_TEST
void wdc_extension_services_set_test_caller(WdcExtensionCandidate *candidate);

/*
 * HX5a deterministic, one-shot fault injection. These seams are compiled only
 * into host contract tests and are not part of the Pulse extension ABI.
 */
typedef enum WdcExtensionTestFaultPoint {
    WDC_EXTENSION_TEST_FAULT_NONE = 0,
    WDC_EXTENSION_TEST_FAULT_SERVICES_BIND_RETURN = 1,
    WDC_EXTENSION_TEST_FAULT_INIT_RETURN = 2,
    WDC_EXTENSION_TEST_FAULT_START_RETURN = 3,
    WDC_EXTENSION_TEST_FAULT_HEALTH_RETURN = 4,
    WDC_EXTENSION_TEST_FAULT_INVOKE_RETURN = 5,
    WDC_EXTENSION_TEST_FAULT_QUIESCE_RETURN = 6,
    WDC_EXTENSION_TEST_FAULT_QUIESCE_HEALTH_RETURN = 7,
    WDC_EXTENSION_TEST_FAULT_DEINIT_RETURN = 8,
    WDC_EXTENSION_TEST_FAULT_UNLOAD_RETURN = 9,
} WdcExtensionTestFaultPoint;

int32_t wdc_extension_test_fault_arm(
    WdcExtensionTestFaultPoint point,
    uint32_t occurrence);
void wdc_extension_test_fault_clear(void);
uint32_t wdc_extension_test_fault_fired(void);
#endif

int32_t wdc_extension_record_service_health(
    WdcExtensionCandidate *candidate,
    const pulse_extension_health_v1 *health);
void wdc_extension_record_service_fault(
    WdcExtensionCandidate *candidate,
    int32_t status,
    uint32_t fault_code);
