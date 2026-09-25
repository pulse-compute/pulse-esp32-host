#pragma once

#include <stdint.h>

#include "pulse_extension.h"
#include "wdc_elf.h"

#ifdef __cplusplus
extern "C" {
#endif

#define WDC_EXTENSION_REGISTRY_CAPACITY 4u
#define WDC_EXTENSION_IMPORT_CAPACITY 16u
#define WDC_EXTENSION_EFFECT_PAYLOAD_MAX 256u

typedef enum WdcExtensionStatus {
    WDC_EXTENSION_OK = 0,
    WDC_EXTENSION_ERR_ARGUMENT = -1,
    WDC_EXTENSION_ERR_STRUCTURE = -2,
    WDC_EXTENSION_ERR_TARGET = -3,
    WDC_EXTENSION_ERR_METADATA = -4,
    WDC_EXTENSION_ERR_DIGEST = -5,
    WDC_EXTENSION_ERR_IMPORT = -6,
    WDC_EXTENSION_ERR_RELOCATION = -7,
    WDC_EXTENSION_ERR_CONSTRUCTOR = -8,
    WDC_EXTENSION_ERR_LOADER = -9,
    WDC_EXTENSION_ERR_DESCRIPTOR = -10,
    WDC_EXTENSION_ERR_DUPLICATE = -11,
    WDC_EXTENSION_ERR_STATE = -12,
    WDC_EXTENSION_ERR_BUDGET = -13,
    WDC_EXTENSION_ERR_LIFECYCLE = -14,
    WDC_EXTENSION_ERR_HEALTH = -15,
    WDC_EXTENSION_ERR_TIMEOUT = -16,
    WDC_EXTENSION_ERR_RESET_REQUIRED = -17,
    WDC_EXTENSION_ERR_NOT_READY = -18,
} WdcExtensionStatus;

typedef enum WdcExtensionState {
    WDC_EXTENSION_EMPTY = 0,
    WDC_EXTENSION_INSPECTED = 1,
    WDC_EXTENSION_RELOCATED = 2,
    WDC_EXTENSION_DESCRIPTOR_VALIDATED = 3,
    WDC_EXTENSION_REGISTRY_SEALED = 4,
    WDC_EXTENSION_INITIALIZING = 5,
    WDC_EXTENSION_INITIALIZED = 6,
    WDC_EXTENSION_STARTING = 7,
    WDC_EXTENSION_STARTED = 8,
    WDC_EXTENSION_QUIESCING = 9,
    WDC_EXTENSION_QUIESCED = 10,
    WDC_EXTENSION_DEINITIALIZED = 11,
    WDC_EXTENSION_RESET_REQUIRED = 12,
} WdcExtensionState;

#define WDC_EXTENSION_FAULT_INIT 0x48583301u
#define WDC_EXTENSION_FAULT_START 0x48583302u
#define WDC_EXTENSION_FAULT_HEALTH 0x48583303u
#define WDC_EXTENSION_FAULT_QUIESCE 0x48583304u
#define WDC_EXTENSION_FAULT_DEINIT 0x48583305u
#define WDC_EXTENSION_FAULT_HOST_SERVICE 0x48583306u
#define WDC_EXTENSION_FAULT_UNLOAD 0x48583501u

typedef struct WdcExtensionProfile {
    uint16_t elf_machine;
    uint16_t architecture_id;
    uint16_t soc_id;
    uint16_t host_abi_major;
    uint16_t host_abi_minor;
    uint16_t reserved0;
    uint32_t max_task_stack_bytes;
    uint32_t max_static_memory_bytes;
    uint32_t max_queue_depth;
    uint32_t max_queue_item_bytes;
    uint32_t max_queue_storage_bytes;
    uint32_t max_event_payload_bytes;
    uint32_t max_effect_request_bytes;
    uint32_t max_effect_completion_bytes;
    const char *const *allowed_imports;
    const uint32_t *allowed_import_addresses;
    uint32_t allowed_import_count;
} WdcExtensionProfile;

typedef struct WdcExtensionInspection {
    pulse_extension_metadata_v1 metadata;
    uint8_t raw_sha256[32];
    uint8_t normalized_artifact_sha256[32];
    uint8_t normalized_metadata_sha256[32];
    uint32_t raw_size;
    uint32_t metadata_file_offset;
    uint32_t entry_virtual_address;
    uint32_t import_count;
    uint32_t relocation_count;
    WdcElfResolvedSymbol imports[WDC_EXTENSION_IMPORT_CAPACITY];
} WdcExtensionInspection;

typedef struct WdcExtensionCandidate {
    WdcExtensionState state;
    const uint8_t *raw_bytes;
    uint32_t raw_size;
    WdcExtensionInspection inspection;
    WdcElfImage *image;
    const pulse_extension_descriptor_v1 *descriptor;
    pulse_extension_descriptor_v1 descriptor_storage;
    WdcElfMemoryLayout memory;
    uint32_t start_entered;
    uint32_t reset_required;
    int32_t last_extension_status;
    uint32_t fault_code;
    pulse_extension_health_v1 observed_health;
    uint32_t observed_health_valid;
} WdcExtensionCandidate;

typedef struct WdcExtensionRegistry {
    WdcExtensionCandidate *candidates[WDC_EXTENSION_REGISTRY_CAPACITY];
    uint32_t count;
    uint32_t sealed;
    uint32_t initialized_count;
    uint32_t started_count;
    uint32_t lifecycle_failed;
    uint32_t reset_required;
} WdcExtensionRegistry;

void wdc_extension_profile_esp32s3(WdcExtensionProfile *out_profile);
void wdc_extension_profile_esp32c6(WdcExtensionProfile *out_profile);

/* Stage one: bounded raw-byte admission. This function cannot execute ELF code. */
int32_t wdc_extension_inspect(const uint8_t *elf_bytes,
                              uint32_t elf_size,
                              const WdcExtensionProfile *profile,
                              WdcExtensionInspection *out_inspection);

/*
 * Stage two: verify byte identity, relocate, call only the pure descriptor
 * entry, and validate the descriptor. No lifecycle function is called.
 */
int32_t wdc_extension_load_descriptor(const uint8_t *elf_bytes,
                                      uint32_t elf_size,
                                      const WdcExtensionInspection *inspection,
                                      WdcExtensionCandidate *out_candidate);

void wdc_extension_registry_init(WdcExtensionRegistry *registry);
int32_t wdc_extension_registry_add(WdcExtensionRegistry *registry,
                                   WdcExtensionCandidate *candidate);
int32_t wdc_extension_registry_seal(WdcExtensionRegistry *registry);

/* HX3 lifecycle calls remain host-owned and registry ordered. */
int32_t wdc_extension_registry_initialize(
    WdcExtensionRegistry *registry,
    const pulse_extension_init_args_v1 *template_args);
int32_t wdc_extension_registry_start(WdcExtensionRegistry *registry);
int32_t wdc_extension_candidate_invoke(
    WdcExtensionCandidate *candidate,
    const pulse_extension_invoke_v1 *request);
int32_t wdc_extension_candidate_health(
    WdcExtensionCandidate *candidate,
    pulse_extension_health_v1 *out_health);
int32_t wdc_extension_registry_quiesce(
    WdcExtensionRegistry *registry,
    const pulse_extension_quiesce_v1 *request);
int32_t wdc_extension_registry_deinitialize(WdcExtensionRegistry *registry);
int32_t wdc_extension_registry_unload_clean(WdcExtensionRegistry *registry);
uint32_t wdc_extension_registry_requires_reset(const WdcExtensionRegistry *registry);

/* Only pre-lifecycle candidates may use the HX2 unload helper. */
int32_t wdc_extension_unload_unstarted(WdcExtensionCandidate *candidate);

#ifdef PULSE_EXTENSION_HOST_TEST
int32_t wdc_extension_test_normalize_descriptor(
    const pulse_extension_descriptor_v1 *loaded_descriptor,
    const WdcExtensionInspection *inspection,
    const WdcElfMemoryLayout *memory,
    pulse_extension_descriptor_v1 *out_descriptor);
#endif

/* Side-effect-free boot link anchor. */
uint32_t wdc_extension_link_anchor(void);

#ifdef __cplusplus
}
#endif
