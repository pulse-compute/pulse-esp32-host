idf_component_register(
    SRCS "wdc_http.c" "wdc_http_service.c" "wdc_http_runtime.c" "wdc_http_platform_espidf.c"
    INCLUDE_DIRS "include"
    REQUIRES wdc_abi wdc_admin wdc_net wdc_runtime
    PRIV_REQUIRES esp_event esp_http_server esp_https_server esp_netif esp_timer esp_wifi freertos
)
