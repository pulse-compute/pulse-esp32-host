#pragma once

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/*
 * This is a private host adapter, not the Pulse extension ABI. Loader-owned
 * structures and symbol-resolution APIs intentionally do not cross it.
 */
typedef struct WdcElfImage WdcElfImage;

#define WDC_ELF_MAX_RESOLVED_SYMBOLS 16u

typedef struct WdcElfResolvedSymbol {
    const char *name;
    uint32_t address;
} WdcElfResolvedSymbol;

typedef enum WdcElfStatus {
    WDC_ELF_OK = 0,
    WDC_ELF_ERR_ARGUMENT = -1,
    WDC_ELF_ERR_NO_MEMORY = -2,
    WDC_ELF_ERR_LOADER = -3,
    WDC_ELF_ERR_RANGE = -4,
} WdcElfStatus;

typedef struct WdcElfMemoryLayout {
    uint32_t executable_address;
    uint32_t executable_size;
    uint32_t writable_address;
    uint32_t writable_size;
    uint32_t unified_segment;
} WdcElfMemoryLayout;

/* Side-effect-free boot link anchor; returns 1 when the adapter API is linked. */
uint32_t wdc_elf_link_anchor(void);

/*
 * Relocate bytes that have already passed the independent bounded inspector.
 * The immutable byte buffer remains borrowed and must outlive the image.
 * This function is deliberately not an admission or validation API.
 */
int32_t wdc_elf_load_inspected(const uint8_t *elf_bytes,
                               uint32_t elf_size,
                               WdcElfImage **out_image);

/* Relocate with one inspector-derived exact name/address table. */
int32_t wdc_elf_load_inspected_with_symbols(const uint8_t *elf_bytes,
                                            uint32_t elf_size,
                                            const WdcElfResolvedSymbol *symbols,
                                            uint32_t symbol_count,
                                            WdcElfImage **out_image);

/* Map an inspector-validated ELF virtual address into the relocated image. */
int32_t wdc_elf_map_virtual(const WdcElfImage *image,
                            uint32_t virtual_address,
                            uint32_t *out_runtime_address);

int32_t wdc_elf_memory_layout(const WdcElfImage *image,
                              WdcElfMemoryLayout *out_layout);

/* The exact underlying loader return code from the last relocation attempt. */
int32_t wdc_elf_loader_code(const WdcElfImage *image);

/* Null-safe, idempotent ownership release. */
int32_t wdc_elf_unload(WdcElfImage **image);

#ifdef __cplusplus
}
#endif
