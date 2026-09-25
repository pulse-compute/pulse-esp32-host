#include "wdc_extension.h"

#include <stddef.h>
#include <stdint.h>
#include <string.h>

#include "wdc_extension_sha256.h"
#include "wdc_extension_internal.h"

#define ELF_HEADER_SIZE 52u
#define ELF_PROGRAM_HEADER_SIZE 32u
#define ELF_SECTION_HEADER_SIZE 40u
#define ELF_SYMBOL_SIZE 16u
#define ELF_REL_SIZE 8u
#define ELF_RELA_SIZE 12u

#define ELF_TYPE_DYNAMIC 3u
#define ELF_PROGRAM_LOAD 1u
#define ELF_PROGRAM_INTERP 3u
#define ELF_PROGRAM_TLS 7u
#define ELF_SECTION_PROGBITS 1u
#define ELF_SECTION_SYMTAB 2u
#define ELF_SECTION_RELA 4u
#define ELF_SECTION_DYNAMIC 6u
#define ELF_SECTION_NOBITS 8u
#define ELF_SECTION_REL 9u
#define ELF_SECTION_DYNSYM 11u
#define ELF_SECTION_FLAG_EXEC 0x4u
#define ELF_SECTION_FLAG_TLS 0x400u
#define ELF_SYMBOL_UNDEFINED 0u
#define ELF_SYMBOL_GLOBAL 1u
#define ELF_SYMBOL_WEAK 2u
#define ELF_SYMBOL_FUNCTION 2u

typedef struct WdcElfSection {
    uint32_t name;
    uint32_t type;
    uint32_t flags;
    uint32_t address;
    uint32_t offset;
    uint32_t size;
    uint32_t link;
    uint32_t info;
    uint32_t alignment;
    uint32_t entry_size;
} WdcElfSection;

typedef const pulse_extension_descriptor_v1 *(*WdcExtensionEntryFn)(void);

static uint16_t read_u16(const uint8_t *bytes)
{
    return (uint16_t)((uint16_t)bytes[0] | ((uint16_t)bytes[1] << 8));
}

static uint32_t read_u32(const uint8_t *bytes)
{
    return (uint32_t)bytes[0] |
           ((uint32_t)bytes[1] << 8) |
           ((uint32_t)bytes[2] << 16) |
           ((uint32_t)bytes[3] << 24);
}

static int range_ok(uint32_t total, uint32_t offset, uint32_t size)
{
    return offset <= total && size <= total - offset;
}

static int table_ok(uint32_t total, uint32_t offset, uint32_t count, uint32_t stride)
{
    return stride != 0u && count <= UINT32_MAX / stride && range_ok(total, offset, count * stride);
}

static int all_zero(const uint8_t *bytes, uint32_t size)
{
    uint32_t index;
    for (index = 0u; index < size; ++index) {
        if (bytes[index] != 0u) {
            return 0;
        }
    }
    return 1;
}

static int digest_equal(const uint8_t left[32], const uint8_t right[32])
{
    uint32_t difference = 0u;
    uint32_t index;
    for (index = 0u; index < 32u; ++index) {
        difference |= (uint32_t)(left[index] ^ right[index]);
    }
    return difference == 0u;
}

static int sha256_bytes(const uint8_t *bytes, uint32_t size, uint8_t output[32])
{
    wdc_extension_sha256(bytes, size, output);
    return 1;
}

static int sha256_with_zero_span(const uint8_t *bytes,
                                 uint32_t size,
                                 uint32_t zero_offset,
                                 uint32_t zero_size,
                                 uint8_t output[32])
{
    static const uint8_t zeros[32] = {0u};
    WdcExtensionSha256 context;
    if (zero_size > sizeof(zeros) || !range_ok(size, zero_offset, zero_size)) {
        return 0;
    }
    wdc_extension_sha256_init(&context);
    wdc_extension_sha256_update(&context, bytes, zero_offset);
    wdc_extension_sha256_update(&context, zeros, zero_size);
    wdc_extension_sha256_update(
        &context,
        bytes + zero_offset + zero_size,
        size - zero_offset - zero_size);
    wdc_extension_sha256_finish(&context, output);
    return 1;
}

static void read_section(const uint8_t *bytes,
                         uint32_t section_table,
                         uint32_t stride,
                         uint32_t index,
                         WdcElfSection *out)
{
    const uint8_t *entry = bytes + section_table + index * stride;
    out->name = read_u32(entry + 0u);
    out->type = read_u32(entry + 4u);
    out->flags = read_u32(entry + 8u);
    out->address = read_u32(entry + 12u);
    out->offset = read_u32(entry + 16u);
    out->size = read_u32(entry + 20u);
    out->link = read_u32(entry + 24u);
    out->info = read_u32(entry + 28u);
    out->alignment = read_u32(entry + 32u);
    out->entry_size = read_u32(entry + 36u);
}

static int bounded_string(const uint8_t *bytes,
                          uint32_t table_offset,
                          uint32_t table_size,
                          uint32_t string_offset,
                          const char **out_string,
                          uint32_t *out_size)
{
    uint32_t index;
    if (string_offset >= table_size) {
        return 0;
    }
    for (index = string_offset; index < table_size; ++index) {
        if (bytes[table_offset + index] == 0u) {
            *out_string = (const char *)(bytes + table_offset + string_offset);
            *out_size = index - string_offset;
            return 1;
        }
    }
    return 0;
}

static int string_is(const char *value, uint32_t value_size, const char *expected)
{
    uint32_t expected_size = (uint32_t)strlen(expected);
    return value_size == expected_size && memcmp(value, expected, expected_size) == 0;
}

static int32_t import_index(const WdcExtensionProfile *profile,
                            const char *name,
                            uint32_t name_size)
{
    uint32_t index;
    for (index = 0u; index < profile->allowed_import_count; ++index) {
        if (profile->allowed_imports[index] != NULL &&
            string_is(name, name_size, profile->allowed_imports[index])) {
            return (int32_t)index;
        }
    }
    return -1;
}

static int inspection_has_import(const WdcExtensionInspection *inspection,
                                 const char *name,
                                 uint32_t name_size)
{
    uint32_t index;
    for (index = 0u; index < inspection->import_count; ++index) {
        if (string_is(name, name_size, inspection->imports[index].name)) {
            return 1;
        }
    }
    return 0;
}

static int supported_relocation(uint16_t machine, uint32_t relocation)
{
    if (machine == 94u) {
        return relocation == 2u || relocation == 3u || relocation == 4u || relocation == 5u;
    }
    if (machine == 243u) {
        return relocation == 0u || relocation == 1u || relocation == 3u || relocation == 5u;
    }
    return 0;
}

static int catalog_valid(const uint32_t values[4], uint16_t count)
{
    uint32_t left;
    uint32_t right;
    if (count < 1u || count > 4u) {
        return 0;
    }
    for (left = 0u; left < 4u; ++left) {
        if ((left < count && values[left] == 0u) || (left >= count && values[left] != 0u)) {
            return 0;
        }
        for (right = left + 1u; right < count; ++right) {
            if (values[left] == values[right]) {
                return 0;
            }
        }
    }
    return 1;
}

static int metadata_valid(const pulse_extension_metadata_v1 *metadata,
                          const WdcExtensionProfile *profile)
{
    uint32_t queue_storage;
    if (memcmp(metadata->magic, PULSE_EXTENSION_METADATA_MAGIC, 8u) != 0 ||
        metadata->format_major != 1u || metadata->format_minor != 0u ||
        metadata->record_size != PULSE_EXTENSION_METADATA_SIZE_V1 ||
        metadata->architecture_id != profile->architecture_id ||
        metadata->soc_id != profile->soc_id || metadata->flags != 0u ||
        metadata->required_host_abi_major != profile->host_abi_major ||
        metadata->required_host_abi_min_minor > profile->host_abi_minor ||
        metadata->extension_abi_major != PULSE_EXTENSION_ABI_MAJOR_V1 ||
        metadata->extension_abi_minor != PULSE_EXTENSION_ABI_MINOR_V1 ||
        all_zero(metadata->extension_id, sizeof(metadata->extension_id)) ||
        metadata->descriptor_size != PULSE_EXTENSION_DESCRIPTOR_SIZE_V1 ||
        metadata->descriptor_alignment != 4u || metadata->reserved0 != 0u ||
        !all_zero(metadata->reserved1, sizeof(metadata->reserved1)) ||
        !catalog_valid(metadata->event_ids, metadata->event_count) ||
        !catalog_valid(metadata->operation_ids, metadata->operation_count)) {
        return 0;
    }
    if (metadata->task_count != 1u || metadata->task_stack_bytes < 2048u ||
        metadata->task_stack_bytes > profile->max_task_stack_bytes ||
        (metadata->task_stack_bytes % 16u) != 0u ||
        metadata->static_memory_bytes > profile->max_static_memory_bytes ||
        metadata->queue_depth < 1u || metadata->queue_depth > profile->max_queue_depth ||
        metadata->queue_item_bytes < 32u ||
        metadata->queue_item_bytes > profile->max_queue_item_bytes ||
        (metadata->queue_item_bytes % 4u) != 0u ||
        metadata->queue_depth > UINT32_MAX / metadata->queue_item_bytes) {
        return 0;
    }
    queue_storage = metadata->queue_depth * metadata->queue_item_bytes;
    return queue_storage <= profile->max_queue_storage_bytes &&
           metadata->max_event_payload_bytes <= profile->max_event_payload_bytes &&
           metadata->max_effect_request_bytes <= profile->max_effect_request_bytes &&
           metadata->max_effect_completion_bytes <= profile->max_effect_completion_bytes;
}

static void profile_common(WdcExtensionProfile *profile)
{
    memset(profile, 0, sizeof(*profile));
    profile->host_abi_major = PULSE_HOST_ABI_MAJOR_V1;
    profile->host_abi_minor = PULSE_HOST_ABI_MINOR_V1;
    profile->max_task_stack_bytes = 8192u;
    profile->max_static_memory_bytes = 16384u;
    profile->max_queue_depth = 16u;
    profile->max_queue_item_bytes = 512u;
    profile->max_queue_storage_bytes = 4096u;
    profile->max_event_payload_bytes = 128u;
    profile->max_effect_request_bytes = 256u;
    profile->max_effect_completion_bytes = 256u;
    wdc_extension_platform_profile_imports(profile);
}

void wdc_extension_profile_esp32s3(WdcExtensionProfile *out_profile)
{
    if (out_profile != NULL) {
        profile_common(out_profile);
        out_profile->elf_machine = 94u;
        out_profile->architecture_id = 1u;
        out_profile->soc_id = 1u;
    }
}

void wdc_extension_profile_esp32c6(WdcExtensionProfile *out_profile)
{
    if (out_profile != NULL) {
        profile_common(out_profile);
        out_profile->elf_machine = 243u;
        out_profile->architecture_id = 2u;
        out_profile->soc_id = 2u;
    }
}

int32_t wdc_extension_inspect(const uint8_t *elf_bytes,
                              uint32_t elf_size,
                              const WdcExtensionProfile *profile,
                              WdcExtensionInspection *out_inspection)
{
    uint32_t program_table;
    uint32_t section_table;
    uint32_t program_stride;
    uint32_t section_stride;
    uint32_t program_count;
    uint32_t section_count;
    uint32_t section_names_index;
    uint32_t index;
    uint32_t metadata_count = 0u;
    uint32_t entry_count = 0u;
    uint8_t entry_binding = 0xffu;
    uint32_t first_load_seen = 0u;
    uint32_t text_seen = 0u;
    WdcElfSection section_names;
    WdcElfSection metadata_section = {0u};

    if (elf_bytes == NULL || profile == NULL || out_inspection == NULL ||
        elf_size < ELF_HEADER_SIZE || profile->allowed_import_count > WDC_EXTENSION_IMPORT_CAPACITY ||
        (profile->allowed_import_count != 0u &&
         (profile->allowed_imports == NULL || profile->allowed_import_addresses == NULL))) {
        return WDC_EXTENSION_ERR_ARGUMENT;
    }
    memset(out_inspection, 0, sizeof(*out_inspection));
    if (memcmp(elf_bytes, "\x7f" "ELF", 4u) != 0 || elf_bytes[4] != 1u ||
        elf_bytes[5] != 1u || elf_bytes[6] != 1u || read_u16(elf_bytes + 16u) != ELF_TYPE_DYNAMIC ||
        read_u32(elf_bytes + 20u) != 1u || read_u16(elf_bytes + 40u) != ELF_HEADER_SIZE) {
        return WDC_EXTENSION_ERR_STRUCTURE;
    }
    if (read_u16(elf_bytes + 18u) != profile->elf_machine) {
        return WDC_EXTENSION_ERR_TARGET;
    }
    program_table = read_u32(elf_bytes + 28u);
    section_table = read_u32(elf_bytes + 32u);
    program_stride = read_u16(elf_bytes + 42u);
    program_count = read_u16(elf_bytes + 44u);
    section_stride = read_u16(elf_bytes + 46u);
    section_count = read_u16(elf_bytes + 48u);
    section_names_index = read_u16(elf_bytes + 50u);
    if (program_stride != ELF_PROGRAM_HEADER_SIZE || section_stride != ELF_SECTION_HEADER_SIZE ||
        section_count == 0u || section_names_index >= section_count ||
        !table_ok(elf_size, program_table, program_count, program_stride) ||
        !table_ok(elf_size, section_table, section_count, section_stride)) {
        return WDC_EXTENSION_ERR_STRUCTURE;
    }

    for (index = 0u; index < program_count; ++index) {
        const uint8_t *program = elf_bytes + program_table + index * program_stride;
        uint32_t type = read_u32(program + 0u);
        uint32_t offset = read_u32(program + 4u);
        uint32_t virtual_address = read_u32(program + 8u);
        uint32_t file_size = read_u32(program + 16u);
        uint32_t memory_size = read_u32(program + 20u);
        if (!range_ok(elf_size, offset, file_size) || (type == ELF_PROGRAM_LOAD && memory_size < file_size)) {
            return WDC_EXTENSION_ERR_STRUCTURE;
        }
        if (type == ELF_PROGRAM_INTERP || type == ELF_PROGRAM_TLS) {
            return WDC_EXTENSION_ERR_CONSTRUCTOR;
        }
        if (type == ELF_PROGRAM_LOAD && first_load_seen == 0u) {
            first_load_seen = 1u;
            if (profile->elf_machine == 243u && virtual_address != 0u) {
                return WDC_EXTENSION_ERR_STRUCTURE;
            }
        }
    }
    if (first_load_seen == 0u) {
        return WDC_EXTENSION_ERR_STRUCTURE;
    }

    read_section(elf_bytes, section_table, section_stride, section_names_index, &section_names);
    if (section_names.type == ELF_SECTION_NOBITS ||
        !range_ok(elf_size, section_names.offset, section_names.size)) {
        return WDC_EXTENSION_ERR_STRUCTURE;
    }

    for (index = 0u; index < section_count; ++index) {
        WdcElfSection section;
        const char *name;
        uint32_t name_size;
        read_section(elf_bytes, section_table, section_stride, index, &section);
        if (section.type != ELF_SECTION_NOBITS && !range_ok(elf_size, section.offset, section.size)) {
            return WDC_EXTENSION_ERR_STRUCTURE;
        }
        if (!bounded_string(elf_bytes, section_names.offset, section_names.size,
                            section.name, &name, &name_size)) {
            return WDC_EXTENSION_ERR_STRUCTURE;
        }
        if (string_is(name, name_size, ".pulse_ext_meta")) {
            metadata_section = section;
            metadata_count += 1u;
        }
        if (string_is(name, name_size, ".text") &&
            (section.flags & ELF_SECTION_FLAG_EXEC) != 0u) {
            text_seen = 1u;
        }
        if (string_is(name, name_size, ".init_array") ||
            string_is(name, name_size, ".fini_array") ||
            string_is(name, name_size, ".ctors") ||
            string_is(name, name_size, ".dtors") ||
            (section.flags & ELF_SECTION_FLAG_TLS) != 0u) {
            return WDC_EXTENSION_ERR_CONSTRUCTOR;
        }
        if (section.type == ELF_SECTION_DYNAMIC) {
            uint32_t entry;
            uint32_t stride = section.entry_size == 0u ? 8u : section.entry_size;
            if (stride < 8u || section.size % stride != 0u) {
                return WDC_EXTENSION_ERR_STRUCTURE;
            }
            for (entry = 0u; entry < section.size / stride; ++entry) {
                uint32_t tag = read_u32(elf_bytes + section.offset + entry * stride);
                if (tag == 1u || tag == 12u || tag == 13u) {
                    return WDC_EXTENSION_ERR_CONSTRUCTOR;
                }
            }
        }
        if (section.type == ELF_SECTION_REL || section.type == ELF_SECTION_RELA) {
            uint32_t entry;
            uint32_t minimum = section.type == ELF_SECTION_RELA ? ELF_RELA_SIZE : ELF_REL_SIZE;
            uint32_t stride = section.entry_size == 0u ? minimum : section.entry_size;
            if (stride < minimum || section.size % stride != 0u) {
                return WDC_EXTENSION_ERR_STRUCTURE;
            }
            for (entry = 0u; entry < section.size / stride; ++entry) {
                uint32_t info = read_u32(elf_bytes + section.offset + entry * stride + 4u);
                if (!supported_relocation(profile->elf_machine, info & 0xffu)) {
                    return WDC_EXTENSION_ERR_RELOCATION;
                }
                out_inspection->relocation_count += 1u;
            }
        }
    }
    if (metadata_count != 1u || (profile->elf_machine == 94u && text_seen == 0u)) {
        return WDC_EXTENSION_ERR_METADATA;
    }
    if (metadata_section.type != ELF_SECTION_PROGBITS || metadata_section.size != 192u ||
        metadata_section.alignment != 4u ||
        (metadata_section.flags & ELF_SECTION_FLAG_EXEC) != 0u) {
        return WDC_EXTENSION_ERR_METADATA;
    }
    memcpy(&out_inspection->metadata, elf_bytes + metadata_section.offset,
           sizeof(out_inspection->metadata));
    if (!metadata_valid(&out_inspection->metadata, profile)) {
        return WDC_EXTENSION_ERR_BUDGET;
    }

    for (index = 0u; index < section_count; ++index) {
        WdcElfSection symbols;
        WdcElfSection strings;
        uint32_t symbol_index;
        uint32_t stride;
        read_section(elf_bytes, section_table, section_stride, index, &symbols);
        if (symbols.type != ELF_SECTION_SYMTAB && symbols.type != ELF_SECTION_DYNSYM) {
            continue;
        }
        if (symbols.link >= section_count) {
            return WDC_EXTENSION_ERR_STRUCTURE;
        }
        read_section(elf_bytes, section_table, section_stride, symbols.link, &strings);
        if (strings.type == ELF_SECTION_NOBITS || !range_ok(elf_size, strings.offset, strings.size)) {
            return WDC_EXTENSION_ERR_STRUCTURE;
        }
        stride = symbols.entry_size == 0u ? ELF_SYMBOL_SIZE : symbols.entry_size;
        if (stride < ELF_SYMBOL_SIZE || symbols.size % stride != 0u) {
            return WDC_EXTENSION_ERR_STRUCTURE;
        }
        for (symbol_index = 0u; symbol_index < symbols.size / stride; ++symbol_index) {
            const uint8_t *symbol = elf_bytes + symbols.offset + symbol_index * stride;
            uint32_t name_offset = read_u32(symbol + 0u);
            uint32_t value = read_u32(symbol + 4u);
            uint8_t info = symbol[12u];
            uint8_t binding = info >> 4;
            uint8_t type = info & 0x0fu;
            uint16_t section_index = read_u16(symbol + 14u);
            const char *name;
            uint32_t name_size;
            if (!bounded_string(elf_bytes, strings.offset, strings.size,
                                name_offset, &name, &name_size)) {
                return WDC_EXTENSION_ERR_STRUCTURE;
            }
            if (name_size == 0u || (binding != ELF_SYMBOL_GLOBAL && binding != ELF_SYMBOL_WEAK)) {
                continue;
            }
            if (section_index == ELF_SYMBOL_UNDEFINED) {
                int32_t allowed_index = import_index(profile, name, name_size);
                if (binding == ELF_SYMBOL_WEAK || allowed_index < 0 ||
                    profile->allowed_import_addresses[allowed_index] == 0u) {
                    return WDC_EXTENSION_ERR_IMPORT;
                }
                if (!inspection_has_import(out_inspection, name, name_size)) {
                    if (out_inspection->import_count >= WDC_EXTENSION_IMPORT_CAPACITY) {
                        return WDC_EXTENSION_ERR_IMPORT;
                    }
                    out_inspection->imports[out_inspection->import_count].name = name;
                    out_inspection->imports[out_inspection->import_count].address =
                        profile->allowed_import_addresses[allowed_index];
                    out_inspection->import_count += 1u;
                }
            } else if (type == ELF_SYMBOL_FUNCTION &&
                       string_is(name, name_size, "pulse_extension_entry_v1")) {
                /*
                 * A dynamic ELF normally repeats one exported function in
                 * both .dynsym and .symtab.  Treat equal name/binding/value
                 * records as one logical export, matching the independent
                 * Python inspector, while still rejecting aliases that point
                 * at a different address or use a different binding.
                 */
                if (entry_count == 0u) {
                    out_inspection->entry_virtual_address = value;
                    entry_binding = binding;
                    entry_count = 1u;
                } else if (out_inspection->entry_virtual_address != value ||
                           entry_binding != binding) {
                    entry_count += 1u;
                }
            }
        }
    }
    if (entry_count != 1u) {
        return WDC_EXTENSION_ERR_METADATA;
    }

    out_inspection->raw_size = elf_size;
    out_inspection->metadata_file_offset = metadata_section.offset;
    if (!sha256_bytes(elf_bytes, elf_size, out_inspection->raw_sha256) ||
        !sha256_with_zero_span(elf_bytes, elf_size, metadata_section.offset + 128u, 32u,
                               out_inspection->normalized_artifact_sha256) ||
        !sha256_with_zero_span(elf_bytes + metadata_section.offset, 192u, 128u, 32u,
                               out_inspection->normalized_metadata_sha256)) {
        return WDC_EXTENSION_ERR_DIGEST;
    }
    if (!digest_equal(out_inspection->metadata.artifact_sha256,
                      out_inspection->normalized_artifact_sha256)) {
        return WDC_EXTENSION_ERR_DIGEST;
    }
    return WDC_EXTENSION_OK;
}

static int memory_contains(uint32_t start, uint32_t size, uint32_t address, uint32_t required)
{
    return required <= size && address >= start && address - start <= size - required;
}

static int readable_contains(const WdcElfMemoryLayout *memory, uint32_t address, uint32_t size)
{
    return memory_contains(memory->executable_address, memory->executable_size, address, size) ||
           memory_contains(memory->writable_address, memory->writable_size, address, size);
}

static int descriptor_valid(const pulse_extension_descriptor_v1 *descriptor,
                            const WdcExtensionInspection *inspection,
                            const WdcElfMemoryLayout *memory)
{
    uint32_t functions[6];
    uint32_t index;
    functions[0] = (uint32_t)(uintptr_t)descriptor->init_fn;
    functions[1] = (uint32_t)(uintptr_t)descriptor->start_fn;
    functions[2] = (uint32_t)(uintptr_t)descriptor->invoke_fn;
    functions[3] = (uint32_t)(uintptr_t)descriptor->health_fn;
    functions[4] = (uint32_t)(uintptr_t)descriptor->quiesce_fn;
    functions[5] = (uint32_t)(uintptr_t)descriptor->deinit_fn;
    if (descriptor->magic != PULSE_EXTENSION_DESCRIPTOR_MAGIC_V1 ||
        descriptor->struct_size != PULSE_EXTENSION_DESCRIPTOR_SIZE_V1 ||
        descriptor->abi_major != PULSE_EXTENSION_ABI_MAJOR_V1 ||
        descriptor->abi_minor != PULSE_EXTENSION_ABI_MINOR_V1 || descriptor->flags != 0u ||
        memcmp(descriptor->extension_id, inspection->metadata.extension_id, 16u) != 0 ||
        !digest_equal(descriptor->metadata_sha256, inspection->normalized_metadata_sha256) ||
        descriptor->event_count != inspection->metadata.event_count ||
        descriptor->operation_count != inspection->metadata.operation_count ||
        memcmp(descriptor->event_ids, inspection->metadata.event_ids,
               sizeof(descriptor->event_ids)) != 0 ||
        memcmp(descriptor->operation_ids, inspection->metadata.operation_ids,
               sizeof(descriptor->operation_ids)) != 0 ||
        descriptor->reserved0 != 0u || !all_zero(descriptor->reserved1, 32u)) {
        return 0;
    }
    for (index = 0u; index < 6u; ++index) {
        if (functions[index] == 0u ||
            !memory_contains(memory->executable_address, memory->executable_size,
                             functions[index], 1u)) {
            return 0;
        }
    }
    return 1;
}

static int32_t normalize_descriptor(
    const pulse_extension_descriptor_v1 *loaded_descriptor,
    const WdcExtensionInspection *inspection,
    const WdcElfMemoryLayout *memory,
    pulse_extension_descriptor_v1 *out_descriptor)
{
    if (loaded_descriptor == NULL || inspection == NULL || memory == NULL ||
        out_descriptor == NULL ||
        !readable_contains(memory,
                           (uint32_t)(uintptr_t)loaded_descriptor,
                           sizeof(*loaded_descriptor))) {
        return WDC_EXTENSION_ERR_DESCRIPTOR;
    }
    memcpy(out_descriptor, loaded_descriptor, sizeof(*out_descriptor));
    return descriptor_valid(out_descriptor, inspection, memory)
               ? WDC_EXTENSION_OK
               : WDC_EXTENSION_ERR_DESCRIPTOR;
}

#ifdef PULSE_EXTENSION_HOST_TEST
int32_t wdc_extension_test_normalize_descriptor(
    const pulse_extension_descriptor_v1 *loaded_descriptor,
    const WdcExtensionInspection *inspection,
    const WdcElfMemoryLayout *memory,
    pulse_extension_descriptor_v1 *out_descriptor)
{
    return normalize_descriptor(loaded_descriptor, inspection, memory, out_descriptor);
}
#endif

int32_t wdc_extension_load_descriptor(const uint8_t *elf_bytes,
                                      uint32_t elf_size,
                                      const WdcExtensionInspection *inspection,
                                      WdcExtensionCandidate *out_candidate)
{
    uint8_t raw_digest[32];
    uint32_t entry_address;
    WdcExtensionEntryFn entry;
    const pulse_extension_descriptor_v1 *loaded_descriptor;
    int32_t code;
    if (elf_bytes == NULL || inspection == NULL || out_candidate == NULL ||
        elf_size != inspection->raw_size || out_candidate->state != WDC_EXTENSION_EMPTY ||
        !sha256_bytes(elf_bytes, elf_size, raw_digest) ||
        !digest_equal(raw_digest, inspection->raw_sha256)) {
        return WDC_EXTENSION_ERR_ARGUMENT;
    }
    memset(out_candidate, 0, sizeof(*out_candidate));
    out_candidate->state = WDC_EXTENSION_INSPECTED;
    out_candidate->raw_bytes = elf_bytes;
    out_candidate->raw_size = elf_size;
    memcpy(&out_candidate->inspection, inspection, sizeof(*inspection));
    code = wdc_elf_load_inspected_with_symbols(
        elf_bytes,
        elf_size,
        inspection->imports,
        inspection->import_count,
        &out_candidate->image);
    if (code != WDC_ELF_OK) {
        memset(out_candidate, 0, sizeof(*out_candidate));
        return WDC_EXTENSION_ERR_LOADER;
    }
    out_candidate->state = WDC_EXTENSION_RELOCATED;
    if (wdc_elf_memory_layout(out_candidate->image, &out_candidate->memory) != WDC_ELF_OK ||
        wdc_elf_map_virtual(out_candidate->image, inspection->entry_virtual_address,
                            &entry_address) != WDC_ELF_OK ||
        !memory_contains(out_candidate->memory.executable_address,
                         out_candidate->memory.executable_size, entry_address, 1u)) {
        wdc_extension_unload_unstarted(out_candidate);
        return WDC_EXTENSION_ERR_DESCRIPTOR;
    }
    entry = (WdcExtensionEntryFn)(uintptr_t)entry_address;
    loaded_descriptor = entry();
    /*
     * elf_loader 1.3.2 packs loaded data sections without restoring each
     * section's ELF alignment.  A correctly aligned .data.rel.ro descriptor
     * can therefore become unaligned when a non-4-byte-sized .rodata precedes
     * it.
     * Bound the loader-owned source before touching it, then normalize the
     * fixed-size descriptor into aligned host-owned storage with memcpy.
     */
    if (normalize_descriptor(loaded_descriptor,
                             inspection,
                             &out_candidate->memory,
                             &out_candidate->descriptor_storage) != WDC_EXTENSION_OK) {
        wdc_extension_unload_unstarted(out_candidate);
        return WDC_EXTENSION_ERR_DESCRIPTOR;
    }
    out_candidate->descriptor = &out_candidate->descriptor_storage;
    out_candidate->state = WDC_EXTENSION_DESCRIPTOR_VALIDATED;
    return WDC_EXTENSION_OK;
}

void wdc_extension_registry_init(WdcExtensionRegistry *registry)
{
    if (registry != NULL) {
        memset(registry, 0, sizeof(*registry));
    }
}

static int candidate_conflicts(const WdcExtensionCandidate *left,
                               const WdcExtensionCandidate *right)
{
    uint32_t l;
    uint32_t r;
    if (memcmp(left->descriptor->extension_id, right->descriptor->extension_id, 16u) == 0) {
        return 1;
    }
    for (l = 0u; l < left->descriptor->event_count; ++l) {
        for (r = 0u; r < right->descriptor->event_count; ++r) {
            if (left->descriptor->event_ids[l] == right->descriptor->event_ids[r]) {
                return 1;
            }
        }
    }
    for (l = 0u; l < left->descriptor->operation_count; ++l) {
        for (r = 0u; r < right->descriptor->operation_count; ++r) {
            if (left->descriptor->operation_ids[l] == right->descriptor->operation_ids[r]) {
                return 1;
            }
        }
    }
    return 0;
}

int32_t wdc_extension_registry_add(WdcExtensionRegistry *registry,
                                   WdcExtensionCandidate *candidate)
{
    uint32_t index;
    if (registry == NULL || candidate == NULL || registry->sealed != 0u ||
        candidate->state != WDC_EXTENSION_DESCRIPTOR_VALIDATED) {
        return WDC_EXTENSION_ERR_STATE;
    }
    if (registry->count >= WDC_EXTENSION_REGISTRY_CAPACITY) {
        return WDC_EXTENSION_ERR_BUDGET;
    }
    for (index = 0u; index < registry->count; ++index) {
        if (candidate_conflicts(registry->candidates[index], candidate)) {
            return WDC_EXTENSION_ERR_DUPLICATE;
        }
    }
    registry->candidates[registry->count++] = candidate;
    return WDC_EXTENSION_OK;
}

int32_t wdc_extension_registry_seal(WdcExtensionRegistry *registry)
{
    uint32_t index;
    if (registry == NULL || registry->sealed != 0u || registry->count == 0u) {
        return WDC_EXTENSION_ERR_STATE;
    }
    registry->sealed = 1u;
    for (index = 0u; index < registry->count; ++index) {
        registry->candidates[index]->state = WDC_EXTENSION_REGISTRY_SEALED;
    }
    return WDC_EXTENSION_OK;
}

int32_t wdc_extension_unload_unstarted(WdcExtensionCandidate *candidate)
{
    int32_t code;
    if (candidate == NULL || candidate->state == WDC_EXTENSION_REGISTRY_SEALED) {
        return WDC_EXTENSION_ERR_STATE;
    }
    code = wdc_elf_unload(&candidate->image);
    if (code != WDC_ELF_OK) {
        return WDC_EXTENSION_ERR_LOADER;
    }
    memset(candidate, 0, sizeof(*candidate));
    return WDC_EXTENSION_OK;
}

static int32_t (*volatile s_keep_inspect)(const uint8_t *, uint32_t,
                                          const WdcExtensionProfile *,
                                          WdcExtensionInspection *) = wdc_extension_inspect;
static int32_t (*volatile s_keep_load)(const uint8_t *, uint32_t,
                                       const WdcExtensionInspection *,
                                       WdcExtensionCandidate *) = wdc_extension_load_descriptor;
static int32_t (*volatile s_keep_add)(WdcExtensionRegistry *, WdcExtensionCandidate *) =
    wdc_extension_registry_add;
static int32_t (*volatile s_keep_seal)(WdcExtensionRegistry *) = wdc_extension_registry_seal;
static int32_t (*volatile s_keep_initialize)(WdcExtensionRegistry *,
                                             const pulse_extension_init_args_v1 *) =
    wdc_extension_registry_initialize;
static int32_t (*volatile s_keep_start)(WdcExtensionRegistry *) =
    wdc_extension_registry_start;
static int32_t (*volatile s_keep_quiesce)(WdcExtensionRegistry *,
                                          const pulse_extension_quiesce_v1 *) =
    wdc_extension_registry_quiesce;
static int32_t (*volatile s_keep_deinitialize)(WdcExtensionRegistry *) =
    wdc_extension_registry_deinitialize;

uint32_t wdc_extension_link_anchor(void)
{
    return s_keep_inspect != NULL && s_keep_load != NULL &&
           s_keep_add != NULL && s_keep_seal != NULL &&
           s_keep_initialize != NULL && s_keep_start != NULL &&
           s_keep_quiesce != NULL && s_keep_deinitialize != NULL;
}
