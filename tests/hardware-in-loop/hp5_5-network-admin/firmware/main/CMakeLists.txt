foreach(HP55_GENERATED
        hp5_5_campaign_config.h
        hp5_5_fixture_blobs.c
        hp5_5_fixture_blobs.h
        hp5_5_provision.c
        hp5_5_provision.h)
    if(NOT EXISTS "${CMAKE_CURRENT_LIST_DIR}/${HP55_GENERATED}")
        message(FATAL_ERROR
            "generated HP5.5 input ${HP55_GENERATED} is missing; use tools/build_hp5_5_network_hardware.py")
    endif()
endforeach()

set(HP55_TARGET_REQUIRES "")
idf_build_get_property(HP55_IDF_TARGET IDF_TARGET)
if(HP55_IDF_TARGET STREQUAL "esp32s3")
    list(APPEND HP55_TARGET_REQUIRES esp_psram)
endif()

idf_component_register(
    SRCS
        "hp5_5_network_admin_main.c"
        "hp5_5_fixture_blobs.c"
        "hp5_5_provision.c"
    INCLUDE_DIRS "."
    REQUIRES
        esp_event
        esp_hw_support
        esp_system
        esp_timer
        freertos
        heap
        nvs_flash
        pthread
        spi_flash
        wdc_abi
        wdc_activation
        wdc_admin
        wdc_app_slots
        wdc_bundle
        wdc_caps
        wdc_control
        wdc_host_identity
        wdc_http
        wdc_net
        wdc_ota
        wdc_profile
        wdc_runtime
    PRIV_REQUIRES esp_wifi ${HP55_TARGET_REQUIRES}
)

target_compile_options(${COMPONENT_LIB} PRIVATE -Wall -Wextra -Werror)
