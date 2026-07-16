#![no_std]

use core::panic::PanicInfo;
use wdc_guest::abi::WDC_OK;
use wdc_guest::host::{self, LogLevel};

#[no_mangle]
pub extern "C" fn wdc_module_init() -> i32 {
    host::log(LogLevel::Info, "noop bundle init");
    WDC_OK
}

#[no_mangle]
pub extern "C" fn wdc_module_on_event(_event_ptr: u32, _event_len: u32) -> i32 {
    WDC_OK
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
