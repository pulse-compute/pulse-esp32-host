#![no_std]

pub mod abi;
pub mod encoding;
pub mod events;
pub mod host;

pub use abi::*;

#[inline]
pub fn ok() -> i32 {
    WDC_OK
}
