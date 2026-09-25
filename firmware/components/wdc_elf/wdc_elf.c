#include "wdc_elf.h"

#include <limits.h>
#include <stdlib.h>
#include <string.h>

#include "esp_elf.h"
#include "private/elf_platform.h"
#include "private/elf_symbol.h"

#if CONFIG_ELF_LOADER_LOAD_PSRAM
#include "wdc_elf_allocator.h"
#endif

struct WdcElfImage {
    esp_elf_t loader;
    const uint8_t *raw_bytes;
    uint32_t raw_size;
    int32_t loader_code;
};

static const WdcElfResolvedSymbol *s_resolved_symbols;
static uint32_t s_resolved_symbol_count;

static uintptr_t wdc_elf_resolve_nothing(const char *name)
{
    (void)name;
    return 0;
}

static uintptr_t wdc_elf_resolve_exact(const char *name)
{
    uint32_t index;
    if (name == NULL) {
        return 0u;
    }
    for (index = 0u; index < s_resolved_symbol_count; ++index) {
        if (strcmp(name, s_resolved_symbols[index].name) == 0) {
            return (uintptr_t)s_resolved_symbols[index].address;
        }
    }
    return 0u;
}

#if !CONFIG_ELF_LOADER_BUS_ADDRESS_MIRROR
static int add_u32(uint32_t left, uint32_t right, uint32_t *out)
{
    if (out == NULL || left > UINT32_MAX - right) {
        return 0;
    }
    *out = left + right;
    return 1;
}
#endif

int32_t wdc_elf_load_inspected(const uint8_t *elf_bytes,
                               uint32_t elf_size,
                               WdcElfImage **out_image)
{
    return wdc_elf_load_inspected_with_symbols(elf_bytes, elf_size, NULL, 0u, out_image);
}

int32_t wdc_elf_load_inspected_with_symbols(const uint8_t *elf_bytes,
                                            uint32_t elf_size,
                                            const WdcElfResolvedSymbol *symbols,
                                            uint32_t symbol_count,
                                            WdcElfImage **out_image)
{
    WdcElfImage *image;
    int32_t code;
    uint32_t left;
    uint32_t right;

    if (elf_bytes == NULL || elf_size == 0u || out_image == NULL || *out_image != NULL ||
        symbol_count > WDC_ELF_MAX_RESOLVED_SYMBOLS ||
        (symbol_count != 0u && symbols == NULL)) {
        return WDC_ELF_ERR_ARGUMENT;
    }
    for (left = 0u; left < symbol_count; ++left) {
        if (symbols[left].name == NULL || symbols[left].name[0] == '\0' ||
            symbols[left].address == 0u) {
            return WDC_ELF_ERR_ARGUMENT;
        }
        for (right = left + 1u; right < symbol_count; ++right) {
            if (symbols[right].name != NULL && strcmp(symbols[left].name, symbols[right].name) == 0) {
                return WDC_ELF_ERR_ARGUMENT;
            }
        }
    }

    image = calloc(1u, sizeof(*image));
    if (image == NULL) {
        return WDC_ELF_ERR_NO_MEMORY;
    }

    image->raw_bytes = elf_bytes;
    image->raw_size = elf_size;
    code = esp_elf_init(&image->loader);
    image->loader_code = code;
    if (code != 0) {
        free(image);
        return WDC_ELF_ERR_LOADER;
    }

#if CONFIG_ELF_LOADER_LOAD_PSRAM
    code = wdc_elf_allocator_prepare(elf_bytes, elf_size);
    image->loader_code = code;
    if (code != 0) {
        esp_elf_deinit(&image->loader);
        free(image);
        return WDC_ELF_ERR_LOADER;
    }
#endif

    /*
     * The loader's configured libc/IDF tables are disabled by the HX1 proof
     * overlays. Installing a reject-all resolver also prevents accidental
     * ambient resolution until HX2 supplies an inspector-derived allowlist.
     */
    s_resolved_symbols = symbols;
    s_resolved_symbol_count = symbol_count;
    elf_set_symbol_resolver(symbol_count == 0u ? wdc_elf_resolve_nothing : wdc_elf_resolve_exact);
    code = esp_elf_relocate(&image->loader, elf_bytes);
#if CONFIG_ELF_LOADER_LOAD_PSRAM
    {
        int32_t allocator_code = wdc_elf_allocator_finish();
        if (code == 0 && allocator_code != 0) {
            code = allocator_code;
        }
    }
#endif
    s_resolved_symbols = NULL;
    s_resolved_symbol_count = 0u;
    elf_reset_symbol_resolver();
    image->loader_code = code;
    if (code != 0) {
        esp_elf_deinit(&image->loader);
        free(image);
        return WDC_ELF_ERR_LOADER;
    }

    *out_image = image;
    return WDC_ELF_OK;
}

int32_t wdc_elf_map_virtual(const WdcElfImage *image,
                            uint32_t virtual_address,
                            uint32_t *out_runtime_address)
{
    uintptr_t mapped;

    if (image == NULL || out_runtime_address == NULL) {
        return WDC_ELF_ERR_ARGUMENT;
    }

#if CONFIG_ELF_LOADER_BUS_ADDRESS_MIRROR
    mapped = esp_elf_map_sym((esp_elf_t *)&image->loader, virtual_address);
#ifdef CONFIG_ELF_LOADER_CACHE_OFFSET
    if (virtual_address >= image->loader.sec[ELF_SEC_TEXT].v_addr &&
        virtual_address - image->loader.sec[ELF_SEC_TEXT].v_addr <
            image->loader.sec[ELF_SEC_TEXT].size) {
        /*
         * esp_elf_map_sym() returns the data-cache address of PSRAM-backed
         * text.  Direct Pulse entry-symbol lookup must perform the same
         * instruction-cache alias conversion that the upstream loader uses
         * for elf->entry and relocated function pointers.
         */
        mapped = elf_remap_text((esp_elf_t *)&image->loader, mapped);
    }
#endif
    if (mapped == 0u || mapped > UINT32_MAX) {
        return WDC_ELF_ERR_RANGE;
    }
#else
    uint32_t segment_end;
    uint32_t offset;
    if (!add_u32(image->loader.svaddr, image->loader.seg_size, &segment_end) ||
        virtual_address < image->loader.svaddr || virtual_address >= segment_end) {
        return WDC_ELF_ERR_RANGE;
    }
    offset = virtual_address - image->loader.svaddr;
    mapped = (uintptr_t)(image->loader.psegment + offset);
    if (mapped > UINT32_MAX) {
        return WDC_ELF_ERR_RANGE;
    }
#endif

    *out_runtime_address = (uint32_t)mapped;
    return WDC_ELF_OK;
}

int32_t wdc_elf_memory_layout(const WdcElfImage *image,
                              WdcElfMemoryLayout *out_layout)
{
#if CONFIG_ELF_LOADER_BUS_ADDRESS_MIRROR
    uintptr_t executable_address;
#endif

    if (image == NULL || out_layout == NULL) {
        return WDC_ELF_ERR_ARGUMENT;
    }

    memset(out_layout, 0, sizeof(*out_layout));
#if CONFIG_ELF_LOADER_BUS_ADDRESS_MIRROR
    executable_address = (uintptr_t)image->loader.ptext;
#ifdef CONFIG_ELF_LOADER_CACHE_OFFSET
    executable_address = elf_remap_text((esp_elf_t *)&image->loader,
                                        executable_address);
#endif
    if (executable_address == 0u || executable_address > UINT32_MAX) {
        return WDC_ELF_ERR_RANGE;
    }
    out_layout->executable_address = (uint32_t)executable_address;
    out_layout->executable_size = (uint32_t)image->loader.sec[ELF_SEC_TEXT].size;
    out_layout->writable_address = (uint32_t)(uintptr_t)image->loader.pdata;
    out_layout->writable_size =
        (uint32_t)(image->loader.sec[ELF_SEC_BSS].size +
                   image->loader.sec[ELF_SEC_DATA].size +
                   image->loader.sec[ELF_SEC_RODATA].size +
                   image->loader.sec[ELF_SEC_DRLRO].size);
    out_layout->unified_segment = 0u;
#else
    out_layout->executable_address = (uint32_t)(uintptr_t)image->loader.psegment;
    out_layout->executable_size = image->loader.seg_size;
    out_layout->writable_address = (uint32_t)(uintptr_t)image->loader.psegment;
    out_layout->writable_size = image->loader.seg_size;
    out_layout->unified_segment = 1u;
#endif
    return WDC_ELF_OK;
}

int32_t wdc_elf_loader_code(const WdcElfImage *image)
{
    return image == NULL ? WDC_ELF_ERR_ARGUMENT : image->loader_code;
}

int32_t wdc_elf_unload(WdcElfImage **image)
{
    if (image == NULL) {
        return WDC_ELF_ERR_ARGUMENT;
    }
    if (*image == NULL) {
        return WDC_ELF_OK;
    }

    esp_elf_deinit(&(*image)->loader);
    (*image)->raw_bytes = NULL;
    (*image)->raw_size = 0u;
    free(*image);
    *image = NULL;
    return WDC_ELF_OK;
}

/*
 * HX1 has no runtime caller yet, but its host proof must contain the actual
 * adapter and loader rather than archives that the linker later discards.
 * Volatile typed references retain each adapter section without executing a
 * loader operation or exposing loader-specific types.
 */
static int32_t (*volatile s_keep_load)(const uint8_t *, uint32_t, WdcElfImage **) =
    wdc_elf_load_inspected;
static int32_t (*volatile s_keep_load_symbols)(const uint8_t *, uint32_t,
                                               const WdcElfResolvedSymbol *, uint32_t,
                                               WdcElfImage **) =
    wdc_elf_load_inspected_with_symbols;
static int32_t (*volatile s_keep_map)(const WdcElfImage *, uint32_t, uint32_t *) =
    wdc_elf_map_virtual;
static int32_t (*volatile s_keep_layout)(const WdcElfImage *, WdcElfMemoryLayout *) =
    wdc_elf_memory_layout;
static int32_t (*volatile s_keep_code)(const WdcElfImage *) = wdc_elf_loader_code;
static int32_t (*volatile s_keep_unload)(WdcElfImage **) = wdc_elf_unload;

uint32_t wdc_elf_link_anchor(void)
{
    return s_keep_load != NULL &&
           s_keep_load_symbols != NULL &&
           s_keep_map != NULL &&
           s_keep_layout != NULL &&
           s_keep_code != NULL &&
           s_keep_unload != NULL;
}
