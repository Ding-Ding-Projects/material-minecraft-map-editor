//! Explicit, immutable startup references. No discovery, acquisition or execution.
use crate::{
    chunk::BlockState,
    file_source::{Error, Source},
    registry::{Registry, BLOCKS_SHA256, REGISTRIES_SHA256},
};
use serde_json::{json, Value};
use std::{
    ffi::OsString,
    path::{Path, PathBuf},
    sync::Arc,
};
pub const PROFILE: &str = "vanilla-java-1.20.1";
pub const SHAPE_SHA256: &str = "88b22690a55926aa1e6b3cc4a29ca52107a1699983d7a36a504c4d8ef1320a21";
pub const RECEIPT_SHA256: &str = "8f81ca9b461bad9c371d9fb1bdec7165ada5c0ebb9802982015ed0dddbcb4cde";
pub const CAPABILITY: &str = "cube-shapes-v1";
#[derive(Default)]
pub struct Options {
    pub root: Option<PathBuf>,
    pub profile: Option<String>,
}
impl Options {
    pub fn parse(args: impl IntoIterator<Item = OsString>) -> Result<Self, &'static str> {
        let mut args = args.into_iter();
        let mut out = Self::default();
        while let Some(flag) = args.next() {
            match flag.to_str() {
                Some("--reference-root") if out.root.is_none() => {
                    out.root = Some(args.next().ok_or("missing reference root argument")?.into())
                }
                Some("--reference-profile") if out.profile.is_none() => {
                    let value = args
                        .next()
                        .ok_or("missing reference profile argument")?
                        .into_string()
                        .map_err(|_| "invalid profile text")?;
                    if value.len() > 64 || !value.is_ascii() {
                        return Err("invalid profile text");
                    }
                    out.profile = Some(value)
                }
                _ => return Err("unknown or duplicate startup argument"),
            }
        }
        if out.root.is_some() != out.profile.is_some() {
            return Err("reference root and profile must be supplied together");
        }
        Ok(out)
    }
}
pub struct Reference {
    pub(crate) registry: Registry,
    pub(crate) memory_charge: usize,
}
#[derive(Clone)]
pub enum Availability {
    Ready(Arc<Reference>),
    Unavailable(&'static str),
}
fn read(root: &Path, name: &str, size: usize, hash: &str) -> Result<Vec<u8>, &'static str> {
    Source::pinned(root, Path::new(name), size, hash).map_err(|e| match e {
        Error::Missing => "reference_file_missing",
        Error::Escape | Error::Linked => "reference_path_rejected",
        Error::Nonregular => "reference_nonregular",
        Error::Budget => "reference_size_mismatch",
        Error::Changed => "reference_hash_or_change_mismatch",
        Error::Identity => "reference_identity_unavailable",
        Error::Timeout => "reference_read_unavailable",
        Error::Io => "reference_read_unavailable",
    })
}
impl Availability {
    pub fn load(options: Options) -> Self {
        let Some(selected) = options.root else {
            return Self::Unavailable("reference_root_missing");
        };
        if options.profile.as_deref() != Some(PROFILE) {
            return Self::Unavailable("unsupported_reference_profile");
        }
        if !selected.is_absolute() {
            return Self::Unavailable("reference_root_not_absolute");
        }
        let root = match std::fs::canonicalize(selected) {
            Ok(p) if p.is_dir() => p,
            _ => return Self::Unavailable("reference_directory_unavailable"),
        };
        let loaded = (|| {
            let blocks = read(&root, "reports/blocks.json", 4915308, BLOCKS_SHA256)?;
            let registries = read(&root, "reports/registries.json", 381349, REGISTRIES_SHA256)?;
            let receipt = read(&root, "registry-source-receipt.json", 864, RECEIPT_SHA256)?;
            let shape = read(
                &root,
                "java-geometry-reference-evidence.json",
                2881,
                SHAPE_SHA256,
            )?;
            let registry = Registry::load(&blocks, &registries, &receipt)
                .map_err(|_| "strict_registry_invalid")?;
            validate_shape(&shape)?;
            let memory_charge = registry.memory_charge();
            if memory_charge > 32 * 1024 * 1024 {
                return Err("reference_memory_budget");
            }
            Ok(Reference {
                registry,
                memory_charge,
            })
        })();
        match loaded {
            Ok(r) => Self::Ready(Arc::new(r)),
            Err(reason) => Self::Unavailable(reason),
        }
    }
    pub fn summary(&self) -> Value {
        match self {
            Self::Ready(_) => {
                json!({"status":"ready","profile":PROFILE,"dataVersion":3465,"registry":registry_identity(),"shapeEvidenceSha256":SHAPE_SHA256,"availableGeometryEvidence":[CAPABILITY]})
            }
            Self::Unavailable(reason) => json!({"status":"unavailable","reasonCode":reason}),
        }
    }
}
pub fn registry_identity() -> Value {
    json!({"schemaVersion":1,"version":PROFILE,"sha256":BLOCKS_SHA256})
}
impl Reference {
    pub fn state(&self, state: &BlockState) -> (Option<u32>, bool) {
        match self.registry.membership(state) {
            Ok(m) => (
                Some(m.state_id),
                state.properties.is_empty()
                    && matches!(
                        state.name.as_str(),
                        "minecraft:stone" | "minecraft:cobblestone"
                    ),
            ),
            Err(_) => (None, false),
        }
    }
}
const MEMBERS: [(&str, &str, u64); 10] = [
    (
        "assets/minecraft/blockstates/stone.json",
        "34476f2bb98e7abec029c07c3cbfd8ba3a0141c0df3f02ff255018dbec625bbc",
        324,
    ),
    (
        "assets/minecraft/blockstates/cobblestone.json",
        "2f97205b9cd9cc167bd2f2ad8036237707a48ee1deb032273bd96565aff64c77",
        84,
    ),
    (
        "assets/minecraft/models/block/stone.json",
        "c0734082e7f1e2f44809737b2fbe1136fc7304bde7232e45fbe921884a4a327e",
        98,
    ),
    (
        "assets/minecraft/models/block/stone_mirrored.json",
        "f6127c3048b1812b664209825271553c71c2b2dae9d6a19933702b6fdbe34370",
        107,
    ),
    (
        "assets/minecraft/models/block/cobblestone.json",
        "dee026b80b7b77c5d540d75b91cfaec770245a2e7affb53555e9e4ad3ddb551f",
        104,
    ),
    (
        "assets/minecraft/models/block/cube_all.json",
        "be3205d629ffb9e03834c3d1d083f8a2c62e9f9ae80820755129408634e9144a",
        227,
    ),
    (
        "assets/minecraft/models/block/cube.json",
        "3e4aacd02e816aeba38f83076596e18ded4cf49c01e17c62d1fce79850ffb84e",
        584,
    ),
    (
        "assets/minecraft/models/block/cube_mirrored_all.json",
        "eb0682e3126d537e8a15af343bc40e32339baa63f4f541143ed969e25e9231e0",
        236,
    ),
    (
        "assets/minecraft/models/block/cube_mirrored.json",
        "e0a7b21709196c8641177e68a0a5e2a25d1de8f82e7ece75120dd38ed5d7a0fa",
        687,
    ),
    (
        "assets/minecraft/models/block/block.json",
        "3ef6c442f1ab55d2a57fa58e28bb831268159052659f12b453b637b31ded1da8",
        997,
    ),
];
fn validate_shape(bytes: &[u8]) -> Result<(), &'static str> {
    let data =
        crate::registry::parse_reference_metadata(bytes).map_err(|_| "shape_manifest_invalid")?;
    if data != expected_shape() {
        return Err("shape_manifest_binding_mismatch");
    }
    Ok(())
}
fn expected_shape() -> Value {
    let mut expected = serde_json::Map::new();
    for(key,value)in[("schemaVersion",json!(1)),("release",json!("1.20.1")),("dataVersion",json!(3465)),("clientUrl",json!("https://piston-data.mojang.com/v1/objects/0c3ec587af28e5a785c0b4a7b8a30f9a8f78f838/client.jar")),("clientSha1",json!("0c3ec587af28e5a785c0b4a7b8a30f9a8f78f838")),("clientSha256",json!("56b71336d2b4fdffd197f56595b0da93e32a946f78f382a299b8f4b92758bb0f")),("clientBytes",json!(23028853)),("executed",json!(false)),("assetsRedistributed",json!(false))]{expected.insert(key.into(),value);}
    expected.insert(
        "members".into(),
        Value::Array(
            MEMBERS
                .iter()
                .map(|(path, sha, bytes)| json!({"path":path,"sha256":sha,"bytes":bytes}))
                .collect(),
        ),
    );
    expected.insert("observations".into(),json!([{"block":"minecraft:cobblestone","properties":{},"shape":"unit-cube","variantCount":1},{"block":"minecraft:stone","properties":{},"shape":"unit-cube","variantCount":4}]));
    expected.insert("evidenceScope".into(),json!("All referenced variants for these two propertyless blocks resolve to one axis-aligned element spanning model coordinates 0 through 16 on every axis, with all six faces. Stone variants differ by texture mirroring and 180-degree Y rotation, which preserve these bounds. No other block geometry, texture rendering, opacity, lighting, collision or complete world-rendering claim."));
    Value::Object(expected)
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn no_default_root_or_implicit_startup_pair() {
        assert!(matches!(
            Availability::load(Options::default()),
            Availability::Unavailable("reference_root_missing")
        ));
        assert!(Options::parse([
            OsString::from("--reference-root"),
            OsString::from("relative")
        ])
        .is_err());
        assert!(Options::parse([OsString::from("--unknown")]).is_err());
        let options = Options::parse(
            [
                "--reference-root",
                "relative",
                "--reference-profile",
                PROFILE,
            ]
            .map(OsString::from),
        )
        .unwrap();
        assert!(matches!(
            Availability::load(options),
            Availability::Unavailable("reference_root_not_absolute")
        ));
    }
    #[test]
    #[ignore = "requires explicitly selected exact reference profile files"]
    fn actual_explicit_reference_root() {
        let root = PathBuf::from(
            std::env::var_os("MWE_TEST_REFERENCE_ROOT")
                .expect("explicit test reference root required"),
        );
        let loaded = Availability::load(Options {
            root: Some(root),
            profile: Some(PROFILE.into()),
        });
        let Availability::Ready(r) = loaded else {
            panic!("exact reference root unavailable")
        };
        let stone = BlockState {
            name: "minecraft:stone".into(),
            properties: vec![],
        };
        assert_eq!(r.state(&stone), (Some(1), true));
        let air = BlockState {
            name: "minecraft:air".into(),
            properties: vec![],
        };
        assert_eq!(r.state(&air), (Some(0), false));
    }
}

#[cfg(test)]
mod negative_tests {
    use super::*;
    #[test]
    fn shape_identity_types_counts_and_scope_cannot_be_weakened() {
        let value = expected_shape();
        assert!(validate_shape(&serde_json::to_vec(&value).unwrap()).is_ok());
        for (key, bad) in [
            ("schemaVersion", json!(true)),
            ("dataVersion", json!(2975)),
            ("executed", json!(true)),
            ("evidenceScope", json!("opaque cubes")),
        ] {
            let mut v = value.clone();
            v[key] = bad;
            assert!(validate_shape(&serde_json::to_vec(&v).unwrap()).is_err());
        }
        let mut v = value.clone();
        v["members"][0]["bytes"] = json!(true);
        assert!(validate_shape(&serde_json::to_vec(&v).unwrap()).is_err());
        let mut v = value;
        v["observations"][1]["variantCount"] = json!(1);
        assert!(validate_shape(&serde_json::to_vec(&v).unwrap()).is_err());
    }
    #[test]
    fn unknown_profile_and_missing_files_remain_unavailable() {
        let root = std::env::temp_dir().join(format!(
            "reference-empty-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        std::fs::create_dir(&root).unwrap();
        assert!(matches!(
            Availability::load(Options {
                root: Some(root.clone()),
                profile: Some("unknown".into())
            }),
            Availability::Unavailable("unsupported_reference_profile")
        ));
        assert!(matches!(
            Availability::load(Options {
                root: Some(root.clone()),
                profile: Some(PROFILE.into())
            }),
            Availability::Unavailable("reference_file_missing")
        ));
        std::fs::remove_dir(root).unwrap();
    }
}
