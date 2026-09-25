idf_component_register(
    SRCS "wdc_app_slots.c"
    INCLUDE_DIRS "include"
    REQUIRES wdc_abi wdc_activation wdc_bundle wdc_host_identity wdc_ota
)
