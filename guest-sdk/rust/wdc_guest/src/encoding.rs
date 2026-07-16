use crate::abi::{
    WDC_ERR_BAD_ENCODING, WDC_ERR_BAD_LENGTH, WDC_ERR_BAD_POINTER, WDC_ERR_NOT_AVAILABLE,
    WDC_ERR_RESPONSE_TOO_SMALL, WDC_OK,
};

const MAJOR_UNSIGNED: u8 = 0;
const MAJOR_NEGATIVE: u8 = 1;
const MAJOR_BYTES: u8 = 2;
const MAJOR_TEXT: u8 = 3;
const MAJOR_ARRAY: u8 = 4;
const MAJOR_MAP: u8 = 5;
const MAJOR_TAG: u8 = 6;
const MAJOR_SIMPLE: u8 = 7;
const SIMPLE_FALSE: u8 = 0xf4;
const SIMPLE_TRUE: u8 = 0xf5;

pub struct Encoder<'a> {
    buf: &'a mut [u8],
    len: usize,
}

impl<'a> Encoder<'a> {
    pub fn new(buf: &'a mut [u8]) -> Self {
        Self { buf, len: 0 }
    }

    pub fn len(&self) -> usize {
        self.len
    }

    pub fn as_slice(&self) -> &[u8] {
        &self.buf[..self.len]
    }

    pub fn begin_map(&mut self, pairs: u32) -> Result<(), i32> {
        self.put_type_value(MAJOR_MAP, pairs as u64)
    }

    pub fn key_u32(&mut self, key: u32, value: u32) -> Result<(), i32> {
        self.put_key(key)?;
        self.put_type_value(MAJOR_UNSIGNED, value as u64)
    }

    pub fn key_i32(&mut self, key: u32, value: i32) -> Result<(), i32> {
        self.put_key(key)?;
        if value >= 0 {
            self.put_type_value(MAJOR_UNSIGNED, value as u64)
        } else {
            self.put_type_value(MAJOR_NEGATIVE, (-1 - value) as u64)
        }
    }

    pub fn key_bool(&mut self, key: u32, value: bool) -> Result<(), i32> {
        self.put_key(key)?;
        self.put_u8(if value { SIMPLE_TRUE } else { SIMPLE_FALSE })
    }

    pub fn key_bytes(&mut self, key: u32, value: &[u8]) -> Result<(), i32> {
        self.put_key(key)?;
        self.put_type_value(MAJOR_BYTES, value.len() as u64)?;
        self.put_raw(value)
    }

    pub fn key_text(&mut self, key: u32, value: &str) -> Result<(), i32> {
        self.put_key(key)?;
        self.put_type_value(MAJOR_TEXT, value.len() as u64)?;
        self.put_raw(value.as_bytes())
    }

    fn put_key(&mut self, key: u32) -> Result<(), i32> {
        self.put_type_value(MAJOR_UNSIGNED, key as u64)
    }

    fn put_u8(&mut self, value: u8) -> Result<(), i32> {
        if self.len >= self.buf.len() {
            return Err(WDC_ERR_RESPONSE_TOO_SMALL);
        }
        self.buf[self.len] = value;
        self.len += 1;
        Ok(())
    }

    fn put_raw(&mut self, value: &[u8]) -> Result<(), i32> {
        if value.len() > self.buf.len().saturating_sub(self.len) {
            return Err(WDC_ERR_RESPONSE_TOO_SMALL);
        }
        let end = self.len + value.len();
        self.buf[self.len..end].copy_from_slice(value);
        self.len = end;
        Ok(())
    }

    fn put_type_value(&mut self, major: u8, value: u64) -> Result<(), i32> {
        let prefix = major << 5;
        if value <= 23 {
            return self.put_u8(prefix | value as u8);
        }
        if value <= 0xff {
            self.put_u8(prefix | 24)?;
            return self.put_u8(value as u8);
        }
        if value <= 0xffff {
            self.put_u8(prefix | 25)?;
            self.put_u8(((value >> 8) & 0xff) as u8)?;
            return self.put_u8((value & 0xff) as u8);
        }
        if value <= 0xffff_ffff {
            self.put_u8(prefix | 26)?;
            for shift in [24, 16, 8, 0] {
                self.put_u8(((value >> shift) & 0xff) as u8)?;
            }
            return Ok(());
        }
        self.put_u8(prefix | 27)?;
        for shift in [56, 48, 40, 32, 24, 16, 8, 0] {
            self.put_u8(((value >> shift) & 0xff) as u8)?;
        }
        Ok(())
    }
}

#[derive(Clone, Copy)]
struct Item {
    major: u8,
    value: u64,
    payload_start: usize,
    payload_len: usize,
    next: usize,
    is_bool: bool,
    bool_value: bool,
}

fn read_type_value(buf: &[u8], offset: usize) -> Result<(u8, u64, usize), i32> {
    if offset >= buf.len() {
        return Err(WDC_ERR_BAD_ENCODING);
    }
    let initial = buf[offset];
    let major = initial >> 5;
    let addl = initial & 0x1f;
    let mut next = offset + 1;
    if addl <= 23 {
        return Ok((major, addl as u64, next));
    }
    if addl == 24 {
        if next >= buf.len() {
            return Err(WDC_ERR_BAD_ENCODING);
        }
        let value = buf[next] as u64;
        next += 1;
        return Ok((major, value, next));
    }
    if addl == 25 {
        if buf.len().saturating_sub(next) < 2 {
            return Err(WDC_ERR_BAD_ENCODING);
        }
        let value = ((buf[next] as u64) << 8) | (buf[next + 1] as u64);
        return Ok((major, value, next + 2));
    }
    if addl == 26 {
        if buf.len().saturating_sub(next) < 4 {
            return Err(WDC_ERR_BAD_ENCODING);
        }
        let value = ((buf[next] as u64) << 24)
            | ((buf[next + 1] as u64) << 16)
            | ((buf[next + 2] as u64) << 8)
            | (buf[next + 3] as u64);
        return Ok((major, value, next + 4));
    }
    if addl == 27 {
        if buf.len().saturating_sub(next) < 8 {
            return Err(WDC_ERR_BAD_ENCODING);
        }
        let mut value = 0u64;
        for i in 0..8 {
            value = (value << 8) | buf[next + i] as u64;
        }
        return Ok((major, value, next + 8));
    }
    Err(WDC_ERR_BAD_ENCODING)
}

fn skip_item(buf: &[u8], offset: usize) -> Result<usize, i32> {
    Ok(read_item(buf, offset)?.next)
}

fn read_item(buf: &[u8], offset: usize) -> Result<Item, i32> {
    if offset >= buf.len() {
        return Err(WDC_ERR_BAD_ENCODING);
    }
    if buf[offset] == SIMPLE_FALSE || buf[offset] == SIMPLE_TRUE {
        return Ok(Item {
            major: MAJOR_SIMPLE,
            value: 0,
            payload_start: 0,
            payload_len: 0,
            next: offset + 1,
            is_bool: true,
            bool_value: buf[offset] == SIMPLE_TRUE,
        });
    }
    let (major, value, mut next) = read_type_value(buf, offset)?;
    let mut item = Item {
        major,
        value,
        payload_start: 0,
        payload_len: 0,
        next,
        is_bool: false,
        bool_value: false,
    };
    if major == MAJOR_BYTES || major == MAJOR_TEXT {
        if value > usize::MAX as u64 {
            return Err(WDC_ERR_BAD_LENGTH);
        }
        let payload_len = value as usize;
        if payload_len > buf.len().saturating_sub(next) {
            return Err(WDC_ERR_BAD_ENCODING);
        }
        item.payload_start = next;
        item.payload_len = payload_len;
        item.next = next + payload_len;
        return Ok(item);
    }
    if major == MAJOR_ARRAY {
        if value > 32 {
            return Err(WDC_ERR_BAD_ENCODING);
        }
        for _ in 0..value {
            next = skip_item(buf, next)?;
        }
        item.next = next;
        return Ok(item);
    }
    if major == MAJOR_MAP {
        if value > 32 {
            return Err(WDC_ERR_BAD_ENCODING);
        }
        for _ in 0..value {
            next = skip_item(buf, next)?;
            next = skip_item(buf, next)?;
        }
        item.next = next;
        return Ok(item);
    }
    if major == MAJOR_TAG {
        return Err(WDC_ERR_BAD_ENCODING);
    }
    Ok(item)
}

fn find_item(buf: &[u8], key: u32) -> Result<Item, i32> {
    if buf.is_empty() {
        return Err(WDC_ERR_NOT_AVAILABLE);
    }
    let (major, pairs, mut offset) = read_type_value(buf, 0)?;
    if major != MAJOR_MAP || pairs > 32 {
        return Err(WDC_ERR_BAD_ENCODING);
    }
    for _ in 0..pairs {
        let key_item = read_item(buf, offset)?;
        offset = key_item.next;
        let value_item = read_item(buf, offset)?;
        offset = value_item.next;
        if key_item.major == MAJOR_UNSIGNED && key_item.value == key as u64 {
            return Ok(value_item);
        }
    }
    Err(WDC_ERR_NOT_AVAILABLE)
}

pub fn find_u32(buf: &[u8], key: u32) -> Result<u32, i32> {
    let item = find_item(buf, key)?;
    if item.major != MAJOR_UNSIGNED || item.value > u32::MAX as u64 {
        return Err(WDC_ERR_BAD_ENCODING);
    }
    Ok(item.value as u32)
}

pub fn find_u64(buf: &[u8], key: u32) -> Result<u64, i32> {
    let item = find_item(buf, key)?;
    if item.major != MAJOR_UNSIGNED {
        return Err(WDC_ERR_BAD_ENCODING);
    }
    Ok(item.value)
}

pub fn find_i32(buf: &[u8], key: u32) -> Result<i32, i32> {
    let item = find_item(buf, key)?;
    if item.major == MAJOR_UNSIGNED && item.value <= i32::MAX as u64 {
        return Ok(item.value as i32);
    }
    if item.major == MAJOR_NEGATIVE && item.value <= i32::MAX as u64 {
        return Ok(-1 - item.value as i32);
    }
    Err(WDC_ERR_BAD_ENCODING)
}

pub fn find_bool(buf: &[u8], key: u32) -> Result<bool, i32> {
    let item = find_item(buf, key)?;
    if !item.is_bool {
        return Err(WDC_ERR_BAD_ENCODING);
    }
    Ok(item.bool_value)
}

pub fn find_bytes<'a>(buf: &'a [u8], key: u32) -> Result<&'a [u8], i32> {
    let item = find_item(buf, key)?;
    if item.major != MAJOR_BYTES {
        return Err(WDC_ERR_BAD_ENCODING);
    }
    Ok(&buf[item.payload_start..item.payload_start + item.payload_len])
}

pub fn find_text<'a>(buf: &'a [u8], key: u32) -> Result<&'a str, i32> {
    let item = find_item(buf, key)?;
    if item.major != MAJOR_TEXT {
        return Err(WDC_ERR_BAD_ENCODING);
    }
    let bytes = &buf[item.payload_start..item.payload_start + item.payload_len];
    core::str::from_utf8(bytes).map_err(|_| WDC_ERR_BAD_ENCODING)
}

pub fn response_status(buf: &[u8]) -> Result<i32, i32> {
    find_i32(buf, crate::abi::WDC_CBOR_KEY_STATUS)
}

pub fn encode_empty_map(buf: &mut [u8]) -> Result<usize, i32> {
    if buf.is_empty() {
        return Err(WDC_ERR_RESPONSE_TOO_SMALL);
    }
    let mut enc = Encoder::new(buf);
    enc.begin_map(0)?;
    Ok(enc.len())
}

pub fn status_to_result(status: i32) -> Result<(), i32> {
    if status == WDC_OK {
        Ok(())
    } else {
        Err(status)
    }
}

pub fn ensure_non_empty(buf: &[u8]) -> Result<(), i32> {
    if buf.is_empty() {
        Err(WDC_ERR_BAD_POINTER)
    } else {
        Ok(())
    }
}
