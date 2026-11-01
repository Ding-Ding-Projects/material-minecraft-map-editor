//! Read-set version 1 and bounded canonical page-payload encoding.
use crate::reference::{CAPABILITY, PROFILE, SHAPE_SHA256};
use crate::registry::BLOCKS_SHA256;
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, HashSet},
    io::Write,
};
type Result<T> = std::result::Result<T, &'static str>;
fn field<'a>(v: &'a Value, key: &str) -> Result<&'a Value> {
    v.get(key).ok_or("missing codec field")
}
fn int(v: &Value) -> Result<i32> {
    v.as_i64()
        .and_then(|n| i32::try_from(n).ok())
        .ok_or("signed integer required")
}
fn uint(v: &Value) -> Result<u64> {
    v.as_u64().ok_or("unsigned integer required")
}
fn string(v: &Value) -> Result<&str> {
    v.as_str().ok_or("string required")
}
fn array(v: &Value) -> Result<&[Value]> {
    v.as_array().map(Vec::as_slice).ok_or("array required")
}
pub fn raw_hex(text: &str, length: usize) -> Result<Vec<u8>> {
    if text.len() != length * 2
        || !text
            .bytes()
            .all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c))
    {
        return Err("invalid lowercase hex");
    }
    text.as_bytes()
        .chunks_exact(2)
        .map(|b| {
            u8::from_str_radix(std::str::from_utf8(b).map_err(|_| "invalid hex")?, 16)
                .map_err(|_| "invalid hex")
        })
        .collect()
}
fn utf8(out: &mut Vec<u8>, text: &str, max: usize) -> Result<()> {
    if text.len() > max || text.contains('\0') {
        return Err("invalid digest string");
    }
    let len = u32::try_from(text.len()).map_err(|_| "digest string too long")?;
    out.extend_from_slice(&len.to_be_bytes());
    out.extend_from_slice(text.as_bytes());
    Ok(())
}
fn optional_u64(out: &mut Vec<u8>, v: &Value) -> Result<()> {
    if v.is_null() {
        out.push(0);
    } else {
        out.push(1);
        out.extend_from_slice(&uint(v)?.to_be_bytes());
    }
    Ok(())
}
pub fn read_set_bytes(manifest: &Value) -> Result<Vec<u8>> {
    if uint(field(manifest, "schemaVersion")?)? != 1
        || uint(field(manifest, "readSetEncoding")?)? != 1
    {
        return Err("unsupported terrain encoding version");
    }
    let dimension = string(field(manifest, "dimension")?)?;
    if dimension.is_empty() || dimension.len() > 256 {
        return Err("invalid dimension");
    }
    let b = field(manifest, "bounds")?;
    let names = [
        "chunkXMin",
        "chunkXMax",
        "chunkZMin",
        "chunkZMax",
        "sectionYMin",
        "sectionYMax",
    ];
    let mut bounds = [0i32; 6];
    for (i, key) in names.iter().enumerate() {
        bounds[i] = int(field(b, key)?)?;
    }
    for i in [0, 2, 4] {
        if bounds[i] > bounds[i + 1] || bounds[i + 1] as i64 - bounds[i] as i64 > 2 {
            return Err("invalid terrain bounds");
        }
    }
    if bounds[4] < -128 || bounds[5] > 127 {
        return Err("invalid section bounds");
    }
    if uint(field(manifest, "geometrySchema")?)? != 1
        || string(field(manifest, "geometryCapability")?)? != CAPABILITY
        || string(field(manifest, "shapeEvidenceSha256")?)? != SHAPE_SHA256
    {
        return Err("unsupported geometry binding");
    }
    let r = field(manifest, "registry")?;
    if uint(field(r, "schemaVersion")?)? != 1
        || string(field(r, "version")?)? != PROFILE
        || string(field(r, "sha256")?)? != BLOCKS_SHA256
    {
        return Err("unsupported registry binding");
    }
    let mut out = b"MWETERRAIN\0READSET\0".to_vec();
    out.extend_from_slice(&1u16.to_be_bytes());
    utf8(&mut out, dimension, 256)?;
    for n in bounds {
        out.extend_from_slice(&n.to_be_bytes());
    }
    out.extend_from_slice(&1u16.to_be_bytes());
    utf8(&mut out, CAPABILITY, 64)?;
    out.extend(raw_hex(SHAPE_SHA256, 32)?);
    out.extend_from_slice(&1u16.to_be_bytes());
    utf8(&mut out, PROFILE, 64)?;
    out.extend(raw_hex(BLOCKS_SHA256, 32)?);
    let coverage = array(field(manifest, "coverage")?)?;
    if coverage.len() > 27 {
        return Err("coverage count limit");
    }
    let mut ordered = BTreeMap::new();
    for entry in coverage {
        let key = (
            int(field(entry, "chunkX")?)?,
            int(field(entry, "chunkZ")?)?,
            int(field(entry, "sectionY")?)?,
        );
        if key.0 < bounds[0]
            || key.0 > bounds[1]
            || key.1 < bounds[2]
            || key.1 > bounds[3]
            || key.2 < bounds[4]
            || key.2 > bounds[5]
            || ordered.insert(key, entry).is_some()
        {
            return Err("invalid or duplicate coverage key");
        }
    }
    let expected = (bounds[1] as i64 - bounds[0] as i64 + 1)
        * (bounds[3] as i64 - bounds[2] as i64 + 1)
        * (bounds[5] as i64 - bounds[4] as i64 + 1);
    if ordered.len() as i64 != expected {
        return Err("incomplete coverage");
    }
    out.extend_from_slice(&(ordered.len() as u32).to_be_bytes());
    for ((x, z, y), entry) in ordered {
        for n in [x, z, y] {
            out.extend_from_slice(&n.to_be_bytes());
        }
        let availability = string(field(entry, "availability")?)?;
        let code = match availability {
            "present" => 0,
            "absent-region" => 1,
            "absent-chunk" => 2,
            "no-decoded-section" => 3,
            "unsupported-data-version" => 4,
            "unsupported-encoding" => 5,
            "corrupt" => 6,
            "budget-exceeded" => 7,
            _ => return Err("invalid availability"),
        };
        out.push(code);
        let version = field(entry, "dataVersion")?;
        if version.is_null() {
            if code == 0 {
                return Err("present coverage version missing");
            }
            out.push(0);
        } else {
            let n = int(version)?;
            if code == 0 && n != 3465 {
                return Err("unsupported present version");
            }
            out.push(1);
            out.extend_from_slice(&n.to_be_bytes());
        }
        let mut counts = [0u32; 4];
        for (i, key) in ["decodedCells", "cubeCells", "airCells", "unsupportedCells"]
            .iter()
            .enumerate()
        {
            counts[i] = u32::try_from(uint(field(entry, key)?)?).map_err(|_| "count overflow")?;
            out.extend_from_slice(&counts[i].to_be_bytes());
        }
        if code == 0 {
            if counts[0] != 4096 || counts[2] != 0 || counts[1] as u64 + counts[3] as u64 != 4096 {
                return Err("invalid present counts");
            }
        } else if counts.iter().any(|n| *n != 0) {
            return Err("unavailable coverage has cells");
        }
        let reason = string(field(entry, "reasonCode")?)?;
        if (code == 0 && !reason.is_empty())
            || (code != 0
                && (reason.is_empty()
                    || reason.len() > 64
                    || !reason
                        .bytes()
                        .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == b'_')))
        {
            return Err("invalid reason code");
        }
        utf8(&mut out, reason, 64)?;
    }
    let sources = array(field(manifest, "sources")?)?;
    if sources.len() > 32 {
        return Err("source count limit");
    }
    let mut sorted = BTreeMap::new();
    for source in sources {
        let path = string(field(source, "relativePath")?)?;
        if path.is_empty()
            || path.len() > 4096
            || path.contains(['\0', ':', '\\'])
            || path.starts_with('/')
            || path
                .split('/')
                .any(|p| p.is_empty() || p == "." || p == "..")
            || sorted.insert(path.as_bytes(), source).is_some()
        {
            return Err("invalid or duplicate source path");
        }
    }
    out.extend_from_slice(&(sources.len() as u32).to_be_bytes());
    let mut identities = HashSet::new();
    for (path, source) in sorted {
        utf8(
            &mut out,
            std::str::from_utf8(path).map_err(|_| "invalid path")?,
            4096,
        )?;
        let observed = string(field(source, "observation")?)?;
        let present = match observed {
            "absent" => false,
            "present" => true,
            _ => return Err("invalid source observation"),
        };
        out.push(u8::from(present));
        let identity = field(source, "fileIdentity")?;
        let size = field(source, "fileBytes")?;
        let time = field(source, "lastWriteFileTime")?;
        let hash = field(source, "contentSha256")?;
        if !present {
            if [identity, size, time, hash].iter().any(|v| !v.is_null()) {
                return Err("absent source carries evidence");
            }
            out.extend_from_slice(&[0; 4]);
            continue;
        }
        if [identity, size, time, hash].iter().any(|v| v.is_null()) {
            return Err("present source evidence missing");
        }
        if uint(field(identity, "scheme")?)? != 1 {
            return Err("unsupported source identity scheme");
        }
        let volume = uint(field(identity, "volumeSerial")?)?;
        let id = raw_hex(string(field(identity, "fileId")?)?, 16)?;
        if !identities.insert((volume, id.clone())) {
            return Err("duplicate present source identity");
        }
        out.extend_from_slice(&[1, 1]);
        out.extend_from_slice(&volume.to_be_bytes());
        out.extend(id);
        optional_u64(&mut out, size)?;
        optional_u64(&mut out, time)?;
        out.push(1);
        out.extend(raw_hex(string(hash)?, 32)?);
    }
    Ok(out)
}
pub fn read_set_digest(manifest: &Value) -> Result<String> {
    Ok(format!("{:x}", Sha256::digest(read_set_bytes(manifest)?)))
}
struct Output(Vec<u8>);
impl Write for Output {
    fn write(&mut self, b: &[u8]) -> std::io::Result<usize> {
        if self.0.len().checked_add(b.len()).is_none_or(|n| n > 262144) {
            return Err(std::io::ErrorKind::FileTooLarge.into());
        }
        self.0.extend_from_slice(b);
        Ok(b.len())
    }
    fn flush(&mut self) -> std::io::Result<()> {
        Ok(())
    }
}
fn canonical(v: &Value, out: &mut Output, depth: usize, nodes: &mut usize) -> Result<()> {
    *nodes = nodes.checked_sub(1).ok_or("payload node limit")?;
    if depth > 16 {
        return Err("payload depth limit");
    }
    match v {
        Value::Object(map) => {
            if map.len() > 65536 {
                return Err("payload map limit");
            }
            out.write_all(b"{").map_err(|_| "payload byte limit")?;
            let mut keys = map.keys().collect::<Vec<_>>();
            keys.sort();
            for (i, k) in keys.into_iter().enumerate() {
                if i > 0 {
                    out.write_all(b",").map_err(|_| "payload byte limit")?;
                }
                serde_json::to_writer(&mut *out, k).map_err(|_| "payload encoding failed")?;
                out.write_all(b":").map_err(|_| "payload byte limit")?;
                canonical(&map[k], out, depth + 1, nodes)?;
            }
            out.write_all(b"}").map_err(|_| "payload byte limit")?;
        }
        Value::Array(items) => {
            if items.len() > 65536 {
                return Err("payload array limit");
            }
            out.write_all(b"[").map_err(|_| "payload byte limit")?;
            for (i, item) in items.iter().enumerate() {
                if i > 0 {
                    out.write_all(b",").map_err(|_| "payload byte limit")?;
                }
                canonical(item, out, depth + 1, nodes)?;
            }
            out.write_all(b"]").map_err(|_| "payload byte limit")?;
        }
        Value::Number(n) if n.is_f64() => return Err("payload floating point unsupported"),
        _ => serde_json::to_writer(&mut *out, v).map_err(|_| "payload encoding failed")?,
    }
    Ok(())
}
pub fn payload_bytes(payload: &Value) -> Result<Vec<u8>> {
    let mut out = Output(Vec::new());
    canonical(payload, &mut out, 0, &mut 100000)?;
    Ok(out.0)
}
pub fn payload_digest(payload: &Value) -> Result<String> {
    Ok(format!("{:x}", Sha256::digest(payload_bytes(payload)?)))
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn canonical_unicode_order_and_bounds() {
        let v = serde_json::json!({"z":"水\n","a":[1,null]});
        assert_eq!(
            String::from_utf8(payload_bytes(&v).unwrap()).unwrap(),
            "{\"a\":[1,null],\"z\":\"水\\n\"}"
        );
        assert!(payload_bytes(&serde_json::json!([1.0])).is_err());
        assert!(payload_bytes(&serde_json::json!("x".repeat(262145))).is_err());
    }
}

#[cfg(test)]
mod shared_vectors {
    use super::*;
    use serde_json::Value;
    fn fixtures() -> Value {
        serde_json::from_str(include_str!("../docs/terrain-wire-v1-fixtures.json")).unwrap()
    }
    #[test]
    fn independent_python_readset_and_page_vectors_match() {
        let f = fixtures();
        for case in f["cases"].as_array().unwrap() {
            let manifest = &case["beginResponse"]["result"];
            assert_eq!(
                read_set_digest(manifest).unwrap(),
                case["readSetDigest"].as_str().unwrap()
            );
            let expected = raw_hex(
                case["readSetBytesHex"].as_str().unwrap(),
                read_set_bytes(manifest).unwrap().len(),
            )
            .unwrap();
            assert_eq!(read_set_bytes(manifest).unwrap(), expected);
            for (page, descriptor) in case["pageResponses"]
                .as_array()
                .unwrap()
                .iter()
                .zip(manifest["pages"].as_array().unwrap())
            {
                assert_eq!(
                    payload_digest(&page["result"]["payload"]).unwrap(),
                    descriptor["payloadSha256"].as_str().unwrap()
                );
                assert_eq!(
                    payload_bytes(page).unwrap().len() as u64,
                    descriptor["encodedBytes"].as_u64().unwrap()
                );
            }
        }
    }
    #[test]
    fn independent_negative_vectors_are_rejected() {
        let f = fixtures();
        let original = &f["cases"][0]["beginResponse"]["result"];
        for vector in f["negativeVectors"].as_array().unwrap() {
            let mut m = original.clone();
            *m.pointer_mut(vector["pointer"].as_str().unwrap()).unwrap() = vector["value"].clone();
            assert!(
                read_set_bytes(&m).is_err(),
                "negative codec vector accepted"
            );
        }
        let mut duplicate = original.clone();
        let entry = duplicate["coverage"][0].clone();
        duplicate["coverage"].as_array_mut().unwrap().push(entry);
        assert!(read_set_bytes(&duplicate).is_err());
        let mut duplicate = original.clone();
        duplicate["sources"][1]["fileIdentity"] = duplicate["sources"][0]["fileIdentity"].clone();
        assert!(read_set_bytes(&duplicate).is_err());
    }
    #[test]
    fn runtime_identity_is_separate_from_source_digest() {
        let f = fixtures();
        let original = &f["cases"][0]["beginResponse"]["result"];
        let mut changed = original.clone();
        changed["worldId"] = serde_json::json!("different-world");
        changed["generation"] = serde_json::json!(8);
        changed["sceneId"] = serde_json::json!("different-scene");
        assert_eq!(
            read_set_digest(original).unwrap(),
            read_set_digest(&changed).unwrap()
        );
    }
}
