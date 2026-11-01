use crate::{
    nbt::{self, Limits, Tag},
    region,
};
use serde_json::{json, Value};
use std::{fs::File, io::Read, path::Path};
pub fn probe(path: &Path) -> nbt::Result<Value> {
    let limits = Limits::default();
    let mut data = Vec::new();
    File::open(path.join("level.dat"))
        .map_err(|_| "level.dat unavailable")?
        .take(limits.bytes as u64 + 1)
        .read_to_end(&mut data)
        .map_err(|_| "level.dat read failed")?;
    if data.len() > limits.bytes {
        return Err("compressed byte budget exceeded");
    }
    let bytes = region::decompress(1, &data, limits.bytes)?;
    let root = nbt::parse(&bytes, limits)?;
    let Tag::Compound(root) = root.tag else {
        return Err("invalid world root");
    };
    let mut values = root.iter().filter(|v| v.name == b"Data");
    let data = values.next().ok_or("missing world Data")?;
    if values.next().is_some() {
        return Err("ambiguous world Data");
    }
    let Tag::Compound(fields) = &data.tag else {
        return Err("invalid world Data");
    };
    let mut versions = fields.iter().filter(|v| v.name == b"DataVersion");
    let version = match versions.next().map(|v| &v.tag) {
        Some(Tag::Int(n)) => Some(*n),
        None => None,
        _ => return Err("invalid DataVersion"),
    };
    if versions.next().is_some() {
        return Err("ambiguous DataVersion");
    }
    Ok(
        json!({"edition":"java","dataVersion":version,"readOnly":true,"editingSupported":false,"versionSupport":"structural-probe-only"}),
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;
    #[test]
    fn gzip_world_probe_and_truncation() {
        let root = nbt::NamedTag {
            name: vec![],
            tag: Tag::Compound(vec![nbt::NamedTag {
                name: b"Data".to_vec(),
                tag: Tag::Compound(vec![nbt::NamedTag {
                    name: b"DataVersion".to_vec(),
                    tag: Tag::Int(1343),
                }]),
            }]),
        };
        let bytes = nbt::write(&root, Limits::default()).unwrap();
        let mut encoder = flate2::write::GzEncoder::new(Vec::new(), flate2::Compression::default());
        encoder.write_all(&bytes).unwrap();
        let gzip = encoder.finish().unwrap();
        assert_eq!(region::decompress(1, &gzip, 1024).unwrap(), bytes);
        assert!(region::decompress(1, &gzip[..gzip.len() - 1], 1024).is_err());
        let mut extra = gzip.clone();
        extra.push(0);
        assert!(region::decompress(1, &extra, 1024).is_err());
        let dir = std::env::temp_dir().join(format!(
            "material-engine-test-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        std::fs::create_dir(&dir).unwrap();
        std::fs::write(dir.join("level.dat"), gzip).unwrap();
        let result = probe(&dir);
        std::fs::remove_file(dir.join("level.dat")).unwrap();
        std::fs::remove_dir(&dir).unwrap();
        assert_eq!(result.unwrap()["dataVersion"], 1343);
    }
}
