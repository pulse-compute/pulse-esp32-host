idf_component_register(
    SRCS "wdc_event_queue.c" "wdc_event_encode.c"
    INCLUDE_DIRS "include"
    REQUIRES wdc_abi
    PRIV_REQUIRES freertos
)
