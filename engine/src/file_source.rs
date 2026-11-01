//! Bounded stable read handles for explicit reference and terrain inputs.
use sha2::{Digest, Sha256};
use std::{
    fs::{self, File, OpenOptions},
    io::{Read, Seek, SeekFrom},
    path::{Path, PathBuf},
};
#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct Stamp {
    pub volume: u64,
    pub id: [u8; 16],
    pub bytes: u64,
    pub last_write: u64,
    creation: u64,
    change: i64,
    attributes: u32,
}
pub(crate) struct Source {
    root: PathBuf,
    relative: PathBuf,
    pub file: File,
    pub stamp: Stamp,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum Error {
    Missing,
    Escape,
    Nonregular,
    Linked,
    Budget,
    Changed,
    Identity,
    Io,
    Timeout,
}
#[cfg(windows)]
fn stamp(file: &File) -> Result<Stamp, Error> {
    use std::os::windows::{fs::MetadataExt, io::AsRawHandle};
    #[repr(C)]
    struct Id {
        volume: u64,
        id: [u8; 16],
    }
    #[link(name = "kernel32")]
    extern "system" {
        fn GetFileInformationByHandleEx(
            handle: *mut std::ffi::c_void,
            class: i32,
            info: *mut std::ffi::c_void,
            size: u32,
        ) -> i32;
    }
    let mut id = Id {
        volume: 0,
        id: [0; 16],
    };
    // SAFETY: File owns a live handle and Id matches FILE_ID_INFO (class 18).
    if unsafe {
        GetFileInformationByHandleEx(
            file.as_raw_handle(),
            18,
            (&mut id as *mut Id).cast(),
            std::mem::size_of::<Id>() as u32,
        )
    } == 0
    {
        return Err(Error::Identity);
    }
    #[repr(C)]
    struct Basic {
        creation: i64,
        access: i64,
        write: i64,
        change: i64,
        attributes: u32,
    }
    let mut basic = Basic {
        creation: 0,
        access: 0,
        write: 0,
        change: 0,
        attributes: 0,
    };
    // SAFETY: Basic matches FILE_BASIC_INFO and the live buffer has its exact size.
    if unsafe {
        GetFileInformationByHandleEx(
            file.as_raw_handle(),
            0,
            (&mut basic as *mut Basic).cast(),
            std::mem::size_of::<Basic>() as u32,
        )
    } == 0
    {
        return Err(Error::Identity);
    }
    let m = file.metadata().map_err(|_| Error::Io)?;
    if !m.is_file() {
        return Err(Error::Nonregular);
    }
    if m.file_attributes() & 0x400 != 0 {
        return Err(Error::Linked);
    }
    Ok(Stamp {
        volume: id.volume,
        id: id.id,
        bytes: m.len(),
        last_write: m.last_write_time(),
        creation: m.creation_time(),
        change: basic.change,
        attributes: m.file_attributes(),
    })
}
#[cfg(not(windows))]
fn stamp(_: &File) -> Result<Stamp, Error> {
    Err(Error::Identity)
}
impl Source {
    pub fn open(root: &Path, relative: &Path, max: u64) -> Result<Self, Error> {
        if relative.is_absolute()
            || relative
                .components()
                .any(|c| !matches!(c, std::path::Component::Normal(_)))
        {
            return Err(Error::Escape);
        }
        let path = root.join(relative);
        let mut parent = path.parent().ok_or(Error::Escape)?;
        loop {
            match fs::canonicalize(parent) {
                Ok(actual) => {
                    if !actual.starts_with(root) {
                        return Err(Error::Escape);
                    }
                    break;
                }
                Err(e) if e.kind() == std::io::ErrorKind::NotFound => {
                    parent = parent.parent().ok_or(Error::Escape)?
                }
                Err(_) => return Err(Error::Io),
            }
        }

        let m = fs::symlink_metadata(&path).map_err(|e| {
            if e.kind() == std::io::ErrorKind::NotFound {
                Error::Missing
            } else {
                Error::Io
            }
        })?;
        if m.file_type().is_symlink() {
            return Err(Error::Linked);
        }
        if !m.is_file() {
            return Err(Error::Nonregular);
        }
        if m.len() > max {
            return Err(Error::Budget);
        }
        #[cfg(windows)]
        {
            use std::os::windows::fs::MetadataExt;
            if m.file_attributes() & 0x400 != 0 {
                return Err(Error::Linked);
            }
        }
        let actual = fs::canonicalize(&path).map_err(|_| Error::Io)?;
        if !actual.starts_with(root) {
            return Err(Error::Escape);
        }
        let mut options = OpenOptions::new();
        options.read(true);
        #[cfg(windows)]
        {
            use std::os::windows::fs::OpenOptionsExt;
            options.custom_flags(0x00200000);
        }
        let file = options.open(path).map_err(|_| Error::Io)?;
        let stamp = stamp(&file)?;
        if stamp.bytes > max {
            return Err(Error::Budget);
        }
        Ok(Self {
            root: root.into(),
            relative: actual
                .strip_prefix(root)
                .map_err(|_| Error::Escape)?
                .to_path_buf(),
            file,
            stamp,
        })
    }
    pub fn relative_path(&self) -> Result<String, Error> {
        let text = self
            .relative
            .to_str()
            .ok_or(Error::Escape)?
            .replace('\\', "/");
        if text.len() > 4096 {
            return Err(Error::Escape);
        }
        Ok(text)
    }
    pub fn verify(&self) -> Result<(), Error> {
        if stamp(&self.file)? != self.stamp {
            return Err(Error::Changed);
        }
        let other =
            Self::open(&self.root, &self.relative, self.stamp.bytes).map_err(|_| Error::Changed)?;
        if other.stamp != self.stamp {
            return Err(Error::Changed);
        }
        Ok(())
    }
    pub fn read_at(&mut self, offset: u64, length: usize) -> Result<Vec<u8>, Error> {
        if offset
            .checked_add(length as u64)
            .is_none_or(|end| end > self.stamp.bytes)
        {
            return Err(Error::Budget);
        }
        self.file
            .seek(SeekFrom::Start(offset))
            .map_err(|_| Error::Io)?;
        let mut bytes = Vec::new();
        bytes.try_reserve_exact(length).map_err(|_| Error::Budget)?;
        bytes.resize(length, 0);
        self.file
            .read_exact(&mut bytes)
            .map_err(|_| Error::Changed)?;
        Ok(bytes)
    }
    pub fn hash(&mut self, deadline: Option<std::time::Instant>) -> Result<[u8; 32], Error> {
        self.file.seek(SeekFrom::Start(0)).map_err(|_| Error::Io)?;
        let mut hash = Sha256::new();
        let mut read = 0u64;
        let mut buffer = [0u8; 65536];
        loop {
            if deadline.is_some_and(|d| std::time::Instant::now() >= d) {
                return Err(Error::Timeout);
            }
            let n = self.file.read(&mut buffer).map_err(|_| Error::Io)?;
            if n == 0 {
                break;
            }
            read = read.checked_add(n as u64).ok_or(Error::Budget)?;
            if read > self.stamp.bytes {
                return Err(Error::Changed);
            }
            hash.update(&buffer[..n]);
        }
        if read != self.stamp.bytes {
            return Err(Error::Changed);
        }
        self.verify()?;
        Ok(hash.finalize().into())
    }
    pub fn pinned(root: &Path, relative: &Path, size: usize, hash: &str) -> Result<Vec<u8>, Error> {
        let mut file = Self::open(root, relative, size as u64)?;
        if file.stamp.bytes != size as u64 {
            return Err(Error::Budget);
        }
        let mut data = Vec::with_capacity(size + 1);
        (&mut file.file)
            .take(size as u64 + 1)
            .read_to_end(&mut data)
            .map_err(|_| Error::Io)?;
        if data.len() != size {
            return Err(Error::Changed);
        }
        file.verify()?;
        if format!("{:x}", Sha256::digest(&data)) != hash {
            return Err(Error::Changed);
        }
        Ok(data)
    }
}

#[cfg(all(test, windows))]
mod tests {
    use super::*;
    #[test]
    fn bounded_reads_identity_and_change_evidence() {
        let root = std::env::temp_dir().join(format!(
            "source-read-test-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        fs::create_dir(&root).unwrap();
        let root = fs::canonicalize(root).unwrap();
        fs::write(root.join("input"), b"abcdef").unwrap();
        let mut source = Source::open(&root, Path::new("input"), 6).unwrap();
        assert_eq!(source.read_at(2, 3).unwrap(), b"cde");
        assert!(source.read_at(5, 2).is_err());
        assert_eq!(
            source.hash(None).unwrap(),
            <[u8; 32]>::from(Sha256::digest(b"abcdef"))
        );
        fs::write(root.join("input"), b"changed").unwrap();
        assert_eq!(source.verify(), Err(Error::Changed));
        drop(source);
        fs::remove_file(root.join("input")).unwrap();
        fs::remove_dir(root).unwrap();
    }
}
