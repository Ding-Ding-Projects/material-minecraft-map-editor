use crate::nbt::{self, Limits, NamedTag};
use flate2::bufread::GzDecoder;
use std::io::{Cursor, Read};
pub fn decompress(kind: u8, data: &[u8], limit: usize) -> nbt::Result<Vec<u8>> {
    if kind == 2 {
        let mut decoder = flate2::Decompress::new(true);
        let mut output = Vec::new();
        let mut block = [0u8; 8192];
        loop {
            let before = decoder.total_out();
            let consumed = decoder.total_in() as usize;
            let status = decoder
                .decompress(&data[consumed..], &mut block, flate2::FlushDecompress::None)
                .map_err(|_| "invalid compressed stream")?;
            let produced = (decoder.total_out() - before) as usize;
            if output.len() + produced > limit {
                return Err("decompressed byte budget exceeded");
            }
            output.extend_from_slice(&block[..produced]);
            if status == flate2::Status::StreamEnd {
                if decoder.total_in() as usize != data.len() {
                    return Err("trailing compressed bytes");
                }
                return Ok(output);
            }
            if produced == 0 && decoder.total_in() as usize == consumed {
                return Err("incomplete compressed stream");
            }
        }
    }
    if kind == 1 {
        let mut decoder = GzDecoder::new(Cursor::new(data));
        let mut output = Vec::new();
        (&mut decoder)
            .take(limit as u64 + 1)
            .read_to_end(&mut output)
            .map_err(|_| "invalid compressed stream")?;
        if output.len() > limit {
            return Err("decompressed byte budget exceeded");
        }
        if decoder.into_inner().position() != data.len() as u64 {
            return Err("trailing compressed bytes");
        }
        return Ok(output);
    }
    let reader: Box<dyn Read + '_> = match kind {
        3 => Box::new(Cursor::new(data)),
        _ => return Err("unsupported compression"),
    };
    let mut output = Vec::new();
    reader
        .take(limit as u64 + 1)
        .read_to_end(&mut output)
        .map_err(|_| "invalid compressed stream")?;
    if output.len() > limit {
        return Err("decompressed byte budget exceeded");
    }
    Ok(output)
}
pub fn header_locations(header: &[u8], file_bytes: u64) -> nbt::Result<[Option<Location>; 1024]> {
    if header.len() != 8192 || file_bytes < 8192 || file_bytes % 4096 != 0 {
        return Err("invalid region length");
    }
    let mut locations = [None; 1024];
    let mut ranges = Vec::new();
    for (i, location) in locations.iter_mut().enumerate() {
        let p = i * 4;
        let sector = u32::from_be_bytes([0, header[p], header[p + 1], header[p + 2]]);
        let count = header[p + 3];
        if sector == 0 && count == 0 {
            continue;
        }
        if sector < 2 || count == 0 {
            return Err("invalid sector location");
        }
        let end = sector as usize + count as usize;
        if end as u64 > file_bytes / 4096 {
            return Err("sector outside file");
        }
        ranges.push((sector as usize, end));
        *location = Some(Location {
            sector,
            count,
            timestamp: u32::from_be_bytes(header[4096 + p..4100 + p].try_into().unwrap()),
        });
    }
    ranges.sort_unstable();
    if ranges.windows(2).any(|w| w[0].1 > w[1].0) {
        return Err("overlapping sectors");
    }
    Ok(locations)
}
#[derive(Debug, Clone, Copy)]
pub struct Location {
    pub sector: u32,
    pub count: u8,
    pub timestamp: u32,
}
pub struct Region<'a> {
    data: &'a [u8],
    locations: [Option<Location>; 1024],
}
impl<'a> Region<'a> {
    /// Validated allocations can be inspected but not replaced.
    /// ```compile_fail
    /// use material_world_engine::region::Region;
    /// let data = vec![0; 8192];
    /// let mut region = Region::parse(&data).unwrap();
    /// region.locations[0] = None;
    /// ```
    pub fn locations(&self) -> &[Option<Location>; 1024] {
        &self.locations
    }
    pub fn parse(data: &'a [u8]) -> nbt::Result<Self> {
        let locations = header_locations(
            data.get(..8192).ok_or("invalid region length")?,
            data.len() as u64,
        )?;
        Ok(Self { data, locations })
    }
    pub fn chunk(&self, index: usize, limits: Limits) -> nbt::Result<Option<NamedTag>> {
        let loc = self
            .locations
            .get(index)
            .ok_or("chunk index out of range")?;
        let Some(loc) = loc else { return Ok(None) };
        if loc.sector < 2 || loc.count == 0 {
            return Err("invalid sector location");
        }
        let start = (loc.sector as usize)
            .checked_mul(4096)
            .ok_or("sector offset overflow")?;
        let end = start
            .checked_add(loc.count as usize * 4096)
            .ok_or("sector offset overflow")?;
        let allocation = self.data.get(start..end).ok_or("sector outside file")?;
        let length = u32::from_be_bytes(
            allocation
                .get(..4)
                .ok_or("truncated chunk header")?
                .try_into()
                .unwrap(),
        ) as usize;
        if length < 1 || length > loc.count as usize * 4096 - 4 {
            return Err("invalid chunk length");
        }
        let compression = *allocation.get(4).ok_or("truncated chunk header")?;
        if compression & 128 != 0 {
            return Err("external chunk storage unsupported");
        }
        let bytes = decompress(
            compression,
            allocation
                .get(5..4 + length)
                .ok_or("truncated chunk payload")?,
            limits.bytes,
        )?;
        Ok(Some(nbt::parse(&bytes, limits)?))
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn allocation_metadata_cannot_produce_unchecked_reads() {
        let bytes = vec![0; 8192];
        let mut region = Region::parse(&bytes).unwrap();
        region.locations[0] = Some(Location {
            sector: 2,
            count: 1,
            timestamp: 0,
        });
        assert!(region.chunk(0, Limits::default()).is_err());
    }
    #[test]
    fn region_locations_and_payload() {
        let mut b = vec![0; 12288];
        b[2] = 2;
        b[3] = 1;
        b[8195] = 5;
        b[8196] = 3;
        b[8197..8201].copy_from_slice(&[10, 0, 0, 0]);
        let r = Region::parse(&b).unwrap();
        assert!(r.chunk(0, Limits::default()).unwrap().is_some());
        assert!(r.chunk(1, Limits::default()).unwrap().is_none());
        assert!(r.chunk(1024, Limits::default()).is_err());
        b[6] = 2;
        b[7] = 1;
        assert!(Region::parse(&b).is_err());
        b[6] = 0;
        b[7] = 0;
        b[8195] = 0;
        assert!(Region::parse(&b)
            .unwrap()
            .chunk(0, Limits::default())
            .is_err());
    }
    #[test]
    fn compression_limits_and_corruption() {
        use std::io::Write;
        let mut e = flate2::write::ZlibEncoder::new(Vec::new(), flate2::Compression::default());
        e.write_all(&[5; 20000]).unwrap();
        let b = e.finish().unwrap();
        assert_eq!(decompress(2, &b, 20000).unwrap(), vec![5; 20000]);
        assert!(decompress(2, &b, 19999).is_err());
        assert!(decompress(2, &b[..b.len() - 3], 20000).is_err());
        assert!(decompress(4, &b, 1000).is_err());
    }
}
mod write;
pub use write::RegionEdit;

/// Reserve the entire declared output allowance before decoding. The returned
/// Vec never grows beyond this payload capacity; trailer completion is required.
pub fn decompress_reserved(kind: u8, data: &[u8], limit: usize) -> nbt::Result<Vec<u8>> {
    if limit > 16 * 1024 * 1024 {
        return Err("decompression budget exceeded");
    }
    let mut output = Vec::new();
    output
        .try_reserve_exact(limit)
        .map_err(|_| "allocation unavailable")?;
    if output.capacity() > limit {
        return Err("decompression allocation budget exceeded");
    }
    let mut block = [0u8; 8192];
    if kind == 2 {
        let mut decoder = flate2::Decompress::new(true);
        loop {
            let before = decoder.total_out();
            let consumed = decoder.total_in() as usize;
            let status = decoder
                .decompress(&data[consumed..], &mut block, flate2::FlushDecompress::None)
                .map_err(|_| "invalid compressed stream")?;
            let n = (decoder.total_out() - before) as usize;
            if output.len().checked_add(n).is_none_or(|n| n > limit) {
                return Err("decompression budget exceeded");
            }
            output.extend_from_slice(&block[..n]);
            if status == flate2::Status::StreamEnd {
                if decoder.total_in() as usize != data.len() {
                    return Err("trailing compressed bytes");
                }
                return Ok(output);
            }
            if n == 0 && decoder.total_in() as usize == consumed {
                return Err("incomplete compressed stream");
            }
        }
    }
    if kind == 3 {
        if data.len() > limit {
            return Err("decompression budget exceeded");
        }
        output.extend_from_slice(data);
        return Ok(output);
    }
    if kind != 1 {
        return Err("unsupported compression");
    }
    let mut decoder = GzDecoder::new(Cursor::new(data));
    loop {
        let n = decoder
            .read(&mut block)
            .map_err(|_| "invalid compressed stream")?;
        if n == 0 {
            break;
        }
        if output.len().checked_add(n).is_none_or(|n| n > limit) {
            return Err("decompression budget exceeded");
        }
        output.extend_from_slice(&block[..n]);
    }
    if decoder.into_inner().position() != data.len() as u64 {
        return Err("trailing compressed bytes");
    }
    Ok(output)
}
#[cfg(test)]
mod bounded_decoder_tests {
    use super::*;
    #[test]
    fn reserved_output_and_header_validation() {
        let raw = [10, 0, 0, 0];
        let decoded = decompress_reserved(3, &raw, 4).unwrap();
        assert_eq!(decoded, raw);
        assert_eq!(decoded.capacity(), 4);
        assert!(decompress_reserved(3, &raw, 3).is_err());
        assert!(header_locations(&[0; 8192], 8193).is_err());
        assert!(header_locations(&[0; 8192], 8192).is_ok());
    }
}
