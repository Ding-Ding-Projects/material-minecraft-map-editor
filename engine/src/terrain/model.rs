use crate::{
    reference::{registry_identity, Reference, CAPABILITY, SHAPE_SHA256},
    terrain_codec,
    terrain_read::{self, Bounds, Counts, Section},
};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{collections::HashMap, path::Path, time::Instant};
pub(super) const PAGE_LIMIT: usize = 262144;
const MIB: usize = 1024 * 1024;
pub(super) struct Begin {
    pub path: std::path::PathBuf,
    pub world_id: String,
    pub dimension: String,
    pub generation: u64,
    pub bounds: Bounds,
}
pub(super) struct Page {
    pub kind: &'static str,
    pub count: u32,
    pub bytes: Vec<u8>,
    pub hash: String,
    pub encoded: usize,
}
struct State {
    bytes: Vec<u8>,
    cube: bool,
}
struct Cells {
    x: i32,
    z: i32,
    y: i32,
    ids: Vec<u16>,
}
pub(super) struct Snapshot {
    pub base: Value,
    pub manifest: Value,
    pub pages: Vec<Page>,
    pub totals: Value,
    pub cursor: usize,
    pub began: Instant,
    pub resident_bytes: usize,
    pub temporary_peak: usize,
    _states: Vec<State>,
    _cells: Vec<Cells>,
}
struct Memory {
    used: usize,
}
impl Memory {
    fn add(&mut self, bytes: usize) -> Result<(), &'static str> {
        self.used = self
            .used
            .checked_add(bytes)
            .filter(|n| *n <= 128 * MIB)
            .ok_or("terrain_budget_exceeded")?;
        Ok(())
    }
}
struct Builder {
    memory: Memory,
    states: Vec<State>,
    index: HashMap<Vec<u8>, u16>,
    cells: Vec<Cells>,
    deadline: Instant,
}
fn check(deadline: Instant) -> Result<(), &'static str> {
    if Instant::now() >= deadline {
        Err("terrain_timed_out")
    } else {
        Ok(())
    }
}
fn reserve<T>(memory: &mut Memory, n: usize) -> Result<Vec<T>, &'static str> {
    memory.add(
        n.checked_mul(std::mem::size_of::<T>())
            .ok_or("terrain_budget_exceeded")?,
    )?;
    let mut out = Vec::new();
    out.try_reserve_exact(n)
        .map_err(|_| "allocation_unavailable")?;
    if out.capacity() > n {
        memory.add((out.capacity() - n) * std::mem::size_of::<T>())?;
    }
    Ok(out)
}
impl Builder {
    fn new(reference: &Reference, deadline: Instant) -> Result<Self, &'static str> {
        let mut memory = Memory { used: 0 };
        memory.add(reference.memory_charge + 2 * MIB)?;
        let states = reserve(&mut memory, 4096)?;
        let cells = reserve(&mut memory, 27)?;
        let mut index = HashMap::new();
        index
            .try_reserve(4096)
            .map_err(|_| "allocation_unavailable")?;
        Ok(Self {
            memory,
            states,
            cells,
            index,
            deadline,
        })
    }
    fn section(&mut self, reference: &Reference, section: Section) -> Result<Counts, &'static str> {
        check(self.deadline)?;
        if self.cells.len() == 27 {
            return Err("terrain_budget_exceeded");
        }
        let mut ids = reserve(&mut self.memory, 4096)?;
        let mut local = vec![None; section.palette.len()];
        let mut cubes = 0u32;
        for (i, &p) in section.indices.iter().enumerate() {
            if i % 256 == 0 {
                check(self.deadline)?;
            }
            let index = p as usize;
            let state = section.palette.get(index).ok_or("invalid_cell_index")?;
            let id = if let Some(id) = local[index] {
                id
            } else {
                if state.name.is_empty()
                    || state.name.len() > 256
                    || state.properties.len() > 64
                    || state
                        .properties
                        .iter()
                        .any(|(k, v)| k.len() > 256 || v.len() > 256)
                {
                    return Err("state_entry_budget");
                }
                let mut properties = state.properties.clone();
                properties.sort();
                let signature =
                    json!({"dataVersion":3465,"name":state.name,"properties":properties});
                let key =
                    terrain_codec::payload_bytes(&signature).map_err(|_| "state_entry_budget")?;
                if key.len() > 4096 {
                    return Err("state_entry_budget");
                }
                let id = if let Some(id) = self.index.get(&key) {
                    *id
                } else {
                    if self.states.len() == 4096 {
                        return Err("terrain_budget_exceeded");
                    }
                    let id = self.states.len() as u16;
                    let (registry, cube) = reference.state(state);
                    let entry = json!({"stateId":id,"dataVersion":3465,"registryStateId":registry,"name":state.name,"properties":properties,"classification":if cube{"unitCubeShape"}else{"unsupported"}});
                    let bytes =
                        terrain_codec::payload_bytes(&entry).map_err(|_| "state_entry_budget")?;
                    if bytes.len() > 4096 {
                        return Err("state_entry_budget");
                    }
                    self.memory.add(key.capacity() + bytes.capacity())?;
                    self.index.insert(key, id);
                    self.states.push(State { bytes, cube });
                    id
                };
                local[index] = Some(id);
                id
            };
            if self.states[id as usize].cube {
                cubes += 1;
            }
            ids.push(id);
        }
        if ids.len() != 4096 {
            return Err("invalid_cell_count");
        }
        self.cells.push(Cells {
            x: section.x,
            z: section.z,
            y: section.y,
            ids,
        });
        Ok(Counts {
            cube: cubes,
            unsupported: 4096 - cubes,
        })
    }
}
pub(super) fn result(base: &Value, extras: Value) -> Value {
    let mut out = base.clone();
    for (k, v) in extras.as_object().expect("internal result object") {
        out[k] = v.clone();
    }
    out
}
pub(super) fn page_result(base: &Value, page: &Page, index: usize) -> Result<Value, &'static str> {
    let payload: Value = serde_json::from_slice(&page.bytes).map_err(|_| "invalid_staged_page")?;
    Ok(result(
        base,
        json!({"pageIndex":index,"kind":page.kind,"recordCount":page.count,"payloadSha256":page.hash,"payload":payload}),
    ))
}
fn store_page(
    pages: &mut Vec<Page>,
    memory: &mut Memory,
    base: &Value,
    generation: u64,
    kind: &'static str,
    count: u32,
    payload: Value,
    total: &mut usize,
) -> Result<(), &'static str> {
    if pages.len() == 1024 {
        return Err("terrain_budget_exceeded");
    }
    let bytes = terrain_codec::payload_bytes(&payload).map_err(|_| "terrain_page_budget")?;
    let hash = format!("{:x}", Sha256::digest(&bytes));
    let mut page = Page {
        kind,
        count,
        bytes,
        hash,
        encoded: 0,
    };
    let response = json!({"version":1,"id":format!("terrain:{generation}:page:{}",pages.len()),"result":page_result(base,&page,pages.len())?});
    let encoded = terrain_codec::payload_bytes(&response)
        .map_err(|_| "terrain_page_budget")?
        .len();
    if encoded > PAGE_LIMIT {
        return Err("terrain_page_budget");
    }
    *total = total
        .checked_add(encoded)
        .filter(|n| *n <= 64 * MIB)
        .ok_or("terrain_encoded_budget")?;
    memory.add(page.bytes.capacity() + page.hash.capacity())?;
    page.encoded = encoded;
    pages.push(page);
    Ok(())
}
fn scene_id() -> Result<String, &'static str> {
    #[cfg(windows)]
    {
        #[link(name = "bcrypt")]
        extern "system" {
            fn BCryptGenRandom(
                algorithm: *mut std::ffi::c_void,
                buffer: *mut u8,
                length: u32,
                flags: u32,
            ) -> i32;
        }
        let mut bytes = [0u8; 16];
        if unsafe { BCryptGenRandom(std::ptr::null_mut(), bytes.as_mut_ptr(), 16, 2) } != 0 {
            return Err("scene_identity_unavailable");
        }
        Ok(bytes.iter().map(|b| format!("{b:02x}")).collect())
    }
    #[cfg(not(windows))]
    {
        Err("scene_identity_unavailable")
    }
}
pub(super) fn build(
    reference: &Reference,
    params: Begin,
    began: Instant,
) -> Result<Snapshot, &'static str> {
    let deadline = began + std::time::Duration::from_secs(30);
    let mut builder = Builder::new(reference, deadline)?;
    let observed = terrain_read::read(
        Path::new(&params.path),
        &params.dimension,
        params.bounds,
        deadline,
        |section| builder.section(reference, section),
    )?;
    check(deadline)?;
    if observed.selected_sector_bytes > 9 * 255 * 4096
        || observed.hashed_bytes > 4 * 256 * MIB as u64 + 16 * MIB as u64
    {
        return Err("terrain_budget_exceeded");
    }
    let mut base = json!({"schemaVersion":1,"readSetEncoding":1,"worldId":params.world_id,"dimension":params.dimension,"generation":params.generation,"sceneId":scene_id()?,"geometrySchema":1,"geometryCapability":CAPABILITY,"shapeEvidenceSha256":SHAPE_SHA256,"registry":registry_identity()});
    let mut manifest = result(
        &base,
        json!({"bounds":params.bounds.json(),"limitProfile":"terrain-small-v1","readOnly":true,"editingSupported":false,"coverage":observed.coverage,"sources":observed.sources}),
    );
    let digest = terrain_codec::read_set_digest(&manifest).map_err(|_| "invalid_read_set")?;
    base["readSetDigest"] = json!(digest);
    manifest["readSetDigest"] = base["readSetDigest"].clone();
    let mut pages = reserve(&mut builder.memory, 1024)?;
    let mut encoded_total = 0usize;
    for states in builder.states.chunks(16) {
        check(deadline)?;
        let values = states
            .iter()
            .map(|s| serde_json::from_slice::<Value>(&s.bytes).map_err(|_| "invalid_staged_state"))
            .collect::<Result<Vec<_>, _>>()?;
        store_page(
            &mut pages,
            &mut builder.memory,
            &base,
            params.generation,
            "states",
            values.len() as u32,
            json!({"states":values}),
            &mut encoded_total,
        )?;
    }
    for cells in &builder.cells {
        check(deadline)?;
        store_page(
            &mut pages,
            &mut builder.memory,
            &base,
            params.generation,
            "cells",
            4096,
            json!({"chunkX":cells.x,"chunkZ":cells.z,"sectionY":cells.y,"stateIds":cells.ids}),
            &mut encoded_total,
        )?;
    }
    let mut faces = Vec::with_capacity(2048);
    let mut face_count = 0usize;
    let mut cube_count = 0usize;
    for cells in &builder.cells {
        for (index, &id) in cells.ids.iter().enumerate() {
            if index % 256 == 0 {
                check(deadline)?;
            }
            if !builder.states[id as usize].cube {
                continue;
            }
            cube_count += 1;
            let (x, z, y) = (index % 16, index / 16 % 16, index / 256);
            for direction in ["xp", "xn", "yp", "yn", "zp", "zn"] {
                if face_count == 663552 {
                    return Err("terrain_face_budget");
                }
                faces.push(json!([cells.x, cells.z, cells.y, x, y, z, direction, id]));
                face_count += 1;
                if faces.len() == 2048 {
                    let payload =
                        json!({"faces":std::mem::replace(&mut faces,Vec::with_capacity(2048))});
                    store_page(
                        &mut pages,
                        &mut builder.memory,
                        &base,
                        params.generation,
                        "faces",
                        2048,
                        payload,
                        &mut encoded_total,
                    )?;
                }
            }
        }
    }
    if !faces.is_empty() {
        let count = faces.len() as u32;
        store_page(
            &mut pages,
            &mut builder.memory,
            &base,
            params.generation,
            "faces",
            count,
            json!({"faces":faces}),
            &mut encoded_total,
        )?;
    }
    let decoded = builder.cells.len() * 4096;
    let totals = json!({"states":builder.states.len(),"sections":builder.cells.len(),"decodedCells":decoded,"cubeCells":cube_count,"airCells":0,"unsupportedCells":decoded-cube_count,"faces":face_count,"pages":pages.len()});
    manifest["totals"] = totals.clone();
    manifest["pages"]=json!(pages.iter().enumerate().map(|(i,p)|json!({"pageIndex":i,"kind":p.kind,"recordCount":p.count,"encodedBytes":p.encoded,"payloadSha256":p.hash})).collect::<Vec<_>>());
    let begin =
        json!({"version":1,"id":format!("terrain:{}:begin",params.generation),"result":manifest});
    let begin_bytes = terrain_codec::payload_bytes(&begin)
        .map_err(|_| "terrain_manifest_budget")?
        .len();
    let end = json!({"version":1,"id":format!("terrain:{}:end",params.generation),"result":result(&base,json!({"released":true,"releasedCounts":totals,"deliveredPages":pages.len()}))});
    let end_bytes = terrain_codec::payload_bytes(&end)
        .map_err(|_| "terrain_encoded_budget")?
        .len();
    if begin_bytes > PAGE_LIMIT
        || encoded_total
            .checked_add(begin_bytes + end_bytes)
            .is_none_or(|n| n > 64 * MIB)
    {
        return Err("terrain_encoded_budget");
    }
    check(deadline)?;
    // Retained cells and states are deliberately kept with the immutable pages.
    let resident = builder.memory.used;
    let snapshot = Snapshot {
        base,
        manifest,
        pages,
        totals,
        cursor: 0,
        began,
        resident_bytes: resident,
        temporary_peak: observed.temporary_peak.max(32 * MIB),
        _states: builder.states,
        _cells: builder.cells,
    };
    Ok(snapshot)
}

impl Snapshot {
    pub(super) fn retained_counts(&self) -> (usize, usize) {
        (
            self._states.len(),
            self._cells.iter().map(|c| c.ids.len()).sum(),
        )
    }
}
#[cfg(test)]
pub(super) fn fixture(case: &Value) -> Snapshot {
    let manifest = case["beginResponse"]["result"].clone();
    let mut base = manifest.clone();
    for k in [
        "bounds",
        "limitProfile",
        "readOnly",
        "editingSupported",
        "coverage",
        "sources",
        "pages",
        "totals",
    ] {
        base.as_object_mut().unwrap().remove(k);
    }
    let pages = case["pageResponses"]
        .as_array()
        .unwrap()
        .iter()
        .map(|p| Page {
            kind: match p["result"]["kind"].as_str().unwrap() {
                "states" => "states",
                "cells" => "cells",
                _ => "faces",
            },
            count: p["result"]["recordCount"].as_u64().unwrap() as u32,
            bytes: terrain_codec::payload_bytes(&p["result"]["payload"]).unwrap(),
            hash: p["result"]["payloadSha256"].as_str().unwrap().into(),
            encoded: serde_json::to_vec(p).unwrap().len(),
        })
        .collect();
    Snapshot {
        base,
        totals: manifest["totals"].clone(),
        manifest,
        pages,
        cursor: 0,
        began: Instant::now(),
        resident_bytes: 0,
        temporary_peak: 0,
        _states: vec![],
        _cells: vec![],
    }
}

#[cfg(test)]
mod budget_tests {
    use super::*;
    #[test]
    fn aggregate_resident_budget_rejects_before_growth() {
        let mut memory = Memory { used: 128 * MIB };
        assert_eq!(memory.add(1), Err("terrain_budget_exceeded"));
        let mut memory = Memory {
            used: 128 * MIB - 1,
        };
        memory.add(1).unwrap();
        assert_eq!(memory.used, 128 * MIB);
        assert_eq!(memory.add(usize::MAX), Err("terrain_budget_exceeded"));
    }
}
