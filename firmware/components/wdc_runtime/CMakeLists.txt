set(WDC_RUNTIME_SOURCES
    "wdc_runtime.c"
    "wdc_runtime_buffer.c"
    "wdc_static_wasm.c")

if(CONFIG_ELF_LOADER_LOAD_PSRAM)
    list(APPEND WDC_RUNTIME_SOURCES "wdc_runtime_allocator.c")
endif()

idf_component_register(
    SRCS ${WDC_RUNTIME_SOURCES}
    INCLUDE_DIRS "include"
    REQUIRES wdc_abi wdc_diag wdc_events
    PRIV_REQUIRES wasm-micro-runtime esp_timer esp_hw_support freertos heap
)

if(CONFIG_ELF_LOADER_LOAD_PSRAM)
    # WAMR 2.4.0~1 otherwise maps writable linear memory into the same
    # cache-backed PSRAM pool used for loaded native text.  Keep the named
    # board lane's linear memory internal while leaving executable mappings
    # under the pinned WAMR port's policy.
    idf_build_set_property(LINK_OPTIONS "-Wl,--wrap=os_mmap" APPEND)
    target_link_libraries(${COMPONENT_LIB} INTERFACE "-u __wrap_os_mmap")
endif()
