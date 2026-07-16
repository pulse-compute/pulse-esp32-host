idf_component_register(
    SRCS "wdc_security.c"
    INCLUDE_DIRS "include"
    REQUIRES wdc_abi wdc_bundle wdc_diag wdc_profile
)
