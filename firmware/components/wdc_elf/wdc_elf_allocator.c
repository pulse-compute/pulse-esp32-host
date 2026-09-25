#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

#include "esp_heap_caps.h"
#include "private/elf_types.h"

#include "wdc_elf_allocator.h"

#define WDC_ELF_MAX_WRITABLE_ALIGNMENT 4096u
#define WDC_ELF_SHIFTED_ALLOCATION_CAPACITY 4u

typedef struct {
    uint32_t size;
    uint32_t alignment;
    uint32_t packed_offset;
    bool present;
} WdcElfPackedSection;

typedef struct {
    uint32_t size;
    uint32_t alignment;
    uint32_t residue;
    bool active;
    bool consumed;
} WdcElfPendingAllocation;

typedef struct {
    void *returned;
    void *allocated;
} WdcElfShiftedAllocation;

enum {
    WDC_ELF_PACKED_DATA = 0,
    WDC_ELF_PACKED_RODATA = 1,
    WDC_ELF_PACKED_DRLRO = 2,
    WDC_ELF_PACKED_BSS = 3,
    WDC_ELF_PACKED_SECTION_COUNT = 4,
};

static WdcElfPendingAllocation s_pending;
static WdcElfShiftedAllocation
    s_shifted_allocations[WDC_ELF_SHIFTED_ALLOCATION_CAPACITY];

static bool range_valid(uint32_t total, uint32_t offset, uint32_t size)
{
    return offset <= total && size <= total - offset;
}

static bool multiply_valid(uint32_t left, uint32_t right, uint32_t *out)
{
    if (out == NULL || (left != 0u && right > UINT32_MAX / left)) {
        return false;
    }
    *out = left * right;
    return true;
}

static bool add_valid(uint32_t left, uint32_t right, uint32_t *out)
{
    if (out == NULL || right > UINT32_MAX - left) {
        return false;
    }
    *out = left + right;
    return true;
}

static bool power_of_two(uint32_t value)
{
    return value != 0u && (value & (value - 1u)) == 0u;
}

static int32_t read_section(const uint8_t *bytes, uint32_t size,
                            const elf32_hdr_t *header, uint32_t index,
                            elf32_shdr_t *section)
{
    uint32_t entry_offset;
    uint32_t index_offset;

    if (bytes == NULL || header == NULL || section == NULL ||
        index >= header->shnum || header->shentsize < sizeof(*section) ||
        !multiply_valid(index, header->shentsize, &index_offset) ||
        !add_valid(header->shoff, index_offset, &entry_offset) ||
        !range_valid(size, entry_offset, sizeof(*section))) {
        return -1;
    }
    memcpy(section, bytes + entry_offset, sizeof(*section));
    return 0;
}

static const char *section_name(const uint8_t *bytes, uint32_t size,
                                const elf32_shdr_t *names,
                                const elf32_shdr_t *section)
{
    const char *name;
    uint32_t available;

    if (bytes == NULL || names == NULL || section == NULL ||
        names->type != SHT_STRTAB ||
        !range_valid(size, names->offset, names->size) ||
        section->name >= names->size) {
        return NULL;
    }
    name = (const char *)(bytes + names->offset + section->name);
    available = names->size - section->name;
    return memchr(name, '\0', available) == NULL ? NULL : name;
}

static int32_t packed_slot(const elf32_shdr_t *section, const char *name)
{
    if (section == NULL || name == NULL) {
        return -1;
    }
    if (section->type == SHT_PROGBITS &&
        (section->flags & SHF_ALLOC) == SHF_ALLOC) {
        if ((section->flags & SHF_WRITE) == SHF_WRITE &&
            strcmp(name, ELF_DATA) == 0) {
            return WDC_ELF_PACKED_DATA;
        }
        if (strcmp(name, ELF_RODATA) == 0) {
            return WDC_ELF_PACKED_RODATA;
        }
        if (strcmp(name, ELF_DATA_REL_RO) == 0) {
            return WDC_ELF_PACKED_DRLRO;
        }
    }
    if (section->type == SHT_NOBITS &&
        (section->flags & (SHF_ALLOC | SHF_WRITE)) ==
            (SHF_ALLOC | SHF_WRITE) &&
        strcmp(name, ELF_BSS) == 0) {
        return WDC_ELF_PACKED_BSS;
    }
    return -1;
}

int32_t wdc_elf_allocator_prepare(const uint8_t *elf_bytes, uint32_t elf_size)
{
    elf32_hdr_t header;
    elf32_shdr_t names;
    WdcElfPackedSection sections[WDC_ELF_PACKED_SECTION_COUNT] = {0};
    uint32_t section_table_size;
    uint32_t packed_size = 0u;
    uint32_t maximum_alignment = 1u;
    uint32_t residue;
    bool solution = false;

    if (s_pending.active || elf_bytes == NULL || elf_size < sizeof(header)) {
        return -1;
    }
    memcpy(&header, elf_bytes, sizeof(header));
    if (memcmp(header.ident, "\x7f" "ELF", 4u) != 0 ||
        header.ident[4] != 1u || header.ident[5] != 1u ||
        header.shnum == 0u || header.shstrndx >= header.shnum ||
        header.shentsize < sizeof(elf32_shdr_t) ||
        !multiply_valid(header.shnum, header.shentsize, &section_table_size) ||
        !range_valid(elf_size, header.shoff, section_table_size) ||
        read_section(elf_bytes, elf_size, &header, header.shstrndx, &names) != 0 ||
        !range_valid(elf_size, names.offset, names.size)) {
        return -1;
    }

    for (uint32_t index = 0u; index < header.shnum; ++index) {
        elf32_shdr_t section;
        const char *name;
        int32_t slot;
        uint32_t alignment;

        if (read_section(elf_bytes, elf_size, &header, index, &section) != 0) {
            return -1;
        }
        name = section_name(elf_bytes, elf_size, &names, &section);
        if (name == NULL) {
            return -1;
        }
        slot = packed_slot(&section, name);
        if (slot < 0) {
            continue;
        }
        if (sections[slot].present ||
            (section.type != SHT_NOBITS &&
             !range_valid(elf_size, section.offset, section.size))) {
            return -1;
        }
        alignment = section.addralign == 0u ? 1u : section.addralign;
        if (!power_of_two(alignment) ||
            alignment > WDC_ELF_MAX_WRITABLE_ALIGNMENT) {
            return -1;
        }
        sections[slot].size = section.size;
        sections[slot].alignment = alignment;
        sections[slot].present = true;
        if (alignment > maximum_alignment) {
            maximum_alignment = alignment;
        }
    }

    for (uint32_t slot = 0u; slot < WDC_ELF_PACKED_SECTION_COUNT; ++slot) {
        if (!sections[slot].present) {
            continue;
        }
        sections[slot].packed_offset = packed_size;
        if (!add_valid(packed_size, sections[slot].size, &packed_size)) {
            return -1;
        }
    }

    for (residue = 0u; residue < maximum_alignment; ++residue) {
        bool compatible = true;
        for (uint32_t slot = 0u; slot < WDC_ELF_PACKED_SECTION_COUNT; ++slot) {
            if (sections[slot].present &&
                ((residue + sections[slot].packed_offset) &
                 (sections[slot].alignment - 1u)) != 0u) {
                compatible = false;
                break;
            }
        }
        if (compatible) {
            solution = true;
            break;
        }
    }
    if (!solution) {
        return -1;
    }

    s_pending.size = packed_size;
    s_pending.alignment = maximum_alignment;
    s_pending.residue = residue;
    s_pending.active = true;
    s_pending.consumed = false;
    return 0;
}

int32_t wdc_elf_allocator_finish(void)
{
    int32_t result;

    if (!s_pending.active) {
        return -1;
    }
    result = (s_pending.size == 0u || s_pending.consumed) ? 0 : -1;
    memset(&s_pending, 0, sizeof(s_pending));
    return result;
}

static int32_t remember_shifted_allocation(void *returned, void *allocated)
{
    for (uint32_t index = 0u;
         index < WDC_ELF_SHIFTED_ALLOCATION_CAPACITY; ++index) {
        if (s_shifted_allocations[index].returned == NULL) {
            s_shifted_allocations[index].returned = returned;
            s_shifted_allocations[index].allocated = allocated;
            return 0;
        }
    }
    return -1;
}

/*
 * The pinned loader distinguishes executable requests at this boundary, but
 * its CONFIG_ELF_LOADER_LOAD_PSRAM adapter allocates every request from PSRAM
 * and packs writable sections without padding. The AITRIP lane keeps text in
 * PSRAM, keeps writable state internal, and selects the prepared base residue
 * that honors every packed section's declared power-of-two alignment.
 */
void *__wrap_esp_elf_malloc(uint32_t size, bool executable)
{
    uint32_t capabilities;
    uint32_t allocation_size;
    uint32_t allocation_alignment;
    uint8_t *allocated;
    uint8_t *returned;

    if (executable) {
        return heap_caps_malloc(size, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    }
    capabilities = MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT;
    if (!s_pending.active) {
        return heap_caps_malloc(size, capabilities);
    }
    if (s_pending.consumed || size != s_pending.size) {
        return NULL;
    }
    s_pending.consumed = true;
    if (!add_valid(size, s_pending.alignment - 1u, &allocation_size)) {
        return NULL;
    }
    allocation_alignment = s_pending.alignment;
    if (allocation_alignment < sizeof(void *)) {
        allocation_alignment = sizeof(void *);
    }
    allocated = heap_caps_aligned_alloc(allocation_alignment, allocation_size,
                                        capabilities);
    if (allocated == NULL) {
        return NULL;
    }
    returned = allocated + s_pending.residue;
    if (returned != allocated &&
        remember_shifted_allocation(returned, allocated) != 0) {
        heap_caps_free(allocated);
        return NULL;
    }
    return returned;
}

void __wrap_esp_elf_free(void *pointer)
{
    if (pointer == NULL) {
        return;
    }
    for (uint32_t index = 0u;
         index < WDC_ELF_SHIFTED_ALLOCATION_CAPACITY; ++index) {
        if (s_shifted_allocations[index].returned == pointer) {
            void *allocated = s_shifted_allocations[index].allocated;
            memset(&s_shifted_allocations[index], 0,
                   sizeof(s_shifted_allocations[index]));
            heap_caps_free(allocated);
            return;
        }
    }
    heap_caps_free(pointer);
}
