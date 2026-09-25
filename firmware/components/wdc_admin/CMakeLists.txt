idf_component_register(
    SRCS "wdc_admin.c" "wdc_admin_serial.c" "wdc_admin_update.c" "wdc_admin_recovery.c"
    INCLUDE_DIRS "include"
    REQUIRES wdc_abi wdc_activation wdc_app_slots wdc_bundle wdc_control wdc_host_identity wdc_ota
)
