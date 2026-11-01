use super::*;
use serde_json::json;
fn fixture() -> (Value, Value) {
    let blocks = json!({"minecraft:air":{"states":[{"id":0,"default":true}]},"fixture:panel":{"properties":{"facing":["north","south"],"powered":["false","true"]},"states":[{"id":1,"properties":{"facing":"north","powered":"false"},"default":true},{"id":2,"properties":{"facing":"north","powered":"true"}},{"id":3,"properties":{"facing":"south","powered":"false"}},{"id":4,"properties":{"facing":"south","powered":"true"}}]}});
    let registries = json!({"minecraft:block":{"protocol_id":0,"default":"minecraft:air","entries":{"minecraft:air":{"protocol_id":0},"fixture:panel":{"protocol_id":1}}}});
    (blocks, registries)
}
fn state(name: &str, properties: &[(&str, &str)]) -> BlockState {
    BlockState {
        name: name.into(),
        properties: properties
            .iter()
            .map(|(k, v)| (k.to_string(), v.to_string()))
            .collect(),
    }
}
#[test]
fn complete_combinations_and_strict_membership() {
    let (b, r) = fixture();
    let registry = Registry::validate(&b, &r).unwrap();
    assert_eq!(
        registry
            .membership(&state("minecraft:air", &[]))
            .unwrap()
            .state_id,
        0
    );
    assert_eq!(
        registry
            .membership(&state(
                "fixture:panel",
                &[("powered", "true"), ("facing", "south")]
            ))
            .unwrap()
            .state_id,
        4
    );
    for s in [
        state("fixture:missing", &[]),
        state("fixture:panel", &[("facing", "north")]),
        state("fixture:panel", &[("facing", "up"), ("powered", "true")]),
        state("fixture:panel", &[("facing", "north"), ("facing", "south")]),
        state(
            "fixture:panel",
            &[("facing", "north"), ("powered", "false"), ("extra", "x")],
        ),
        state(
            "Fixture:panel",
            &[("facing", "north"), ("powered", "false")],
        ),
    ] {
        assert!(registry.membership(&s).is_err());
    }
    assert_eq!(
        registry.default_state("fixture:panel").unwrap(),
        state(
            "fixture:panel",
            &[("facing", "north"), ("powered", "false")]
        )
    );
}
#[test]
fn malformed_report_inventories_are_rejected() {
    let (b, r) = fixture();
    let mut variants = Vec::new();
    let mut v = b.clone();
    v["fixture:panel"]["states"][1]["id"] = json!(true);
    variants.push(v);
    let mut v = b.clone();
    v["fixture:panel"]["states"][1]["id"] = json!(1);
    variants.push(v);
    let mut v = b.clone();
    v["fixture:panel"]["states"][1]["properties"] =
        v["fixture:panel"]["states"][0]["properties"].clone();
    variants.push(v);
    let mut v = b.clone();
    v["fixture:panel"]["states"][1]["default"] = json!(true);
    variants.push(v);
    let mut v = b.clone();
    v["fixture:panel"]["properties"]["facing"] = json!(["north", "north"]);
    variants.push(v);
    let mut v = b.clone();
    v["fixture:panel"]["states"].as_array_mut().unwrap().pop();
    variants.push(v);
    let mut v = b.clone();
    v["fixture:panel"]["states"][0]["properties"]["unexpected"] = json!("x");
    variants.push(v);
    for v in variants {
        assert!(Registry::validate(&v, &r).is_err());
    }
    let mut bad = r.clone();
    bad["minecraft:block"]["entries"]
        .as_object_mut()
        .unwrap()
        .remove("fixture:panel");
    assert!(Registry::validate(&b, &bad).is_err());
    let mut bad = r.clone();
    bad["minecraft:block"]["entries"]["fixture:panel"]["protocol_id"] = json!(true);
    assert!(Registry::validate(&b, &bad).is_err());
}
#[test]
fn bounded_unique_key_parser_rejects_malformed_shapes() {
    for bytes in [
        br#"{"same":1,"same":2}"#.as_slice(),
        br#"{"outer":{"key":0,"key":1}}"#,
        b"[",
        b"{} true",
    ] {
        assert!(json::parse(bytes, 1024).is_err());
    }
    assert!(json::parse(&vec![b' '; 1025], 1024).is_err());
    assert!(json::parse(
        format!("{}0{}", "[".repeat(17), "]".repeat(17)).as_bytes(),
        1024
    )
    .is_err());
    assert!(json::parse(format!("\"{}\"", "x".repeat(257)).as_bytes(), 1024).is_err());
}
fn receipt_value() -> Value {
    json!({"schemaVersion":1,"release":"1.20.1","dataVersion":3465,"serverSha256":SERVER_SHA256,"javaVersion":"17.0.19","generator":{"launcherArguments":["-DbundlerMainClass=net.minecraft.data.Main","-jar","server.jar","--reports","--output","extracted-reports"],"exitCode":0,"evidence":"controller-observed-exit-and-local-log","logSha256":GENERATOR_LOG_SHA256},"reports":{"blocks":{"bytes":BLOCKS_BYTES,"sha256":BLOCKS_SHA256},"registries":{"bytes":REGISTRIES_BYTES,"sha256":REGISTRIES_SHA256}},"generationTimestamp":null})
}
#[test]
fn fixed_provenance_is_required_not_a_structural_fallback() {
    let valid = serde_json::to_vec(&receipt_value()).unwrap();
    assert!(receipt(&valid).is_ok());
    assert!(Registry::load(b"{}", b"{}", &valid).is_err());
    assert!(Registry::load(b"{}", b"{}", b"{}").is_err());
    for (key, value) in [
        ("schemaVersion", json!(true)),
        ("dataVersion", json!(2975)),
        ("release", json!("1.20")),
        ("serverSha256", json!("0".repeat(64))),
    ] {
        let mut v = receipt_value();
        v[key] = value;
        assert!(receipt(&serde_json::to_vec(&v).unwrap()).is_err());
    }
    let mut v = receipt_value();
    v["generator"]["exitCode"] = json!(true);
    assert!(receipt(&serde_json::to_vec(&v).unwrap()).is_err());
}
#[test]
#[ignore = "requires pinned ignored official reports and controller provenance receipt"]
fn official_1201_report_membership() {
    use std::path::Path;
    let base = Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .join("build/java-reference/1.20.1");
    let b = std::fs::read(base.join("extracted-reports/reports/blocks.json"))
        .expect("official blocks report unavailable");
    let r = std::fs::read(base.join("extracted-reports/reports/registries.json"))
        .expect("official registries report unavailable");
    let source = std::fs::read(base.join("registry-source-receipt.json"))
        .expect("producer receipt unavailable");
    let registry = Registry::load(&b, &r, &source).unwrap();
    assert_eq!(
        (
            registry.block_count(),
            registry.state_count(),
            registry.registry_count()
        ),
        (1003, 24135, 66)
    );
    assert!(registry.membership(&state("minecraft:stone", &[])).is_ok());
    assert!(registry
        .membership(&state("minecraft:oak_log", &[("axis", "y")]))
        .is_ok());
    assert!(registry
        .membership(&state(
            "minecraft:oak_stairs",
            &[
                ("facing", "east"),
                ("half", "bottom"),
                ("shape", "straight"),
                ("waterlogged", "false")
            ]
        ))
        .is_ok());
    assert!(registry
        .membership(&state("minecraft:oak_log", &[]))
        .is_err());
    assert!(registry
        .membership(&state("minecraft:oak_log", &[("axis", "q")]))
        .is_err());
    let original = chunk_fixture(false, true);
    let replacement = crate::edit::BlockReplacement {
        x: 0,
        y: 0,
        z: 0,
        state: state("minecraft:stone", &[]),
    };
    let edited =
        crate::edit::replace_section_blocks(&original, &registry, -4, &[replacement]).unwrap();
    assert!(edited.relighting_required && edited.derived_data_stale);
    let summary = crate::chunk::summarize(&edited.root).unwrap();
    let crate::chunk::Blocks::Palette { states, indices } = &summary.sections[0].blocks else {
        panic!()
    };
    assert_eq!(states[indices[0] as usize].name, "minecraft:stone");
    assert!(
        crate::edit::replace_section_blocks(&chunk_fixture(true, false), &registry, -4, &[])
            .is_err()
    );
}

fn chunk_fixture(unknown_used: bool, other_unknown: bool) -> crate::nbt::NamedTag {
    use crate::nbt::{NamedTag, Tag};
    fn n(name: &str, tag: Tag) -> NamedTag {
        NamedTag {
            name: name.as_bytes().to_vec(),
            tag,
        }
    }
    let palette = vec![
        Tag::Compound(vec![n("Name", Tag::String(b"minecraft:air".to_vec()))]),
        Tag::Compound(vec![
            n("Name", Tag::String(b"fixture:unknown".to_vec())),
            n("retained", Tag::Int(7)),
        ]),
    ];
    let mut words = vec![0; 256];
    if unknown_used {
        words[0] = 1;
    }
    let mut sections = vec![Tag::Compound(vec![
        n("Y", Tag::Byte(-4)),
        n(
            "block_states",
            Tag::Compound(vec![
                n("palette", Tag::List(10, palette.clone())),
                n("data", Tag::LongArray(words)),
            ]),
        ),
    ])];
    if other_unknown {
        sections.push(Tag::Compound(vec![
            n("Y", Tag::Byte(-3)),
            n(
                "block_states",
                Tag::Compound(vec![n("palette", Tag::List(10, vec![palette[1].clone()]))]),
            ),
        ]));
    }
    NamedTag {
        name: vec![],
        tag: Tag::Compound(vec![
            n("DataVersion", Tag::Int(3465)),
            n("xPos", Tag::Int(0)),
            n("zPos", Tag::Int(0)),
            n("sections", Tag::List(10, sections)),
        ]),
    }
}
#[test]
fn edits_require_replacement_and_selected_used_state_membership() {
    use crate::edit::{replace_section_blocks, BlockReplacement};
    let (b, r) = fixture();
    let registry = Registry::validate(&b, &r).unwrap();
    let original = chunk_fixture(false, true);
    let replacement = BlockReplacement {
        x: 0,
        y: 0,
        z: 0,
        state: state(
            "fixture:panel",
            &[("facing", "north"), ("powered", "false")],
        ),
    };
    let result = replace_section_blocks(&original, &registry, -4, &[replacement.clone()]).unwrap();
    assert!(result.relighting_required && result.derived_data_stale);
    assert_eq!(result.changed_blocks, 1);
    let before = crate::nbt::write(&original, crate::nbt::Limits::default()).unwrap();
    let invalid = BlockReplacement {
        x: 1,
        y: 0,
        z: 0,
        state: state("fixture:panel", &[]),
    };
    assert!(replace_section_blocks(&original, &registry, -4, &[replacement, invalid]).is_err());
    assert_eq!(
        crate::nbt::write(&original, crate::nbt::Limits::default()).unwrap(),
        before
    );
    assert!(replace_section_blocks(&chunk_fixture(true, false), &registry, -4, &[]).is_err());
    let summary = crate::chunk::summarize(&result.root).unwrap();
    let crate::chunk::Blocks::Palette { states, .. } = &summary.sections[0].blocks else {
        panic!()
    };
    assert_eq!(states[1].name, "fixture:unknown");
    assert_eq!(summary.sections[1].y, -3);
}
#[test]
fn unrelated_sparse_registry_ids_are_valid_but_block_ids_are_not_sparse() {
    let (b, mut r) = fixture();
    r["fixture:other"] = json!({"protocol_id":1,"entries":{"fixture:sparse":{"protocol_id":4}}});
    assert!(Registry::validate(&b, &r).is_ok());
    r["minecraft:block"]["entries"]["fixture:panel"]["protocol_id"] = json!(4);
    assert!(Registry::validate(&b, &r).is_err());
}

#[test]
fn numeric_types_missing_defaults_and_receipt_hashes_fail_closed() {
    let (b, r) = fixture();
    for id in [json!(1.0), json!(-1), json!(4294967296u64)] {
        let mut v = b.clone();
        v["fixture:panel"]["states"][0]["id"] = id;
        assert!(Registry::validate(&v, &r).is_err());
    }
    let mut v = b.clone();
    v["fixture:panel"]["states"][0]
        .as_object_mut()
        .unwrap()
        .remove("default");
    assert!(Registry::validate(&v, &r).is_err());
    let mut v = receipt_value();
    v["reports"]["blocks"]["sha256"] = json!("0".repeat(64));
    assert!(receipt(&serde_json::to_vec(&v).unwrap()).is_err());
    let mut v = receipt_value();
    v["generator"]["logSha256"] = json!("0".repeat(64));
    assert!(receipt(&serde_json::to_vec(&v).unwrap()).is_err());
}
