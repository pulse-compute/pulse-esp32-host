idf_component_register(
    SRCS "wdc_net.c"
    INCLUDE_DIRS "include"
    REQUIRES wdc_abi wdc_diag wdc_events wdc_profile
)
