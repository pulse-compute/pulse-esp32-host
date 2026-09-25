if(NOT EXISTS "${CMAKE_CURRENT_LIST_DIR}/hx45_extension_blob.c")
    message(FATAL_ERROR
        "generated HX4.5 extension blob is missing; use tools/build_hx45_s3_aitrip.py")
endif()

idf_component_register(
    SRCS "hx45_s3_aitrip_main.c" "hx45_extension_blob.c"
    INCLUDE_DIRS "."
    REQUIRES
        esp_psram
        esp_hw_support
        esp_timer
        esp_system
        freertos
        heap
        pthread
        spi_flash
        wdc_abi
        wdc_diag
        wdc_elf
        wdc_events
        wdc_extension
        wdc_runtime
)

target_compile_options(${COMPONENT_LIB} PRIVATE -Wall -Wextra -Werror)
if(PULSE_HX5B_PRESSURE)
    target_compile_definitions(${COMPONENT_LIB} PRIVATE PULSE_HX5B_PRESSURE=1)
endif()
