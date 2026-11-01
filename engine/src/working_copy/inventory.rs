use super::CopyLimits;
use std::{
    fs::{self, File, Metadata, OpenOptions},
    path::{Path, PathBuf},
    time::SystemTime,
};
#[derive(Clone, Debug, PartialEq, Eq)]
pub(super) struct Stamp {
    pub length: u64,
    modified: SystemTime,
    identity: (u64, u64),
    change: (i64, i64),
    attributes: u32,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub(super) struct Entry {
    pub path: PathBuf,
    pub directory: bool,
    pub stamp: Stamp,
}
pub(super) fn linked(metadata: &Metadata) -> bool {
    if metadata.file_type().is_symlink() {
        return true;
    }
    #[cfg(windows)]
    {
        use std::os::windows::fs::MetadataExt;
        return metadata.file_attributes() & 0x400 != 0;
    }
    #[cfg(not(windows))]
    {
        false
    }
}
pub(super) fn open_checked(root: &Path, relative: &Path) -> Result<File, &'static str> {
    let path = root.join(relative);
    let metadata = fs::symlink_metadata(&path).map_err(|_| "source entry unavailable")?;
    if linked(&metadata) || (!metadata.is_file() && !metadata.is_dir()) {
        return Err("linked or nonregular source entry");
    }
    super::security::source_safe(&path, &metadata)?;
    let resolved = fs::canonicalize(&path).map_err(|_| "source entry unavailable")?;
    if !resolved.starts_with(root) {
        return Err("source entry escapes root");
    }
    let mut options = OpenOptions::new();
    options.read(true);
    #[cfg(windows)]
    {
        use std::os::windows::fs::OpenOptionsExt;
        options.custom_flags(0x00200000 | 0x02000000);
    }
    #[cfg(target_os = "linux")]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.custom_flags(0x20000);
    }
    let file = options
        .open(&path)
        .map_err(|_| "source entry open failed")?;
    let metadata = file
        .metadata()
        .map_err(|_| "source entry metadata failed")?;
    if linked(&metadata) || (!metadata.is_file() && !metadata.is_dir()) {
        return Err("linked or nonregular source entry");
    }
    super::security::source_safe(&path, &metadata)?;
    stamp(&file)?;
    Ok(file)
}
#[cfg(windows)]
fn windows_identity(file: &File) -> Result<((u64, u64), u32), &'static str> {
    use std::os::windows::io::AsRawHandle;
    #[repr(C)]
    struct Time {
        low: u32,
        high: u32,
    }
    #[repr(C)]
    struct Info {
        attributes: u32,
        creation: Time,
        access: Time,
        write: Time,
        volume: u32,
        size_high: u32,
        size_low: u32,
        links: u32,
        index_high: u32,
        index_low: u32,
    }
    #[link(name = "kernel32")]
    extern "system" {
        fn GetFileInformationByHandle(handle: *mut std::ffi::c_void, info: *mut Info) -> i32;
    }
    let mut info: Info = unsafe { std::mem::zeroed() };
    // SAFETY: the live File owns the handle and Info has the documented C layout.
    if unsafe { GetFileInformationByHandle(file.as_raw_handle(), &mut info) } == 0 {
        return Err("source identity unavailable");
    }
    Ok((
        (
            info.volume as u64,
            ((info.index_high as u64) << 32) | info.index_low as u64,
        ),
        info.links,
    ))
}
pub(super) fn stamp(file: &File) -> Result<Stamp, &'static str> {
    let m = file
        .metadata()
        .map_err(|_| "source entry metadata failed")?;
    let modified = m
        .modified()
        .map_err(|_| "source modification time unavailable")?;
    #[cfg(windows)]
    {
        use std::os::windows::fs::MetadataExt;
        let (identity, links) = windows_identity(file)?;
        if m.is_file() && links != 1 {
            return Err("hard-linked source files unsupported");
        }
        Ok(Stamp {
            length: m.len(),
            modified,
            identity,
            change: (0, 0),
            attributes: m.file_attributes(),
        })
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        if m.is_file() && m.nlink() != 1 {
            return Err("hard-linked source files unsupported");
        }
        Ok(Stamp {
            length: m.len(),
            modified,
            identity: (m.dev(), m.ino()),
            change: (m.ctime(), m.ctime_nsec()),
            attributes: m.mode(),
        })
    }
    #[cfg(not(any(windows, unix)))]
    {
        let _ = modified;
        Err("source identity unsupported on this platform")
    }
}
fn charge_record_budget(left: &mut usize, path: &Path) -> Result<(), &'static str> {
    let cost = path
        .to_str()
        .ok_or("source path representation unsupported")?
        .len()
        .checked_mul(6)
        .and_then(|n| n.checked_add(256))
        .ok_or("source recovery inventory budget exceeded")?;
    *left = left
        .checked_sub(cost)
        .ok_or("source recovery inventory budget exceeded")?;
    Ok(())
}
pub(super) fn inventory(root: &Path, limits: CopyLimits) -> Result<Vec<Entry>, &'static str> {
    fn walk(
        root: &Path,
        relative: PathBuf,
        depth: usize,
        limits: CopyLimits,
        left: &mut usize,
        bytes: &mut u64,
        record_budget: &mut usize,
        entries: &mut Vec<Entry>,
    ) -> Result<(), &'static str> {
        if depth > limits.max_depth {
            return Err("source depth limit exceeded");
        }
        if relative.to_str().is_none() || relative.as_os_str().len() > 32768 {
            return Err("source path representation unsupported");
        }
        charge_record_budget(record_budget, &relative)?;
        let file = open_checked(root, &relative)?;
        let m = file
            .metadata()
            .map_err(|_| "source entry metadata failed")?;
        let record = stamp(&file)?;
        let directory = m.is_dir();
        if !directory {
            if record.length > limits.max_file_bytes {
                return Err("source file byte limit exceeded");
            }
            *bytes = bytes
                .checked_add(record.length)
                .ok_or("source byte count overflow")?;
            if *bytes > limits.max_bytes {
                return Err("source total byte limit exceeded");
            }
        }
        entries.push(Entry {
            path: relative.clone(),
            directory,
            stamp: record,
        });
        if directory {
            let mut children = Vec::new();
            for child in
                fs::read_dir(root.join(&relative)).map_err(|_| "source directory read failed")?
            {
                *left = left.checked_sub(1).ok_or("source entry limit exceeded")?;
                children.push(
                    child
                        .map_err(|_| "source directory read failed")?
                        .file_name(),
                );
            }
            children.sort();
            for name in children {
                walk(
                    root,
                    relative.join(name),
                    depth + 1,
                    limits,
                    left,
                    bytes,
                    record_budget,
                    entries,
                )?;
            }
        }
        Ok(())
    }
    let mut entries = Vec::new();
    let mut left = limits
        .max_entries
        .checked_sub(1)
        .ok_or("source entry limit exceeded")?;
    walk(
        root,
        PathBuf::new(),
        0,
        limits,
        &mut left,
        &mut 0,
        &mut (super::MANIFEST_LIMIT / 2),
        &mut entries,
    )?;
    Ok(entries)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn recovery_inventory_cost_stops_before_allocating_more_records() {
        let mut left = 256;
        assert!(charge_record_budget(&mut left, Path::new("")).is_ok());
        assert!(charge_record_budget(&mut left, Path::new("next")).is_err());
    }
}
