idf_component_register(
    SRCS "app_main.c" "shell_main.c"
    INCLUDE_DIRS "."
    REQUIRES wdc_abi wdc_activation wdc_admin wdc_app wdc_app_slots wdc_bundle wdc_caps wdc_control wdc_diag wdc_elf wdc_extension wdc_events wdc_host_identity wdc_profile wdc_hal wdc_http wdc_net wdc_runtime wdc_safety wdc_security wdc_ota nvs_flash app_update esp_partition freertos pthread
)
