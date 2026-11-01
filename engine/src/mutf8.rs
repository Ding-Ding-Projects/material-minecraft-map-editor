//! Java modified UTF-8 views without changing the retained NBT bytes.
use crate::nbt::Result;
pub fn decode_units(bytes: &[u8]) -> Result<Vec<u16>> {
    let mut units = Vec::new();
    let mut i = 0;
    while i < bytes.len() {
        let a = bytes[i];
        i += 1;
        let unit = match a {
            1..=0x7f => a as u16,
            0xc0..=0xdf => {
                let b = *bytes.get(i).ok_or("truncated modified UTF-8")?;
                i += 1;
                if b & 0xc0 != 0x80 {
                    return Err("invalid modified UTF-8 continuation");
                }
                let n = ((a as u16 & 31) << 6) | (b as u16 & 63);
                if n < 128 && n != 0 {
                    return Err("overlong modified UTF-8");
                }
                if n == 0 && (a != 0xc0 || b != 0x80) {
                    return Err("invalid modified UTF-8 null");
                }
                n
            }
            0xe0..=0xef => {
                let b = *bytes.get(i).ok_or("truncated modified UTF-8")?;
                let c = *bytes.get(i + 1).ok_or("truncated modified UTF-8")?;
                i += 2;
                if b & 0xc0 != 0x80 || c & 0xc0 != 0x80 {
                    return Err("invalid modified UTF-8 continuation");
                }
                let n = ((a as u16 & 15) << 12) | ((b as u16 & 63) << 6) | (c as u16 & 63);
                if n < 2048 {
                    return Err("overlong modified UTF-8");
                }
                n
            }
            _ => return Err("invalid modified UTF-8 leading byte"),
        };
        units.push(unit);
    }
    Ok(units)
}
pub fn decode(bytes: &[u8]) -> Result<String> {
    String::from_utf16(&decode_units(bytes)?).map_err(|_| "unpaired modified UTF-8 surrogate")
}
pub fn encode_units(units: &[u16]) -> Vec<u8> {
    let mut out = Vec::new();
    for &u in units {
        match u {
            1..=127 => out.push(u as u8),
            0..=2047 => {
                out.push(0xc0 | (u >> 6) as u8);
                out.push(0x80 | (u & 63) as u8);
            }
            _ => {
                out.push(0xe0 | (u >> 12) as u8);
                out.push(0x80 | ((u >> 6) & 63) as u8);
                out.push(0x80 | (u & 63) as u8);
            }
        }
    }
    out
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn null_bmp_and_supplementary() {
        let s = "a\0水😀";
        let units: Vec<u16> = s.encode_utf16().collect();
        let b = encode_units(&units);
        assert_eq!(decode(&b).unwrap(), s);
        assert_eq!(decode_units(&b).unwrap(), units);
    }
    #[test]
    fn isolated_surrogate_has_lossless_units_but_no_text() {
        let b = encode_units(&[0xd800]);
        assert_eq!(decode_units(&b).unwrap(), vec![0xd800]);
        assert!(decode(&b).is_err());
    }
    #[test]
    fn malformed_sequences() {
        for b in [
            &[0][..],
            &[0xc1, 0x81],
            &[0xc0],
            &[0xe0, 0x80, 0x80],
            &[0xe1, 0x20, 0x80],
            &[0xf0, 0x9f, 0x98, 0x80],
            &[0x80],
        ] {
            assert!(decode_units(b).is_err());
        }
    }
}
