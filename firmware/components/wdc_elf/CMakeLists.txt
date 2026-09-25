set(WDC_ELF_SOURCES "wdc_elf.c")

if(CONFIG_ELF_LOADER_LOAD_PSRAM)
    list(APPEND WDC_ELF_SOURCES "wdc_elf_allocator.c")
elseif(CONFIG_IDF_TARGET_ESP32C6)
    list(APPEND WDC_ELF_SOURCES "wdc_elf_c6_allocator.c")
endif()

idf_component_register(
    SRCS ${WDC_ELF_SOURCES}
    INCLUDE_DIRS "include"
    PRIV_REQUIRES elf_loader heap
    WHOLE_ARCHIVE
)

if(CONFIG_ELF_LOADER_LOAD_PSRAM OR CONFIG_IDF_TARGET_ESP32C6)
    # Both isolated hardware lanes override the pinned loader's allocator:
    # S3 keeps text in PSRAM while retaining ELF-owned task/queue state in
    # internal byte-accessible RAM; C6 restores the executable capability
    # discarded by the unified-segment branch.
    idf_build_set_property(LINK_OPTIONS "-Wl,--wrap=esp_elf_malloc" APPEND)
    idf_build_set_property(LINK_OPTIONS "-Wl,--wrap=esp_elf_free" APPEND)
    target_link_libraries(${COMPONENT_LIB} INTERFACE
        "-u __wrap_esp_elf_malloc"
        "-u __wrap_esp_elf_free")
endif()
