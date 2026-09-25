#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "wdc_admin.h"
#include "wdc_app_slots.h"

#ifdef __cplusplus
extern "C" {
#endif

#define WDC_ADMIN_UPDATE_WORKING_BYTES 65536u
#define WDC_ADMIN_UPDATE_LARGEST_ALLOCATION_BYTES 65536u
#define WDC_ADMIN_UPDATE_MAX_CHUNK_BYTES 1024u
#define WDC_ADMIN_UPDATE_QUIESCE_DEADLINE_MS 10000u
#define WDC_ADMIN_UPDATE_STREAM_IDLE_DEADLINE_MS 30000u
#define WDC_ADMIN_UPDATE_TRANSACTION_DEADLINE_MS 900000u
#define WDC_ADMIN_UPDATE_RATE_WINDOW_MS 1000u
#define WDC_ADMIN_UPDATE_RATE_CHUNKS_PER_WINDOW 64u
#define WDC_ADMIN_UPDATE_RATE_BYTES_PER_WINDOW 65536u

typedef enum WdcAdminUpdateState {
    WDC_ADMIN_UPDATE_STATE_NONE = 0,
    WDC_ADMIN_UPDATE_STATE_IDLE = 1,
    WDC_ADMIN_UPDATE_STATE_QUIESCING = 2,
    WDC_ADMIN_UPDATE_STATE_STREAMING = 3,
    WDC_ADMIN_UPDATE_STATE_VERIFIED = 4,
    WDC_ADMIN_UPDATE_STATE_REBOOT_HANDOFF = 5,
} WdcAdminUpdateState;

/* Positive, host-private proof returned only after ordered lifecycle work. */
typedef struct WdcAdminUpdateQuiesceEvidence {
    uint32_t guest_quiesced;
    uint32_t native_refinements_quiesced;
    uint32_t guest_unloaded;
    uint32_t native_refinements_unloaded;
    uint32_t guest_loaded_after;
    uint32_t native_refinements_loaded_after;
    uint32_t flags;
    uint32_t reserved;
    uint64_t completed_monotonic_ms;
} WdcAdminUpdateQuiesceEvidence;

typedef int32_t (*WdcAdminUpdateQuiesceFn)(
    void *context,
    uint64_t deadline_ms,
    WdcAdminUpdateQuiesceEvidence *out_evidence);

typedef int32_t (*WdcAdminUpdateHeapSnapshotFn)(
    void *context,
    WdcControlHeapSnapshot *out_heap);

typedef struct WdcAdminUpdateLifecycle {
    WdcAdminUpdateQuiesceFn quiesce_and_unload;
    WdcAdminUpdateHeapSnapshotFn heap_snapshot_after_unload;
    void *context;
} WdcAdminUpdateLifecycle;

typedef struct WdcAdminUpdateConfig {
    WdcAdminCore *core;
    WdcBundleMetadataV1 *metadata;
    const WdcHostFingerprintV1 *running_host_fingerprint;
    const WdcAppSlotVerifyPolicy *slot_verify_policy;
    const WdcActivationPolicy *activation_policy;
    WdcAdminUpdateLifecycle lifecycle;
    uint8_t *working_buffer;
    uint32_t working_buffer_bytes;
} WdcAdminUpdateConfig;

typedef struct WdcAdminUpdateEngine {
    WdcAdminCore *core;
    WdcBundleMetadataV1 *metadata;
    WdcHostFingerprintV1 running_host_fingerprint;
    WdcBundleVerifyPolicy bundle_verify_policy;
    WdcAppSlotVerifyPolicy slot_verify_policy;
    WdcActivationPolicy activation_policy;
    WdcAdminUpdateLifecycle lifecycle;
    uint8_t *working_buffer;
    WdcAppSlotStageSession stage;
    WdcAppSlotStageResult stage_result;
    WdcControlAdmissionDecision admission;
    WdcBundleSlotRecord last_confirmed_record;
    WdcAdminUpdateState state;
    WdcBundleSlotId target_slot;
    WdcBundleSlotId authority_active_slot;
    WdcBundleSlotId authority_last_good_slot;
    uint32_t expected_total_bytes;
    uint32_t streamed_bytes;
    uint32_t metadata_commits;
    uint32_t rate_window_chunks;
    uint32_t rate_window_bytes;
    uint64_t transaction_deadline_ms;
    uint64_t stream_idle_deadline_ms;
    uint64_t rate_window_start_ms;
    uint8_t expected_artifact_sha256[32];
    bool initialized;
    bool staging_active;
    bool verification_complete;
    bool recovery_origin;
} WdcAdminUpdateEngine;

int32_t wdc_admin_update_init(WdcAdminUpdateEngine *engine,
                              const WdcAdminUpdateConfig *config);

/* Executes one already accepted HP4.2 update command and writes one terminal. */
int32_t wdc_admin_update_execute(WdcAdminUpdateEngine *engine,
                                 const WdcAdminAcceptedCommand *command,
                                 uint64_t now_ms);

/* Enforces the cross-command stream-idle and transaction deadlines. */
int32_t wdc_admin_update_poll(WdcAdminUpdateEngine *engine,
                              uint64_t now_ms);

/* Changes the idle return mode after HP4.3 enters host-only recovery. */
int32_t wdc_admin_update_set_idle_mode(WdcAdminUpdateEngine *engine,
                                       WdcAdminMode mode);

WdcAdminUpdateState wdc_admin_update_state(
    const WdcAdminUpdateEngine *engine);
uint32_t wdc_admin_update_static_bytes(void);

/* Side-effect-free firmware link anchor. */
uint32_t wdc_admin_update_link_anchor(void);

#ifdef __cplusplus
}
#endif
