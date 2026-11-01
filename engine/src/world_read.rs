//! Contained read-only world discovery and bounded region inspection.
use crate::{
    chunk::{self, Blocks},
    nbt::{self, Limits},
    region::Region,
};
use serde_json::{json, Value};
use std::{
    collections::HashSet,
    fs::{self, File},
    io::{Read, Write},
    path::{Path, PathBuf},
};
pub const MAX_REGION_BYTES: u64 = 256 * 1024 * 1024;
const MAX_DISCOVERY_ENTRIES: usize = 4096;
const MAX_DIMENSIONS: usize = 64;
struct Dimension {
    id: String,
    path: PathBuf,
}
fn root(path: &Path) -> nbt::Result<PathBuf> {
    let root = fs::canonicalize(path).map_err(|_| "world directory unavailable")?;
    if !root.is_dir() {
        return Err("invalid world directory");
    }
    Ok(root)
}
fn child(parent: &Path, path: &Path) -> nbt::Result<Option<PathBuf>> {
    match fs::symlink_metadata(path) {
        Ok(_) => (),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(_) => return Err("world entry unavailable"),
    };
    let resolved = fs::canonicalize(path).map_err(|_| "world entry unavailable")?;
    if !resolved.starts_with(parent) {
        return Err("world entry escapes its parent");
    }
    Ok(Some(resolved))
}
fn component(s: &str) -> bool {
    !s.is_empty()
        && s != "."
        && s != ".."
        && s.bytes()
            .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b"_-.".contains(&b))
}
fn valid_id(id: &str) -> bool {
    if id.len() > 256 {
        return false;
    }
    let Some((namespace, path)) = id.split_once(':') else {
        return false;
    };
    component(namespace) && path.split('/').all(component)
}
fn has_region(path: &Path) -> nbt::Result<bool> {
    match child(path, &path.join("region"))? {
        Some(p) if p.is_dir() => Ok(true),
        Some(_) => Err("invalid region directory"),
        None => Ok(false),
    }
}
fn discover(path: &Path) -> nbt::Result<Vec<Dimension>> {
    let root = root(path)?;
    let mut result = Vec::new();
    for (id, relative) in [
        ("minecraft:overworld", ""),
        ("minecraft:the_nether", "DIM-1"),
        ("minecraft:the_end", "DIM1"),
    ] {
        let p = if relative.is_empty() {
            Some(root.clone())
        } else {
            child(&root, &root.join(relative))?
        };
        if let Some(p) = p {
            if !p.is_dir() {
                return Err("invalid dimension directory");
            }
            if has_region(&p)? {
                result.push(Dimension {
                    id: id.into(),
                    path: p,
                });
            }
        }
    }
    if let Some(custom) = child(&root, &root.join("dimensions"))? {
        let mut remaining = MAX_DISCOVERY_ENTRIES;
        let mut visited = HashSet::new();
        walk(
            &custom,
            &custom,
            Vec::new(),
            &mut remaining,
            &mut visited,
            &mut result,
        )?;
    }
    if result.len() > MAX_DIMENSIONS {
        return Err("dimension budget exceeded");
    }
    result.sort_by(|a, b| a.id.cmp(&b.id));
    if result.windows(2).any(|w| w[0].id == w[1].id) {
        return Err("duplicate dimension identifier");
    }
    Ok(result)
}
fn walk(
    base: &Path,
    current: &Path,
    parts: Vec<String>,
    remaining: &mut usize,
    visited: &mut HashSet<PathBuf>,
    out: &mut Vec<Dimension>,
) -> nbt::Result<()> {
    if parts.len() > 9 {
        return Err("dimension depth budget exceeded");
    }
    if !visited.insert(current.to_path_buf()) {
        return Err("cyclic dimension mapping");
    }
    if parts.len() >= 2 && has_region(current)? {
        let id = format!("{}:{}", parts[0], parts[1..].join("/"));
        if !valid_id(&id) {
            return Err("invalid dimension identifier");
        }
        out.push(Dimension {
            id,
            path: current.to_path_buf(),
        });
        if out.len() > MAX_DIMENSIONS {
            return Err("dimension budget exceeded");
        }
    }
    for entry in fs::read_dir(current).map_err(|_| "dimension discovery failed")? {
        *remaining = remaining
            .checked_sub(1)
            .ok_or("dimension entry budget exceeded")?;
        let entry = entry.map_err(|_| "dimension discovery failed")?;
        let name = entry.file_name();
        let name = name.to_str().ok_or("invalid dimension identifier")?;
        if parts.len() >= 2 && ["region", "entities", "poi", "data"].contains(&name) {
            continue;
        }
        let resolved = child(base, &entry.path())?.ok_or("world entry unavailable")?;
        if !resolved.is_dir() {
            continue;
        }
        if !component(name) {
            return Err("invalid dimension identifier");
        }
        let mut next = parts.clone();
        next.push(name.into());
        walk(base, &resolved, next, remaining, visited, out)?;
    }
    Ok(())
}
pub fn dimensions(path: &Path) -> nbt::Result<Value> {
    let values = discover(path)?
        .into_iter()
        .map(|d| json!({"id":d.id,"readOnly":true}))
        .collect::<Vec<_>>();
    Ok(json!({"dimensions":values,"readOnly":true}))
}
pub fn region_coordinates(x: i32, z: i32) -> (i32, i32, usize) {
    (
        x.div_euclid(32),
        z.div_euclid(32),
        (z.rem_euclid(32) * 32 + x.rem_euclid(32)) as usize,
    )
}
fn encoded_size_within(value: &Value, max: usize) -> bool {
    struct Counter {
        used: usize,
        max: usize,
    }
    impl Write for Counter {
        fn write(&mut self, buf: &[u8]) -> std::io::Result<usize> {
            self.used = self
                .used
                .checked_add(buf.len())
                .ok_or(std::io::ErrorKind::OutOfMemory)?;
            if self.used > self.max {
                return Err(std::io::ErrorKind::OutOfMemory.into());
            }
            Ok(buf.len())
        }
        fn flush(&mut self) -> std::io::Result<()> {
            Ok(())
        }
    }
    serde_json::to_writer(Counter { used: 0, max }, value).is_ok()
}
pub fn bounded_response(value: Value, id: &Value) -> Value {
    if encoded_size_within(&value, crate::protocol::MAX_FRAME) {
        value
    } else {
        json!({"version":1,"id":id,"error":{"code":"response_too_large","message":"Response exceeds frame limit"}})
    }
}
pub fn chunk_summary(path: &Path, dimension: &str, x: i32, z: i32) -> nbt::Result<Value> {
    if !valid_id(dimension) {
        return Err("invalid dimension identifier");
    }
    let dim = discover(path)?
        .into_iter()
        .find(|d| d.id == dimension)
        .ok_or("dimension unavailable")?;
    let region_dir = child(&dim.path, &dim.path.join("region"))?.ok_or("region unavailable")?;
    let (rx, rz, index) = region_coordinates(x, z);
    let file = child(&region_dir, &region_dir.join(format!("r.{rx}.{rz}.mca")))?;
    let absent =
        || json!({"dimension":dimension,"chunkX":x,"chunkZ":z,"available":false,"readOnly":true});
    let Some(file) = file else {
        return Ok(absent());
    };
    let before_open = fs::metadata(&file).map_err(|_| "region unavailable")?;
    if !before_open.is_file() {
        return Err("region is not a regular file");
    }
    if before_open.len() > MAX_REGION_BYTES {
        return Err("region byte budget exceeded");
    }
    let handle = File::open(file).map_err(|_| "region unavailable")?;
    let metadata = handle.metadata().map_err(|_| "region unavailable")?;
    if !metadata.is_file() || metadata.len() > MAX_REGION_BYTES {
        return Err("region byte budget exceeded");
    }
    let mut bytes = Vec::new();
    handle
        .take(MAX_REGION_BYTES + 1)
        .read_to_end(&mut bytes)
        .map_err(|_| "region read failed")?;
    if bytes.len() as u64 > MAX_REGION_BYTES {
        return Err("region byte budget exceeded");
    }
    let region = Region::parse(&bytes)?;
    let Some(raw) = region.chunk(index, Limits::default())? else {
        return Ok(absent());
    };
    let summary = chunk::summarize(&raw)?;
    if summary.x != x || summary.z != z {
        return Err("chunk coordinate mismatch");
    }
    let sections = summary
        .sections
        .iter()
        .map(|section| {
            let blocks = match &section.blocks {
                Blocks::Numeric(values) => json!({"kind":"numeric","blocks":values}),
                Blocks::Palette { states, indices } => {
                    let states = states
                        .iter()
                        .map(|s| json!({"name":s.name,"properties":s.properties}))
                        .collect::<Vec<_>>();
                    json!({"kind":"palette","palette":states,"indices":indices})
                }
            };
            json!({"sectionY":section.y,"minimumBlockY":section.y*16,"blocks":blocks})
        })
        .collect::<Vec<_>>();
    Ok(
        json!({"dimension":dimension,"chunkX":x,"chunkZ":z,"available":true,"readOnly":true,"editingSupported":false,"dataVersion":summary.data_version,"blockOrder":"y-z-x","sections":sections}),
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::nbt::{NamedTag, Tag};
    struct Fixture(PathBuf);
    impl Fixture {
        fn new() -> Self {
            let p = std::env::temp_dir().join(format!(
                "engine-world-read-{}-{}",
                std::process::id(),
                std::time::SystemTime::now()
                    .duration_since(std::time::UNIX_EPOCH)
                    .unwrap()
                    .as_nanos()
            ));
            fs::create_dir(&p).unwrap();
            Self(p)
        }
    }
    impl Drop for Fixture {
        fn drop(&mut self) {
            fs::remove_dir_all(&self.0).unwrap();
        }
    }
    fn named(name: &str, tag: Tag) -> NamedTag {
        NamedTag {
            name: name.as_bytes().to_vec(),
            tag,
        }
    }
    fn write_chunk(world: &Path, x: i32, z: i32, version: i32) {
        let root = NamedTag {
            name: vec![],
            tag: Tag::Compound(vec![
                named("DataVersion", Tag::Int(version)),
                named("xPos", Tag::Int(x)),
                named("zPos", Tag::Int(z)),
                named(
                    "sections",
                    Tag::List(
                        10,
                        vec![Tag::Compound(vec![
                            named("Y", Tag::Byte(-4)),
                            named(
                                "block_states",
                                Tag::Compound(vec![named(
                                    "palette",
                                    Tag::List(
                                        10,
                                        vec![Tag::Compound(vec![named(
                                            "Name",
                                            Tag::String(b"minecraft:stone".to_vec()),
                                        )])],
                                    ),
                                )]),
                            ),
                        ])],
                    ),
                ),
            ]),
        };
        let payload = nbt::write(&root, Limits::default()).unwrap();
        let mut encoder =
            flate2::write::ZlibEncoder::new(Vec::new(), flate2::Compression::default());
        encoder.write_all(&payload).unwrap();
        let compressed = encoder.finish().unwrap();
        let (rx, rz, index) = region_coordinates(x, z);
        let count = (compressed.len() + 5).div_ceil(4096);
        let mut file = vec![0; 8192 + count * 4096];
        file[index * 4 + 2] = 2;
        file[index * 4 + 3] = count as u8;
        file[8192..8196].copy_from_slice(&((compressed.len() + 1) as u32).to_be_bytes());
        file[8196] = 2;
        file[8197..8197 + compressed.len()].copy_from_slice(&compressed);
        fs::create_dir_all(world.join("region")).unwrap();
        fs::write(world.join(format!("region/r.{rx}.{rz}.mca")), file).unwrap();
    }
    #[test]
    fn negative_coordinate_floor_division_and_edges() {
        assert_eq!(region_coordinates(-1, -1), (-1, -1, 1023));
        assert_eq!(region_coordinates(-32, -32), (-1, -1, 0));
        assert_eq!(region_coordinates(-33, 32), (-2, 1, 31));
        assert_eq!(region_coordinates(31, 31), (0, 0, 1023));
        assert_eq!(region_coordinates(32, 32), (1, 1, 0));
        assert_eq!(
            region_coordinates(i32::MIN, i32::MAX),
            (-67108864, 67108863, 992)
        );
    }
    #[test]
    fn protocol_reads_real_region_fixtures_and_absence() {
        let f = Fixture::new();
        for (x, z) in [(-1, -1), (31, 31), (32, 32)] {
            write_chunk(&f.0, x, z, 2975);
            let result = crate::protocol::dispatch(
                json!({"version":1,"id":"chunk","method":"world.chunk_summary","params":{"path":f.0.to_str().unwrap(),"dimension":"minecraft:overworld","chunkX":x,"chunkZ":z}}),
            );
            assert_eq!(result["result"]["available"], true);
            assert_eq!(result["result"]["chunkX"], x);
            assert_eq!(result["result"]["sections"][0]["minimumBlockY"], -64);
            assert_eq!(
                result["result"]["sections"][0]["blocks"]["palette"][0]["name"],
                "minecraft:stone"
            );
            assert_eq!(
                result["result"]["sections"][0]["blocks"]["indices"]
                    .as_array()
                    .unwrap()
                    .len(),
                4096
            );
        }
        assert_eq!(
            chunk_summary(&f.0, "minecraft:overworld", 30, 30).unwrap()["available"],
            false
        );
        assert_eq!(
            chunk_summary(&f.0, "minecraft:overworld", 1000, 1000).unwrap()["available"],
            false
        );
    }
    #[test]
    fn discovery_and_invalid_dimension_identifiers() {
        let f = Fixture::new();
        for p in [
            "region",
            "DIM-1/region",
            "DIM1/region",
            "dimensions/example/deep/cave/region",
        ] {
            fs::create_dir_all(f.0.join(p)).unwrap();
        }
        let result = dimensions(&f.0).unwrap();
        let ids = result["dimensions"]
            .as_array()
            .unwrap()
            .iter()
            .map(|n| n["id"].as_str().unwrap())
            .collect::<Vec<_>>();
        assert_eq!(
            ids,
            vec![
                "example:deep/cave",
                "minecraft:overworld",
                "minecraft:the_end",
                "minecraft:the_nether"
            ]
        );
        for id in [
            "../region",
            "example:../outside",
            "example:/absolute",
            "example:a//b",
            "example:a\\b",
            "C:/outside",
        ] {
            assert!(chunk_summary(&f.0, id, 0, 0).is_err());
        }
    }
    #[test]
    fn invalid_region_unknown_version_and_coordinate_mismatch() {
        let f = Fixture::new();
        write_chunk(&f.0, 0, 0, 999999);
        assert!(chunk_summary(&f.0, "minecraft:overworld", 0, 0).is_err());
        write_chunk(&f.0, 0, 0, 2975);
        let mut bytes = fs::read(f.0.join("region/r.0.0.mca")).unwrap();
        bytes[6] = 2;
        bytes[7] = 1;
        fs::write(f.0.join("region/r.0.0.mca"), &bytes).unwrap();
        assert!(chunk_summary(&f.0, "minecraft:overworld", 1, 0).is_err());
        fs::write(f.0.join("region/r.0.0.mca"), b"invalid").unwrap();
        let result = crate::protocol::dispatch(
            json!({"version":1,"id":1,"method":"world.chunk_summary","params":{"path":f.0.to_str().unwrap(),"dimension":"minecraft:overworld","chunkX":0,"chunkZ":0}}),
        );
        assert_eq!(result["error"]["code"], "world_read_failed");
        assert!(!result.to_string().contains(f.0.to_str().unwrap()));
    }
    #[test]
    fn frame_output_and_invalid_coordinate_limits() {
        let result = bounded_response(
            json!({"large":"x".repeat(crate::protocol::MAX_FRAME)}),
            &json!(1),
        );
        assert_eq!(result["error"]["code"], "response_too_large");
        let result = crate::protocol::dispatch(
            json!({"version":1,"id":1,"method":"world.chunk_summary","params":{"path":"unused","dimension":"minecraft:overworld","chunkX":2147483648i64,"chunkZ":0}}),
        );
        assert_eq!(result["error"]["code"], "invalid_params");
    }
    #[test]
    fn static_nonregular_region_is_rejected_before_open() {
        let fixture = Fixture::new();
        fs::create_dir_all(fixture.0.join("region/r.0.0.mca")).unwrap();
        assert_eq!(
            chunk_summary(&fixture.0, "minecraft:overworld", 0, 0).unwrap_err(),
            "region is not a regular file"
        );
    }
    #[test]
    fn coordinate_mismatch_and_region_size_limit() {
        let f = Fixture::new();
        write_chunk(&f.0, 0, 0, 2975);
        fs::rename(f.0.join("region/r.0.0.mca"), f.0.join("region/r.1.0.mca")).unwrap();
        assert_eq!(
            chunk_summary(&f.0, "minecraft:overworld", 32, 0).unwrap_err(),
            "chunk coordinate mismatch"
        );
        let file = File::create(f.0.join("region/r.1.0.mca")).unwrap();
        file.set_len(MAX_REGION_BYTES + 4096).unwrap();
        assert_eq!(
            chunk_summary(&f.0, "minecraft:overworld", 32, 0).unwrap_err(),
            "region byte budget exceeded"
        );
    }
    #[test]
    fn invalid_id_does_not_create_an_oversized_error_frame() {
        let result = crate::protocol::dispatch(
            json!({"version":1,"id":"x".repeat(crate::protocol::MAX_FRAME),"method":"engine.info"}),
        );
        assert!(encoded_size_within(&result, crate::protocol::MAX_FRAME));
        assert!(result["id"].is_null());
    }
    #[test]
    fn canonical_containment_rejects_parent_escape() {
        let a = Fixture::new();
        let b = Fixture::new();
        assert!(child(&fs::canonicalize(&a.0).unwrap(), &b.0).is_err());
    }
    #[cfg(windows)]
    #[test]
    fn junction_escape_is_rejected() {
        let world = Fixture::new();
        let outside = Fixture::new();
        let link = world.0.join("DIM-1");
        let result = std::process::Command::new("cmd.exe")
            .args(["/c", "mklink", "/J"])
            .arg(&link)
            .arg(&outside.0)
            .output()
            .unwrap();
        assert!(
            result.status.success(),
            "fixture junction creation unavailable"
        );
        let verdict = dimensions(&world.0);
        fs::remove_dir(&link).unwrap();
        assert!(verdict.is_err());
    }
    #[cfg(unix)]
    #[test]
    fn symlink_escape_is_rejected() {
        let world = Fixture::new();
        let outside = Fixture::new();
        std::os::unix::fs::symlink(&outside.0, world.0.join("DIM-1")).unwrap();
        assert!(dimensions(&world.0).is_err());
    }
}

pub(crate) fn resolve_dimension(path: &Path, id: &str) -> nbt::Result<PathBuf> {
    if !valid_id(id) {
        return Err("invalid dimension identifier");
    }
    let root = root(path)?;
    let relative = match id {
        "minecraft:overworld" => PathBuf::new(),
        "minecraft:the_nether" => PathBuf::from("DIM-1"),
        "minecraft:the_end" => PathBuf::from("DIM1"),
        _ => {
            let (namespace, name) = id.split_once(':').ok_or("invalid dimension identifier")?;
            if name
                .split('/')
                .skip(1)
                .any(|part| ["region", "entities", "poi", "data"].contains(&part))
            {
                return Err("dimension unavailable");
            }
            PathBuf::from("dimensions").join(namespace).join(name)
        }
    };
    let dimension = if relative.as_os_str().is_empty() {
        root.clone()
    } else {
        child(&root, &root.join(relative))?.ok_or("dimension unavailable")?
    };
    if !dimension.is_dir() || !has_region(&dimension)? {
        return Err("dimension unavailable");
    }
    Ok(dimension)
}
