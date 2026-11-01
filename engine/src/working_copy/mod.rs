//! Stable-snapshot working copies. No source writes or automatic recovery.
use serde_json::json;
use sha2::{Digest, Sha256};
use std::{
    fs::{self, File, OpenOptions},
    io::{Read, Write},
    path::{Path, PathBuf},
    sync::atomic::{AtomicU64, Ordering},
};
mod inventory;
mod publish;
use inventory::{inventory, open_checked, stamp, Entry};
#[derive(Clone, Copy)]
pub struct CopyLimits {
    pub max_entries: usize,
    pub max_depth: usize,
    pub max_bytes: u64,
    pub max_file_bytes: u64,
}
impl Default for CopyLimits {
    fn default() -> Self {
        Self {
            max_entries: 10000,
            max_depth: 64,
            max_bytes: 64 * 1024 * 1024 * 1024,
            max_file_bytes: 8 * 1024 * 1024 * 1024,
        }
    }
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Phase {
    InventoryReady,
    FileCopied,
    CopyingFile,
    VerifyingFile,
    BeforePublish,
}
pub struct Progress {
    pub phase: Phase,
    pub files: usize,
    pub bytes: u64,
}
#[derive(Clone, Copy, PartialEq, Eq)]
pub enum Control {
    Continue,
    Cancel,
}
#[derive(Debug)]
pub struct CopyFailure {
    pub reason: &'static str,
    pub staging: Option<PathBuf>,
    pub recovery_recorded: bool,
}
#[derive(Debug)]
pub struct CopyReceipt {
    pub destination: PathBuf,
    pub staging: PathBuf,
    pub files: usize,
    pub bytes: u64,
    pub final_recovery_recorded: bool,
}
struct Completed {
    path: PathBuf,
    bytes: u64,
    sha256: String,
}
struct Run {
    source: PathBuf,
    destination: PathBuf,
    stage: PathBuf,
    payload: PathBuf,
    completed: Vec<Completed>,
    bytes: u64,
    sequence: usize,
}
const MANIFEST_LIMIT: usize = 8 * 1024 * 1024;
struct BoundedWriter {
    file: File,
    left: usize,
}
impl Write for BoundedWriter {
    fn write(&mut self, b: &[u8]) -> std::io::Result<usize> {
        if b.len() > self.left {
            return Err(std::io::ErrorKind::FileTooLarge.into());
        }
        self.file.write_all(b)?;
        self.left -= b.len();
        Ok(b.len())
    }
    fn flush(&mut self) -> std::io::Result<()> {
        self.file.flush()
    }
}
impl Run {
    fn record(&mut self, status: &str, reason: Option<&str>) -> bool {
        self.sequence += 1;
        let record = json!({"schemaVersion":1,"status":status,"reason":reason,"source":self.source,"destination":self.destination,"payload":"payload","filesCopied":self.completed.len(),"bytesCopied":self.bytes,"files":self.completed.iter().map(|f|json!({"path":f.path,"bytes":f.bytes,"sha256":f.sha256})).collect::<Vec<_>>(),"liveSnapshotConsistencyClaim":false,"automaticResumeSupported":false});
        let result = (|| {
            let file = OpenOptions::new().create_new(true).write(true).open(
                self.stage
                    .join(format!("recovery-{:06}.json", self.sequence)),
            )?;
            let mut out = BoundedWriter {
                file,
                left: MANIFEST_LIMIT,
            };
            serde_json::to_writer(&mut out, &record)?;
            out.file.sync_all()
        })(); // Earlier complete records are never overwritten.
        result.is_ok()
    }
    fn failed(mut self, reason: &'static str) -> CopyFailure {
        let recorded = self.record(
            if reason == "cancelled" {
                "cancelled"
            } else {
                "failed"
            },
            Some(reason),
        );
        CopyFailure {
            reason,
            staging: Some(self.stage),
            recovery_recorded: recorded,
        }
    }
}
fn setup(source: &Path, destination: &Path) -> Result<Run, &'static str> {
    let source_input = fs::symlink_metadata(source).map_err(|_| "source unavailable")?;
    if inventory::linked(&source_input) {
        return Err("linked source root unsupported");
    }
    let source = fs::canonicalize(source).map_err(|_| "source unavailable")?;
    if !source.is_dir() {
        return Err("source must be a directory");
    }
    let leaf = destination.file_name().ok_or("invalid destination name")?;
    if destination
        .components()
        .any(|c| matches!(c, std::path::Component::ParentDir))
    {
        return Err("destination parent traversal unsupported");
    }
    let parent = fs::canonicalize(
        destination
            .parent()
            .ok_or("destination parent unavailable")?,
    )
    .map_err(|_| "destination parent unavailable")?;
    if !parent.is_dir() {
        return Err("destination parent must be a directory");
    }
    let destination = parent.join(leaf);
    if source.to_str().is_none() || destination.to_str().is_none() {
        return Err("copy root path representation unsupported");
    }
    if destination.starts_with(&source) || source.starts_with(&destination) {
        return Err("source and destination overlap");
    }
    match fs::symlink_metadata(&destination) {
        Ok(_) => return Err("destination already exists"),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => (),
        Err(_) => return Err("destination unavailable"),
    }
    static COUNT: AtomicU64 = AtomicU64::new(0);
    let mut chosen = None;
    for _ in 0..3 {
        let suffix = COUNT.fetch_add(1, Ordering::Relaxed);
        let time = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_err(|_| "clock unavailable")?
            .as_nanos();
        let stage = parent.join(format!(
            ".world-copy-{}-{time}-{suffix}",
            std::process::id()
        ));
        match fs::create_dir(&stage) {
            Ok(()) => {
                chosen = Some(stage);
                break;
            }
            Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => continue,
            Err(_) => return Err("staging creation failed"),
        }
    }
    let stage = chosen.ok_or("staging name collision")?;
    let payload = stage.join("payload");
    let run = Run {
        source,
        destination,
        stage,
        payload,
        completed: Vec::new(),
        bytes: 0,
        sequence: 0,
    };
    Ok(run)
}
fn hash_file(
    mut file: File,
    max: u64,
    observer: &mut impl FnMut(Progress) -> Control,
    files: usize,
) -> Result<(u64, String), &'static str> {
    let mut bytes = 0u64;
    let mut hash = Sha256::new();
    let mut buffer = [0u8; 65536];
    loop {
        let n = file
            .read(&mut buffer)
            .map_err(|_| "verification read failed")?;
        if n == 0 {
            break;
        }
        bytes = bytes.checked_add(n as u64).ok_or("byte count overflow")?;
        if bytes > max {
            return Err("source changed or file limit exceeded");
        }
        hash.update(&buffer[..n]);
        if observer(Progress {
            phase: Phase::VerifyingFile,
            files,
            bytes,
        }) == Control::Cancel
        {
            return Err("cancelled");
        }
    }
    Ok((bytes, format!("{:x}", hash.finalize())))
}
fn validate_level(root: &Path) -> Result<(), &'static str> {
    let mut file = open_checked(root, Path::new("level.dat"))?;
    let before = stamp(&file)?;
    let limits = crate::nbt::Limits::default();
    if before.length > limits.bytes as u64 {
        return Err("level.dat byte limit exceeded");
    }
    let mut bytes = Vec::new();
    (&mut file)
        .take(limits.bytes as u64 + 1)
        .read_to_end(&mut bytes)
        .map_err(|_| "level.dat read failed")?;
    if stamp(&file)? != before {
        return Err("source changed during level validation");
    }
    crate::world::probe_compressed(&bytes, limits).map_err(|_| "invalid level.dat")?;
    Ok(())
}
fn copy_entry(
    run: &mut Run,
    entry: &Entry,
    observer: &mut impl FnMut(Progress) -> Control,
) -> Result<(), &'static str> {
    let target = run.payload.join(&entry.path);
    if entry.directory {
        if !entry.path.as_os_str().is_empty() {
            fs::create_dir(&target).map_err(|_| "staging directory creation failed")?;
        }
        return Ok(());
    }
    let mut input = open_checked(&run.source, &entry.path)?;
    if stamp(&input)? != entry.stamp {
        return Err("source changed before copy");
    }
    let mut output = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&target)
        .map_err(|_| "staging file creation failed")?;
    let mut hash = Sha256::new();
    let mut copied = 0u64;
    let mut buffer = [0u8; 65536];
    loop {
        let n = input.read(&mut buffer).map_err(|_| "source read failed")?;
        if n == 0 {
            break;
        }
        copied = copied.checked_add(n as u64).ok_or("byte count overflow")?;
        if copied > entry.stamp.length {
            return Err("source changed during copy");
        }
        output
            .write_all(&buffer[..n])
            .map_err(|_| "staging write failed")?;
        hash.update(&buffer[..n]);
        if observer(Progress {
            phase: Phase::CopyingFile,
            files: run.completed.len(),
            bytes: run.bytes + copied,
        }) == Control::Cancel
        {
            return Err("cancelled");
        }
    }
    if copied != entry.stamp.length || stamp(&input)? != entry.stamp {
        return Err("source changed during copy");
    }
    output.sync_all().map_err(|_| "staging sync failed")?;
    run.bytes = run.bytes.checked_add(copied).ok_or("byte count overflow")?;
    run.completed.push(Completed {
        path: entry.path.clone(),
        bytes: copied,
        sha256: format!("{:x}", hash.finalize()),
    });
    Ok(())
}
/// Copy only a caller-selected stable snapshot. The observer can cancel at
/// deterministic boundaries; it must not mutate source or owned staging.
pub fn build(
    source: &Path,
    destination: &Path,
    limits: CopyLimits,
    observer: &mut impl FnMut(Progress) -> Control,
) -> Result<CopyReceipt, CopyFailure> {
    if limits.max_entries == 0
        || limits.max_entries > 100000
        || limits.max_depth > 128
        || limits.max_file_bytes > 512 * 1024 * 1024 * 1024
        || limits.max_bytes > 1024 * 1024 * 1024 * 1024
    {
        return Err(CopyFailure {
            reason: "invalid copy limits",
            staging: None,
            recovery_recorded: false,
        });
    }
    let mut run = setup(source, destination).map_err(|reason| CopyFailure {
        reason,
        staging: None,
        recovery_recorded: false,
    })?;
    if !run.record("created", None) {
        return Err(run.failed("initial recovery record failed"));
    }
    let perform = (|| {
        let before = inventory(&run.source, limits)?;
        if observer(Progress {
            phase: Phase::InventoryReady,
            files: 0,
            bytes: 0,
        }) == Control::Cancel
        {
            return Err("cancelled");
        }
        validate_level(&run.source).map_err(|_| "invalid source level.dat")?;
        fs::create_dir(&run.payload).map_err(|_| "payload creation failed")?;
        for entry in &before {
            copy_entry(&mut run, entry, observer)?;
            if !entry.directory
                && observer(Progress {
                    phase: Phase::FileCopied,
                    files: run.completed.len(),
                    bytes: run.bytes,
                }) == Control::Cancel
            {
                return Err("cancelled");
            }
        }
        if observer(Progress {
            phase: Phase::BeforePublish,
            files: run.completed.len(),
            bytes: run.bytes,
        }) == Control::Cancel
        {
            return Err("cancelled");
        }
        if inventory(&run.source, limits)? != before {
            return Err("source inventory changed");
        }
        for completed in &run.completed {
            let source_file = open_checked(&run.source, &completed.path)?;
            let (bytes, hash) =
                hash_file(source_file, completed.bytes, observer, run.completed.len())?;
            if bytes != completed.bytes || hash != completed.sha256 {
                return Err("source content changed");
            }
            let file = open_checked(&run.payload, &completed.path)?;
            let (bytes, hash) = hash_file(file, completed.bytes, observer, run.completed.len())?;
            if bytes != completed.bytes || hash != completed.sha256 {
                return Err("staging verification failed");
            }
        }
        if inventory(&run.source, limits)? != before {
            return Err("source inventory changed");
        }
        validate_level(&run.payload).map_err(|_| "copied level.dat invalid")?;
        if !run.record("verified", None) {
            return Err("verified recovery record failed");
        }
        // A final observed inventory check follows the cancellation boundary.
        if inventory(&run.source, limits)? != before {
            return Err("source inventory changed");
        }
        let staged = inventory(&run.payload, limits)?;
        if !staged
            .iter()
            .map(|e| {
                (
                    &e.path,
                    e.directory,
                    if e.directory { 0 } else { e.stamp.length },
                )
            })
            .eq(before.iter().map(|e| {
                (
                    &e.path,
                    e.directory,
                    if e.directory { 0 } else { e.stamp.length },
                )
            }))
        {
            return Err("staging inventory changed");
        }
        publish::no_replace(&run.payload, &run.destination)
            .map_err(|_| "destination publication failed")?;
        Ok(())
    })();
    if let Err(reason) = perform {
        return Err(run.failed(reason));
    }
    let recorded = run.record("published", None);
    Ok(CopyReceipt {
        destination: run.destination,
        staging: run.stage,
        files: run.completed.len(),
        bytes: run.bytes,
        final_recovery_recorded: recorded,
    })
}
#[cfg(test)]
mod tests;
