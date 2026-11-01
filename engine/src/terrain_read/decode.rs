use super::{check, coverage, unavailable, Bounds, Counts, Section, DECOMP, FIXED, MIB, TEMP};
use crate::{
    chunk::{self, Blocks},
    nbt::{self, Limits, NamedTag, Tag},
    region,
};
use serde_json::Value;
use std::{collections::BTreeMap, time::Instant};
pub(super) fn fields(tag: &Tag) -> Result<&[NamedTag], &'static str> {
    if let Tag::Compound(v) = tag {
        Ok(v)
    } else {
        Err("compound_required")
    }
}
pub(super) fn optional<'a>(v: &'a [NamedTag], key: &[u8]) -> Result<Option<&'a Tag>, &'static str> {
    let mut found = v.iter().filter(|n| n.name == key);
    let result = found.next().map(|n| &n.tag);
    if found.next().is_some() {
        return Err("duplicate_field");
    }
    Ok(result)
}
pub(super) fn integer(v: Option<&Tag>) -> Result<i32, &'static str> {
    if let Some(Tag::Int(n)) = v {
        Ok(*n)
    } else {
        Err("integer_required")
    }
}
fn semantic_bound(section: &Tag) -> Result<usize, &'static str> {
    let f = fields(section)?;
    let bs = optional(f, b"block_states")?.ok_or("section_blocks_missing")?;
    let bs = fields(bs)?;
    let Some(Tag::List(10, palette)) = optional(bs, b"palette")? else {
        return Err("invalid_palette");
    };
    if palette.is_empty() || palette.len() > 4096 {
        return Err("invalid_palette");
    }
    let mut bound = 32768usize;
    for state in palette {
        let f = fields(state)?;
        let Some(Tag::String(name)) = optional(f, b"Name")? else {
            return Err("invalid_block_name");
        };
        bound = bound
            .checked_add(256 + name.len().checked_mul(8).ok_or("semantic_budget")?)
            .ok_or("semantic_budget")?;
        if let Some(properties) = optional(f, b"Properties")? {
            let properties = fields(properties)?;
            if properties.len() > 64 {
                return Err("property_budget");
            }
            for p in properties {
                let Tag::String(value) = &p.tag else {
                    return Err("invalid_property");
                };
                bound = bound
                    .checked_add(
                        256 + p
                            .name
                            .len()
                            .checked_add(value.len())
                            .and_then(|n| n.checked_mul(8))
                            .ok_or("semantic_budget")?,
                    )
                    .ok_or("semantic_budget")?;
            }
        }
    }
    Ok(bound)
}
pub(super) fn chunk(
    extent: &[u8],
    extent_capacity: usize,
    x: i32,
    z: i32,
    bounds: Bounds,
    deadline: Instant,
    entries: &mut Vec<Value>,
    section: &mut impl FnMut(Section) -> Result<Counts, &'static str>,
    peak: &mut usize,
) -> Result<(), &'static str> {
    let length = u32::from_be_bytes(extent[..4].try_into().unwrap()) as usize;
    if length < 1 || length > extent.len() - 4 {
        unavailable(
            entries,
            x,
            z,
            bounds,
            "corrupt",
            None,
            "invalid_chunk_length",
        );
        return Ok(());
    }
    let kind = extent[4];
    if kind & 128 != 0 || !matches!(kind, 1..=3) {
        unavailable(
            entries,
            x,
            z,
            bounds,
            "unsupported-encoding",
            None,
            "compression_unsupported",
        );
        return Ok(());
    }
    let decompressed = match region::decompress_reserved(kind, &extent[5..4 + length], DECOMP) {
        Ok(v) => v,
        Err(message) => {
            unavailable(
                entries,
                x,
                z,
                bounds,
                if message.contains("budget") {
                    "budget-exceeded"
                } else {
                    "corrupt"
                },
                None,
                if message.contains("budget") {
                    "decompression_budget"
                } else {
                    "invalid_compression"
                },
            );
            return Ok(());
        }
    };
    let base = FIXED + extent_capacity + decompressed.capacity();
    if base >= TEMP {
        return Err("terrain_budget_exceeded");
    }
    let parsed = match nbt::parse_charged(
        &decompressed,
        Limits {
            bytes: DECOMP,
            ..Limits::default()
        },
        Some((TEMP - base).min(64 * MIB)),
    ) {
        Ok(v) => v,
        Err(message) => {
            unavailable(
                entries,
                x,
                z,
                bounds,
                if message.contains("budget") {
                    "budget-exceeded"
                } else {
                    "corrupt"
                },
                None,
                if message.contains("budget") {
                    "nbt_budget"
                } else {
                    "invalid_nbt"
                },
            );
            return Ok(());
        }
    };
    *peak = (*peak).max(base + parsed.peak_allocated_bytes);
    let top = match fields(&parsed.root.tag) {
        Ok(v) => v,
        Err(_) => {
            unavailable(entries, x, z, bounds, "corrupt", None, "invalid_chunk_root");
            return Ok(());
        }
    };
    let version = optional(top, b"DataVersion")
        .ok()
        .and_then(|v| integer(v).ok());
    if version != Some(3465) {
        unavailable(
            entries,
            x,
            z,
            bounds,
            "unsupported-data-version",
            version,
            "unsupported_data_version",
        );
        return Ok(());
    }
    if integer(optional(top, b"xPos").ok().flatten()).ok() != Some(x)
        || integer(optional(top, b"zPos").ok().flatten()).ok() != Some(z)
    {
        unavailable(
            entries,
            x,
            z,
            bounds,
            "corrupt",
            version,
            "chunk_coordinate_mismatch",
        );
        return Ok(());
    }
    let sections = match optional(top, b"sections") {
        Ok(Some(Tag::List(10, v))) => v,
        Ok(None) => {
            unavailable(
                entries,
                x,
                z,
                bounds,
                "no-decoded-section",
                version,
                "no_decoded_section",
            );
            return Ok(());
        }
        Ok(Some(Tag::List(0, v))) if v.is_empty() => {
            unavailable(
                entries,
                x,
                z,
                bounds,
                "no-decoded-section",
                version,
                "no_decoded_section",
            );
            return Ok(());
        }
        _ => {
            unavailable(
                entries,
                x,
                z,
                bounds,
                "corrupt",
                version,
                "invalid_sections",
            );
            return Ok(());
        }
    };
    let mut positions = BTreeMap::new();
    let mut invalid = false;
    for s in sections {
        let y = fields(s)
            .ok()
            .and_then(|f| optional(f, b"Y").ok().flatten());
        if let Some(Tag::Byte(y)) = y {
            if positions.insert(*y as i32, s).is_some() {
                invalid = true;
                break;
            }
        } else {
            invalid = true;
            break;
        }
    }
    if invalid {
        unavailable(
            entries,
            x,
            z,
            bounds,
            "corrupt",
            version,
            "invalid_section_identity",
        );
        return Ok(());
    }
    for y in bounds.ymin..=bounds.ymax {
        check(deadline)?;
        let Some(raw_section) = positions.get(&y) else {
            entries.push(coverage(
                x,
                z,
                y,
                "no-decoded-section",
                version,
                "no_decoded_section",
                None,
            ));
            continue;
        };
        let bound = match semantic_bound(raw_section) {
            Ok(v) => v,
            Err("section_blocks_missing") => {
                entries.push(coverage(
                    x,
                    z,
                    y,
                    "no-decoded-section",
                    version,
                    "no_decoded_section",
                    None,
                ));
                continue;
            }
            Err(_) => {
                entries.push(coverage(
                    x,
                    z,
                    y,
                    "unsupported-encoding",
                    version,
                    "section_encoding_unsupported",
                    None,
                ));
                continue;
            }
        };
        if base
            .checked_add(parsed.allocated_bytes)
            .and_then(|n| n.checked_add(bound))
            .is_none_or(|n| n > TEMP)
        {
            entries.push(coverage(
                x,
                z,
                y,
                "budget-exceeded",
                version,
                "semantic_budget",
                None,
            ));
            continue;
        }
        *peak = (*peak).max(base + parsed.allocated_bytes + bound);
        let view = match chunk::nested_palette_view(raw_section) {
            Ok(Blocks::Palette { states, indices }) => (states, indices),
            _ => {
                entries.push(coverage(
                    x,
                    z,
                    y,
                    "unsupported-encoding",
                    version,
                    "section_encoding_unsupported",
                    None,
                ));
                continue;
            }
        };
        let counts = section(Section {
            x,
            z,
            y,
            palette: view.0,
            indices: view.1,
        })?;
        if counts.cube as u64 + counts.unsupported as u64 != 4096 {
            return Err("invalid_classification_counts");
        }
        entries.push(coverage(x, z, y, "present", version, "", Some(counts)));
    }
    Ok(())
}
