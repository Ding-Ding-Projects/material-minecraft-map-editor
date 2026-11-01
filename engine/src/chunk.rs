//! Read-only, explicitly version-selected Java block section views.
use crate::nbt::{NamedTag, Result, Tag};
use std::collections::HashSet;
pub const MAX_STATE_PROPERTIES: usize = 64;
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Format {
    Numeric,
    Continuous,
    Padded,
    NestedPadded,
}
impl Format {
    pub fn for_data_version(v: i32) -> Result<Self> {
        match v {
            1343 => Ok(Self::Numeric),
            1631 | 1976 | 2230 => Ok(Self::Continuous),
            2586 | 2730 => Ok(Self::Padded),
            2975 | 3337 | 3465 => Ok(Self::NestedPadded),
            _ => Err("unverified DataVersion"),
        }
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct BlockState {
    pub name: String,
    pub properties: Vec<(String, String)>,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Blocks {
    Numeric(Vec<(u16, u8)>),
    Palette {
        states: Vec<BlockState>,
        indices: Vec<u16>,
    },
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Section {
    pub y: i32,
    pub blocks: Blocks,
}
impl Section {
    pub fn world_y(&self, local_y: u8) -> Result<i32> {
        if local_y > 15 {
            return Err("local coordinate out of range");
        }
        self.y
            .checked_mul(16)
            .and_then(|n| n.checked_add(local_y as i32))
            .ok_or("world height overflow")
    }
    pub fn index(x: u8, y: u8, z: u8) -> Result<usize> {
        if x > 15 || y > 15 || z > 15 {
            return Err("local coordinate out of range");
        }
        Ok(y as usize * 256 + z as usize * 16 + x as usize)
    }
}
pub struct ChunkSummary<'a> {
    pub raw: &'a NamedTag,
    pub data_version: i32,
    pub x: i32,
    pub z: i32,
    pub sections: Vec<Section>,
}
fn fields(t: &Tag) -> Result<&[NamedTag]> {
    if let Tag::Compound(v) = t {
        Ok(v)
    } else {
        Err("expected compound")
    }
}
fn optional<'a>(v: &'a [NamedTag], key: &[u8]) -> Result<Option<&'a Tag>> {
    let mut matches = v.iter().filter(|n| n.name == key);
    let result = matches.next().map(|n| &n.tag);
    if matches.next().is_some() {
        return Err("duplicate semantic field");
    }
    Ok(result)
}
fn get<'a>(v: &'a [NamedTag], key: &[u8]) -> Result<&'a Tag> {
    optional(v, key)?.ok_or("missing semantic field")
}
fn int(t: &Tag) -> Result<i32> {
    if let Tag::Int(n) = t {
        Ok(*n)
    } else {
        Err("expected integer")
    }
}
fn bytes(t: &Tag, n: usize) -> Result<&[u8]> {
    if let Tag::ByteArray(v) = t {
        if v.len() == n {
            return Ok(v);
        }
    }
    Err("invalid numeric array length")
}
fn compounds(t: &Tag) -> Result<&[Tag]> {
    if let Tag::List(10, v) = t {
        if v.iter().all(|n| matches!(n, Tag::Compound(_))) {
            return Ok(v);
        }
    }
    Err("expected compound list")
}
fn text(t: &Tag) -> Result<String> {
    if let Tag::String(v) = t {
        crate::mutf8::decode(v)
    } else {
        Err("expected string")
    }
}
fn nibble(v: &[u8], i: usize) -> u8 {
    (v[i / 2] >> ((i % 2) * 4)) & 15
}
pub fn unpack(words: &[i64], palette_len: usize, padded: bool) -> Result<Vec<u16>> {
    if palette_len == 0 || palette_len > 4096 {
        return Err("invalid palette length");
    }
    let bits = (usize::BITS - (palette_len - 1).leading_zeros()).max(4) as usize;
    let per = 64 / bits;
    let expected = if padded {
        4096usize.div_ceil(per)
    } else {
        (4096 * bits).div_ceil(64)
    };
    if words.len() != expected {
        return Err("invalid packed array length");
    }
    let mask = (1u64 << bits) - 1;
    let mut result = Vec::with_capacity(4096);
    for i in 0..4096 {
        let (word, shift) = if padded {
            (i / per, (i % per) * bits)
        } else {
            (i * bits / 64, i * bits % 64)
        };
        let mut value = (words[word] as u64) >> shift;
        if !padded && shift + bits > 64 {
            value |= (words[word + 1] as u64) << (64 - shift);
        }
        let value = (value & mask) as usize;
        if value >= palette_len {
            return Err("palette index out of range");
        }
        result.push(value as u16);
    }
    Ok(result)
}
fn palette_section(v: &[NamedTag], format: Format) -> Result<Blocks> {
    let nested = format == Format::NestedPadded;
    let v = if nested {
        fields(get(v, b"block_states")?)?
    } else {
        v
    };
    let entries = compounds(get(v, if nested { b"palette" } else { b"Palette" })?)?;
    if entries.is_empty() || entries.len() > 4096 {
        return Err("invalid palette length");
    }
    let mut states = Vec::new();
    for entry in entries {
        let f = fields(entry)?;
        let name = text(get(f, b"Name")?)?;
        if name.is_empty() {
            return Err("empty block name");
        }
        let mut properties = Vec::new();
        if let Some(p) = optional(f, b"Properties")? {
            let source = fields(p)?;
            if source.len() > MAX_STATE_PROPERTIES {
                return Err("block property budget exceeded");
            }
            let mut seen = HashSet::with_capacity(source.len());
            for n in source {
                let key = crate::mutf8::decode(&n.name)?;
                if !seen.insert(key.clone()) {
                    return Err("duplicate block property");
                }
                properties.push((key, text(&n.tag)?));
            }
        }
        states.push(BlockState { name, properties });
    }
    let data = optional(v, if nested { b"data" } else { b"BlockStates" })?;
    let indices = match data {
        None if nested && states.len() == 1 => vec![0; 4096],
        Some(Tag::LongArray(words)) => unpack(words, states.len(), format != Format::Continuous)?,
        _ => return Err("missing or invalid packed states"),
    };
    Ok(Blocks::Palette { states, indices })
}
pub fn summarize(root: &NamedTag) -> Result<ChunkSummary<'_>> {
    let top = fields(&root.tag)?;
    let data_version = int(get(top, b"DataVersion")?)?;
    let format = Format::for_data_version(data_version)?;
    let body = if format == Format::NestedPadded {
        top
    } else {
        fields(get(top, b"Level")?)?
    };
    let x = int(get(body, b"xPos")?)?;
    let z = int(get(body, b"zPos")?)?;
    let section_key: &[u8] = if format == Format::NestedPadded {
        b"sections"
    } else {
        b"Sections"
    };
    let mut sections = Vec::new();
    for section in compounds(get(body, section_key)?)? {
        let v = fields(section)?;
        let y = match get(v, b"Y")? {
            Tag::Byte(n) => *n as i32,
            _ => return Err("expected byte section height"),
        };
        if sections.iter().any(|s: &Section| s.y == y) {
            return Err("duplicate section height");
        }
        let blocks = if format == Format::Numeric {
            let blocks = bytes(get(v, b"Blocks")?, 4096)?;
            let metadata = bytes(get(v, b"Data")?, 2048)?;
            let add = optional(v, b"Add")?.map(|t| bytes(t, 2048)).transpose()?;
            let mut values = Vec::with_capacity(4096);
            for i in 0..4096 {
                values.push((
                    blocks[i] as u16 | ((add.map_or(0, |a| nibble(a, i)) as u16) << 8),
                    nibble(metadata, i),
                ));
            }
            Blocks::Numeric(values)
        } else {
            palette_section(v, format)?
        };
        sections.push(Section { y, blocks });
    }
    sections.sort_by_key(|s| s.y);
    Ok(ChunkSummary {
        raw: root,
        data_version,
        x,
        z,
        sections,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    fn named(name: &str, tag: Tag) -> NamedTag {
        NamedTag {
            name: name.as_bytes().to_vec(),
            tag,
        }
    }
    fn fixture(version: i32, y: i8, extra: Vec<NamedTag>) -> NamedTag {
        let mut section = vec![named("Y", Tag::Byte(y))];
        section.extend(extra);
        let modern = version == 2975;
        let body = vec![
            named("xPos", Tag::Int(-2)),
            named("zPos", Tag::Int(3)),
            named(
                if modern { "sections" } else { "Sections" },
                Tag::List(10, vec![Tag::Compound(section)]),
            ),
        ];
        let mut root = vec![named("DataVersion", Tag::Int(version))];
        if modern {
            root.extend(body)
        } else {
            root.push(named("Level", Tag::Compound(body)))
        }
        NamedTag {
            name: vec![],
            tag: Tag::Compound(root),
        }
    }
    fn packed(len: usize, padded: bool, values: &[(usize, u16)]) -> Vec<i64> {
        let bits = (usize::BITS - (len - 1).leading_zeros()).max(4) as usize;
        let per = 64 / bits;
        let mut words = vec![
            0u64;
            if padded {
                4096usize.div_ceil(per)
            } else {
                (4096 * bits).div_ceil(64)
            }
        ];
        for &(i, v) in values {
            let (w, s) = if padded {
                (i / per, (i % per) * bits)
            } else {
                (i * bits / 64, i * bits % 64)
            };
            words[w] |= (v as u64) << s;
            if !padded && s + bits > 64 {
                words[w + 1] |= (v as u64) >> (64 - s);
            }
        }
        words.into_iter().map(|n| n as i64).collect()
    }
    #[test]
    fn five_bit_boundaries_and_malformed_arrays() {
        for padded in [false, true] {
            let values = [
                (0, 16),
                (11, 15),
                (12, 16),
                (13, 14),
                (63, 13),
                (64, 12),
                (4095, 16),
            ];
            let words = packed(17, padded, &values);
            let result = unpack(&words, 17, padded).unwrap();
            for &(i, n) in &values {
                assert_eq!(result[i], n);
            }
            assert!(unpack(&words[..words.len() - 1], 17, padded).is_err());
            let invalid = packed(17, padded, &[(12, 31)]);
            assert!(unpack(&invalid, 17, padded).is_err());
        }
        assert!(unpack(&[], 0, true).is_err());
    }
    #[test]
    fn numeric_nibbles_and_coordinates() {
        let mut blocks = vec![0; 4096];
        blocks[4095] = 0xab;
        let mut add = vec![0; 2048];
        add[2047] = 0xc0;
        let mut metadata = vec![0; 2048];
        metadata[2047] = 0xd0;
        let root = fixture(
            1343,
            15,
            vec![
                named("Blocks", Tag::ByteArray(blocks)),
                named("Data", Tag::ByteArray(metadata)),
                named("Add", Tag::ByteArray(add)),
            ],
        );
        let summary = summarize(&root).unwrap();
        assert!(std::ptr::eq(summary.raw, &root));
        assert_eq!((summary.x, summary.z), (-2, 3));
        let Blocks::Numeric(values) = &summary.sections[0].blocks else {
            panic!()
        };
        assert_eq!(values[4095], (0xcab, 13));
        assert_eq!(summary.sections[0].world_y(15).unwrap(), 255);
        assert_eq!(Section::index(15, 15, 15).unwrap(), 4095);
        assert_eq!(Section::index(0, 1, 0).unwrap(), 256);
        assert!(Section::index(16, 0, 0).is_err());
    }
    #[test]
    fn modern_singleton_and_negative_height() {
        let states = Tag::Compound(vec![named(
            "palette",
            Tag::List(
                10,
                vec![Tag::Compound(vec![named(
                    "Name",
                    Tag::String(b"minecraft:stone".to_vec()),
                )])],
            ),
        )]);
        let root = fixture(2975, -4, vec![named("block_states", states)]);
        let summary = summarize(&root).unwrap();
        assert_eq!(summary.sections[0].world_y(0).unwrap(), -64);
        let Blocks::Palette { states, indices } = &summary.sections[0].blocks else {
            panic!()
        };
        assert_eq!(states[0].name, "minecraft:stone");
        assert_eq!(indices.len(), 4096);
        assert!(indices.iter().all(|n| *n == 0));
    }
    #[test]
    fn flattened_dispatch_and_properties() {
        for (version, padded) in [(2230, false), (2586, true)] {
            let entries = (0..17)
                .map(|i| {
                    Tag::Compound(vec![
                        named(
                            "Name",
                            Tag::String(format!("minecraft:block_{i}").into_bytes()),
                        ),
                        named(
                            "Properties",
                            Tag::Compound(vec![named("axis", Tag::String(b"x".to_vec()))]),
                        ),
                    ])
                })
                .collect();
            let root = fixture(
                version,
                0,
                vec![
                    named("Palette", Tag::List(10, entries)),
                    named(
                        "BlockStates",
                        Tag::LongArray(packed(17, padded, &[(12, 16), (4095, 15)])),
                    ),
                ],
            );
            let summary = summarize(&root).unwrap();
            let Blocks::Palette { states, indices } = &summary.sections[0].blocks else {
                panic!()
            };
            assert_eq!(indices[12], 16);
            assert_eq!(indices[4095], 15);
            assert_eq!(states[16].properties[0], ("axis".into(), "x".into()));
        }
        assert!(Format::for_data_version(999999).is_err());
    }
    #[test]
    fn malformed_sections_and_duplicate_fields() {
        let root = fixture(
            1343,
            0,
            vec![
                named("Blocks", Tag::ByteArray(vec![0; 4095])),
                named("Data", Tag::ByteArray(vec![0; 2048])),
            ],
        );
        assert!(summarize(&root).is_err());
        let mut root = fixture(2975, 0, vec![]);
        assert!(summarize(&root).is_err());
        let Tag::Compound(v) = &mut root.tag else {
            panic!()
        };
        v.push(named("DataVersion", Tag::Int(2975)));
        assert!(summarize(&root).is_err());
    }
    fn property_fixture(count: usize, duplicate: bool) -> NamedTag {
        let mut properties: Vec<NamedTag> = (0..count)
            .map(|i| {
                named(
                    &format!("property_{i}"),
                    Tag::String(format!("value_{i}").into_bytes()),
                )
            })
            .collect();
        if duplicate && count > 1 {
            properties[count - 1].name = properties[0].name.clone();
        }
        fixture(
            2975,
            0,
            vec![named(
                "block_states",
                Tag::Compound(vec![named(
                    "palette",
                    Tag::List(
                        10,
                        vec![Tag::Compound(vec![
                            named("Name", Tag::String(b"minecraft:test".to_vec())),
                            named("Properties", Tag::Compound(properties)),
                        ])],
                    ),
                )]),
            )],
        )
    }
    #[test]
    fn property_budget_order_and_duplicate_detection() {
        let root = property_fixture(64, false);
        let view = summarize(&root).unwrap();
        let Blocks::Palette { states, .. } = &view.sections[0].blocks else {
            panic!()
        };
        assert_eq!(states[0].properties.len(), 64);
        for (i, (key, value)) in states[0].properties.iter().enumerate() {
            assert_eq!(key, &format!("property_{i}"));
            assert_eq!(value, &format!("value_{i}"));
        }
        assert!(summarize(&property_fixture(65, false)).is_err());
        assert!(summarize(&property_fixture(64, true)).is_err());
    }
}
