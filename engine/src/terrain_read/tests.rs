use super::*;
use std::fs;
struct Fixture(PathBuf);
use std::path::PathBuf;
impl Fixture {
    fn new(name: &str) -> Self {
        let root = std::env::temp_dir().join(format!(
            "terrain-read-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        fs::create_dir(&root).unwrap();
        let fixtures: Value =
            serde_json::from_str(include_str!("../../docs/terrain-wire-v1-fixtures.json")).unwrap();
        let case = fixtures["cases"]
            .as_array()
            .unwrap()
            .iter()
            .find(|v| v["name"] == name)
            .unwrap();
        for file in case["files"].as_array().unwrap() {
            let target = root.join(file["relativePath"].as_str().unwrap());
            fs::create_dir_all(target.parent().unwrap()).unwrap();
            let hex = file["bytesHex"].as_str().unwrap();
            fs::write(
                target,
                crate::terrain_codec::raw_hex(hex, hex.len() / 2).unwrap(),
            )
            .unwrap();
        }
        fs::create_dir_all(root.join("region")).unwrap();
        Self(root)
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        fs::remove_dir_all(&self.0).unwrap();
    }
}
fn bounds() -> Bounds {
    Bounds {
        xmin: -1,
        xmax: -1,
        zmin: 0,
        zmax: 0,
        ymin: -4,
        ymax: -4,
    }
}
fn counts(s: Section) -> Result<Counts, &'static str> {
    assert_eq!((s.x, s.z, s.y), (-1, 0, -4));
    assert_eq!(s.indices.len(), 4096);
    let cube = s
        .indices
        .iter()
        .filter(|n| s.palette[**n as usize].name == "minecraft:stone")
        .count() as u32;
    Ok(Counts {
        cube,
        unsupported: 4096 - cube,
    })
}
#[test]
fn actual_selected_sectors_preserve_cells_and_hash_full_large_file() {
    let fixture = Fixture::new("one_cube_and_unsupported_cells");
    let path = fixture.0.join("region/r.-1.0.mca");
    fs::OpenOptions::new()
        .write(true)
        .open(&path)
        .unwrap()
        .set_len(64 * MIB as u64)
        .unwrap();
    let result = read(
        &fixture.0,
        "minecraft:overworld",
        bounds(),
        Instant::now() + std::time::Duration::from_secs(10),
        counts,
    )
    .unwrap();
    assert_eq!(result.coverage[0]["decodedCells"], 4096);
    assert_eq!(result.coverage[0]["cubeCells"], 1);
    assert_eq!(result.coverage[0]["unsupportedCells"], 4095);
    assert_eq!(result.selected_sector_bytes, 4096);
    assert!(result.hashed_bytes >= 64 * MIB as u64);
    assert!(result.temporary_peak <= TEMP);
    assert_eq!(fs::metadata(path).unwrap().len(), 64 * MIB as u64);
}
#[test]
fn absent_and_unsupported_are_never_invented_air() {
    let fixture = Fixture::new("absent_region");
    let result = read(
        &fixture.0,
        "minecraft:overworld",
        bounds(),
        Instant::now() + std::time::Duration::from_secs(10),
        |_| panic!("absent section decoded"),
    )
    .unwrap();
    assert_eq!(result.coverage[0]["availability"], "absent-region");
    assert_eq!(result.coverage[0]["decodedCells"], 0);
    assert_eq!(
        result
            .sources
            .iter()
            .filter(|s| s["observation"] == "absent")
            .count(),
        1
    );
    let fixture = Fixture::new("unsupported_only");
    let result = read(
        &fixture.0,
        "minecraft:overworld",
        bounds(),
        Instant::now() + std::time::Duration::from_secs(10),
        counts,
    )
    .unwrap();
    assert_eq!(result.coverage[0]["airCells"], 0);
    assert_eq!(result.coverage[0]["unsupportedCells"], 4096);
}
#[test]
fn changed_sources_reject_entire_read_and_deadline_is_checked() {
    let fixture = Fixture::new("one_cube_and_unsupported_cells");
    let changed = fixture.0.join("region/r.-1.0.mca");
    let result = read(
        &fixture.0,
        "minecraft:overworld",
        bounds(),
        Instant::now() + std::time::Duration::from_secs(10),
        |s| {
            let result = counts(s);
            fs::OpenOptions::new()
                .write(true)
                .open(&changed)
                .unwrap()
                .set_len(16384)
                .unwrap();
            result
        },
    );
    assert_eq!(result.err(), Some("changed_during_read"));
    assert_eq!(
        read(
            Path::new("unused"),
            "minecraft:overworld",
            bounds(),
            Instant::now(),
            counts
        )
        .err(),
        Some("terrain_timed_out")
    );
}
#[test]
fn static_corrupt_chunk_retains_consistent_unavailable_coverage() {
    let fixture = Fixture::new("one_cube_and_unsupported_cells");
    let path = fixture.0.join("region/r.-1.0.mca");
    let mut bytes = fs::read(&path).unwrap();
    bytes[8192..8196].fill(0);
    fs::write(&path, bytes).unwrap();
    let result = read(
        &fixture.0,
        "minecraft:overworld",
        bounds(),
        Instant::now() + std::time::Duration::from_secs(10),
        |_| panic!("corrupt chunk decoded"),
    )
    .unwrap();
    assert_eq!(result.coverage[0]["availability"], "corrupt");
    assert_eq!(result.sources.len(), 2);
    assert_eq!(result.coverage[0]["decodedCells"], 0);
}
