//! Process-owned single immutable terrain session.
use crate::reference::{Availability, CAPABILITY};
use serde_json::{json, Value};
use std::time::{Duration, Instant};
mod model;
mod transport;
use model::{Begin, Snapshot};
pub use transport::serve;
pub struct Session {
    reference: Availability,
    started: bool,
    snapshot: Option<Snapshot>,
    last_activity: Instant,
    accepted: Option<Instant>,
}
fn error(id: &Value, code: &str) -> Value {
    json!({"version":1,"id":id,"error":{"code":code,"message":code}})
}
fn integer(v: &Value) -> Result<i32, &'static str> {
    v.as_i64()
        .and_then(|n| i32::try_from(n).ok())
        .ok_or("invalid_terrain_integer")
}
fn generation(v: &Value) -> Result<u64, &'static str> {
    v.as_u64()
        .filter(|n| *n <= 9007199254740991)
        .ok_or("invalid_generation")
}
fn exact_keys(v: &Value, keys: &[&str]) -> Result<(), &'static str> {
    let object = v.as_object().ok_or("invalid_terrain_params")?;
    if object.len() != keys.len() || object.keys().any(|k| !keys.contains(&k.as_str())) {
        return Err("invalid_terrain_params");
    }
    Ok(())
}
fn text<'a>(v: &'a Value, key: &str, max: usize) -> Result<&'a str, &'static str> {
    v.get(key)
        .and_then(Value::as_str)
        .filter(|s| !s.is_empty() && s.len() <= max && !s.contains('\0'))
        .ok_or("invalid_terrain_text")
}
fn begin(params: &Value) -> Result<Begin, &'static str> {
    exact_keys(
        params,
        &[
            "path",
            "worldId",
            "dimension",
            "generation",
            "geometryCapability",
            "limitProfile",
            "chunkXMin",
            "chunkXMax",
            "chunkZMin",
            "chunkZMax",
            "sectionYMin",
            "sectionYMax",
        ],
    )?;
    if text(params, "geometryCapability", 64)? != CAPABILITY
        || text(params, "limitProfile", 64)? != "terrain-small-v1"
    {
        return Err("unsupported_terrain_profile");
    }
    let path = std::path::PathBuf::from(text(params, "path", 32768)?);
    if !path.is_absolute() {
        return Err("world_path_not_absolute");
    }
    let world = text(params, "worldId", 128)?;
    if !world
        .bytes()
        .all(|c| c.is_ascii_alphanumeric() || b"_.:-".contains(&c))
    {
        return Err("invalid_world_identity");
    }
    let dimension = text(params, "dimension", 256)?;
    let b = crate::terrain_read::Bounds {
        xmin: integer(&params["chunkXMin"])?,
        xmax: integer(&params["chunkXMax"])?,
        zmin: integer(&params["chunkZMin"])?,
        zmax: integer(&params["chunkZMax"])?,
        ymin: integer(&params["sectionYMin"])?,
        ymax: integer(&params["sectionYMax"])?,
    };
    if !b.valid() {
        return Err("invalid_terrain_bounds");
    }
    Ok(Begin {
        path,
        world_id: world.into(),
        dimension: dimension.into(),
        generation: generation(&params["generation"])?,
        bounds: b,
    })
}
const IDENTITIES: [&str; 9] = [
    "worldId",
    "dimension",
    "generation",
    "sceneId",
    "readSetDigest",
    "registry",
    "geometrySchema",
    "geometryCapability",
    "shapeEvidenceSha256",
];
impl Session {
    pub fn new(reference: Availability) -> Self {
        Self {
            reference,
            started: false,
            snapshot: None,
            last_activity: Instant::now(),
            accepted: None,
        }
    }
    pub fn wait_remaining(&self) -> Option<Duration> {
        if !self.started {
            return None;
        }
        let now = Instant::now();
        let idle = self.last_activity + Duration::from_secs(5);
        let deadline = self
            .accepted
            .map(|began| began + Duration::from_secs(30))
            .unwrap_or(idle);
        Some(idle.min(deadline).saturating_duration_since(now))
    }
    pub fn release(&mut self) {
        self.snapshot = None;
    }
    pub fn dispatch(&mut self, request: Value) -> Value {
        let id = request.get("id").cloned().unwrap_or(Value::Null);
        if !request.is_object()
            || request.get("version").and_then(Value::as_u64) != Some(1)
            || !(id.is_string() || id.is_i64() || id.is_u64())
            || id.as_str().is_some_and(|s| s.len() > 128)
        {
            return error(&Value::Null, "invalid_request");
        }
        if self.wait_remaining().is_some_and(|d| d.is_zero()) {
            self.release();
            return error(&id, "terrain_session_expired");
        }
        self.last_activity = Instant::now();
        let method = request.get("method").and_then(Value::as_str).unwrap_or("");
        if !matches!(
            method,
            "world.terrain_begin" | "world.terrain_page" | "world.terrain_end"
        ) {
            if self.started && method != "engine.info" {
                return error(&id, "scene_active");
            }
            let info = method == "engine.info";
            let mut response =
                crate::protocol::dispatch_with_reference(request, Some(&self.reference));
            if info && response.get("result").is_some() {
                let methods = response["result"]["methods"].as_array_mut().unwrap();
                for name in [
                    "world.terrain_begin",
                    "world.terrain_page",
                    "world.terrain_end",
                ] {
                    methods.push(json!(name));
                }
                response["result"]["terrainCapabilities"] =
                    if matches!(self.reference, Availability::Ready(_)) {
                        json!([CAPABILITY])
                    } else {
                        json!([])
                    };
            }
            return response;
        }
        if exact_keys(&request, &["version", "id", "method", "params"]).is_err() {
            return error(&id, "invalid_terrain_request");
        }
        let params = &request["params"];
        if method == "world.terrain_begin" {
            if self.started {
                return error(&id, "scene_already_started");
            }
            let params = match begin(params) {
                Ok(v) => v,
                Err(code) => return error(&id, code),
            };
            if id.as_str() != Some(format!("terrain:{}:begin", params.generation).as_str()) {
                return error(&id, "invalid_terrain_request_id");
            }
            let Availability::Ready(reference) = &self.reference else {
                return error(&id, "reference_unavailable");
            };
            let began = Instant::now();
            match model::build(reference, params, began) {
                Ok(snapshot) => {
                    if snapshot.resident_bytes > 128 * 1024 * 1024
                        || snapshot.temporary_peak > 96 * 1024 * 1024
                    {
                        return error(&id, "terrain_budget_exceeded");
                    }
                    let retained = snapshot.retained_counts();
                    if retained.0 as u64 != snapshot.totals["states"].as_u64().unwrap_or(u64::MAX)
                        || retained.1 as u64
                            != snapshot.totals["decodedCells"].as_u64().unwrap_or(u64::MAX)
                    {
                        return error(&id, "invalid_staged_inventory");
                    }
                    let response = json!({"version":1,"id":id,"result":snapshot.manifest});
                    self.snapshot = Some(snapshot);
                    self.started = true;
                    self.accepted = self.snapshot.as_ref().map(|s| s.began);
                    self.last_activity = Instant::now();
                    return response;
                }
                Err(code) => return error(&id, code),
            }
        }
        let Some(snapshot) = self.snapshot.as_mut() else {
            return error(&id, "scene_not_found");
        };
        if params.get("sceneId") != snapshot.base.get("sceneId") {
            return error(&id, "scene_not_found");
        }
        let mut keys = IDENTITIES.to_vec();
        if method == "world.terrain_page" {
            keys.push("pageIndex");
        }
        if exact_keys(params, &keys).is_err()
            || IDENTITIES
                .iter()
                .any(|key| params.get(*key) != snapshot.base.get(*key))
        {
            self.release();
            return error(&id, "scene_identity_mismatch");
        }
        if generation(&params["generation"]).is_err()
            || params["geometrySchema"].as_u64() != Some(1)
            || params["registry"]["schemaVersion"].as_u64() != Some(1)
        {
            self.release();
            return error(&id, "scene_identity_mismatch");
        }
        let gen = snapshot.base["generation"].as_u64().unwrap();
        if method == "world.terrain_page" {
            let index = params["pageIndex"]
                .as_u64()
                .and_then(|n| usize::try_from(n).ok());
            if index != Some(snapshot.cursor) || snapshot.cursor >= snapshot.pages.len() {
                self.release();
                return error(&id, "page_sequence_error");
            }
            if id.as_str() != Some(format!("terrain:{gen}:page:{}", snapshot.cursor).as_str()) {
                self.release();
                return error(&id, "invalid_terrain_request_id");
            }
            let response = match model::page_result(
                &snapshot.base,
                &snapshot.pages[snapshot.cursor],
                snapshot.cursor,
            ) {
                Ok(v) => json!({"version":1,"id":id,"result":v}),
                Err(code) => {
                    self.release();
                    return error(&id, code);
                }
            };
            if serde_json::to_vec(&response).map(|v| v.len()).ok()
                != Some(snapshot.pages[snapshot.cursor].encoded)
            {
                self.release();
                return error(&id, "staged_page_size_mismatch");
            }
            snapshot.cursor += 1;
            return response;
        }
        if id.as_str() != Some(format!("terrain:{gen}:end").as_str()) {
            self.release();
            return error(&id, "invalid_terrain_request_id");
        }
        let result = model::result(
            &snapshot.base,
            json!({"released":true,"releasedCounts":snapshot.totals,"deliveredPages":snapshot.cursor}),
        );
        self.release();
        json!({"version":1,"id":id,"result":result})
    }
}
#[cfg(test)]
mod tests;
