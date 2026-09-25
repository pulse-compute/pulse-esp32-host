#include "wdc_admin.h"

#include <string.h>

_Static_assert(sizeof(WdcAdminSerialAdapter) <=
                   WDC_ADMIN_SERIAL_STATIC_BUDGET_BYTES,
               "HP4.1 serial normalizer exceeds its fixed budget");

static uint16_t read_u16_le(const uint8_t *bytes)
{
    return (uint16_t)((uint16_t)bytes[0] |
                      ((uint16_t)bytes[1] << 8u));
}

static uint32_t read_u32_le(const uint8_t *bytes)
{
    return (uint32_t)bytes[0] |
           ((uint32_t)bytes[1] << 8u) |
           ((uint32_t)bytes[2] << 16u) |
           ((uint32_t)bytes[3] << 24u);
}

static uint64_t read_u64_le(const uint8_t *bytes)
{
    return (uint64_t)read_u32_le(bytes) |
           ((uint64_t)read_u32_le(bytes + 4u) << 32u);
}

static void decode_request(const uint8_t *bytes, WdcAdminRequest *request)
{
    memset(request, 0, sizeof(*request));
    request->struct_size = read_u32_le(bytes + 0u);
    request->version_major = read_u16_le(bytes + 4u);
    request->version_minor = read_u16_le(bytes + 6u);
    request->command = read_u32_le(bytes + 8u);
    request->flags = read_u32_le(bytes + 12u);
    request->payload_bytes = read_u32_le(bytes + 16u);
    request->slot = read_u32_le(bytes + 20u);
    request->expected_total_bytes = read_u32_le(bytes + 24u);
    request->reserved0 = read_u32_le(bytes + 28u);
    request->request_id = read_u64_le(bytes + 32u);
    request->deadline_ms = read_u64_le(bytes + 40u);
    request->authorization_epoch = read_u64_le(bytes + 48u);
    request->session_nonce = read_u64_le(bytes + 56u);
    request->command_sequence = read_u64_le(bytes + 64u);
    memcpy(request->artifact_sha256, bytes + 72u,
           sizeof(request->artifact_sha256));
    memcpy(request->reserved1, bytes + 104u,
           sizeof(request->reserved1));
}

static int32_t reject_frame(WdcAdminSerialAdapter *adapter,
                            WdcAdminPreacceptRejection rejection,
                            WdcAdminPreacceptResult *out_rejection)
{
    int32_t status = wdc_admin_rejection_status(rejection);
    memset(out_rejection, 0, sizeof(*out_rejection));
    out_rejection->rejection = rejection;
    out_rejection->status = status;
    wdc_admin_serial_reset(adapter);
    return status;
}

int32_t wdc_admin_serial_init(WdcAdminSerialAdapter *adapter,
                              WdcAdminCore *core)
{
    if (adapter == NULL || core == NULL || !core->initialized) {
        return WDC_ERR_BAD_POINTER;
    }
    memset(adapter, 0, sizeof(*adapter));
    adapter->core = core;
    return WDC_OK;
}

void wdc_admin_serial_reset(WdcAdminSerialAdapter *adapter)
{
    WdcAdminCore *core;
    if (adapter == NULL) {
        return;
    }
    core = adapter->core;
    memset(adapter, 0, sizeof(*adapter));
    adapter->core = core;
}

int32_t wdc_admin_serial_feed(
    WdcAdminSerialAdapter *adapter,
    const uint8_t *bytes,
    uint32_t bytes_len,
    uint64_t now_ms,
    uint32_t *out_consumed,
    bool *out_frame_complete,
    WdcAdminPreacceptResult *out_rejection)
{
    uint32_t body_bytes;
    if (adapter == NULL || out_consumed == NULL ||
        out_frame_complete == NULL || out_rejection == NULL ||
        adapter->core == NULL || !adapter->core->initialized ||
        (bytes_len != 0u && bytes == NULL)) {
        return WDC_ERR_BAD_POINTER;
    }
    *out_consumed = 0u;
    *out_frame_complete = false;
    memset(out_rejection, 0, sizeof(*out_rejection));
    while (*out_consumed < bytes_len) {
        if (adapter->received_bytes >= WDC_ADMIN_MAX_FRAME_BYTES) {
            *out_frame_complete = true;
            return reject_frame(adapter, WDC_ADMIN_REJECTION_BOUNDS,
                                out_rejection);
        }
        adapter->frame[adapter->received_bytes] = bytes[*out_consumed];
        adapter->received_bytes += 1u;
        *out_consumed += 1u;
        if (!adapter->header_ready && adapter->received_bytes == 4u) {
            body_bytes = read_u32_le(adapter->frame);
            if (body_bytes < WDC_ADMIN_REQUEST_BYTES) {
                *out_frame_complete = true;
                return reject_frame(adapter, WDC_ADMIN_REJECTION_BAD_FRAME,
                                    out_rejection);
            }
            if (body_bytes > WDC_ADMIN_MAX_FRAME_BYTES - 4u) {
                *out_frame_complete = true;
                return reject_frame(adapter, WDC_ADMIN_REJECTION_BOUNDS,
                                    out_rejection);
            }
            adapter->expected_frame_bytes = body_bytes + 4u;
            adapter->header_ready = true;
        }
        if (adapter->header_ready &&
            adapter->received_bytes == adapter->expected_frame_bytes) {
            WdcAdminRequest request;
            uint32_t payload_bytes =
                adapter->expected_frame_bytes - 4u - WDC_ADMIN_REQUEST_BYTES;
            int32_t status;
            decode_request(adapter->frame + 4u, &request);
            status = wdc_admin_submit(
                adapter->core,
                &request,
                payload_bytes != 0u
                    ? adapter->frame + 4u + WDC_ADMIN_REQUEST_BYTES
                    : NULL,
                payload_bytes,
                now_ms,
                out_rejection);
            wdc_admin_serial_reset(adapter);
            *out_frame_complete = true;
            return status;
        }
    }
    return WDC_OK;
}
