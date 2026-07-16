use crate::abi::*;
use crate::encoding::{self, Encoder};

#[repr(i32)]
pub enum LogLevel {
    Debug = 0,
    Info = 1,
    Warn = 2,
    Error = 3,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct SysInfo<'a> {
    pub abi_major: u32,
    pub abi_minor: u32,
    pub shell_version: &'a str,
    pub build_stage: &'a str,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct NetStatus {
    pub connected: bool,
    pub state: u32,
    pub last_request_id: u32,
}

#[cfg(target_arch = "wasm32")]
#[link(wasm_import_module = "wdc")]
extern "C" {
    #[link_name = "wdc_log"]
    fn wdc_import_log(level: i32, ptr: u32, len: u32) -> i32;
    #[link_name = "wdc_millis"]
    fn wdc_import_millis() -> u64;
    #[link_name = "wdc_random"]
    fn wdc_import_random(ptr: u32, len: u32) -> i32;
    #[link_name = "wdc_yield"]
    fn wdc_import_yield() -> i32;
    #[link_name = "wdc_host_call"]
    fn wdc_import_host_call(opcode: u32, req_ptr: u32, req_len: u32, rsp_ptr: u32, rsp_cap: u32) -> i32;
}

pub fn log(level: LogLevel, msg: &str) -> i32 {
    #[cfg(target_arch = "wasm32")]
    unsafe {
        return wdc_import_log(level as i32, msg.as_ptr() as u32, msg.len() as u32);
    }

    #[cfg(not(target_arch = "wasm32"))]
    {
        let _ = (level, msg);
        WDC_OK
    }
}

pub fn millis() -> u64 {
    #[cfg(target_arch = "wasm32")]
    unsafe {
        return wdc_import_millis();
    }

    #[cfg(not(target_arch = "wasm32"))]
    {
        0
    }
}

pub fn random(buf: &mut [u8]) -> i32 {
    #[cfg(target_arch = "wasm32")]
    unsafe {
        return wdc_import_random(buf.as_mut_ptr() as u32, buf.len() as u32);
    }

    #[cfg(not(target_arch = "wasm32"))]
    {
        for b in buf.iter_mut() {
            *b = 0;
        }
        WDC_OK
    }
}

pub fn yield_now() -> i32 {
    #[cfg(target_arch = "wasm32")]
    unsafe {
        return wdc_import_yield();
    }

    #[cfg(not(target_arch = "wasm32"))]
    {
        WDC_OK
    }
}

pub fn host_call(opcode: u32, request: &[u8], response: &mut [u8]) -> i32 {
    #[cfg(target_arch = "wasm32")]
    unsafe {
        return wdc_import_host_call(
            opcode,
            request.as_ptr() as u32,
            request.len() as u32,
            response.as_mut_ptr() as u32,
            response.len() as u32,
        );
    }

    #[cfg(not(target_arch = "wasm32"))]
    {
        let _ = (opcode, request, response);
        WDC_ERR_NOT_AVAILABLE
    }
}

fn status_from_response(call_status: i32, response: &[u8]) -> Result<(), i32> {
    if call_status != WDC_OK {
        return Err(call_status);
    }
    let contract_status = encoding::response_status(response)?;
    if contract_status == WDC_OK {
        Ok(())
    } else {
        Err(contract_status)
    }
}

pub fn sys_get_info<'a>(response: &'a mut [u8]) -> Result<SysInfo<'a>, i32> {
    let request = [0xa0u8];
    let call_status = host_call(WDC_OP_SYS_GET_INFO, &request, response);
    status_from_response(call_status, response)?;
    Ok(SysInfo {
        abi_major: encoding::find_u32(response, WDC_CBOR_KEY_ABI_MAJOR)?,
        abi_minor: encoding::find_u32(response, WDC_CBOR_KEY_ABI_MINOR)?,
        shell_version: encoding::find_text(response, WDC_CBOR_KEY_SHELL_VERSION)?,
        build_stage: encoding::find_text(response, WDC_CBOR_KEY_BUILD_STAGE)?,
    })
}

pub fn timer_set(timer_id: u32, delay_ms: u32, repeat: bool) -> Result<(), i32> {
    let mut request = [0u8; 32];
    let mut response = [0u8; 32];
    let mut enc = Encoder::new(&mut request);
    enc.begin_map(3)?;
    enc.key_u32(WDC_CBOR_KEY_TIMER_ID, timer_id)?;
    enc.key_u32(WDC_CBOR_KEY_DELAY_MS, delay_ms)?;
    enc.key_bool(WDC_CBOR_KEY_REPEAT, repeat)?;
    let call_status = host_call(WDC_OP_TIMER_SET, enc.as_slice(), &mut response);
    status_from_response(call_status, &response)
}

pub fn timer_cancel(timer_id: u32) -> Result<(), i32> {
    let mut request = [0u8; 16];
    let mut response = [0u8; 32];
    let mut enc = Encoder::new(&mut request);
    enc.begin_map(1)?;
    enc.key_u32(WDC_CBOR_KEY_TIMER_ID, timer_id)?;
    let call_status = host_call(WDC_OP_TIMER_CANCEL, enc.as_slice(), &mut response);
    status_from_response(call_status, &response)
}

pub fn gpio_set(resource_id: u32, value: bool) -> Result<(), i32> {
    let mut request = [0u8; 16];
    let mut response = [0u8; 32];
    let mut enc = Encoder::new(&mut request);
    enc.begin_map(2)?;
    enc.key_u32(WDC_CBOR_KEY_RESOURCE_ID, resource_id)?;
    enc.key_bool(WDC_CBOR_KEY_VALUE, value)?;
    let call_status = host_call(WDC_OP_GPIO_SET, enc.as_slice(), &mut response);
    status_from_response(call_status, &response)
}

pub fn gpio_get(resource_id: u32) -> Result<bool, i32> {
    let mut request = [0u8; 16];
    let mut response = [0u8; 40];
    let mut enc = Encoder::new(&mut request);
    enc.begin_map(1)?;
    enc.key_u32(WDC_CBOR_KEY_RESOURCE_ID, resource_id)?;
    let call_status = host_call(WDC_OP_GPIO_GET, enc.as_slice(), &mut response);
    status_from_response(call_status, &response)?;
    Ok(encoding::find_u32(&response, WDC_CBOR_KEY_VALUE)? != 0)
}

pub fn config_set(key: &str, value: &[u8], request: &mut [u8], response: &mut [u8]) -> Result<(), i32> {
    let mut enc = Encoder::new(request);
    enc.begin_map(2)?;
    enc.key_text(WDC_CBOR_KEY_KEY, key)?;
    enc.key_bytes(WDC_CBOR_KEY_DATA, value)?;
    let call_status = host_call(WDC_OP_CONFIG_SET, enc.as_slice(), response);
    status_from_response(call_status, response)
}

pub fn config_get<'a>(key: &str, request: &mut [u8], response: &'a mut [u8]) -> Result<&'a [u8], i32> {
    let mut enc = Encoder::new(request);
    enc.begin_map(1)?;
    enc.key_text(WDC_CBOR_KEY_KEY, key)?;
    let call_status = host_call(WDC_OP_CONFIG_GET, enc.as_slice(), response);
    status_from_response(call_status, response)?;
    encoding::find_bytes(response, WDC_CBOR_KEY_DATA)
}


pub fn net_status(response: &mut [u8]) -> Result<NetStatus, i32> {
    let request = [0xa0u8];
    let call_status = host_call(WDC_OP_NET_STATUS, &request, response);
    status_from_response(call_status, response)?;
    Ok(NetStatus {
        connected: encoding::find_bool(response, WDC_CBOR_KEY_CONNECTED)?,
        state: encoding::find_u32(response, WDC_CBOR_KEY_NETWORK_STATE)?,
        last_request_id: match encoding::find_u32(response, WDC_CBOR_KEY_REQUEST_ID) {
            Ok(id) => id,
            Err(WDC_ERR_NOT_AVAILABLE) => 0,
            Err(e) => return Err(e),
        },
    })
}

pub fn mqtt_publish(resource_id: u32, topic: &str, payload: &[u8], qos: u32, request: &mut [u8], response: &mut [u8]) -> Result<u32, i32> {
    let mut enc = Encoder::new(request);
    enc.begin_map(4)?;
    enc.key_u32(WDC_CBOR_KEY_RESOURCE_ID, resource_id)?;
    enc.key_text(WDC_CBOR_KEY_TOPIC, topic)?;
    enc.key_bytes(WDC_CBOR_KEY_DATA, payload)?;
    enc.key_u32(WDC_CBOR_KEY_QOS, qos)?;
    let call_status = host_call(WDC_OP_MQTT_PUBLISH, enc.as_slice(), response);
    status_from_response(call_status, response)?;
    encoding::find_u32(response, WDC_CBOR_KEY_REQUEST_ID)
}

pub fn mqtt_subscribe(resource_id: u32, topic: &str, request: &mut [u8], response: &mut [u8]) -> Result<u32, i32> {
    let mut enc = Encoder::new(request);
    enc.begin_map(2)?;
    enc.key_u32(WDC_CBOR_KEY_RESOURCE_ID, resource_id)?;
    enc.key_text(WDC_CBOR_KEY_TOPIC, topic)?;
    let call_status = host_call(WDC_OP_MQTT_SUBSCRIBE, enc.as_slice(), response);
    status_from_response(call_status, response)?;
    encoding::find_u32(response, WDC_CBOR_KEY_REQUEST_ID)
}

pub fn http_request(resource_id: u32, method: &str, url: &str, body: &[u8], request: &mut [u8], response: &mut [u8]) -> Result<(u32, u32), i32> {
    let mut enc = Encoder::new(request);
    enc.begin_map(4)?;
    enc.key_u32(WDC_CBOR_KEY_RESOURCE_ID, resource_id)?;
    enc.key_text(WDC_CBOR_KEY_METHOD, method)?;
    enc.key_text(WDC_CBOR_KEY_URL, url)?;
    enc.key_bytes(WDC_CBOR_KEY_DATA, body)?;
    let call_status = host_call(WDC_OP_HTTP_REQUEST, enc.as_slice(), response);
    status_from_response(call_status, response)?;
    Ok((
        encoding::find_u32(response, WDC_CBOR_KEY_REQUEST_ID)?,
        encoding::find_u32(response, WDC_CBOR_KEY_HTTP_STATUS)?,
    ))
}
