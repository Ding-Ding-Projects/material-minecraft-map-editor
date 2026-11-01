//! Private-from-creation output ACLs and fail-closed source protection checks.
#[cfg(not(windows))]
use std::{
    fs::{File, Metadata},
    path::Path,
};
#[cfg(windows)]
mod windows;
#[cfg(windows)]
pub(super) use windows::{private_dir, private_file, source_safe, verify_private};
#[cfg(not(windows))]
pub(super) fn private_dir(_: &Path) -> std::io::Result<()> {
    Err(std::io::ErrorKind::Unsupported.into())
}
#[cfg(not(windows))]
pub(super) fn private_file(_: &Path) -> std::io::Result<File> {
    Err(std::io::ErrorKind::Unsupported.into())
}
#[cfg(not(windows))]
pub(super) fn verify_private(_: &Path) -> Result<(), &'static str> {
    Err("private ACL verification unsupported")
}
#[cfg(not(windows))]
pub(super) fn source_safe(_: &Path, _: &Metadata) -> Result<(), &'static str> {
    Err("source protection inspection unsupported")
}
