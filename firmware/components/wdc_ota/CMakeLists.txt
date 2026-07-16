idf_component_register(
    SRCS "wdc_ota.c"
    INCLUDE_DIRS "include"
    REQUIRES wdc_abi wdc_bundle esp_partition
)
