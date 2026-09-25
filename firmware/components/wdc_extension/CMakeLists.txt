idf_component_register(
    SRCS
        "wdc_extension.c"
        "wdc_extension_bridge.c"
        "wdc_extension_host_services.c"
        "wdc_extension_lifecycle.c"
        "wdc_extension_platform_espidf.c"
        "wdc_extension_sha256.c"
    INCLUDE_DIRS "include" "../../../native-sdk/c/include"
    REQUIRES esp_timer freertos wdc_elf wdc_abi wdc_events wdc_runtime
    WHOLE_ARCHIVE
)

get_filename_component(PULSE_NATIVE_SDK_DIR "${CMAKE_CURRENT_LIST_DIR}/../../../native-sdk" ABSOLUTE)
target_compile_options(${COMPONENT_LIB} PRIVATE
    "-fdebug-prefix-map=${PULSE_NATIVE_SDK_DIR}=/NATIVE_SDK"
    "-fmacro-prefix-map=${PULSE_NATIVE_SDK_DIR}=/NATIVE_SDK"
)
