idf_component_register(
    SRCS "wdc_diag.c"
    INCLUDE_DIRS "include"
    REQUIRES wdc_abi esp_timer esp_system
)
