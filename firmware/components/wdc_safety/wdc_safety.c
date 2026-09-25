#include "wdc_safety.h"

#include <stdio.h>
#include <string.h>

#include "wdc_diag.h"
#include "wdc_events.h"
#include "wdc_gpio.h"

static const WdcDeviceProfile *s_profile;
static WdcCapabilityAuthorizer s_cap_authorizer;
static WdcSafetyStatus s_status;

const char *wdc_safety_state_name(WdcSafetyState state)
{
    switch (state) {
    case WDC_SAFETY_STATE_UNINITIALIZED: return "uninitialized";
    case WDC_SAFETY_STATE_BOOT_SAFE: return "boot_safe";
    case WDC_SAFETY_STATE_NO_BUNDLE: return "no_bundle";
    case WDC_SAFETY_STATE_APP_RUNNING: return "app_running";
    case WDC_SAFETY_STATE_APP_FAULT_STOPPED: return "app_fault_stopped";
    default: return "unknown";
    }
}

const char *wdc_safety_fault_name(WdcSafetyFaultKind fault)
{
    switch (fault) {
    case WDC_SAFETY_FAULT_NONE: return "none";
    case WDC_SAFETY_FAULT_NO_BUNDLE: return "no_bundle";
    case WDC_SAFETY_FAULT_RUNTIME_TRAP: return "runtime_trap";
    case WDC_SAFETY_FAULT_RUNTIME_NON_OK: return "runtime_non_ok";
    case WDC_SAFETY_FAULT_CONTRACT_VIOLATION: return "contract_violation";
    case WDC_SAFETY_FAULT_HOST_IO: return "host_io";
    case WDC_SAFETY_FAULT_MANUAL: return "manual";
    default: return "unknown";
    }
}

static bool opcode_is_effectful_when_stopped(uint32_t opcode)
{
    switch (opcode) {
    case WDC_OP_GPIO_SET:
    case WDC_OP_TIMER_SET:
    case WDC_OP_TIMER_CANCEL:
    case WDC_OP_CONFIG_SET:
    case WDC_OP_CONFIG_DELETE:
    case WDC_OP_MQTT_PUBLISH:
    case WDC_OP_MQTT_SUBSCRIBE:
    case WDC_OP_HTTP_REQUEST:
    case WDC_OP_HTTP_RESPOND:
    case WDC_OP_EFFECT_INVOKE:
    case WDC_OP_BLE_SET_VALUE:
    case WDC_OP_BLE_NOTIFY:
    case WDC_OP_KV_SET:
    case WDC_OP_KV_DELETE:
        return true;
    default:
        return false;
    }
}

static void post_safety_event(uint32_t event_type, uint32_t code)
{
    uint8_t payload[4] = {
        (uint8_t)(code & 0xffu),
        (uint8_t)((code >> 8u) & 0xffu),
        (uint8_t)((code >> 16u) & 0xffu),
        (uint8_t)((code >> 24u) & 0xffu),
    };
    WdcEvent event;
    if (wdc_event_make(&event, event_type, WDC_EVENT_RESOURCE_NONE, 0u, payload, sizeof(payload)) == WDC_OK) {
        int32_t status = wdc_events_post(&event);
        if (status == WDC_OK) {
            s_status.last_fault_event_id = event.event_id;
        }
    }
}

static void log_transition(const char *reason)
{
    char msg[WDC_DIAG_MESSAGE_MAX];
    (void)snprintf(msg, sizeof(msg), "safety state=%s reason=%s outputs_safe=%s",
                   wdc_safety_state_name(s_status.state),
                   reason != NULL ? reason : "",
                   s_status.physical_outputs_safe ? "true" : "false");
    (void)wdc_diag_log(s_status.state == WDC_SAFETY_STATE_APP_FAULT_STOPPED ? WDC_LOG_ERROR : WDC_LOG_INFO, msg);
}

bool wdc_safety_physical_outputs_safe(void)
{
    s_status.physical_outputs_safe = wdc_hal_gpio_outputs_match_safe_levels(s_profile);
    return s_status.physical_outputs_safe;
}

int32_t wdc_safety_force_safe_outputs(const char *reason)
{
    if (s_profile == NULL) {
        return WDC_ERR_INVALID_STATE;
    }
    int32_t status = wdc_hal_apply_safe_gpio_defaults(s_profile);
    if (status != WDC_OK) {
        s_status.last_fault_kind = WDC_SAFETY_FAULT_HOST_IO;
        s_status.last_fault_status = status;
        s_status.physical_outputs_safe = false;
        (void)wdc_diag_log(WDC_LOG_ERROR, "failed to force safe GPIO outputs");
        return status;
    }
    s_status.safe_defaults_applied = wdc_hal_safe_gpio_defaults_applied();
    s_status.safe_force_count++;
    s_status.physical_outputs_safe = wdc_hal_gpio_outputs_match_safe_levels(s_profile);
    if (reason != NULL) {
        char msg[WDC_DIAG_MESSAGE_MAX];
        (void)snprintf(msg, sizeof(msg), "safe GPIO outputs forced: %s", reason);
        (void)wdc_diag_log(WDC_LOG_WARN, msg);
    }
    return WDC_OK;
}

int32_t wdc_safety_init(const WdcDeviceProfile *profile)
{
    if (profile == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    int32_t status = wdc_profile_validate_basic(profile);
    if (status != WDC_OK) {
        return status;
    }
    memset(&s_status, 0, sizeof(s_status));
    memset(&s_cap_authorizer, 0, sizeof(s_cap_authorizer));
    s_profile = profile;
    s_status.state = WDC_SAFETY_STATE_BOOT_SAFE;
    status = wdc_hal_install_host_gpio_bridge(profile);
    if (status != WDC_OK) {
        return status;
    }
    status = wdc_safety_force_safe_outputs("safety init");
    if (status != WDC_OK) {
        return status;
    }
    log_transition("init");
    post_safety_event(WDC_EVENT_SAFETY_STATE_CHANGED, (uint32_t)s_status.state);
    return WDC_OK;
}

int32_t wdc_safety_install_guarded_authorizer(const WdcDeviceProfile *profile,
                                              const WdcCapabilitySet *set)
{
    if (profile == NULL || set == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    if (s_profile == NULL) {
        int32_t status = wdc_safety_init(profile);
        if (status != WDC_OK) {
            return status;
        }
    }
    s_cap_authorizer.profile = profile;
    s_cap_authorizer.capability_set = set;
    wdc_host_call_set_authorizer(wdc_safety_authorize_host_call, &s_cap_authorizer);
    return WDC_OK;
}

void wdc_safety_clear_guarded_authorizer(void)
{
    wdc_host_call_clear_authorizer();
    memset(&s_cap_authorizer, 0, sizeof(s_cap_authorizer));
}

int32_t wdc_safety_mark_app_running(const char *bundle_id, uint32_t bundle_version)
{
    if (s_profile == NULL) {
        return WDC_ERR_INVALID_STATE;
    }
    s_status.state = WDC_SAFETY_STATE_APP_RUNNING;
    s_status.last_fault_kind = WDC_SAFETY_FAULT_NONE;
    s_status.last_fault_status = WDC_OK;
    s_status.last_runtime_outcome = WDC_RUNTIME_OUTCOME_NOT_STARTED;
    s_status.active_bundle_version = bundle_version;
    if (bundle_id == NULL) {
        bundle_id = "<unknown>";
    }
    (void)snprintf(s_status.active_bundle, sizeof(s_status.active_bundle), "%s", bundle_id);
    s_status.physical_outputs_safe = wdc_hal_gpio_outputs_match_safe_levels(s_profile);
    log_transition("app running");
    post_safety_event(WDC_EVENT_SAFETY_STATE_CHANGED, (uint32_t)s_status.state);
    return WDC_OK;
}

int32_t wdc_safety_enter_no_bundle_mode(const char *reason)
{
    int32_t status = wdc_safety_force_safe_outputs(reason != NULL ? reason : "no bundle");
    if (status != WDC_OK) {
        return status;
    }
    s_status.state = WDC_SAFETY_STATE_NO_BUNDLE;
    s_status.last_fault_kind = WDC_SAFETY_FAULT_NO_BUNDLE;
    s_status.last_fault_status = WDC_OK;
    (void)snprintf(s_status.last_fault_reason, sizeof(s_status.last_fault_reason), "%s", reason != NULL ? reason : "no bundle loaded");
    log_transition(reason != NULL ? reason : "no bundle");
    post_safety_event(WDC_EVENT_SAFETY_STATE_CHANGED, (uint32_t)s_status.state);
    return WDC_OK;
}

static WdcSafetyFaultKind fault_from_report(const WdcRuntimeReport *runtime_report, WdcSafetyFaultKind fallback)
{
    if (runtime_report == NULL) {
        return fallback;
    }
    if (runtime_report->outcome == WDC_RUNTIME_OUTCOME_GUEST_TRAPPED) {
        return WDC_SAFETY_FAULT_RUNTIME_TRAP;
    }
    if (runtime_report->outcome == WDC_RUNTIME_OUTCOME_GUEST_NON_OK_STATUS) {
        return WDC_SAFETY_FAULT_RUNTIME_NON_OK;
    }
    if (runtime_report->outcome == WDC_RUNTIME_OUTCOME_INVALID_PAYLOAD || runtime_report->outcome == WDC_RUNTIME_OUTCOME_INVALID_STATE) {
        return WDC_SAFETY_FAULT_CONTRACT_VIOLATION;
    }
    return fallback;
}

int32_t wdc_safety_stop_app(WdcSafetyFaultKind fault,
                            int32_t status,
                            const char *reason,
                            const WdcRuntimeReport *runtime_report)
{
    if (reason == NULL) {
        reason = "app stopped";
    }
    s_status.fault_count++;
    s_status.last_fault_kind = fault_from_report(runtime_report, fault);
    s_status.last_fault_status = status;
    s_status.last_runtime_outcome = runtime_report != NULL ? runtime_report->outcome : WDC_RUNTIME_OUTCOME_NOT_STARTED;
    (void)snprintf(s_status.last_fault_reason, sizeof(s_status.last_fault_reason), "%s", reason);
    wdc_diag_record_breadcrumb((int32_t)WDC_SAFETY_STATE_APP_FAULT_STOPPED,
                               (int32_t)s_status.last_fault_kind,
                               status,
                               (int32_t)s_status.last_runtime_outcome,
                               s_status.active_bundle,
                               s_status.active_bundle_version,
                               reason);

    int32_t safe_status = wdc_safety_force_safe_outputs(reason);
    s_status.state = WDC_SAFETY_STATE_APP_FAULT_STOPPED;
    s_status.physical_outputs_safe = wdc_hal_gpio_outputs_match_safe_levels(s_profile);
    log_transition(reason);
    post_safety_event(WDC_EVENT_FAULT, (uint32_t)s_status.last_fault_kind);
    return safe_status == WDC_OK ? WDC_OK : safe_status;
}

void wdc_safety_get_status(WdcSafetyStatus *out_status)
{
    if (out_status != NULL) {
        s_status.physical_outputs_safe = wdc_hal_gpio_outputs_match_safe_levels(s_profile);
        *out_status = s_status;
    }
}

void wdc_safety_reset_for_test(void)
{
    s_profile = NULL;
    memset(&s_cap_authorizer, 0, sizeof(s_cap_authorizer));
    memset(&s_status, 0, sizeof(s_status));
    wdc_hal_gpio_reset_state_for_test();
    wdc_host_call_clear_authorizer();
}

int32_t wdc_safety_authorize_host_call(void *ctx,
                                       uint32_t opcode,
                                       const uint8_t *request,
                                       uint32_t request_len,
                                       int32_t *out_decision_status)
{
    if (out_decision_status == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    if (opcode_is_effectful_when_stopped(opcode) && s_status.state != WDC_SAFETY_STATE_APP_RUNNING) {
        s_status.denied_while_stopped_count++;
        *out_decision_status = WDC_ERR_INVALID_STATE;
        return WDC_OK;
    }

    int32_t decision = WDC_OK;
    int32_t status = wdc_caps_authorize_host_call(ctx, opcode, request, request_len, &decision);
    if (status != WDC_OK) {
        return status;
    }
    if (decision == WDC_ERR_CAPABILITY_DENIED) {
        s_status.denied_by_capability_count++;
    }
    if (decision == WDC_ERR_RATE_LIMITED) {
        s_status.denied_by_rate_limit_count++;
    }
    *out_decision_status = decision;
    return WDC_OK;
}
