//! R4 event envelope decoding helpers.

use crate::abi::*;
use crate::encoding;

pub use crate::abi::{
    WDC_EVENT_BOOT, WDC_EVENT_CONFIG_CHANGED, WDC_EVENT_FAULT, WDC_EVENT_GPIO_CHANGED,
    WDC_EVENT_MODULE_PROBATION_ENDING, WDC_EVENT_MODULE_PROBATION_STARTED,
    WDC_EVENT_NET_CONNECTED, WDC_EVENT_NET_DISCONNECTED, WDC_EVENT_MQTT_MESSAGE,
    WDC_EVENT_HTTP_RESPONSE, WDC_EVENT_NETWORK_STATUS_CHANGED, WDC_EVENT_SHUTDOWN_REQUEST,
    WDC_EVENT_TIMER_FIRED,
};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct EventEnvelope<'a> {
    pub abi_version: u32,
    pub event_type: u32,
    pub event_id: u32,
    pub timestamp_ms: u64,
    pub resource_id: Option<u32>,
    pub payload: &'a [u8],
}

pub fn decode_event_envelope(buf: &[u8]) -> Result<EventEnvelope<'_>, i32> {
    let abi_version = encoding::find_u32(buf, WDC_CBOR_KEY_ABI_VERSION)?;
    if abi_version != WDC_R4_EVENT_ABI_VERSION {
        return Err(WDC_ERR_UNSUPPORTED_ABI);
    }
    let resource_id = match encoding::find_u32(buf, WDC_CBOR_KEY_RESOURCE_ID) {
        Ok(id) => Some(id),
        Err(WDC_ERR_NOT_AVAILABLE) => None,
        Err(e) => return Err(e),
    };
    let payload = match encoding::find_bytes(buf, WDC_CBOR_KEY_PAYLOAD) {
        Ok(bytes) => bytes,
        Err(WDC_ERR_NOT_AVAILABLE) => &[],
        Err(e) => return Err(e),
    };
    Ok(EventEnvelope {
        abi_version,
        event_type: encoding::find_u32(buf, WDC_CBOR_KEY_EVENT_TYPE)?,
        event_id: encoding::find_u32(buf, WDC_CBOR_KEY_EVENT_ID)?,
        timestamp_ms: encoding::find_u64(buf, WDC_CBOR_KEY_TIMESTAMP_MS)?,
        resource_id,
        payload,
    })
}
