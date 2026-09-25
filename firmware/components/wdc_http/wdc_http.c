#include "wdc_http.h"

uint32_t wdc_http_link_anchor(void)
{
    return wdc_http_service_link_anchor() + wdc_http_platform_link_anchor();
}
