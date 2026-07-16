#![no_std]

use core::panic::PanicInfo;
use wdc_guest::abi::{WDC_OK, WDC_R3_RESOURCE_RELAY_1};
use wdc_guest::host;

#[no_mangle]
pub extern "C" fn wdc_module_init() -> i32 {
    match host::gpio_set(WDC_R3_RESOURCE_RELAY_1, false) {
        Ok(()) => WDC_OK,
        Err(status) => status,
    }
}

#[no_mangle]
pub extern "C" fn wdc_module_on_event(_event_ptr: u32, _event_len: u32) -> i32 {
    match host::gpio_get(WDC_R3_RESOURCE_RELAY_1) {
        Ok(value) => match host::gpio_set(WDC_R3_RESOURCE_RELAY_1, !value) {
            Ok(()) => WDC_OK,
            Err(status) => status,
        },
        Err(status) => status,
    }
}

#[no_mangle]
pub extern "C" fn wdc_module_health() -> i32 {
    WDC_OK
}

#[no_mangle]
pub extern "C" fn wdc_module_shutdown(_reason: i32) -> i32 {
    WDC_OK
}

#[panic_handler]
fn panic(_info: &PanicInfo) -> ! {
    loop {}
}
