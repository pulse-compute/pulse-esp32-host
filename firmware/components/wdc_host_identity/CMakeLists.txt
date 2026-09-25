idf_component_register(
    SRCS "wdc_host_identity.c" "wdc_host_fingerprint_generated.c"
    INCLUDE_DIRS "include"
    REQUIRES wdc_abi wdc_control
)
