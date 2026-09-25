if(NOT EXISTS "${CMAKE_CURRENT_LIST_DIR}/hp3_5_campaign_config.h" OR
   NOT EXISTS "${CMAKE_CURRENT_LIST_DIR}/hp3_5_bundle_blob.c")
    message(FATAL_ERROR
        "generated HP3.5 campaign inputs are missing; use tools/build_hp3_5_slot_hardware.py")
endif()

set(HP35_TARGET_REQUIRES "")
idf_build_get_property(HP35_IDF_TARGET IDF_TARGET)
if(HP35_IDF_TARGET STREQUAL "esp32s3")
    list(APPEND HP35_TARGET_REQUIRES esp_psram)
endif()

idf_component_register(
    SRCS "hp3_5_slot_hardware_main.c" "hp3_5_bundle_blob.c"
    INCLUDE_DIRS "."
    REQUIRES
        esp_hw_support
        esp_partition
        esp_system
        esp_timer
        freertos
        heap
        mbedtls
        nvs_flash
        spi_flash
        wdc_abi
        wdc_activation
        wdc_app_slots
        wdc_bundle
        wdc_control
        wdc_host_identity
        wdc_ota
        wdc_profile
    PRIV_REQUIRES
        ${HP35_TARGET_REQUIRES}
)

target_compile_options(${COMPONENT_LIB} PRIVATE -Wall -Wextra -Werror)
