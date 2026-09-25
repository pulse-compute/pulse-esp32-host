idf_component_register(
    SRCS "wdc_control.c" "wdc_control_platform_espidf.c"
    INCLUDE_DIRS "include"
    REQUIRES wdc_abi
    PRIV_REQUIRES freertos heap
)
