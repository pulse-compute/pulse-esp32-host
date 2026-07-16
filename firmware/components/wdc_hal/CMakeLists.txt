idf_component_register(
    SRCS "wdc_gpio_espidf.c"
    INCLUDE_DIRS "include"
    REQUIRES wdc_abi wdc_profile driver
)
