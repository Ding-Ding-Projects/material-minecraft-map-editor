use std::path::Path;
/// The kernel must reject an existing destination, including an empty directory.
pub(super) fn no_replace(source: &Path, destination: &Path) -> std::io::Result<()> {
    #[cfg(windows)]
    {
        use std::os::windows::ffi::OsStrExt;
        #[link(name = "kernel32")]
        extern "system" {
            fn MoveFileExW(source: *const u16, destination: *const u16, flags: u32) -> i32;
        }
        let source: Vec<u16> = source.as_os_str().encode_wide().chain(Some(0)).collect();
        let destination: Vec<u16> = destination
            .as_os_str()
            .encode_wide()
            .chain(Some(0))
            .collect();
        if source[..source.len() - 1].contains(&0)
            || destination[..destination.len() - 1].contains(&0)
        {
            return Err(std::io::ErrorKind::InvalidInput.into());
        }
        // SAFETY: both pointers name live NUL-terminated UTF-16 arrays. Flags zero
        // deliberately omit replacement and cross-volume copy options.
        if unsafe { MoveFileExW(source.as_ptr(), destination.as_ptr(), 0) } == 0 {
            return Err(std::io::Error::last_os_error());
        }
        Ok(())
    }
    #[cfg(target_os = "linux")]
    {
        use std::ffi::CString;
        use std::os::unix::ffi::OsStrExt;
        extern "C" {
            fn renameat2(
                oldfd: i32,
                old: *const std::ffi::c_char,
                newfd: i32,
                new: *const std::ffi::c_char,
                flags: u32,
            ) -> i32;
        }
        let source = CString::new(source.as_os_str().as_bytes())
            .map_err(|_| std::io::ErrorKind::InvalidInput)?;
        let destination = CString::new(destination.as_os_str().as_bytes())
            .map_err(|_| std::io::ErrorKind::InvalidInput)?;
        // SAFETY: live C strings, AT_FDCWD, and the documented RENAME_NOREPLACE flag.
        if unsafe { renameat2(-100, source.as_ptr(), -100, destination.as_ptr(), 1) } != 0 {
            return Err(std::io::Error::last_os_error());
        }
        Ok(())
    }
    #[cfg(not(any(windows, target_os = "linux")))]
    {
        let _ = (source, destination);
        Err(std::io::ErrorKind::Unsupported.into())
    }
}
