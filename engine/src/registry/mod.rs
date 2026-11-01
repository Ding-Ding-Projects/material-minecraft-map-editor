//! Immutable vanilla 1.20.1 state membership. No registry fallback or execution.
use crate::chunk::BlockState;
use serde_json::{Map, Value};
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, HashMap, HashSet};
mod json;
pub const DATA_VERSION: i32 = 3465;
pub const SERVER_SHA256: &str = "3af73a9dc5a102e38147946360dd27d4d70bae7055bf91cf2151cd5d121b79e0";
pub const BLOCKS_SHA256: &str = "f10d5da83ec8cd995d4f484b788c5b1467a490728e687c629a681450e3253017";
pub const REGISTRIES_SHA256: &str =
    "3702ca0119f46233c387dda959b42c549daa42b759fc049d834e1012028323f4";
const GENERATOR_LOG_SHA256: &str =
    "31890bb7385e49eef5ac0f2a53f65ef0b86514d973d3e03e5b28eff5fb193090";
const BLOCKS_BYTES: usize = 4915308;
const REGISTRIES_BYTES: usize = 381349;
type Result<T> = std::result::Result<T, &'static str>;
type Properties = Vec<(String, String)>;
struct Block {
    properties: BTreeMap<String, HashSet<String>>,
    states: HashMap<Properties, u32>,
    default: Properties,
    protocol_id: u32,
}
pub struct Registry {
    blocks: HashMap<String, Block>,
    state_count: usize,
    registry_count: usize,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Membership {
    pub state_id: u32,
    pub block_protocol_id: u32,
}
fn object(v: &Value) -> Result<&Map<String, Value>> {
    v.as_object().ok_or("registry object required")
}
fn field<'a>(v: &'a Map<String, Value>, key: &str) -> Result<&'a Value> {
    v.get(key).ok_or("required registry field missing")
}
fn shape(v: &Map<String, Value>, required: &[&str], optional: &[&str]) -> Result<()> {
    if required.iter().any(|k| !v.contains_key(*k))
        || v.keys()
            .any(|k| !required.contains(&k.as_str()) && !optional.contains(&k.as_str()))
    {
        return Err("unexpected registry fields");
    }
    Ok(())
}
fn text(v: &Value) -> Result<&str> {
    let v = v.as_str().ok_or("registry string required")?;
    if v.is_empty() || v.len() > 128 {
        return Err("invalid registry string length");
    }
    Ok(v)
}
fn integer(v: &Value) -> Result<u32> {
    v.as_u64()
        .and_then(|v| u32::try_from(v).ok())
        .ok_or("registry unsigned integer required")
}
fn resource(v: &str) -> bool {
    let Some((namespace, path)) = v.split_once(':') else {
        return false;
    };
    !namespace.is_empty()
        && !path.is_empty()
        && namespace
            .bytes()
            .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || b"_.-".contains(&c))
        && path
            .bytes()
            .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || b"_.-/".contains(&c))
}
fn property_text(v: &str) -> bool {
    !v.is_empty()
        && v.len() <= 64
        && v.bytes()
            .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || b"_-".contains(&c))
}
fn sha(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}
fn receipt(bytes: &[u8]) -> Result<()> {
    let v = json::parse(bytes, 65536)?;
    let v = object(&v)?;
    shape(
        v,
        &[
            "schemaVersion",
            "release",
            "dataVersion",
            "serverSha256",
            "javaVersion",
            "generator",
            "reports",
            "generationTimestamp",
        ],
        &[],
    )?;
    if integer(field(v, "schemaVersion")?)? != 1
        || text(field(v, "release")?)? != "1.20.1"
        || integer(field(v, "dataVersion")?)? != DATA_VERSION as u32
        || text(field(v, "serverSha256")?)? != SERVER_SHA256
        || text(field(v, "javaVersion")?)? != "17.0.19"
        || !field(v, "generationTimestamp")?.is_null()
    {
        return Err("registry provenance binding mismatch");
    }
    let generator = object(field(v, "generator")?)?;
    shape(
        generator,
        &["launcherArguments", "exitCode", "evidence", "logSha256"],
        &[],
    )?;
    let expected = [
        "-DbundlerMainClass=net.minecraft.data.Main",
        "-jar",
        "server.jar",
        "--reports",
        "--output",
        "extracted-reports",
    ];
    let arguments = field(generator, "launcherArguments")?
        .as_array()
        .ok_or("generator arguments required")?;
    if arguments.len() != expected.len()
        || !arguments
            .iter()
            .zip(expected)
            .all(|(a, b)| a.as_str() == Some(b))
        || integer(field(generator, "exitCode")?)? != 0
        || text(field(generator, "evidence")?)? != "controller-observed-exit-and-local-log"
    {
        return Err("unverified registry generator provenance");
    }
    let log = text(field(generator, "logSha256")?)?;
    if log != GENERATOR_LOG_SHA256
        || log.len() != 64
        || !log
            .bytes()
            .all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c))
    {
        return Err("invalid generator log digest");
    }
    let reports = object(field(v, "reports")?)?;
    shape(reports, &["blocks", "registries"], &[])?;
    for (name, size, hash) in [
        ("blocks", BLOCKS_BYTES, BLOCKS_SHA256),
        ("registries", REGISTRIES_BYTES, REGISTRIES_SHA256),
    ] {
        let r = object(field(reports, name)?)?;
        shape(r, &["bytes", "sha256"], &[])?;
        if integer(field(r, "bytes")?)? as usize != size || text(field(r, "sha256")?)? != hash {
            return Err("registry report receipt mismatch");
        }
    }
    Ok(())
}
impl Registry {
    /// The receipt is a producer attestation, not authenticated execution proof.
    /// Exact fixed report hashes are checked independently before parsing reports.
    pub fn load(blocks: &[u8], registries: &[u8], source_receipt: &[u8]) -> Result<Self> {
        receipt(source_receipt)?;
        if blocks.len() != BLOCKS_BYTES
            || registries.len() != REGISTRIES_BYTES
            || sha(blocks) != BLOCKS_SHA256
            || sha(registries) != REGISTRIES_SHA256
        {
            return Err("registry report hash or size mismatch");
        }
        let out = Self::parse(blocks, registries)?;
        if out.blocks.len() != 1003 || out.state_count != 24135 || out.registry_count != 66 {
            return Err("official registry inventory mismatch");
        }
        Ok(out)
    }
    fn parse(blocks: &[u8], registries: &[u8]) -> Result<Self> {
        let blocks = json::parse(blocks, 8 * 1024 * 1024)?;
        let registries = json::parse(registries, 1024 * 1024)?;
        Self::validate(&blocks, &registries)
    }
    fn validate(blocks: &Value, registries: &Value) -> Result<Self> {
        let source = object(blocks)?;
        if source.is_empty() || source.len() > 1003 {
            return Err("block registry count limit exceeded");
        }
        let all_registries = object(registries)?;
        if all_registries.is_empty() || all_registries.len() > 128 {
            return Err("registry count limit exceeded");
        }
        let mut registry_ids = HashSet::new();
        for (name, value) in all_registries {
            if !resource(name) || name.len() > 128 {
                return Err("invalid registry name");
            }
            let definition = object(value)?;
            shape(definition, &["entries", "protocol_id"], &["default"])?;
            if !registry_ids.insert(integer(field(definition, "protocol_id")?)?) {
                return Err("duplicate registry protocol id");
            }
            let entries = object(field(definition, "entries")?)?;
            if entries.len() > 65536 {
                return Err("registry entry limit exceeded");
            }
            let mut ids = HashSet::new();
            for (name, value) in entries {
                if !resource(name) || name.len() > 128 {
                    return Err("invalid registry entry name");
                }
                let entry = object(value)?;
                shape(entry, &["protocol_id"], &[])?;
                if !ids.insert(integer(field(entry, "protocol_id")?)?) {
                    return Err("duplicate registry entry id");
                }
            }
            if name == "minecraft:block"
                && ids
                    .iter()
                    .copied()
                    .max()
                    .is_some_and(|n| n as u64 + 1 != entries.len() as u64)
            {
                return Err("noncontiguous registry entry ids");
            }
            if let Some(default) = definition.get("default") {
                if !entries.contains_key(text(default)?) {
                    return Err("registry default unavailable");
                }
            }
        }
        if registry_ids
            .iter()
            .copied()
            .max()
            .is_some_and(|n| n as u64 + 1 != all_registries.len() as u64)
        {
            return Err("noncontiguous registry protocol ids");
        }
        let block_registry = object(field(all_registries, "minecraft:block")?)?;
        if text(field(block_registry, "default")?)? != "minecraft:air" {
            return Err("unexpected block registry default");
        }
        let protocol_entries = object(field(block_registry, "entries")?)?;
        if protocol_entries.len() != source.len()
            || source.keys().any(|k| !protocol_entries.contains_key(k))
        {
            return Err("cross-report block inventory mismatch");
        }
        let mut result = HashMap::new();
        let mut global_ids = HashSet::new();
        for (name, value) in source {
            if !resource(name) || name.len() > 128 {
                return Err("invalid block name");
            }
            let definition = object(value)?;
            shape(definition, &["states"], &["properties"])?;
            let mut properties = BTreeMap::new();
            let mut product = 1usize;
            if let Some(p) = definition.get("properties") {
                let p = object(p)?;
                if p.is_empty() || p.len() > 16 {
                    return Err("block property count exceeded");
                }
                for (key, values) in p {
                    if !property_text(key) {
                        return Err("invalid property key");
                    }
                    let values = values.as_array().ok_or("property values array required")?;
                    if values.is_empty() || values.len() > 64 {
                        return Err("property value count exceeded");
                    }
                    let mut set = HashSet::new();
                    for value in values {
                        let value = text(value)?;
                        if !property_text(value) || !set.insert(value.to_owned()) {
                            return Err("invalid or duplicate property value");
                        }
                    }
                    product = product
                        .checked_mul(set.len())
                        .filter(|n| *n <= 4096)
                        .ok_or("state product limit exceeded")?;
                    properties.insert(key.clone(), set);
                }
            }
            let states = field(definition, "states")?
                .as_array()
                .ok_or("block state array required")?;
            if states.len() != product {
                return Err("incomplete block state combinations");
            }
            let mut lookup = HashMap::new();
            let mut default = None;
            for state in states {
                let state = object(state)?;
                shape(state, &["id"], &["properties", "default"])?;
                let id = integer(field(state, "id")?)?;
                if !global_ids.insert(id) || global_ids.len() > 65536 {
                    return Err("duplicate or excessive state ids");
                }
                let mut state_properties = Vec::new();
                if let Some(p) = state.get("properties") {
                    for (k, v) in object(p)? {
                        let value = text(v)?;
                        if !properties
                            .get(k)
                            .is_some_and(|values| values.contains(value))
                        {
                            return Err("invalid state property membership");
                        }
                        state_properties.push((k.clone(), value.to_owned()));
                    }
                }
                if state_properties.len() != properties.len() {
                    return Err("state property keys incomplete");
                }
                state_properties.sort();
                if lookup.insert(state_properties.clone(), id).is_some() {
                    return Err("duplicate state combination");
                }
                if let Some(marker) = state.get("default") {
                    if marker.as_bool() != Some(true) || default.replace(state_properties).is_some()
                    {
                        return Err("invalid or duplicate default state");
                    }
                }
            }
            let protocol = integer(field(
                object(field(protocol_entries, name)?)?,
                "protocol_id",
            )?)?;
            result.insert(
                name.clone(),
                Block {
                    properties,
                    states: lookup,
                    default: default.ok_or("default state missing")?,
                    protocol_id: protocol,
                },
            );
        }
        if global_ids
            .iter()
            .copied()
            .max()
            .is_some_and(|n| n as u64 + 1 != global_ids.len() as u64)
        {
            return Err("noncontiguous state ids");
        }
        Ok(Self {
            blocks: result,
            state_count: global_ids.len(),
            registry_count: all_registries.len(),
        })
    }
    pub(crate) fn memory_charge(&self) -> usize {
        fn pairs(p: &Properties) -> usize {
            p.capacity() * std::mem::size_of::<(String, String)>()
                + p.iter()
                    .map(|(k, v)| k.capacity() + v.capacity())
                    .sum::<usize>()
        }
        let mut total = self.blocks.capacity() * 2 * std::mem::size_of::<(String, Block)>() + 4096;
        for (name, block) in &self.blocks {
            total += name.capacity()
                + 4096
                + block.properties.len() * 2 * std::mem::size_of::<(String, HashSet<String>)>();
            for (key, values) in &block.properties {
                total += key.capacity()
                    + 4096
                    + values.capacity() * 2 * std::mem::size_of::<String>()
                    + values.iter().map(String::capacity).sum::<usize>();
            }
            total += block.states.capacity() * 2 * std::mem::size_of::<(Properties, u32)>() + 4096;
            for key in block.states.keys() {
                total += pairs(key);
            }
            total += pairs(&block.default);
        }
        total
    }
    pub fn data_version(&self) -> i32 {
        DATA_VERSION
    }
    pub fn block_count(&self) -> usize {
        self.blocks.len()
    }
    pub fn registry_count(&self) -> usize {
        self.registry_count
    }
    pub fn state_count(&self) -> usize {
        self.state_count
    }
    pub fn membership(&self, state: &BlockState) -> Result<Membership> {
        if state.name.len() > 128
            || state.properties.len() > 16
            || state
                .properties
                .iter()
                .any(|(k, v)| k.len() > 64 || v.len() > 64)
        {
            return Err("registry membership input limits exceeded");
        }
        let block = self
            .blocks
            .get(&state.name)
            .ok_or("unknown registry block")?;
        if state.properties.len() != block.properties.len() {
            return Err("registry property keys mismatch");
        }
        let mut properties = Vec::with_capacity(state.properties.len());
        let mut seen = HashSet::new();
        for (key, value) in &state.properties {
            if !seen.insert(key)
                || !block
                    .properties
                    .get(key)
                    .is_some_and(|values| values.contains(value))
            {
                return Err("invalid registry property membership");
            }
            properties.push((key.clone(), value.clone()));
        }
        properties.sort();
        let state_id = *block
            .states
            .get(&properties)
            .ok_or("registry state combination unavailable")?;
        Ok(Membership {
            state_id,
            block_protocol_id: block.protocol_id,
        })
    }
    /// Explicit default resolution is separate from strict membership validation.
    pub fn default_state(&self, name: &str) -> Result<BlockState> {
        if name.len() > 128 {
            return Err("registry block name limit exceeded");
        }
        let block = self.blocks.get(name).ok_or("unknown registry block")?;
        Ok(BlockState {
            name: name.into(),
            properties: block.default.clone(),
        })
    }
    #[cfg(test)]
    pub(crate) fn test_propertyless(names: &[String]) -> Self {
        let mut blocks = HashMap::new();
        for (index, name) in names.iter().enumerate() {
            blocks.insert(
                name.clone(),
                Block {
                    properties: BTreeMap::new(),
                    states: HashMap::from([(vec![], index as u32)]),
                    default: vec![],
                    protocol_id: index as u32,
                },
            );
        }
        Self {
            state_count: blocks.len(),
            registry_count: 1,
            blocks,
        }
    }
}
#[cfg(test)]
mod tests;

pub(crate) fn parse_reference_metadata(bytes: &[u8]) -> Result<Value> {
    json::parse_with_string_limit(bytes, 65536, 1024)
}

pub(crate) fn parse_protocol(bytes: &[u8]) -> Result<Value> {
    json::parse_with_limits(bytes, crate::protocol::MAX_FRAME, 32768, 10000)
}
