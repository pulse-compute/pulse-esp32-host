idf_component_register(
    SRCS "app_main.c" "shell_main.c"
    INCLUDE_DIRS "."
    REQUIRES wdc_abi wdc_activation wdc_app wdc_bundle wdc_caps wdc_diag wdc_events wdc_profile wdc_hal wdc_net wdc_runtime wdc_safety wdc_security wdc_ota nvs_flash app_update esp_partition freertos
)
