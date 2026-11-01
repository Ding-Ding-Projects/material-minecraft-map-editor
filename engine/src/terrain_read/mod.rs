//! Selected-sector staged reads. No whole-region allocation or world writes.
mod decode;
use decode::{fields, optional};

use crate::{
    file_source::{Error, Source},
    nbt::{self, Limits},
    region,
};
use serde_json::{json, Value};
use std::{
    collections::{BTreeMap, HashSet},
    path::Path,
    time::Instant,
};
const MIB: usize = 1024 * 1024;
const TEMP: usize = 96 * MIB;
const FIXED: usize = 6 * MIB;
const DECOMP: usize = 16 * MIB;
#[derive(Clone, Copy, Debug)]
pub struct Bounds {
    pub xmin: i32,
    pub xmax: i32,
    pub zmin: i32,
    pub zmax: i32,
    pub ymin: i32,
    pub ymax: i32,
}
impl Bounds {
    pub fn json(self) -> Value {
        json!({"chunkXMin":self.xmin,"chunkXMax":self.xmax,"chunkZMin":self.zmin,"chunkZMax":self.zmax,"sectionYMin":self.ymin,"sectionYMax":self.ymax})
    }
    pub fn valid(self) -> bool {
        self.xmin <= self.xmax
            && self.xmax as i64 - self.xmin as i64 <= 2
            && self.zmin <= self.zmax
            && self.zmax as i64 - self.zmin as i64 <= 2
            && self.ymin >= -128
            && self.ymax <= 127
            && self.ymin <= self.ymax
            && self.ymax - self.ymin <= 2
    }
}
pub struct Section {
    pub x: i32,
    pub z: i32,
    pub y: i32,
    pub palette: Vec<crate::chunk::BlockState>,
    pub indices: Vec<u16>,
}
#[derive(Clone, Copy)]
pub struct Counts {
    pub cube: u32,
    pub unsupported: u32,
}
pub struct ReadSet {
    pub coverage: Vec<Value>,
    pub sources: Vec<Value>,
    pub temporary_peak: usize,
    pub selected_sector_bytes: usize,
    pub hashed_bytes: u64,
}
fn error(e: Error) -> &'static str {
    match e {
        Error::Changed => "changed_during_read",
        Error::Escape | Error::Linked => "world_path_rejected",
        Error::Identity => "source_identity_unavailable",
        Error::Timeout => "terrain_timed_out",
        Error::Budget => "terrain_budget_exceeded",
        _ => "source_read_unavailable",
    }
}
fn check(deadline: Instant) -> Result<(), &'static str> {
    if Instant::now() >= deadline {
        Err("terrain_timed_out")
    } else {
        Ok(())
    }
}
fn coverage(
    x: i32,
    z: i32,
    y: i32,
    kind: &str,
    version: Option<i32>,
    reason: &str,
    counts: Option<Counts>,
) -> Value {
    let c = counts.unwrap_or(Counts {
        cube: 0,
        unsupported: 0,
    });
    json!({"chunkX":x,"chunkZ":z,"sectionY":y,"availability":kind,"dataVersion":version,"decodedCells":if counts.is_some(){4096}else{0},"cubeCells":c.cube,"airCells":0,"unsupportedCells":c.unsupported,"reasonCode":reason})
}
fn unavailable(
    entries: &mut Vec<Value>,
    x: i32,
    z: i32,
    b: Bounds,
    kind: &str,
    version: Option<i32>,
    reason: &str,
) {
    for y in b.ymin..=b.ymax {
        entries.push(coverage(x, z, y, kind, version, reason, None));
    }
}
fn source_record(source: &Source, hash: [u8; 32]) -> Result<Value, &'static str> {
    let path = source.relative_path().map_err(error)?;
    Ok(
        json!({"relativePath":path,"observation":"present","fileIdentity":{"scheme":1,"volumeSerial":source.stamp.volume,"fileId":source.stamp.id.iter().map(|b|format!("{b:02x}")).collect::<String>()},"fileBytes":source.stamp.bytes,"lastWriteFileTime":source.stamp.last_write,"contentSha256":hash.iter().map(|b|format!("{b:02x}")).collect::<String>()}),
    )
}
fn absent(path: &str) -> Value {
    json!({"relativePath":path,"observation":"absent","fileIdentity":null,"fileBytes":null,"lastWriteFileTime":null,"contentSha256":null})
}
pub fn read(
    path: &Path,
    dimension: &str,
    bounds: Bounds,
    deadline: Instant,
    mut section: impl FnMut(Section) -> Result<Counts, &'static str>,
) -> Result<ReadSet, &'static str> {
    if !bounds.valid() {
        return Err("invalid_terrain_bounds");
    }
    check(deadline)?;
    let root = std::fs::canonicalize(path).map_err(|_| "world_unavailable")?;
    let dim = crate::world_read::resolve_dimension(&root, dimension)
        .map_err(|_| "dimension_unavailable")?;
    let mut sources = Vec::new();
    let mut retained = Vec::new();
    let mut identities = HashSet::new();
    let mut missing = Vec::new();
    let mut entries = Vec::new();
    let mut peak = FIXED;
    let mut selected_sector_bytes = 0usize;
    let mut hashed_bytes = 0u64;
    let mut level = Source::open(&root, Path::new("level.dat"), DECOMP as u64).map_err(error)?;
    let hash = level.hash(Some(deadline)).map_err(error)?;
    hashed_bytes += level.stamp.bytes;
    let data = level
        .read_at(0, level.stamp.bytes as usize)
        .map_err(error)?;
    let raw =
        region::decompress_reserved(1, &data, DECOMP).map_err(|_| "invalid_level_metadata")?;
    let parsed = nbt::parse_charged(
        &raw,
        Limits {
            bytes: DECOMP,
            ..Limits::default()
        },
        Some((TEMP - FIXED - data.capacity() - raw.capacity()).min(64 * MIB)),
    )
    .map_err(|_| "invalid_level_metadata")?;
    let top = fields(&parsed.root.tag).map_err(|_| "invalid_level_metadata")?;
    let Some(data_tag) = optional(top, b"Data").map_err(|_| "invalid_level_metadata")? else {
        return Err("invalid_level_metadata");
    };
    let level_fields = fields(data_tag).map_err(|_| "invalid_level_metadata")?;
    match optional(level_fields, b"DataVersion").map_err(|_| "invalid_level_metadata")? {
        None | Some(nbt::Tag::Int(_)) => (),
        _ => return Err("invalid_level_metadata"),
    }
    peak = peak.max(FIXED + data.capacity() + raw.capacity() + parsed.peak_allocated_bytes);
    drop(parsed);
    drop(raw);
    drop(data);
    identities.insert((level.stamp.volume, level.stamp.id));
    sources.push(source_record(&level, hash)?);
    retained.push(level);
    let region_dir = dim.join("region");
    let mut regions = BTreeMap::new();
    for x in bounds.xmin..=bounds.xmax {
        for z in bounds.zmin..=bounds.zmax {
            let (rx, rz, index) = crate::world_read::region_coordinates(x, z);
            regions
                .entry((rx, rz))
                .or_insert_with(Vec::new)
                .push((x, z, index));
        }
    }
    if regions.len() > 4 {
        return Err("terrain_budget_exceeded");
    }
    for ((rx, rz), chunks) in regions {
        check(deadline)?;
        let candidate = region_dir.join(format!("r.{rx}.{rz}.mca"));
        let relative = candidate
            .strip_prefix(&root)
            .map_err(|_| "world_path_rejected")?;
        let mut file = match Source::open(&root, relative, 256 * MIB as u64) {
            Ok(file) => file,
            Err(Error::Missing) => {
                let relative = relative
                    .to_str()
                    .ok_or("world_path_rejected")?
                    .replace('\\', "/");
                sources.push(absent(&relative));
                missing.push(
                    candidate
                        .strip_prefix(&root)
                        .map_err(|_| "world_path_rejected")?
                        .to_path_buf(),
                );
                for (x, z, _) in chunks {
                    unavailable(
                        &mut entries,
                        x,
                        z,
                        bounds,
                        "absent-region",
                        None,
                        "absent_region",
                    );
                }
                continue;
            }
            Err(e) => return Err(error(e)),
        };
        if !identities.insert((file.stamp.volume, file.stamp.id)) {
            return Err("duplicate_source_identity");
        }
        let hash = file.hash(Some(deadline)).map_err(error)?;
        hashed_bytes = hashed_bytes
            .checked_add(file.stamp.bytes)
            .ok_or("terrain_budget_exceeded")?;
        sources.push(source_record(&file, hash)?);
        let header = if file.stamp.bytes >= 8192 {
            Some(file.read_at(0, 8192).map_err(error)?)
        } else {
            None
        };
        let locations = header
            .as_ref()
            .and_then(|h| region::header_locations(h, file.stamp.bytes).ok());
        for (x, z, index) in chunks {
            check(deadline)?;
            let Some(locations) = &locations else {
                unavailable(
                    &mut entries,
                    x,
                    z,
                    bounds,
                    "corrupt",
                    None,
                    "invalid_region_header",
                );
                continue;
            };
            let Some(location) = locations[index] else {
                unavailable(
                    &mut entries,
                    x,
                    z,
                    bounds,
                    "absent-chunk",
                    None,
                    "absent_chunk",
                );
                continue;
            };
            let extent = file
                .read_at(
                    location.sector as u64 * 4096,
                    location.count as usize * 4096,
                )
                .map_err(error)?;
            selected_sector_bytes += extent.len();
            decode::chunk(
                &extent,
                extent.capacity(),
                x,
                z,
                bounds,
                deadline,
                &mut entries,
                &mut section,
                &mut peak,
            )?;
        }
        file.verify().map_err(error)?;
        retained.push(file);
    }
    check(deadline)?;
    for file in &retained {
        file.verify().map_err(error)?;
    }
    for path in missing {
        match Source::open(&root, &path, 0) {
            Err(Error::Missing) => (),
            _ => return Err("changed_during_read"),
        }
    }
    if sources.len() > 32 {
        return Err("terrain_budget_exceeded");
    }
    entries.sort_by_key(|e| {
        (
            e["chunkX"].as_i64().unwrap(),
            e["chunkZ"].as_i64().unwrap(),
            e["sectionY"].as_i64().unwrap(),
        )
    });
    sources.sort_by(|a, b| {
        a["relativePath"]
            .as_str()
            .unwrap()
            .as_bytes()
            .cmp(b["relativePath"].as_str().unwrap().as_bytes())
    });
    Ok(ReadSet {
        coverage: entries,
        sources,
        temporary_peak: peak,
        selected_sector_bytes,
        hashed_bytes,
    })
}

#[cfg(all(test, windows))]
mod tests;
