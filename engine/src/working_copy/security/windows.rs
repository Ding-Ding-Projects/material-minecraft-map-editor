use std::{
    ffi::c_void,
    fs::{File, Metadata},
    os::windows::{ffi::OsStrExt, fs::MetadataExt, io::FromRawHandle},
    path::Path,
    ptr,
};
type Handle = *mut c_void;
#[repr(C)]
struct Attributes {
    length: u32,
    descriptor: *mut c_void,
    inherit: i32,
}
#[repr(C)]
struct AclSize {
    count: u32,
    used: u32,
    free: u32,
}
#[repr(C)]
struct StreamData {
    size: i64,
    name: [u16; 296],
}
#[link(name = "kernel32")]
extern "system" {
    fn GetCurrentProcess() -> Handle;
    fn CloseHandle(h: Handle) -> i32;
    fn LocalFree(p: *mut c_void) -> *mut c_void;
    fn CreateDirectoryW(path: *const u16, attributes: *const Attributes) -> i32;
    fn CreateFileW(
        path: *const u16,
        access: u32,
        share: u32,
        attributes: *const Attributes,
        creation: u32,
        flags: u32,
        template: Handle,
    ) -> Handle;
    fn FindFirstStreamW(path: *const u16, level: u32, data: *mut StreamData, flags: u32) -> Handle;
    fn FindNextStreamW(h: Handle, data: *mut StreamData) -> i32;
    fn FindClose(h: Handle) -> i32;
    fn GetLastError() -> u32;
}
#[link(name = "advapi32")]
extern "system" {
    fn OpenProcessToken(process: Handle, access: u32, token: *mut Handle) -> i32;
    fn GetTokenInformation(
        token: Handle,
        class: u32,
        info: *mut c_void,
        length: u32,
        returned: *mut u32,
    ) -> i32;
    fn ConvertSidToStringSidW(sid: *const c_void, text: *mut *mut u16) -> i32;
    fn ConvertStringSecurityDescriptorToSecurityDescriptorW(
        text: *const u16,
        revision: u32,
        descriptor: *mut *mut c_void,
        size: *mut u32,
    ) -> i32;
    fn GetNamedSecurityInfoW(
        path: *const u16,
        kind: u32,
        info: u32,
        owner: *mut *mut c_void,
        group: *mut *mut c_void,
        dacl: *mut *mut c_void,
        sacl: *mut *mut c_void,
        descriptor: *mut *mut c_void,
    ) -> u32;
    fn GetSecurityDescriptorControl(
        descriptor: *const c_void,
        control: *mut u16,
        revision: *mut u32,
    ) -> i32;
    fn GetAclInformation(acl: *const c_void, info: *mut AclSize, size: u32, class: u32) -> i32;
    fn GetAce(acl: *const c_void, index: u32, ace: *mut *mut c_void) -> i32;
}
struct Local(*mut c_void);
impl Drop for Local {
    fn drop(&mut self) {
        unsafe {
            LocalFree(self.0);
        }
    }
}
struct Token(Handle);
impl Drop for Token {
    fn drop(&mut self) {
        unsafe {
            CloseHandle(self.0);
        }
    }
}
fn wide(path: &Path) -> std::io::Result<Vec<u16>> {
    let v = path
        .as_os_str()
        .encode_wide()
        .chain(Some(0))
        .collect::<Vec<_>>();
    if v[..v.len() - 1].contains(&0) {
        return Err(std::io::ErrorKind::InvalidInput.into());
    }
    Ok(v)
}
fn sid_text(sid: *const c_void) -> std::io::Result<String> {
    let mut text = ptr::null_mut();
    if unsafe { ConvertSidToStringSidW(sid, &mut text) } == 0 {
        return Err(std::io::Error::last_os_error());
    }
    let _owned = Local(text.cast());
    let mut length = 0;
    while length < 256 && unsafe { *text.add(length) } != 0 {
        length += 1;
    }
    if length == 256 {
        return Err(std::io::ErrorKind::InvalidData.into());
    }
    String::from_utf16(unsafe { std::slice::from_raw_parts(text, length) })
        .map_err(|_| std::io::ErrorKind::InvalidData.into())
}
fn user_sid() -> std::io::Result<String> {
    let mut token = ptr::null_mut();
    if unsafe { OpenProcessToken(GetCurrentProcess(), 8, &mut token) } == 0 {
        return Err(std::io::Error::last_os_error());
    }
    let _token = Token(token);
    let mut needed = 0;
    unsafe {
        GetTokenInformation(token, 1, ptr::null_mut(), 0, &mut needed);
    }
    if needed == 0 || needed > 65536 {
        return Err(std::io::ErrorKind::InvalidData.into());
    }
    let mut buffer = vec![0usize; (needed as usize).div_ceil(std::mem::size_of::<usize>())];
    if unsafe { GetTokenInformation(token, 1, buffer.as_mut_ptr().cast(), needed, &mut needed) }
        == 0
    {
        return Err(std::io::Error::last_os_error());
    }
    let sid = unsafe { ptr::read_unaligned(buffer.as_ptr().cast::<*const c_void>()) };
    sid_text(sid)
}
fn descriptor() -> std::io::Result<Local> {
    let user = user_sid()?;
    let sddl = format!("O:{user}D:P(A;OICI;FA;;;{user})(A;OICI;FA;;;SY)");
    let text = sddl.encode_utf16().chain(Some(0)).collect::<Vec<_>>();
    let mut raw = ptr::null_mut();
    if unsafe {
        ConvertStringSecurityDescriptorToSecurityDescriptorW(
            text.as_ptr(),
            1,
            &mut raw,
            ptr::null_mut(),
        )
    } == 0
    {
        return Err(std::io::Error::last_os_error());
    }
    Ok(Local(raw))
}
fn attributes(sd: &Local) -> Attributes {
    Attributes {
        length: std::mem::size_of::<Attributes>() as u32,
        descriptor: sd.0,
        inherit: 0,
    }
}
pub(in crate::working_copy) fn private_dir(path: &Path) -> std::io::Result<()> {
    let path = wide(path)?;
    let sd = descriptor()?;
    if unsafe { CreateDirectoryW(path.as_ptr(), &attributes(&sd)) } == 0 {
        return Err(std::io::Error::last_os_error());
    }
    Ok(())
}
pub(in crate::working_copy) fn private_file(path: &Path) -> std::io::Result<File> {
    let path = wide(path)?;
    let sd = descriptor()?;
    let handle = unsafe {
        CreateFileW(
            path.as_ptr(),
            0x40000000,
            7,
            &attributes(&sd),
            1,
            0x80,
            ptr::null_mut(),
        )
    };
    if handle as isize == -1 {
        return Err(std::io::Error::last_os_error());
    }
    Ok(unsafe { File::from_raw_handle(handle) })
}
fn acl_count(acl: *const c_void) -> Result<u32, &'static str> {
    if acl.is_null() {
        return Ok(0);
    }
    let mut info = AclSize {
        count: 0,
        used: 0,
        free: 0,
    };
    if unsafe { GetAclInformation(acl, &mut info, std::mem::size_of::<AclSize>() as u32, 2) } == 0
        || info.count > 1024
    {
        return Err("ACL inspection failed");
    }
    Ok(info.count)
}
/// Read back the actual owner, protected DACL, ACE types/masks and exact SIDs.
pub(in crate::working_copy) fn verify_private(path: &Path) -> Result<(), &'static str> {
    let user = user_sid().map_err(|_| "current-user identity unavailable")?;
    let path = wide(path).map_err(|_| "ACL path unsupported")?;
    let (mut owner, mut dacl, mut raw) = (ptr::null_mut(), ptr::null_mut(), ptr::null_mut());
    let result = unsafe {
        GetNamedSecurityInfoW(
            path.as_ptr(),
            1,
            1 | 4,
            &mut owner,
            ptr::null_mut(),
            &mut dacl,
            ptr::null_mut(),
            &mut raw,
        )
    };
    if result != 0 {
        return Err("private ACL readback failed");
    }
    let _descriptor = Local(raw);
    if owner.is_null()
        || dacl.is_null()
        || sid_text(owner).map_err(|_| "owner SID unavailable")? != user
    {
        return Err("private owner or DACL mismatch");
    }
    let (mut control, mut revision) = (0, 0);
    if unsafe { GetSecurityDescriptorControl(raw, &mut control, &mut revision) } == 0
        || control & 0x1000 == 0
    {
        return Err("output DACL is not protected");
    }
    let count = acl_count(dacl)?;
    if count != 2 {
        return Err("unexpected output ACL principals");
    }
    let (mut current, mut system) = (false, false);
    for index in 0..count {
        let mut ace = ptr::null_mut();
        if unsafe { GetAce(dacl, index, &mut ace) } == 0 || ace.is_null() {
            return Err("output ACE unavailable");
        }
        let bytes = ace.cast::<u8>();
        let kind = unsafe { *bytes };
        let flags = unsafe { *bytes.add(1) };
        let size = unsafe { ptr::read_unaligned(bytes.add(2).cast::<u16>()) };
        if kind != 0 || flags & !0x13 != 0 || size < 12 {
            return Err("unexpected output ACE");
        }
        let mask = unsafe { ptr::read_unaligned(bytes.add(4).cast::<u32>()) };
        if mask != 0x1f01ff {
            return Err("unexpected output access rights");
        }
        let sid = sid_text(unsafe { bytes.add(8) }.cast()).map_err(|_| "output SID unavailable")?;
        if sid == user {
            current = true;
        } else if sid != "S-1-5-18" {
            return Err("unexpected output ACL principal");
        }
        if sid == "S-1-5-18" {
            system = true;
        }
    }
    if !current || !system {
        return Err("required private ACL principals missing");
    }
    Ok(())
}
fn reject_attributes(attributes: u32) -> Result<(), &'static str> {
    if attributes & 0x4000 != 0 {
        return Err("encrypted source entries unsupported");
    }
    Ok(())
}
pub(in crate::working_copy) fn source_safe(
    path: &Path,
    metadata: &Metadata,
) -> Result<(), &'static str> {
    reject_attributes(metadata.file_attributes())?;
    let path = wide(path).map_err(|_| "source security path unsupported")?;
    let mut data: StreamData = unsafe { std::mem::zeroed() };
    let handle = unsafe { FindFirstStreamW(path.as_ptr(), 0, &mut data, 0) };
    if handle as isize == -1 {
        if unsafe { GetLastError() } != 38 {
            return Err("source stream inspection unavailable");
        }
    } else {
        let result = (|| {
            for _ in 0..1024 {
                let end = data
                    .name
                    .iter()
                    .position(|n| *n == 0)
                    .ok_or("invalid source stream metadata")?;
                let name = String::from_utf16(&data.name[..end])
                    .map_err(|_| "invalid source stream metadata")?;
                if name != "::$DATA" {
                    return Err("named streams and security-origin metadata unsupported");
                }
                if unsafe { FindNextStreamW(handle, &mut data) } == 0 {
                    return if unsafe { GetLastError() } == 38 {
                        Ok(())
                    } else {
                        Err("source stream inspection failed")
                    };
                }
            }
            Err("source stream count limit exceeded")
        })();
        unsafe {
            FindClose(handle);
        }
        result?;
    }
    let (mut sacl, mut raw) = (ptr::null_mut(), ptr::null_mut());
    if unsafe {
        GetNamedSecurityInfoW(
            path.as_ptr(),
            1,
            0x10 | 0x20 | 0x40,
            ptr::null_mut(),
            ptr::null_mut(),
            ptr::null_mut(),
            &mut sacl,
            &mut raw,
        )
    } != 0
    {
        return Err("source security-label inspection unavailable");
    }
    let _descriptor = Local(raw);
    if acl_count(sacl)? > 0 {
        return Err("explicit source security labels unsupported");
    }
    Ok(())
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn encrypted_attribute_is_rejected_without_decrypting() {
        assert!(reject_attributes(0x4000).is_err());
        assert!(reject_attributes(0x80).is_ok());
    }
}
