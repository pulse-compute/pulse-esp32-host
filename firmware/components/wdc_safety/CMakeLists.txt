idf_component_register(
    SRCS "wdc_safety.c"
    INCLUDE_DIRS "include"
    REQUIRES wdc_abi wdc_caps wdc_diag wdc_events wdc_hal wdc_profile wdc_runtime
)
