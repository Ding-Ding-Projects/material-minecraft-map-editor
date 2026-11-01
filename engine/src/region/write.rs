//! New-buffer serialization. This module never opens or writes world files.
use super::{Location, Region};
use crate::nbt::{self, Limits, NamedTag};
use std::{collections::BTreeMap, io::Write};
const SECTOR: usize = 4096;
const MAX_REGION: usize = 256 * 1024 * 1024;
const MAX_CHUNK: usize = 255 * SECTOR;
#[derive(Clone)]
pub struct RegionEdit {
    pub index: usize,
    pub root: NamedTag,
    pub timestamp: u32,
}
struct BoundedOutput(Vec<u8>);
impl Write for BoundedOutput {
    fn write(&mut self, bytes: &[u8]) -> std::io::Result<usize> {
        if self
            .0
            .len()
            .checked_add(bytes.len())
            .is_none_or(|n| n > MAX_CHUNK - 5)
        {
            return Err(std::io::ErrorKind::FileTooLarge.into());
        }
        self.0.extend_from_slice(bytes);
        Ok(bytes.len())
    }
    fn flush(&mut self) -> std::io::Result<()> {
        Ok(())
    }
}
fn encode(root: &NamedTag, limits: Limits) -> nbt::Result<Vec<u8>> {
    let bytes = nbt::write(root, limits)?;
    let mut encoder =
        flate2::write::ZlibEncoder::new(BoundedOutput(Vec::new()), flate2::Compression::default());
    encoder
        .write_all(&bytes)
        .map_err(|_| "compressed chunk exceeds allocation limit")?;
    let compressed = encoder
        .finish()
        .map_err(|_| "compressed chunk exceeds allocation limit")?
        .0;
    let length = compressed.len() + 1;
    let mut result = Vec::with_capacity((length + 4).div_ceil(SECTOR) * SECTOR);
    result.extend_from_slice(&(length as u32).to_be_bytes());
    result.push(2);
    result.extend_from_slice(&compressed);
    result.resize(result.len().div_ceil(SECTOR) * SECTOR, 0);
    Ok(result)
}
impl Region<'_> {
    /// Build a separate validated region image. All unchanged allocated sectors
    /// and their timestamps are copied verbatim; no filesystem writes occur.
    pub fn rebuild(&self, edits: &[RegionEdit], limits: Limits) -> nbt::Result<Vec<u8>> {
        if self.data.len() > MAX_REGION {
            return Err("region byte budget exceeded");
        }
        let mut changed = BTreeMap::new();
        for edit in edits {
            if edit.index >= 1024 {
                return Err("chunk index out of range");
            }
            if changed.insert(edit.index, edit).is_some() {
                return Err("duplicate chunk edit");
            }
        }
        // Preserve complete original bytes, including free sectors, for no-ops.
        changed.retain(|index, edit| {
            !self.locations[*index].is_some_and(|location| {
                location.timestamp == edit.timestamp
                    && self.chunk(*index, limits).ok().flatten().as_ref() == Some(&edit.root)
            })
        });
        if changed.is_empty() {
            return Ok(self.data.to_vec());
        }
        let mut result = vec![0; 8192];
        // Retain timestamps even for unallocated positions.
        result[4096..8192].copy_from_slice(&self.data[4096..8192]);
        for index in 0..1024 {
            let mut encoded = None;
            let (payload, timestamp) = if let Some(edit) = changed.get(&index) {
                encoded = Some(encode(&edit.root, limits)?);
                (encoded.as_ref().unwrap().as_slice(), edit.timestamp)
            } else if let Some(location) = self.locations[index] {
                let begin = location.sector as usize * SECTOR;
                let end = begin + location.count as usize * SECTOR;
                (
                    self.data.get(begin..end).ok_or("sector outside file")?,
                    location.timestamp,
                )
            } else {
                continue;
            };
            let count = payload.len() / SECTOR;
            let sector = result.len() / SECTOR;
            if count == 0
                || count > 255
                || sector > 0x00ff_ffff
                || result
                    .len()
                    .checked_add(payload.len())
                    .is_none_or(|n| n > MAX_REGION)
            {
                return Err("region allocation budget exceeded");
            }
            let location = Location {
                sector: sector as u32,
                count: count as u8,
                timestamp,
            };
            let p = index * 4;
            let offset = location.sector.to_be_bytes();
            result[p..p + 3].copy_from_slice(&offset[1..]);
            result[p + 3] = location.count;
            result[4096 + p..4100 + p].copy_from_slice(&timestamp.to_be_bytes());
            result.extend_from_slice(payload);
            drop(encoded);
        }
        Region::parse(&result)?;
        Ok(result)
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    use crate::nbt::Tag;
    fn root(n: i32) -> NamedTag {
        NamedTag {
            name: vec![],
            tag: Tag::Compound(vec![NamedTag {
                name: b"unknown".to_vec(),
                tag: Tag::Int(n),
            }]),
        }
    }
    #[test]
    fn new_buffer_roundtrip_noop_and_unchanged_payload() {
        let original = vec![0; 8192];
        let region = Region::parse(&original).unwrap();
        let first = region
            .rebuild(
                &[
                    RegionEdit {
                        index: 0,
                        root: root(1),
                        timestamp: 123,
                    },
                    RegionEdit {
                        index: 1023,
                        root: root(2),
                        timestamp: 456,
                    },
                ],
                Limits::default(),
            )
            .unwrap();
        let r = Region::parse(&first).unwrap();
        assert_eq!(r.rebuild(&[], Limits::default()).unwrap(), first);
        assert_eq!(
            r.rebuild(
                &[RegionEdit {
                    index: 0,
                    root: root(1),
                    timestamp: 123
                }],
                Limits::default()
            )
            .unwrap(),
            first
        );
        let old = r.locations[1023].unwrap();
        let old_bytes =
            &first[old.sector as usize * 4096..(old.sector as usize + old.count as usize) * 4096];
        let modified = r
            .rebuild(
                &[RegionEdit {
                    index: 0,
                    root: root(3),
                    timestamp: 789,
                }],
                Limits::default(),
            )
            .unwrap();
        let new = Region::parse(&modified).unwrap();
        assert_eq!(new.chunk(0, Limits::default()).unwrap(), Some(root(3)));
        assert_eq!(new.chunk(1023, Limits::default()).unwrap(), Some(root(2)));
        let loc = new.locations[1023].unwrap();
        assert_eq!(loc.timestamp, 456);
        assert_eq!(
            &modified
                [loc.sector as usize * 4096..(loc.sector as usize + loc.count as usize) * 4096],
            old_bytes
        );
        assert_eq!(original, vec![0; 8192]);
    }
    #[test]
    fn invalid_edits_and_limits() {
        let b = vec![0; 8192];
        let r = Region::parse(&b).unwrap();
        let edit = RegionEdit {
            index: 1024,
            root: root(1),
            timestamp: 0,
        };
        assert!(r.rebuild(&[edit], Limits::default()).is_err());
        let edit = RegionEdit {
            index: 0,
            root: root(1),
            timestamp: 0,
        };
        assert!(r
            .rebuild(&[edit.clone(), edit.clone()], Limits::default())
            .is_err());
        assert!(r
            .rebuild(
                &[edit],
                Limits {
                    bytes: 2,
                    ..Limits::default()
                }
            )
            .is_err());
        let mut output = BoundedOutput(Vec::new());
        assert!(output.write_all(&vec![0; MAX_CHUNK]).is_err());
    }
    #[test]
    fn opaque_unchanged_allocations_and_timestamps_are_preserved() {
        let mut bytes = vec![0; 3 * 4096];
        bytes[7 * 4 + 2] = 2;
        bytes[7 * 4 + 3] = 1;
        bytes[4096 + 7 * 4..4100 + 7 * 4].copy_from_slice(&9876u32.to_be_bytes());
        for (i, b) in bytes[8192..].iter_mut().enumerate() {
            *b = (i % 251) as u8;
        }
        let region = Region::parse(&bytes).unwrap();
        let result = region
            .rebuild(
                &[RegionEdit {
                    index: 0,
                    root: root(4),
                    timestamp: 10,
                }],
                Limits::default(),
            )
            .unwrap();
        let output = Region::parse(&result).unwrap();
        let location = output.locations[7].unwrap();
        assert_eq!(location.timestamp, 9876);
        assert_eq!(
            &result[location.sector as usize * 4096
                ..(location.sector as usize + location.count as usize) * 4096],
            &bytes[8192..]
        );
    }
    #[test]
    fn incompressible_changed_chunk_stops_at_allocation_limit() {
        let mut seed = 1u64;
        let payload = (0..2 * 1024 * 1024)
            .map(|_| {
                seed ^= seed << 13;
                seed ^= seed >> 7;
                seed ^= seed << 17;
                seed as u8
            })
            .collect();
        let root = NamedTag {
            name: vec![],
            tag: Tag::Compound(vec![NamedTag {
                name: b"payload".to_vec(),
                tag: Tag::ByteArray(payload),
            }]),
        };
        assert!(encode(&root, Limits::default()).is_err());
    }
}
