//! In-memory selected-section edits for one explicitly admitted DataVersion.
//! Lighting, heightmaps and other derived data are preserved, not recalculated.
use crate::{
    chunk::{self, BlockState, Blocks, Section},
    nbt::{NamedTag, Result, Tag},
};
use std::collections::{HashMap, HashSet};
#[derive(Clone)]
pub struct BlockReplacement {
    pub x: u8,
    pub y: u8,
    pub z: u8,
    pub state: BlockState,
}
pub struct EditResult {
    pub root: NamedTag,
    pub changed_blocks: usize,
    pub relighting_required: bool,
    pub derived_data_stale: bool,
}
fn compound(t: &Tag) -> Result<&[NamedTag]> {
    if let Tag::Compound(v) = t {
        Ok(v)
    } else {
        Err("expected compound")
    }
}
fn field<'a>(fields: &'a [NamedTag], name: &[u8]) -> Result<&'a Tag> {
    let mut found = fields.iter().filter(|n| n.name == name);
    let value = &found.next().ok_or("missing edit field")?.tag;
    if found.next().is_some() {
        return Err("duplicate edit field");
    }
    Ok(value)
}
fn field_mut<'a>(fields: &'a mut [NamedTag], name: &[u8]) -> Result<&'a mut Tag> {
    let mut found = fields.iter_mut().filter(|n| n.name == name);
    let value = &mut found.next().ok_or("missing edit field")?.tag;
    if found.next().is_some() {
        return Err("duplicate edit field");
    }
    Ok(value)
}
fn key(state: &BlockState) -> (String, Vec<(String, String)>) {
    let mut props = state.properties.clone();
    props.sort();
    (state.name.clone(), props)
}
fn validate(state: &BlockState) -> Result<()> {
    let Some((namespace, path)) = state.name.split_once(':') else {
        return Err("invalid replacement block name");
    };
    let allowed = |s: &str| {
        !s.is_empty()
            && s.len() <= 256
            && s.bytes()
                .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b"_-./".contains(&b))
    };
    if !allowed(namespace) || namespace.contains('/') || !allowed(path) {
        return Err("invalid replacement block name");
    }
    if state.properties.len() > chunk::MAX_STATE_PROPERTIES {
        return Err("block property budget exceeded");
    }
    let mut seen = HashSet::new();
    for (k, v) in &state.properties {
        if !allowed(k) || k.contains('/') || !allowed(v) || v.contains('/') || !seen.insert(k) {
            return Err("invalid replacement block property");
        }
    }
    Ok(())
}
fn state_tag(state: &BlockState) -> Tag {
    let mut fields = vec![NamedTag {
        name: b"Name".to_vec(),
        tag: Tag::String(crate::mutf8::encode_units(
            &state.name.encode_utf16().collect::<Vec<_>>(),
        )),
    }];
    if !state.properties.is_empty() {
        fields.push(NamedTag {
            name: b"Properties".to_vec(),
            tag: Tag::Compound(
                state
                    .properties
                    .iter()
                    .map(|(k, v)| NamedTag {
                        name: crate::mutf8::encode_units(&k.encode_utf16().collect::<Vec<_>>()),
                        tag: Tag::String(crate::mutf8::encode_units(
                            &v.encode_utf16().collect::<Vec<_>>(),
                        )),
                    })
                    .collect(),
            ),
        });
    }
    Tag::Compound(fields)
}
pub fn pack_padded(indices: &[u16], palette_len: usize) -> Result<Vec<i64>> {
    if indices.len() != 4096 || palette_len == 0 || palette_len > 4096 {
        return Err("invalid palette packing input");
    }
    let bits = (usize::BITS - (palette_len - 1).leading_zeros()).max(4) as usize;
    let per = 64 / bits;
    let mut words = vec![0u64; 4096usize.div_ceil(per)];
    for (i, &value) in indices.iter().enumerate() {
        if value as usize >= palette_len {
            return Err("palette index out of range");
        }
        words[i / per] |= (value as u64) << ((i % per) * bits);
    }
    Ok(words.into_iter().map(|n| n as i64).collect())
}
pub fn replace_section_blocks(
    root: &NamedTag,
    registry: &crate::registry::Registry,
    section_y: i8,
    replacements: &[BlockReplacement],
) -> Result<EditResult> {
    let fields = compound(&root.tag)?;
    if !matches!(field(fields, b"DataVersion")?, Tag::Int(3465)) {
        return Err("editing supports only DataVersion 3465");
    }
    if replacements.len() > 4096 {
        return Err("replacement budget exceeded");
    }
    let summary = chunk::summarize(root)?;
    let section = summary
        .sections
        .iter()
        .find(|s| s.y == section_y as i32)
        .ok_or("selected section unavailable")?;
    let Blocks::Palette { states, indices } = &section.blocks else {
        return Err("selected section must use palette states");
    };
    if registry.data_version() != 3465 {
        return Err("registry version mismatch");
    }
    let mut checked = HashSet::new();
    for replacement in replacements {
        let index = Section::index(replacement.x, replacement.y, replacement.z)?;
        if !checked.insert(index) {
            return Err("duplicate selected block");
        }
        validate(&replacement.state)?;
        registry.membership(&replacement.state)?;
    }
    let used: HashSet<u16> = indices.iter().copied().collect();
    for index in used {
        registry.membership(&states[index as usize])?;
    }
    let mut states = states.clone();
    let mut indices = indices.clone();
    let mut lookup: HashMap<_, u16> = HashMap::new();
    for (i, state) in states.iter().enumerate() {
        lookup.entry(key(state)).or_insert(i as u16);
    }
    let original_len = states.len();
    let mut selected = HashSet::new();
    let mut changed = 0;
    for replacement in replacements {
        let index = Section::index(replacement.x, replacement.y, replacement.z)?;
        if !selected.insert(index) {
            return Err("duplicate selected block");
        }
        validate(&replacement.state)?;
        let k = key(&replacement.state);
        if key(&states[indices[index] as usize]) == k {
            continue;
        }
        let palette_index = if let Some(&i) = lookup.get(&k) {
            i
        } else {
            if states.len() == 4096 {
                return Err("palette capacity exceeded");
            }
            let i = states.len() as u16;
            states.push(replacement.state.clone());
            lookup.insert(k, i);
            i
        };
        indices[index] = palette_index;
        changed += 1;
    }
    let mut output = root.clone();
    if changed == 0 {
        return Ok(EditResult {
            root: output,
            changed_blocks: 0,
            relighting_required: false,
            derived_data_stale: false,
        });
    }
    let Tag::Compound(top) = &mut output.tag else {
        unreachable!()
    };
    let Tag::List(10, sections) = field_mut(top, b"sections")? else {
        return Err("invalid sections");
    };
    let mut target = None;
    for s in sections {
        let Tag::Compound(fields) = s else {
            return Err("invalid section");
        };
        if matches!(field(fields,b"Y")?,Tag::Byte(y) if *y==section_y) {
            target = Some(fields);
            break;
        }
    }
    let fields = target.ok_or("selected section unavailable")?;
    let Tag::Compound(block_states) = field_mut(fields, b"block_states")? else {
        return Err("invalid block states");
    };
    let Tag::List(10, palette) = field_mut(block_states, b"palette")? else {
        return Err("invalid palette");
    };
    for state in &states[original_len..] {
        palette.push(state_tag(state));
    }
    let packed = Tag::LongArray(pack_padded(&indices, states.len())?);
    if let Some(data) = block_states.iter_mut().find(|n| n.name == b"data") {
        data.tag = packed;
    } else {
        block_states.push(NamedTag {
            name: b"data".to_vec(),
            tag: packed,
        });
    }
    chunk::summarize(&output)?;
    Ok(EditResult {
        root: output,
        changed_blocks: changed,
        relighting_required: true,
        derived_data_stale: true,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{
        nbt::{self, Limits},
        region::{Region, RegionEdit},
    };
    fn replace_section_blocks(
        root: &NamedTag,
        y: i8,
        replacements: &[BlockReplacement],
    ) -> Result<EditResult> {
        let mut names = (0..1000)
            .map(|i| format!("minecraft:block_{i}"))
            .collect::<Vec<_>>();
        names.extend([
            "minecraft:granite".into(),
            "minecraft:stone".into(),
            "minecraft:new_state".into(),
        ]);
        let registry = crate::registry::Registry::test_propertyless(&names);
        super::replace_section_blocks(root, &registry, y, replacements)
    }
    fn named(name: &str, tag: Tag) -> NamedTag {
        NamedTag {
            name: name.as_bytes().to_vec(),
            tag,
        }
    }
    fn state(name: &str) -> BlockState {
        BlockState {
            name: format!("minecraft:{name}"),
            properties: vec![],
        }
    }
    fn fixture(palette_len: usize) -> NamedTag {
        let palette = (0..palette_len)
            .map(|n| {
                let mut tag = state_tag(&state(&format!("block_{}", n % 1000)));
                let Tag::Compound(v) = &mut tag else {
                    unreachable!()
                };
                v.push(named("unrecognized_palette_field", Tag::Long(n as i64)));
                tag
            })
            .collect();
        let mut block_states = vec![
            named("palette", Tag::List(10, palette)),
            named("unrecognized_states_field", Tag::ByteArray(vec![1, 2, 3])),
        ];
        if palette_len > 1 {
            block_states.push(named(
                "data",
                Tag::LongArray(pack_padded(&vec![0; 4096], palette_len).unwrap()),
            ));
        }
        NamedTag {
            name: b"chunk".to_vec(),
            tag: Tag::Compound(vec![
                named("DataVersion", Tag::Int(3465)),
                named("xPos", Tag::Int(-1)),
                named("zPos", Tag::Int(-1)),
                named(
                    "entities",
                    Tag::List(
                        10,
                        vec![Tag::Compound(vec![named(
                            "unknown_entity",
                            Tag::String(vec![0xc0, 0x80]),
                        )])],
                    ),
                ),
                named("unknown_root", Tag::IntArray(vec![7, 8, 9])),
                named(
                    "sections",
                    Tag::List(
                        10,
                        vec![Tag::Compound(vec![
                            named("Y", Tag::Byte(-4)),
                            named("BlockLight", Tag::ByteArray(vec![13; 2048])),
                            named("SkyLight", Tag::ByteArray(vec![15; 2048])),
                            named(
                                "biomes",
                                Tag::Compound(vec![named(
                                    "palette",
                                    Tag::List(8, vec![Tag::String(b"minecraft:plains".to_vec())]),
                                )]),
                            ),
                            named("unknown_section", Tag::Double(0x7ff8000000000001)),
                            named("block_states", Tag::Compound(block_states)),
                        ])],
                    ),
                ),
            ]),
        }
    }
    fn replacement(x: u8, y: u8, z: u8, name: &str) -> BlockReplacement {
        BlockReplacement {
            x,
            y,
            z,
            state: state(name),
        }
    }
    fn selected(root: &NamedTag) -> &[NamedTag] {
        let top = compound(&root.tag).unwrap();
        let Tag::List(10, sections) = field(top, b"sections").unwrap() else {
            panic!()
        };
        compound(&sections[0]).unwrap()
    }
    #[test]
    fn singleton_growth_preserves_unknown_data_and_reports_relighting() {
        let original = fixture(1);
        let original_bytes = nbt::write(&original, Limits::default()).unwrap();
        let edited =
            replace_section_blocks(&original, -4, &[replacement(15, 15, 15, "granite")]).unwrap();
        assert_eq!(edited.changed_blocks, 1);
        assert!(edited.relighting_required && edited.derived_data_stale);
        let summary = chunk::summarize(&edited.root).unwrap();
        let Blocks::Palette { states, indices } = &summary.sections[0].blocks else {
            panic!()
        };
        assert_eq!(states.len(), 2);
        assert_eq!(states[indices[4095] as usize].name, "minecraft:granite");
        assert_eq!(indices[0], 0);
        assert_eq!(summary.sections[0].world_y(15).unwrap(), -49);
        let before = compound(&original.tag).unwrap();
        let after = compound(&edited.root.tag).unwrap();
        for key in [b"entities".as_slice(), b"unknown_root", b"xPos", b"zPos"] {
            assert_eq!(field(before, key).unwrap(), field(after, key).unwrap());
        }
        for key in [
            b"BlockLight".as_slice(),
            b"SkyLight",
            b"biomes",
            b"unknown_section",
        ] {
            assert_eq!(
                field(selected(&original), key).unwrap(),
                field(selected(&edited.root), key).unwrap()
            );
        }
        let bs_before = compound(field(selected(&original), b"block_states").unwrap()).unwrap();
        let bs_after = compound(field(selected(&edited.root), b"block_states").unwrap()).unwrap();
        assert_eq!(
            field(bs_before, b"unrecognized_states_field").unwrap(),
            field(bs_after, b"unrecognized_states_field").unwrap()
        );
        let Tag::List(10, p_before) = field(bs_before, b"palette").unwrap() else {
            panic!()
        };
        let Tag::List(10, p_after) = field(bs_after, b"palette").unwrap() else {
            panic!()
        };
        assert_eq!(p_before[0], p_after[0]);
        assert_eq!(
            nbt::write(&original, Limits::default()).unwrap(),
            original_bytes
        );
        let empty = vec![0; 8192];
        let rebuilt = Region::parse(&empty)
            .unwrap()
            .rebuild(
                &[RegionEdit {
                    index: 1023,
                    root: edited.root.clone(),
                    timestamp: 91,
                }],
                Limits::default(),
            )
            .unwrap();
        let region = Region::parse(&rebuilt).unwrap();
        assert_eq!(
            region.chunk(1023, Limits::default()).unwrap(),
            Some(edited.root)
        );
    }
    #[test]
    fn no_op_is_byte_exact_and_does_not_claim_relighting() {
        let original = fixture(1);
        let edited =
            replace_section_blocks(&original, -4, &[replacement(0, 0, 0, "block_0")]).unwrap();
        assert_eq!(edited.changed_blocks, 0);
        assert!(!edited.relighting_required && !edited.derived_data_stale);
        assert_eq!(
            nbt::write(&original, Limits::default()).unwrap(),
            nbt::write(&edited.root, Limits::default()).unwrap()
        );
    }
    #[test]
    fn palette_growth_reencodes_five_bit_boundaries() {
        let original = fixture(16);
        let replacements = vec![
            replacement(12, 0, 0, "granite"),
            replacement(13, 0, 0, "granite"),
            replacement(15, 15, 15, "granite"),
        ];
        let edited = replace_section_blocks(&original, -4, &replacements).unwrap();
        let summary = chunk::summarize(&edited.root).unwrap();
        let Blocks::Palette { states, indices } = &summary.sections[0].blocks else {
            panic!()
        };
        assert_eq!(states.len(), 17);
        for i in [12, 13, 4095] {
            assert_eq!(indices[i], 16);
        }
        assert_eq!(indices[11], 0);
        assert_eq!(indices[14], 0);
        let words = pack_padded(indices, 17).unwrap();
        assert_eq!(words.len(), 342);
        assert_eq!(chunk::unpack(&words, 17, true).unwrap(), *indices);
    }
    #[test]
    fn unsupported_selection_and_malformed_palette_fail_without_mutation() {
        let original = fixture(1);
        for edits in [
            vec![replacement(16, 0, 0, "stone")],
            vec![
                replacement(0, 0, 0, "stone"),
                replacement(0, 0, 0, "granite"),
            ],
            vec![replacement(0, 0, 0, "BAD_NAME")],
        ] {
            assert!(replace_section_blocks(&original, -4, &edits).is_err());
        }
        assert!(replace_section_blocks(&original, -3, &[]).is_err());
        let mut unsupported = original.clone();
        let Tag::Compound(top) = &mut unsupported.tag else {
            panic!()
        };
        *field_mut(top, b"DataVersion").unwrap() = Tag::Int(2975);
        assert!(replace_section_blocks(&unsupported, -4, &[]).is_err());
        let mut malformed = fixture(2);
        let Tag::Compound(top) = &mut malformed.tag else {
            panic!()
        };
        let Tag::List(10, sections) = field_mut(top, b"sections").unwrap() else {
            panic!()
        };
        let Tag::Compound(fields) = &mut sections[0] else {
            panic!()
        };
        let Tag::Compound(bs) = field_mut(fields, b"block_states").unwrap() else {
            panic!()
        };
        *field_mut(bs, b"data").unwrap() = Tag::LongArray(vec![0]);
        assert!(replace_section_blocks(&malformed, -4, &[replacement(0, 0, 0, "stone")]).is_err());
        assert!(pack_padded(&vec![0; 4095], 1).is_err());
        assert!(pack_padded(&vec![2; 4096], 2).is_err());
    }
    #[test]
    fn palette_capacity_is_explicit() {
        let original = fixture(4096);
        assert!(
            replace_section_blocks(&original, -4, &[replacement(0, 0, 0, "new_state")]).is_err()
        );
        assert_eq!(
            replace_section_blocks(&original, -4, &[replacement(0, 0, 0, "block_999")])
                .unwrap()
                .changed_blocks,
            1
        );
    }
}
