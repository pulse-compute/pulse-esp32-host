idf_component_register(
    SRCS "wdc_app.c"
    INCLUDE_DIRS "include"
    REQUIRES wdc_abi wdc_activation wdc_bundle wdc_caps wdc_diag wdc_ota wdc_profile wdc_runtime wdc_safety
)
