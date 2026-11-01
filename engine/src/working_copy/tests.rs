use super::*;
use crate::nbt::{self, Limits, NamedTag, Tag};
struct Fixture(PathBuf);
impl Fixture {
    fn new() -> Self {
        let p = std::env::temp_dir().join(format!(
            "working-copy-test-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        fs::create_dir(&p).unwrap();
        Self(p)
    }
    fn source(&self) -> PathBuf {
        let p = self.0.join("source");
        fs::create_dir(&p).unwrap();
        let root = NamedTag {
            name: vec![],
            tag: Tag::Compound(vec![NamedTag {
                name: b"Data".to_vec(),
                tag: Tag::Compound(vec![
                    NamedTag {
                        name: b"DataVersion".to_vec(),
                        tag: Tag::Int(3465),
                    },
                    NamedTag {
                        name: b"unknown".to_vec(),
                        tag: Tag::ByteArray(vec![1, 2, 3]),
                    },
                ]),
            }]),
        };
        let mut zip = flate2::write::GzEncoder::new(Vec::new(), flate2::Compression::default());
        zip.write_all(&nbt::write(&root, Limits::default()).unwrap())
            .unwrap();
        fs::write(p.join("level.dat"), zip.finish().unwrap()).unwrap();
        fs::write(
            p.join("unknown.bin"),
            (0..200000).map(|i| (i % 251) as u8).collect::<Vec<_>>(),
        )
        .unwrap();
        fs::create_dir(p.join("empty")).unwrap();
        p
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        fs::remove_dir_all(&self.0).unwrap();
    }
}
fn keep_going(_: Progress) -> Control {
    Control::Continue
}
fn records(stage: &Path) -> Vec<serde_json::Value> {
    let mut files = fs::read_dir(stage)
        .unwrap()
        .filter_map(|e| {
            let e = e.unwrap();
            (e.file_name().to_str().unwrap().starts_with("recovery-")).then_some(e.path())
        })
        .collect::<Vec<_>>();
    files.sort();
    files
        .into_iter()
        .filter_map(|p| serde_json::from_slice(&fs::read(p).unwrap()).ok())
        .collect()
}
#[test]
fn exact_unknown_bytes_and_empty_directories_are_copied() {
    let fixture = Fixture::new();
    let source = fixture.source();
    let destination = fixture.0.join("new-world");
    let before = fs::read(source.join("level.dat")).unwrap();
    let receipt = build(
        &source,
        &destination,
        CopyLimits::default(),
        &mut keep_going,
    )
    .unwrap();
    assert_eq!(receipt.files, 2);
    assert!(receipt.final_recovery_recorded);
    assert_eq!(fs::read(destination.join("level.dat")).unwrap(), before);
    assert_eq!(
        fs::read(destination.join("unknown.bin")).unwrap(),
        fs::read(source.join("unknown.bin")).unwrap()
    );
    assert!(destination.join("empty").is_dir());
    assert!(!destination.join("recovery-000001.json").exists());
    assert_eq!(
        records(&receipt.staging).last().unwrap()["status"],
        "published"
    );
    assert_eq!(fs::read(source.join("level.dat")).unwrap(), before);
}
#[test]
fn existing_destination_and_nested_destination_are_untouched() {
    let fixture = Fixture::new();
    let source = fixture.source();
    let destination = fixture.0.join("existing");
    fs::create_dir(&destination).unwrap();
    fs::write(destination.join("marker"), b"owned").unwrap();
    assert!(build(
        &source,
        &destination,
        CopyLimits::default(),
        &mut keep_going
    )
    .is_err());
    assert_eq!(fs::read(destination.join("marker")).unwrap(), b"owned");
    let nested = source.join("copy");
    assert!(build(&source, &nested, CopyLimits::default(), &mut keep_going).is_err());
    assert!(!nested.exists());
}
#[test]
fn publication_race_never_replaces_even_empty_directory() {
    let fixture = Fixture::new();
    let source = fixture.source();
    let destination = fixture.0.join("race");
    let error = build(
        &source,
        &destination,
        CopyLimits::default(),
        &mut |progress| {
            if progress.phase == Phase::BeforePublish {
                fs::create_dir(&destination).unwrap();
            }
            Control::Continue
        },
    )
    .unwrap_err();
    assert_eq!(error.reason, "destination publication failed");
    assert!(destination.is_dir());
    assert_eq!(fs::read_dir(&destination).unwrap().count(), 0);
    let stage = error.staging.unwrap();
    assert!(stage.join("payload/level.dat").is_file());
    assert_eq!(records(&stage).last().unwrap()["status"], "failed");
}
#[test]
fn cancellation_retains_partial_payload_and_recovery() {
    let fixture = Fixture::new();
    let source = fixture.source();
    let destination = fixture.0.join("cancelled");
    let error = build(
        &source,
        &destination,
        CopyLimits::default(),
        &mut |progress| {
            if progress.phase == Phase::CopyingFile && progress.bytes > 65536 {
                Control::Cancel
            } else {
                Control::Continue
            }
        },
    )
    .unwrap_err();
    assert_eq!(error.reason, "cancelled");
    assert!(!destination.exists());
    let stage = error.staging.unwrap();
    assert!(stage.join("payload/unknown.bin").is_file());
    assert!(
        fs::metadata(stage.join("payload/unknown.bin"))
            .unwrap()
            .len()
            < 200000
    );
    assert_eq!(records(&stage).last().unwrap()["status"], "cancelled");
}
#[test]
fn observed_source_change_prevents_publication() {
    let fixture = Fixture::new();
    let source = fixture.source();
    let destination = fixture.0.join("changed");
    let mut changed = false;
    let error = build(
        &source,
        &destination,
        CopyLimits::default(),
        &mut |progress| {
            if progress.phase == Phase::FileCopied && progress.files == 2 && !changed {
                changed = true;
                let path = source.join("unknown.bin");
                let modified = fs::metadata(&path).unwrap().modified().unwrap();
                fs::write(&path, vec![42; 200000]).unwrap();
                File::options()
                    .write(true)
                    .open(path)
                    .unwrap()
                    .set_times(fs::FileTimes::new().set_modified(modified))
                    .unwrap();
            }
            Control::Continue
        },
    )
    .unwrap_err();
    assert!(error.reason.starts_with("source"));
    assert!(error.staging.is_some());
    assert!(!destination.exists());
}
#[test]
fn bounded_inventory_and_invalid_level_keep_recovery() {
    for limits in [
        CopyLimits {
            max_entries: 1,
            ..CopyLimits::default()
        },
        CopyLimits {
            max_depth: 0,
            ..CopyLimits::default()
        },
        CopyLimits {
            max_bytes: 1,
            ..CopyLimits::default()
        },
        CopyLimits {
            max_file_bytes: 1,
            ..CopyLimits::default()
        },
    ] {
        let fixture = Fixture::new();
        let source = fixture.source();
        let destination = fixture.0.join("limited");
        let error = build(&source, &destination, limits, &mut keep_going).unwrap_err();
        assert!(error.staging.is_some());
        assert!(!destination.exists());
        assert_eq!(
            records(&error.staging.unwrap()).last().unwrap()["status"],
            "failed"
        );
    }
    let fixture = Fixture::new();
    let source = fixture.source();
    fs::write(source.join("level.dat"), b"invalid").unwrap();
    let error = build(
        &source,
        &fixture.0.join("invalid"),
        CopyLimits::default(),
        &mut keep_going,
    )
    .unwrap_err();
    assert_eq!(error.reason, "invalid source level.dat");
    assert!(error.recovery_recorded);
}
#[test]
fn hard_linked_files_are_rejected() {
    let fixture = Fixture::new();
    let source = fixture.source();
    fs::hard_link(source.join("unknown.bin"), source.join("linked.bin")).unwrap();
    let destination = fixture.0.join("linked");
    let error = build(
        &source,
        &destination,
        CopyLimits::default(),
        &mut keep_going,
    )
    .unwrap_err();
    assert!(error.reason.contains("linked"));
    assert!(!destination.exists());
}
#[cfg(windows)]
#[test]
fn junction_entries_are_rejected_without_following() {
    let fixture = Fixture::new();
    let source = fixture.source();
    let outside = fixture.0.join("outside");
    fs::create_dir(&outside).unwrap();
    let link = source.join("junction");
    let result = std::process::Command::new("cmd.exe")
        .args(["/c", "mklink", "/J"])
        .arg(&link)
        .arg(&outside)
        .output()
        .unwrap();
    assert!(result.status.success());
    let result = build(
        &source,
        &fixture.0.join("junction-copy"),
        CopyLimits::default(),
        &mut keep_going,
    );
    fs::remove_dir(link).unwrap();
    assert!(result.unwrap_err().reason.contains("linked"));
}
#[cfg(unix)]
#[test]
fn symlink_entries_are_rejected() {
    let fixture = Fixture::new();
    let source = fixture.source();
    std::os::unix::fs::symlink(source.join("unknown.bin"), source.join("linked")).unwrap();
    assert!(build(
        &source,
        &fixture.0.join("symlink-copy"),
        CopyLimits::default(),
        &mut keep_going
    )
    .unwrap_err()
    .reason
    .contains("linked"));
}

#[test]
fn file_created_at_publication_race_is_preserved() {
    let fixture = Fixture::new();
    let source = fixture.source();
    let destination = fixture.0.join("race-file");
    let result = build(
        &source,
        &destination,
        CopyLimits::default(),
        &mut |progress| {
            if progress.phase == Phase::BeforePublish {
                fs::write(&destination, b"caller-owned-race").unwrap();
            }
            Control::Continue
        },
    );
    assert_eq!(result.unwrap_err().reason, "destination publication failed");
    assert_eq!(fs::read(destination).unwrap(), b"caller-owned-race");
}
#[test]
fn unexpected_staging_entries_prevent_publication() {
    let fixture = Fixture::new();
    let source = fixture.source();
    let destination = fixture.0.join("injected");
    let result = build(
        &source,
        &destination,
        CopyLimits::default(),
        &mut |progress| {
            if progress.phase == Phase::BeforePublish {
                let stage = fs::read_dir(&fixture.0)
                    .unwrap()
                    .map(|e| e.unwrap().path())
                    .find(|p| {
                        p.file_name()
                            .unwrap()
                            .to_str()
                            .unwrap()
                            .starts_with(".world-copy-")
                    })
                    .unwrap();
                fs::write(stage.join("payload/unexpected"), b"extra").unwrap();
            }
            Control::Continue
        },
    );
    assert_eq!(result.unwrap_err().reason, "staging inventory changed");
    assert!(!destination.exists());
}
#[cfg(unix)]
#[test]
fn unix_socket_entry_is_rejected_as_nonregular() {
    let fixture = Fixture::new();
    let source = fixture.source();
    let _socket = std::os::unix::net::UnixDatagram::bind(source.join("socket")).unwrap();
    let error = build(
        &source,
        &fixture.0.join("socket-copy"),
        CopyLimits::default(),
        &mut keep_going,
    )
    .unwrap_err();
    assert_eq!(error.reason, "linked or nonregular source entry");
}

#[test]
fn cancellation_during_hash_verification_retains_full_staging() {
    let fixture = Fixture::new();
    let source = fixture.source();
    let destination = fixture.0.join("verify-cancel");
    let error = build(
        &source,
        &destination,
        CopyLimits::default(),
        &mut |progress| {
            if progress.phase == Phase::VerifyingFile {
                Control::Cancel
            } else {
                Control::Continue
            }
        },
    )
    .unwrap_err();
    assert_eq!(error.reason, "cancelled");
    assert_eq!(
        fs::read(error.staging.as_ref().unwrap().join("payload/unknown.bin")).unwrap(),
        fs::read(source.join("unknown.bin")).unwrap()
    );
    assert!(!destination.exists());
}
