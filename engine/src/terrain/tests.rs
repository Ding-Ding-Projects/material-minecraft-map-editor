use super::*;
use std::{
    io::{Cursor, Read},
    sync::{Arc, Condvar, Mutex},
};
fn fixtures() -> Value {
    serde_json::from_str(include_str!("../../docs/terrain-wire-v1-fixtures.json")).unwrap()
}
fn staged() -> Session {
    let fixture = fixtures();
    let mut session = Session::new(Availability::Unavailable("test_reference_not_used"));
    let snapshot = model::fixture(&fixture["cases"][0]);
    session.accepted = Some(snapshot.began);
    session.started = true;
    session.snapshot = Some(snapshot);
    session
}
#[test]
fn sequential_pages_end_and_second_begin_are_process_owned() {
    let f = fixtures();
    let case = &f["cases"][0];
    let mut s = staged();
    for (request, response) in case["pageRequests"]
        .as_array()
        .unwrap()
        .iter()
        .zip(case["pageResponses"].as_array().unwrap())
    {
        assert_eq!(s.dispatch(request.clone()), *response);
    }
    let ended = s.dispatch(case["endRequest"].clone());
    assert_eq!(ended, case["endResponse"]);
    assert!(s.snapshot.is_none());
    assert_eq!(
        s.dispatch(case["beginRequest"].clone())["error"]["code"],
        "scene_already_started"
    );
    assert_eq!(
        s.dispatch(case["pageRequests"][0].clone())["error"]["code"],
        "scene_not_found"
    );
}
#[test]
fn skipped_repeated_wrong_identity_and_boolean_pages_fail_closed() {
    let f = fixtures();
    let case = &f["cases"][0];
    let mut s = staged();
    assert_eq!(
        s.dispatch(case["pageRequests"][1].clone())["error"]["code"],
        "page_sequence_error"
    );
    assert!(s.snapshot.is_none());
    let mut s = staged();
    s.dispatch(case["pageRequests"][0].clone());
    assert_eq!(
        s.dispatch(case["pageRequests"][0].clone())["error"]["code"],
        "page_sequence_error"
    );
    for (key, value) in [
        ("generation", json!(true)),
        ("geometryCapability", json!("cube-faces-v1")),
        ("pageIndex", json!(false)),
    ] {
        let mut s = staged();
        let mut request = case["pageRequests"][0].clone();
        request["params"][key] = value;
        assert!(s.dispatch(request).get("error").is_some());
        assert!(s.snapshot.is_none());
    }
}
#[test]
fn explicit_early_end_releases_all_and_timeout_cannot_revive_scene() {
    let f = fixtures();
    let mut s = staged();
    let response = s.dispatch(f["cases"][0]["endRequest"].clone());
    assert_eq!(response["result"]["deliveredPages"], 0);
    assert!(s.snapshot.is_none());
    let mut s = staged();
    s.accepted = Some(Instant::now() - Duration::from_secs(31));
    assert_eq!(
        s.dispatch(f["cases"][0]["pageRequests"][0].clone())["error"]["code"],
        "terrain_session_expired"
    );
    assert!(s.snapshot.is_none());
}
#[test]
fn missing_reference_and_integer_admission_are_truthful() {
    let mut s = Session::new(Availability::Unavailable("reference_root_missing"));
    let mut request = fixtures()["cases"][0]["beginRequest"].clone();
    request["params"]["path"] = json!(std::env::temp_dir().to_str().unwrap());
    assert_eq!(
        s.dispatch(request.clone())["error"]["code"],
        "reference_unavailable"
    );
    for value in [json!(true), json!(9007199254740992u64), json!(7.0)] {
        request["params"]["generation"] = value;
        assert!(s.dispatch(request.clone()).get("error").is_some());
    }
    assert!(s.snapshot.is_none());
}
fn frame(bytes: &[u8]) -> Vec<u8> {
    let mut result = (bytes.len() as u32).to_be_bytes().to_vec();
    result.extend_from_slice(bytes);
    result
}
#[test]
fn raw_duplicate_keys_and_oversized_world_paths_do_not_silently_coerce() {
    let mut out = Vec::new();
    let data=frame(br#"{"version":1,"id":"x","method":"engine.info","method":"world.terrain_begin","params":{}}"#);
    serve(
        Cursor::new(data),
        &mut out,
        Session::new(Availability::Unavailable("reference_root_missing")),
    )
    .unwrap();
    let result: Value = serde_json::from_slice(&out[4..]).unwrap();
    assert_eq!(result["error"]["code"], "invalid_json");
    assert!(crate::registry::parse_protocol(
        &serde_json::to_vec(&json!({"path":"a".repeat(32769)})).unwrap()
    )
    .is_err());
    assert!(crate::registry::parse_protocol(
        &serde_json::to_vec(&json!({"path":"a".repeat(32768)})).unwrap()
    )
    .is_ok());
}
struct Hold {
    release: Arc<(Mutex<bool>, Condvar)>,
}
impl Read for Hold {
    fn read(&mut self, _: &mut [u8]) -> std::io::Result<usize> {
        let (lock, condition) = &*self.release;
        let mut ready = lock.lock().unwrap();
        while !*ready {
            ready = condition.wait(ready).unwrap();
        }
        Ok(0)
    }
}
#[test]
fn idle_wait_expires_even_when_stdin_remains_open() {
    let release = Arc::new((Mutex::new(false), Condvar::new()));
    let mut s = staged();
    s.last_activity = Instant::now() - Duration::from_millis(4950);
    let began = Instant::now();
    let result = serve(
        Hold {
            release: release.clone(),
        },
        Vec::new(),
        s,
    );
    let (lock, condition) = &*release;
    *lock.lock().unwrap() = true;
    condition.notify_all();
    assert_eq!(result.unwrap_err().kind(), std::io::ErrorKind::TimedOut);
    assert!(began.elapsed() < Duration::from_secs(2));
}
#[test]
#[ignore = "requires explicit pinned reference root; no downloaded code execution"]
fn actual_persistent_scene_retains_cells_and_all_six_faces() {
    let selected = std::path::PathBuf::from(
        std::env::var_os("MWE_TEST_REFERENCE_ROOT").expect("explicit root required"),
    );
    let reference = Availability::load(crate::reference::Options {
        root: Some(selected),
        profile: Some(crate::reference::PROFILE.into()),
    });
    assert!(matches!(reference, Availability::Ready(_)));
    let f = fixtures();
    for case in f["cases"].as_array().unwrap() {
        let root = std::env::temp_dir().join(format!(
            "terrain-session-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        std::fs::create_dir(&root).unwrap();
        for file in case["files"].as_array().unwrap() {
            let target = root.join(file["relativePath"].as_str().unwrap());
            std::fs::create_dir_all(target.parent().unwrap()).unwrap();
            let text = file["bytesHex"].as_str().unwrap();
            std::fs::write(
                target,
                crate::terrain_codec::raw_hex(text, text.len() / 2).unwrap(),
            )
            .unwrap();
        }
        std::fs::create_dir_all(root.join("region")).unwrap();
        let mut s = Session::new(reference.clone());
        let mut request = case["beginRequest"].clone();
        request["params"]["path"] = json!(root.to_str().unwrap());
        let response = s.dispatch(request);
        assert!(
            response.get("result").is_some(),
            "actual scene begin failed"
        );
        let manifest = &response["result"];
        assert_eq!(
            manifest["totals"],
            case["beginResponse"]["result"]["totals"]
        );
        let snapshot = s.snapshot.as_ref().unwrap();
        assert_eq!(
            snapshot.retained_counts().1,
            manifest["totals"]["decodedCells"].as_u64().unwrap() as usize
        );
        assert!(
            snapshot.resident_bytes <= 128 * 1024 * 1024
                && snapshot.temporary_peak <= 96 * 1024 * 1024
        );
        for descriptor in manifest["pages"].as_array().unwrap() {
            let index = descriptor["pageIndex"].as_u64().unwrap();
            let mut params = manifest.clone();
            params
                .as_object_mut()
                .unwrap()
                .retain(|k, _| IDENTITIES.contains(&k.as_str()));
            params["pageIndex"] = json!(index);
            let page=s.dispatch(json!({"version":1,"id":format!("terrain:7:page:{index}"),"method":"world.terrain_page","params":params}));
            assert!(page.get("result").is_some(), "actual page failed");
            assert_eq!(
                serde_json::to_vec(&page).unwrap().len() as u64,
                descriptor["encodedBytes"].as_u64().unwrap()
            );
            assert_eq!(
                crate::terrain_codec::payload_digest(&page["result"]["payload"]).unwrap(),
                descriptor["payloadSha256"].as_str().unwrap()
            );
        }
        let mut params = manifest.clone();
        params
            .as_object_mut()
            .unwrap()
            .retain(|k, _| IDENTITIES.contains(&k.as_str()));
        let end = s.dispatch(
            json!({"version":1,"id":"terrain:7:end","method":"world.terrain_end","params":params}),
        );
        assert_eq!(end["result"]["released"], true);
        assert!(s.snapshot.is_none());
        std::fs::remove_dir_all(root).unwrap();
    }
}

#[test]
fn invalid_raw_json_releases_preexisting_scene() {
    let f = fixtures();
    let duplicate = br#"{"version":1,"version":1,"id":"bad","method":"engine.info","params":{}}"#;
    let mut input = frame(duplicate);
    input.extend(frame(
        &serde_json::to_vec(&f["cases"][0]["pageRequests"][0]).unwrap(),
    ));
    let mut output = Vec::new();
    serve(Cursor::new(input), &mut output, staged()).unwrap();
    let first = u32::from_be_bytes(output[..4].try_into().unwrap()) as usize;
    let second_offset = 4 + first;
    let second: Value = serde_json::from_slice(&output[second_offset + 4..]).unwrap();
    assert_eq!(second["error"]["code"], "scene_not_found");
}

#[test]
#[ignore = "requires explicit pinned reference root; synthetic mixed region only"]
fn actual_mixed_stone_cobble_retains_all_neighbor_faces() {
    use crate::nbt::{Limits, NamedTag, Tag};
    use crate::region::{Region, RegionEdit};
    let selected = std::path::PathBuf::from(
        std::env::var_os("MWE_TEST_REFERENCE_ROOT").expect("explicit root required"),
    );
    let reference = Availability::load(crate::reference::Options {
        root: Some(selected),
        profile: Some(crate::reference::PROFILE.into()),
    });
    let Availability::Ready(reference) = reference else {
        panic!("verified references unavailable")
    };
    let f = fixtures();
    let case = &f["cases"][0];
    let bytes =
        crate::terrain_codec::raw_hex(case["files"][1]["bytesHex"].as_str().unwrap(), 12288)
            .unwrap();
    let mut chunk = Region::parse(&bytes)
        .unwrap()
        .chunk(31, Limits::default())
        .unwrap()
        .unwrap();
    let Tag::Compound(top) = &mut chunk.tag else {
        panic!()
    };
    top.iter_mut().find(|n| n.name == b"zPos").unwrap().tag = Tag::Int(-1);
    let Tag::List(10, sections) = &mut top.iter_mut().find(|n| n.name == b"sections").unwrap().tag
    else {
        panic!()
    };
    let Tag::Compound(section) = &mut sections[0] else {
        panic!()
    };
    let Tag::Compound(blocks) = &mut section
        .iter_mut()
        .find(|n| n.name == b"block_states")
        .unwrap()
        .tag
    else {
        panic!()
    };
    let names = [
        "minecraft:stone",
        "minecraft:cobblestone",
        "minecraft:air",
        "minecraft:glass",
    ];
    blocks
        .iter_mut()
        .find(|n| n.name == b"palette")
        .unwrap()
        .tag = Tag::List(
        10,
        names
            .iter()
            .map(|name| {
                Tag::Compound(vec![NamedTag {
                    name: b"Name".to_vec(),
                    tag: Tag::String(name.as_bytes().to_vec()),
                }])
            })
            .collect(),
    );
    let mut indices = Vec::new();
    for y in 0..16 {
        for z in 0..16 {
            for x in 0..16 {
                let mut state = if y < 4 { 0 } else { 2 };
                if (4..=5).contains(&x) && (4..=5).contains(&z) && (4..=10).contains(&y) {
                    state = 1;
                }
                if (x, z, y) == (10, 10, 6) {
                    state = 3;
                }
                indices.push(state);
            }
        }
    }
    blocks.iter_mut().find(|n| n.name == b"data").unwrap().tag =
        Tag::LongArray(crate::edit::pack_padded(&indices, 4).unwrap());
    let root = std::env::temp_dir().join(format!(
        "terrain-mixed-{}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    std::fs::create_dir(&root).unwrap();
    std::fs::create_dir(root.join("region")).unwrap();
    let level = case["files"][0]["bytesHex"].as_str().unwrap();
    let level = crate::terrain_codec::raw_hex(level, level.len() / 2).unwrap();
    std::fs::write(root.join("level.dat"), &level).unwrap();
    let empty = vec![0; 8192];
    let region = Region::parse(&empty)
        .unwrap()
        .rebuild(
            &[RegionEdit {
                index: 1023,
                root: chunk,
                timestamp: 0,
            }],
            Limits::default(),
        )
        .unwrap();
    std::fs::write(root.join("region/r.-1.-1.mca"), &region).unwrap();
    let snapshot = model::build(
        &reference,
        model::Begin {
            path: root.clone(),
            world_id: "fixture-mixed".into(),
            dimension: "minecraft:overworld".into(),
            generation: 1,
            bounds: crate::terrain_read::Bounds {
                xmin: -1,
                xmax: -1,
                zmin: -1,
                zmax: -1,
                ymin: -4,
                ymax: -4,
            },
        },
        Instant::now(),
    )
    .unwrap();
    assert_eq!(snapshot.manifest["totals"]["cubeCells"], 1052);
    assert_eq!(snapshot.manifest["totals"]["unsupportedCells"], 3044);
    assert_eq!(snapshot.manifest["totals"]["faces"], 6312);
    assert_eq!(snapshot.retained_counts().1, 4096);
    let mut directions =
        std::collections::HashMap::<(i64, i64, i64), std::collections::HashSet<String>>::new();
    for page in &snapshot.pages {
        if page.kind != "faces" {
            continue;
        }
        let payload: Value = serde_json::from_slice(&page.bytes).unwrap();
        for face in payload["faces"].as_array().unwrap() {
            assert_eq!(face[0], -1);
            assert_eq!(face[1], -1);
            assert_eq!(face[2], -4);
            let key = (
                face[3].as_i64().unwrap(),
                face[4].as_i64().unwrap(),
                face[5].as_i64().unwrap(),
            );
            assert!(directions
                .entry(key)
                .or_default()
                .insert(face[6].as_str().unwrap().into()));
        }
    }
    assert_eq!(directions.len(), 1052);
    assert!(directions.values().all(|v| v.len() == 6));
    assert_eq!(std::fs::read(root.join("level.dat")).unwrap(), level);
    assert_eq!(
        std::fs::read(root.join("region/r.-1.-1.mca")).unwrap(),
        region
    );
    drop(snapshot);
    std::fs::remove_dir_all(root).unwrap();
}
