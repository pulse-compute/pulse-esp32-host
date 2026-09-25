#include "wdc_http_service.h"

#include "wdc_runtime.h"

int32_t wdc_http_runtime_dispatch(void *context,
                                  const uint8_t *event_cbor,
                                  uint32_t event_bytes,
                                  uint64_t deadline_ms)
{
    (void)deadline_ms;
    if (context == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    return wdc_runtime_call_event_cbor((WdcRuntime *)context, event_cbor,
                                       event_bytes);
}
