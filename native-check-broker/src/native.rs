//! Probe-only supervisor. Never route untrusted request argv into this module.
//! Restricted tokens/Jobs here do NOT establish complete OS isolation.
use sha2::{Digest, Sha256};
use std::{
    fs::{File, OpenOptions},
    io::{Read, Seek, SeekFrom},
    mem::{size_of, size_of_val, zeroed},
    os::windows::{
        ffi::OsStrExt,
        fs::OpenOptionsExt,
        io::{AsRawHandle, FromRawHandle},
    },
    path::{Path, PathBuf},
    ptr::{null, null_mut},
    sync::{
        Mutex,
        atomic::{AtomicBool, Ordering},
    },
    thread,
    time::{Duration, Instant},
};
use windows_sys::Win32::{
    Foundation::*,
    Security::{Authorization::*, *},
    Storage::FileSystem::*,
    System::{
        Com::CoCreateGuid,
        JobObjects::*,
        Pipes::*,
        StationsAndDesktops::*,
        SystemInformation::*,
        SystemServices::{
            PROCESS_MITIGATION_SYSTEM_CALL_DISABLE_POLICY, SE_GROUP_ENABLED, SE_GROUP_INTEGRITY,
        },
        Threading::*,
    },
};

#[derive(Debug)]
pub struct Error {
    pub operation: &'static str,
    pub win32: u32,
}
pub type Result<T> = std::result::Result<T, Error>;
fn fail(operation: &'static str) -> Error {
    Error {
        operation,
        win32: unsafe { GetLastError() },
    }
}
fn check(ok: i32, operation: &'static str) -> Result<()> {
    if ok == 0 {
        Err(fail(operation))
    } else {
        Ok(())
    }
}
fn wide(s: impl AsRef<std::ffi::OsStr>) -> Vec<u16> {
    s.as_ref().encode_wide().chain(Some(0)).collect()
}
pub struct Handle(HANDLE);
unsafe impl Send for Handle {}
impl Handle {
    fn new(h: HANDLE, op: &'static str) -> Result<Self> {
        if h.is_null() || h == INVALID_HANDLE_VALUE {
            Err(fail(op))
        } else {
            Ok(Self(h))
        }
    }
}
impl Drop for Handle {
    fn drop(&mut self) {
        unsafe {
            CloseHandle(self.0);
        }
    }
}
struct Descriptor(PSECURITY_DESCRIPTOR);
impl Descriptor {
    fn new(s: &str) -> Result<Self> {
        let mut p = null_mut();
        unsafe {
            check(
                ConvertStringSecurityDescriptorToSecurityDescriptorW(
                    wide(s).as_ptr(),
                    1,
                    &mut p,
                    null_mut(),
                ),
                "security-descriptor",
            )?;
        }
        Ok(Self(p))
    }
    fn attributes(&self) -> SECURITY_ATTRIBUTES {
        SECURITY_ATTRIBUTES {
            nLength: size_of::<SECURITY_ATTRIBUTES>() as u32,
            lpSecurityDescriptor: self.0,
            bInheritHandle: 0,
        }
    }
}
impl Drop for Descriptor {
    fn drop(&mut self) {
        unsafe {
            LocalFree(self.0);
        }
    }
}

fn token_buffer(token: HANDLE, class: TOKEN_INFORMATION_CLASS) -> Result<Vec<usize>> {
    let mut n = 0;
    unsafe {
        GetTokenInformation(token, class, null_mut(), 0, &mut n);
    }
    if n == 0 {
        return Err(fail("token-size"));
    }
    let mut data = vec![0usize; (n as usize).div_ceil(size_of::<usize>())];
    unsafe {
        check(
            GetTokenInformation(token, class, data.as_mut_ptr().cast(), n, &mut n),
            "token-information",
        )?;
    }
    Ok(data)
}
fn own_token() -> Result<Handle> {
    let mut token = null_mut();
    unsafe {
        check(
            OpenProcessToken(
                GetCurrentProcess(),
                TOKEN_QUERY | TOKEN_DUPLICATE | TOKEN_ASSIGN_PRIMARY | TOKEN_ADJUST_DEFAULT,
                &mut token,
            ),
            "open-token",
        )?;
    }
    Handle::new(token, "token")
}
pub fn own_sid() -> Result<String> {
    let token = own_token()?;
    let data = token_buffer(token.0, TokenUser)?;
    let user = unsafe { &*(data.as_ptr().cast::<TOKEN_USER>()) };
    let mut text = null_mut();
    unsafe {
        check(
            ConvertSidToStringSidW(user.User.Sid, &mut text),
            "sid-string",
        )?;
    }
    let mut len = 0;
    unsafe {
        while *text.add(len) != 0 {
            len += 1;
        }
    }
    let result = String::from_utf16_lossy(unsafe { std::slice::from_raw_parts(text, len) });
    unsafe {
        LocalFree(text.cast());
    }
    Ok(result)
}
fn sid(kind: WELL_KNOWN_SID_TYPE) -> Result<Vec<u64>> {
    let mut data = vec![0u64; 16];
    let mut size = (data.len() * 8) as u32;
    unsafe {
        check(
            CreateWellKnownSid(kind, null_mut(), data.as_mut_ptr().cast(), &mut size),
            "well-known-sid",
        )?;
    }
    Ok(data)
}
#[derive(Debug, serde::Serialize, serde::Deserialize)]
pub struct TokenFacts {
    pub restricted: bool,
    pub elevated: bool,
    pub enabled_admin: bool,
    pub low_integrity: bool,
    pub unexpected_enabled_privilege: bool,
}
impl TokenFacts {
    pub fn admissible(&self) -> bool {
        self.restricted
            && !self.elevated
            && !self.enabled_admin
            && self.low_integrity
            && !self.unexpected_enabled_privilege
    }
}
fn inspect_token(token: HANDLE) -> Result<TokenFacts> {
    let elevation = token_buffer(token, TokenElevation)?;
    let elevated =
        unsafe { (*(elevation.as_ptr().cast::<TOKEN_ELEVATION>())).TokenIsElevated != 0 };
    let admin = sid(WinBuiltinAdministratorsSid)?;
    let groups = token_buffer(token, TokenGroups)?;
    let groups = unsafe { &*(groups.as_ptr().cast::<TOKEN_GROUPS>()) };
    let groups =
        unsafe { std::slice::from_raw_parts(groups.Groups.as_ptr(), groups.GroupCount as usize) };
    let enabled_admin=groups.iter().any(|g| unsafe { EqualSid(g.Sid,admin.as_ptr().cast_mut().cast())!=0 } && g.Attributes & SE_GROUP_ENABLED as u32!=0);
    let integrity = token_buffer(token, TokenIntegrityLevel)?;
    let label = unsafe { &*(integrity.as_ptr().cast::<TOKEN_MANDATORY_LABEL>()) };
    let count = unsafe { *GetSidSubAuthorityCount(label.Label.Sid) };
    let rid = unsafe { *GetSidSubAuthority(label.Label.Sid, (count - 1) as u32) };
    let mut notify = unsafe { zeroed() };
    unsafe {
        check(
            LookupPrivilegeValueW(
                null(),
                wide("SeChangeNotifyPrivilege").as_ptr(),
                &mut notify,
            ),
            "privilege-luid",
        )?;
    }
    let privileges = token_buffer(token, TokenPrivileges)?;
    let privileges = unsafe { &*(privileges.as_ptr().cast::<TOKEN_PRIVILEGES>()) };
    let privileges = unsafe {
        std::slice::from_raw_parts(
            privileges.Privileges.as_ptr(),
            privileges.PrivilegeCount as usize,
        )
    };
    let unexpected_enabled_privilege = privileges.iter().any(|p| {
        p.Attributes & SE_PRIVILEGE_ENABLED != 0
            && (p.Luid.LowPart != notify.LowPart || p.Luid.HighPart != notify.HighPart)
    });
    Ok(TokenFacts {
        restricted: unsafe { IsTokenRestricted(token) != 0 },
        elevated,
        enabled_admin,
        low_integrity: rid == 4096,
        unexpected_enabled_privilege,
    })
}
pub fn current_token_facts() -> Result<TokenFacts> {
    let mut token = null_mut();
    unsafe {
        check(
            OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &mut token),
            "query-own-token",
        )?;
    }
    let token = Handle::new(token, "query-token")?;
    inspect_token(token.0)
}
#[cfg(test)]
fn restricted_token() -> Result<Handle> {
    restricted_token_for_desktop(None)
}
fn restricted_token_for_desktop(marker: Option<&str>) -> Result<Handle> {
    let source = own_token()?;
    let admin = sid(WinBuiltinAdministratorsSid)?;
    let disabled = SID_AND_ATTRIBUTES {
        Sid: admin.as_ptr().cast_mut().cast(),
        Attributes: 0,
    };
    let restricted = sid(WinRestrictedCodeSid)?;
    let world = sid(WinWorldSid)?;
    let users = sid(WinBuiltinUsersSid)?;
    let mut restricting: Vec<_> = [&restricted, &world, &users]
        .map(|s| SID_AND_ATTRIBUTES {
            Sid: s.as_ptr().cast_mut().cast(),
            Attributes: 0,
        })
        .into();
    let mut marker_sid = null_mut();
    if let Some(marker) = marker {
        unsafe {
            check(
                ConvertStringSidToSidW(wide(marker).as_ptr(), &mut marker_sid),
                "desktop-marker-sid",
            )?;
        }
        restricting.push(SID_AND_ATTRIBUTES {
            Sid: marker_sid,
            Attributes: 0,
        });
    }
    let mut token = null_mut();
    let created = unsafe {
        CreateRestrictedToken(
            source.0,
            DISABLE_MAX_PRIVILEGE,
            1,
            &disabled,
            0,
            null(),
            restricting.len() as u32,
            restricting.as_ptr(),
            &mut token,
        )
    };
    let create_error = if created == 0 {
        Some(fail("create-restricted-token"))
    } else {
        None
    };
    unsafe {
        if !marker_sid.is_null() {
            LocalFree(marker_sid);
        }
    }
    if let Some(error) = create_error {
        return Err(error);
    }
    let token = Handle::new(token, "restricted-token")?;
    if let Some(marker) = marker {
        // Only this new token's default for future owned objects is changed.
        // Existing host objects and the source token keep their original ACLs.
        let data = token_buffer(token.0, TokenDefaultDacl)?;
        let original = unsafe { &*(data.as_ptr().cast::<TOKEN_DEFAULT_DACL>()) };
        if original.DefaultDacl.is_null() {
            return Err(Error {
                operation: "source-default-dacl-null",
                win32: 0,
            });
        }
        let mut marker_sid = null_mut();
        unsafe {
            check(
                ConvertStringSidToSidW(wide(marker).as_ptr(), &mut marker_sid),
                "default-dacl-marker",
            )?;
        }
        let entry = EXPLICIT_ACCESS_W {
            grfAccessPermissions: GENERIC_ALL,
            grfAccessMode: GRANT_ACCESS,
            grfInheritance: NO_INHERITANCE,
            Trustee: TRUSTEE_W {
                pMultipleTrustee: null_mut(),
                MultipleTrusteeOperation: NO_MULTIPLE_TRUSTEE,
                TrusteeForm: TRUSTEE_IS_SID,
                TrusteeType: TRUSTEE_IS_UNKNOWN,
                ptstrName: marker_sid.cast(),
            },
        };
        let mut acl = null_mut();
        let status = unsafe { SetEntriesInAclW(1, &entry, original.DefaultDacl, &mut acl) };
        unsafe {
            LocalFree(marker_sid);
        }
        if status != ERROR_SUCCESS {
            return Err(Error {
                operation: "default-dacl-owned-objects",
                win32: status,
            });
        }
        let default = TOKEN_DEFAULT_DACL { DefaultDacl: acl };
        let status = unsafe {
            SetTokenInformation(
                token.0,
                TokenDefaultDacl,
                (&default as *const TOKEN_DEFAULT_DACL).cast(),
                size_of_val(&default) as u32,
            )
        };
        let error = if status == 0 {
            Some(fail("set-private-token-default-dacl"))
        } else {
            None
        };
        unsafe {
            LocalFree(acl.cast());
        }
        if let Some(error) = error {
            return Err(error);
        }
    }
    let low = sid(WinLowLabelSid)?;
    let label = TOKEN_MANDATORY_LABEL {
        Label: SID_AND_ATTRIBUTES {
            Sid: low.as_ptr().cast_mut().cast(),
            Attributes: SE_GROUP_INTEGRITY as u32,
        },
    };
    unsafe {
        check(
            SetTokenInformation(
                token.0,
                TokenIntegrityLevel,
                (&label as *const TOKEN_MANDATORY_LABEL).cast(),
                (size_of::<TOKEN_MANDATORY_LABEL>() + GetLengthSid(label.Label.Sid) as usize)
                    as u32,
            ),
            "set-integrity",
        )?;
    }
    if !inspect_token(token.0)?.admissible() {
        return Err(Error {
            operation: "token-not-admissible",
            win32: 0,
        });
    }
    Ok(token)
}

/// Grants access only to this owned fixture, never to a host/system directory.
pub fn fixture_acl(path: &Path, allow_restricted: bool, low: bool) -> Result<()> {
    let user = own_sid()?;
    let rc = if allow_restricted {
        "(A;OICI;GA;;;RC)"
    } else {
        ""
    };
    let label = if low { "S:(ML;OICI;NW;;;LW)" } else { "" };
    let descriptor = Descriptor::new(&format!("D:P(A;OICI;FA;;;{user}){rc}{label}"))?;
    let flags = DACL_SECURITY_INFORMATION | if low { LABEL_SECURITY_INFORMATION } else { 0 };
    unsafe {
        check(
            SetFileSecurityW(wide(path).as_ptr(), flags, descriptor.0),
            "fixture-acl",
        )
    }
}

/// An opened image plus non-reparse ancestor handles held without delete sharing.
/// These handles prevent replacement of the validated fixture through launch.
pub struct PinnedImage {
    path: PathBuf,
    file: File,
    _directories: Vec<File>,
    pub sha256: String,
    id: (u32, u32, u32),
}
fn file_id(file: &File) -> Result<(u32, u32, u32)> {
    let mut info = unsafe { zeroed() };
    unsafe {
        check(
            GetFileInformationByHandle(file.as_raw_handle().cast(), &mut info),
            "file-identity",
        )?;
    }
    Ok((
        info.dwVolumeSerialNumber,
        info.nFileIndexHigh,
        info.nFileIndexLow,
    ))
}
impl PinnedImage {
    pub fn open(path: &Path, expected: &str) -> Result<Self> {
        use std::os::windows::fs::MetadataExt;
        let path = std::path::absolute(path).map_err(|_| Error {
            operation: "absolute-image",
            win32: 0,
        })?;
        let mut directories = Vec::new();
        for parent in path
            .ancestors()
            .skip(1)
            .collect::<Vec<_>>()
            .into_iter()
            .rev()
        {
            let file = OpenOptions::new()
                .read(true)
                .share_mode(FILE_SHARE_READ | FILE_SHARE_WRITE)
                .custom_flags(FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT)
                .open(parent)
                .map_err(|_| fail("open-image-parent"))?;
            if file
                .metadata()
                .map_err(|_| fail("parent-metadata"))?
                .file_attributes()
                & FILE_ATTRIBUTE_REPARSE_POINT
                != 0
            {
                return Err(Error {
                    operation: "reparse-parent",
                    win32: 0,
                });
            }
            directories.push(file);
        }
        let mut file = OpenOptions::new()
            .read(true)
            .share_mode(FILE_SHARE_READ)
            .custom_flags(FILE_FLAG_OPEN_REPARSE_POINT)
            .open(&path)
            .map_err(|_| fail("open-image"))?;
        let metadata = file.metadata().map_err(|_| fail("image-metadata"))?;
        if !metadata.is_file()
            || metadata.file_attributes() & FILE_ATTRIBUTE_REPARSE_POINT != 0
            || metadata.len() > 32 * 1024 * 1024
        {
            return Err(Error {
                operation: "image-kind-or-size",
                win32: 0,
            });
        }
        let mut hash = Sha256::new();
        let mut data = [0u8; 8192];
        loop {
            let n = file.read(&mut data).map_err(|_| fail("hash-image"))?;
            if n == 0 {
                break;
            }
            hash.update(&data[..n]);
        }
        let sha256 = format!("{:x}", hash.finalize());
        file.seek(SeekFrom::Start(0))
            .map_err(|_| fail("rewind-image"))?;
        if sha256 != expected {
            return Err(Error {
                operation: "image-hash-mismatch",
                win32: 0,
            });
        }
        let id = file_id(&file)?;
        Ok(Self {
            path,
            file,
            _directories: directories,
            sha256,
            id,
        })
    }
}
static STATION_LOCK: Mutex<()> = Mutex::new(());
fn object_name(object: HANDLE) -> Result<String> {
    let mut bytes = 0;
    unsafe {
        GetUserObjectInformationW(object, UOI_NAME, null_mut(), 0, &mut bytes);
    }
    if bytes == 0 {
        return Err(fail("user-object-name-size"));
    }
    let mut name = vec![0u16; (bytes as usize).div_ceil(2)];
    unsafe {
        check(
            GetUserObjectInformationW(
                object,
                UOI_NAME,
                name.as_mut_ptr().cast(),
                bytes,
                &mut bytes,
            ),
            "user-object-name",
        )?;
    }
    let length = name.iter().position(|c| *c == 0).unwrap_or(name.len());
    Ok(String::from_utf16_lossy(&name[..length]))
}
fn object_security(object: HANDLE, info: u32) -> Result<Vec<usize>> {
    let mut bytes = 0;
    unsafe {
        GetUserObjectSecurity(object, &info, null_mut(), 0, &mut bytes);
    }
    if bytes == 0 {
        return Err(fail("user-object-security-size"));
    }
    let mut data = vec![0usize; (bytes as usize).div_ceil(size_of::<usize>())];
    unsafe {
        check(
            GetUserObjectSecurity(object, &info, data.as_mut_ptr().cast(), bytes, &mut bytes),
            "user-object-security",
        )?;
    }
    Ok(data)
}
fn security_text(sd: PSECURITY_DESCRIPTOR, info: u32) -> Result<String> {
    let mut text = null_mut();
    let mut len = 0;
    unsafe {
        check(
            ConvertSecurityDescriptorToStringSecurityDescriptorW(sd, 1, info, &mut text, &mut len),
            "security-readback-string",
        )?;
    }
    let units = unsafe { std::slice::from_raw_parts(text, len as usize) };
    let value = String::from_utf16_lossy(
        &units[..units.iter().position(|c| *c == 0).unwrap_or(units.len())],
    );
    unsafe {
        LocalFree(text.cast());
    }
    Ok(value)
}
fn desktop_input(object: HDESK) -> Result<bool> {
    let mut input = 0i32;
    unsafe {
        check(
            GetUserObjectInformationW(
                object,
                UOI_IO,
                (&mut input as *mut i32).cast(),
                size_of_val(&input) as u32,
                null_mut(),
            ),
            "private-desktop-input-state",
        )?;
    }
    Ok(input != 0)
}
fn desktop_identity() -> Result<(String, String)> {
    let mut id = windows_sys::core::GUID::from_u128(0);
    let status = unsafe { CoCreateGuid(&mut id) };
    if status < 0 {
        return Err(Error {
            operation: "desktop-random-identity",
            win32: status as u32,
        });
    }
    let tail = u64::from_be_bytes(id.data4);
    let name = format!(
        "mss-probe-{:08x}{:04x}{:04x}{tail:016x}",
        id.data1, id.data2, id.data3
    );
    let status = unsafe { CoCreateGuid(&mut id) };
    if status < 0 {
        return Err(Error {
            operation: "desktop-random-marker",
            win32: status as u32,
        });
    }
    let tail = u64::from_be_bytes(id.data4);
    Ok((
        name,
        format!(
            "S-1-5-21-{}-{}-{}-{}",
            id.data1,
            ((id.data2 as u32) << 16) | id.data3 as u32,
            (tail >> 32) as u32,
            tail as u32
        ),
    ))
}
struct Desktop {
    desktop: HDESK,
    name: Vec<u16>,
    marker: String,
    parent_desktop: usize,
    parent_thread: u32,
    station: usize,
    station_security: Vec<usize>,
}
// The creating helper exits before the handle is transferred. No thread is
// switched to this desktop, and only this owner closes its handle.
unsafe impl Send for Desktop {}
impl Desktop {
    fn create() -> Result<Self> {
        let (name, marker) = desktop_identity()?;
        Self::create_named(name, marker)
    }
    fn create_named(name: String, marker: String) -> Result<Self> {
        let _lock = STATION_LOCK.lock().unwrap_or_else(|e| e.into_inner());
        let station = unsafe { GetProcessWindowStation() };
        let parent = unsafe { GetThreadDesktop(GetCurrentThreadId()) };
        if station.is_null() || parent.is_null() {
            return Err(fail("parent-gui-context"));
        }
        let info = OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION;
        let station_security = object_security(station, info)?;
        let station_name = object_name(station)?;
        let full_name = wide(format!("{station_name}\\{name}"));
        let desktop_name = name.clone();
        let desktop_marker = marker.clone();
        let helper = thread::spawn(move || -> Result<(usize, String)> {
            // CreateDesktop opens an existing object on collision. Refuse that
            // path before creation, then independently verify the nonce DACL to
            // catch a race; never reconfigure an existing object's security.
            let existing = unsafe { OpenDesktopW(wide(&name).as_ptr(), 0, 0, READ_CONTROL) };
            if !existing.is_null() {
                unsafe {
                    CloseDesktop(existing);
                }
                return Err(Error {
                    operation: "private-desktop-collision",
                    win32: ERROR_ALREADY_EXISTS,
                });
            }
            if unsafe { GetLastError() } != ERROR_FILE_NOT_FOUND {
                return Err(fail("private-desktop-collision-check"));
            }
            // CreateProcessAsUser requires full access to its specified desktop.
            // This grant is limited to this fresh object and nonce restricting
            // SID; Win32k lockdown is independently checked before Resume.
            let descriptor = Descriptor::new(&format!(
                "O:{}D:P(A;;0xf01ff;;;{})(A;;0xf01ff;;;{})S:AI(ML;;NW;;;LW)",
                own_sid()?,
                own_sid()?,
                marker
            ))?;
            let expected = security_text(descriptor.0, info | LABEL_SECURITY_INFORMATION)?;
            let attrs = descriptor.attributes();
            let desktop = unsafe {
                CreateDesktopW(wide(&name).as_ptr(), null(), null(), 0, GENERIC_ALL, &attrs)
            };
            if desktop.is_null() {
                return Err(fail("create-private-desktop"));
            }
            // Do not close on this thread: CreateDesktop assigns the object to
            // its creator. Join first so even a failed readback can close it.
            Ok((desktop as usize, expected))
        });
        let (desktop, expected) = helper.join().map_err(|_| Error {
            operation: "private-desktop-helper",
            win32: 0,
        })??;
        let result = Desktop {
            desktop: desktop as HDESK,
            name: full_name,
            marker: desktop_marker,
            parent_desktop: parent as usize,
            parent_thread: unsafe { GetCurrentThreadId() },
            station: station as usize,
            station_security,
        };
        let security = object_security(result.desktop, info | LABEL_SECURITY_INFORMATION)?;
        let actual = security_text(
            security.as_ptr().cast_mut().cast(),
            info | LABEL_SECURITY_INFORMATION,
        )?;
        if expected != actual {
            return Err(Error {
                operation: "private-desktop-security",
                win32: 0,
            });
        }
        if object_name(result.desktop)? != desktop_name || desktop_input(result.desktop)? {
            return Err(Error {
                operation: "private-desktop-identity-or-input",
                win32: 0,
            });
        }
        result.verify_parent()?;
        Ok(result)
    }
    fn verify_parent(&self) -> Result<()> {
        if unsafe { GetProcessWindowStation() } as usize != self.station
            || unsafe { GetThreadDesktop(self.parent_thread) } as usize != self.parent_desktop
            || object_security(
                self.station as HANDLE,
                OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION,
            )? != self.station_security
            || desktop_input(self.desktop)?
        {
            return Err(Error {
                operation: "parent-context-changed-or-desktop-interactive",
                win32: 0,
            });
        }
        Ok(())
    }
    fn close_checked(&mut self) -> Result<()> {
        let name = object_name(self.desktop)?;
        unsafe {
            check(CloseDesktop(self.desktop), "close-own-private-desktop")?;
        }
        self.desktop = null_mut();
        let reopened = unsafe { OpenDesktopW(wide(name).as_ptr(), 0, 0, READ_CONTROL) };
        let error = unsafe { GetLastError() };
        if !reopened.is_null() {
            unsafe {
                CloseDesktop(reopened);
            }
            return Err(Error {
                operation: "private-desktop-cleanup-unconfirmed",
                win32: 0,
            });
        }
        if error != ERROR_FILE_NOT_FOUND {
            return Err(Error {
                operation: "private-desktop-cleanup-observation",
                win32: error,
            });
        }
        Ok(())
    }
}
impl Drop for Desktop {
    fn drop(&mut self) {
        if !self.desktop.is_null() {
            unsafe {
                CloseDesktop(self.desktop);
            }
        }
    }
}

struct Attributes {
    data: Vec<usize>,
    initialized: bool,
}
impl Attributes {
    fn new(count: u32) -> Result<Self> {
        let mut bytes = 0;
        unsafe {
            InitializeProcThreadAttributeList(null_mut(), count, 0, &mut bytes);
        }
        if bytes == 0 {
            return Err(fail("attribute-list-size"));
        }
        let mut result = Self {
            data: vec![0; (bytes as usize).div_ceil(size_of::<usize>())],
            initialized: false,
        };
        unsafe {
            check(
                InitializeProcThreadAttributeList(result.ptr(), count, 0, &mut bytes),
                "attribute-list",
            )?;
        }
        result.initialized = true;
        Ok(result)
    }
    fn ptr(&mut self) -> LPPROC_THREAD_ATTRIBUTE_LIST {
        self.data.as_mut_ptr().cast()
    }
    fn set<T>(&mut self, kind: u32, value: &[T]) -> Result<()> {
        unsafe {
            check(
                UpdateProcThreadAttribute(
                    self.ptr(),
                    0,
                    kind as usize,
                    value.as_ptr().cast(),
                    std::mem::size_of_val(value),
                    null_mut(),
                    null(),
                ),
                "process-attribute",
            )
        }
    }
}
impl Drop for Attributes {
    fn drop(&mut self) {
        if self.initialized {
            unsafe {
                DeleteProcThreadAttributeList(self.ptr());
            }
        }
    }
}
fn pipe() -> Result<(Handle, Handle)> {
    let mut read = null_mut();
    let mut write = null_mut();
    let attrs = SECURITY_ATTRIBUTES {
        nLength: size_of::<SECURITY_ATTRIBUTES>() as u32,
        lpSecurityDescriptor: null_mut(),
        bInheritHandle: 1,
    };
    unsafe {
        check(CreatePipe(&mut read, &mut write, &attrs, 0), "create-pipe")?;
    }
    let read = Handle::new(read, "pipe-read")?;
    let write = Handle::new(write, "pipe-write")?;
    unsafe {
        check(
            SetHandleInformation(read.0, HANDLE_FLAG_INHERIT, 0),
            "pipe-parent-no-inherit",
        )?;
    }
    Ok((read, write))
}
fn capture(handle: Handle) -> thread::JoinHandle<(Vec<u8>, bool)> {
    thread::spawn(move || {
        let mut file = unsafe { File::from_raw_handle(handle.0.cast()) };
        std::mem::forget(handle);
        let mut bytes = Vec::new();
        let mut incomplete = false;
        let mut buf = [0u8; 4096];
        loop {
            match file.read(&mut buf) {
                Ok(0) => break,
                Ok(n) => {
                    let keep = n.min(65536usize.saturating_sub(bytes.len()));
                    bytes.extend_from_slice(&buf[..keep]);
                    incomplete |= keep != n;
                }
                Err(_) => {
                    incomplete = true;
                    break;
                }
            }
        }
        (bytes, incomplete)
    })
}
fn quote(arg: &str) -> String {
    let mut result = String::from("\"");
    let mut slashes = 0;
    for c in arg.chars() {
        if c == '\\' {
            slashes += 1;
        } else {
            if c == '"' {
                result.push_str(&"\\".repeat(slashes * 2 + 1));
            } else {
                result.push_str(&"\\".repeat(slashes));
            }
            slashes = 0;
            result.push(c);
        }
    }
    result.push_str(&"\\".repeat(slashes * 2));
    result.push('"');
    result
}
#[derive(Debug, PartialEq, Eq)]
pub enum End {
    Exited(u32),
    TimedOut,
    Cancelled,
    DescendantsRemaining,
}
#[derive(Debug)]
pub struct Observation {
    pub end: End,
    pub stdout: Vec<u8>,
    pub stderr: Vec<u8>,
    pub output_incomplete: bool,
    pub cleanup_confirmed: bool,
    pub token: TokenFacts,
    pub pid: u32,
    pub birth: u64,
    pub desktop: String,
    pub desktop_receives_input: bool,
    pub parent_desktop_unchanged: bool,
    pub station_acl_unchanged: bool,
    /// None is an unavailable observation, never proof of no GUI connection.
    pub child_connected_desktop: Option<String>,
    pub child_desktop_query_win32: Option<u32>,
    pub desktop_cleanup_confirmed: bool,
}
pub struct Run {
    job: Handle,
    process: Handle,
    _desktop: Desktop,
    _image: PinnedImage,
    stdout: Option<thread::JoinHandle<(Vec<u8>, bool)>>,
    stderr: Option<thread::JoinHandle<(Vec<u8>, bool)>>,
    pub pid: u32,
    pub birth: u64,
    token: TokenFacts,
    child_connected_desktop: Option<String>,
    child_desktop_query_win32: Option<u32>,
}
unsafe impl Send for Run {}
fn active(job: HANDLE) -> Result<u32> {
    let mut info = unsafe { zeroed::<JOBOBJECT_BASIC_ACCOUNTING_INFORMATION>() };
    unsafe {
        check(
            QueryInformationJobObject(
                job,
                JobObjectBasicAccountingInformation,
                (&mut info as *mut JOBOBJECT_BASIC_ACCOUNTING_INFORMATION).cast(),
                size_of_val(&info) as u32,
                null_mut(),
            ),
            "job-accounting",
        )?;
    }
    Ok(info.ActiveProcesses)
}
fn has_descendants(job: HANDLE, primary: u32) -> Result<bool> {
    // A signalled primary can remain in Job accounting briefly. Distinguish
    // that case from a live descendant without granting a cleanup grace period
    // to descendants or confusing primary exit with whole-tree termination.
    let mut data = [0usize; 6]; // header + the enforced four-process maximum
    let list = data.as_mut_ptr().cast::<JOBOBJECT_BASIC_PROCESS_ID_LIST>();
    unsafe {
        check(
            QueryInformationJobObject(
                job,
                JobObjectBasicProcessIdList,
                list.cast(),
                size_of_val(&data) as u32,
                null_mut(),
            ),
            "job-process-identities",
        )?;
        let count = (*list).NumberOfProcessIdsInList as usize;
        if count > 4 {
            return Err(Error {
                operation: "job-process-list-overflow",
                win32: 0,
            });
        }
        Ok(
            std::slice::from_raw_parts((*list).ProcessIdList.as_ptr(), count)
                .iter()
                .any(|pid| *pid != primary as usize),
        )
    }
}
fn create_job() -> Result<Handle> {
    let job = Handle::new(unsafe { CreateJobObjectW(null(), null()) }, "create-job")?;
    let mut limits = unsafe { zeroed::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() };
    limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        | JOB_OBJECT_LIMIT_ACTIVE_PROCESS
        | JOB_OBJECT_LIMIT_PROCESS_MEMORY
        | JOB_OBJECT_LIMIT_JOB_MEMORY
        | JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION;
    limits.BasicLimitInformation.ActiveProcessLimit = 4;
    limits.ProcessMemoryLimit = 128 * 1024 * 1024;
    limits.JobMemoryLimit = 256 * 1024 * 1024;
    unsafe {
        check(
            SetInformationJobObject(
                job.0,
                JobObjectExtendedLimitInformation,
                (&limits as *const JOBOBJECT_EXTENDED_LIMIT_INFORMATION).cast(),
                size_of_val(&limits) as u32,
            ),
            "job-limits",
        )?;
    }
    let cpu = JOBOBJECT_CPU_RATE_CONTROL_INFORMATION {
        ControlFlags: JOB_OBJECT_CPU_RATE_CONTROL_ENABLE | JOB_OBJECT_CPU_RATE_CONTROL_HARD_CAP,
        Anonymous: JOBOBJECT_CPU_RATE_CONTROL_INFORMATION_0 { CpuRate: 1000 },
    };
    unsafe {
        check(
            SetInformationJobObject(
                job.0,
                JobObjectCpuRateControlInformation,
                (&cpu as *const JOBOBJECT_CPU_RATE_CONTROL_INFORMATION).cast(),
                size_of_val(&cpu) as u32,
            ),
            "job-cpu",
        )?;
    }
    Ok(job)
}
impl Run {
    /// This API is for compiled, owner-controlled probe fixtures only.
    pub fn launch(image: PinnedImage, args: &[String], cwd: &Path) -> Result<Self> {
        if args.len() > 16
            || args
                .iter()
                .any(|s| s.len() > 2048 || s.chars().any(char::is_control))
            || std::path::absolute(cwd).ok().as_deref() != image.path.parent()
        {
            return Err(Error {
                operation: "probe-arguments-or-cwd",
                win32: 0,
            });
        }
        let desktop = Desktop::create()?;
        let token = restricted_token_for_desktop(Some(&desktop.marker))?;
        let token_value = token.0 as usize;
        let station_name = object_name(desktop.station as HANDLE)?;
        let desktop_name = object_name(desktop.desktop)?;
        thread::spawn(move || -> Result<()> {
            unsafe {
                check(
                    ImpersonateLoggedOnUser(token_value as HANDLE),
                    "preflight-impersonate-owned-token",
                )?;
            }
            struct Revert;
            impl Drop for Revert {
                fn drop(&mut self) {
                    if unsafe { RevertToSelf() } == 0 {
                        std::process::abort();
                    }
                }
            }
            let _revert = Revert;
            let station =
                unsafe { OpenWindowStationW(wide(station_name).as_ptr(), 0, GENERIC_ALL) };
            if station.is_null() {
                return Err(fail("restricted-open-unchanged-station"));
            }
            unsafe {
                CloseWindowStation(station);
            }
            let desk = unsafe { OpenDesktopW(wide(desktop_name).as_ptr(), 0, 0, GENERIC_ALL) };
            if desk.is_null() {
                return Err(fail("restricted-open-own-desktop"));
            }
            unsafe {
                CloseDesktop(desk);
            }
            Ok(())
        })
        .join()
        .map_err(|_| Error {
            operation: "desktop-access-preflight-helper",
            win32: 0,
        })??;
        let job = create_job()?;
        let (stdout_read, stdout_write) = pipe()?;
        let (stderr_read, stderr_write) = pipe()?;
        let input = OpenOptions::new()
            .read(true)
            .open("NUL")
            .map_err(|_| fail("open-null-input"))?;
        unsafe {
            check(
                SetHandleInformation(
                    input.as_raw_handle().cast(),
                    HANDLE_FLAG_INHERIT,
                    HANDLE_FLAG_INHERIT,
                ),
                "null-input-inherit",
            )?;
        }
        let handles = [input.as_raw_handle().cast(), stdout_write.0, stderr_write.0];
        let jobs = [job.0];
        // winbase.h: PROCESS_CREATION_MITIGATION_POLICY_WIN32K_SYSTEM_CALL_DISABLE_ALWAYS_ON.
        let mitigations = [1u64 << 28];
        let mut attributes = Attributes::new(3)?;
        attributes.set(PROC_THREAD_ATTRIBUTE_HANDLE_LIST, &handles)?;
        attributes.set(PROC_THREAD_ATTRIBUTE_JOB_LIST, &jobs)?;
        attributes.set(PROC_THREAD_ATTRIBUTE_MITIGATION_POLICY, &mitigations)?;
        let mut startup = unsafe { zeroed::<STARTUPINFOEXW>() };
        startup.StartupInfo.cb = size_of::<STARTUPINFOEXW>() as u32;
        startup.StartupInfo.lpDesktop = desktop.name.as_ptr().cast_mut();
        startup.StartupInfo.dwFlags = STARTF_USESTDHANDLES;
        startup.StartupInfo.hStdInput = handles[0];
        startup.StartupInfo.hStdOutput = handles[1];
        startup.StartupInfo.hStdError = handles[2];
        startup.lpAttributeList = attributes.ptr();
        let mut windows = [0u16; 32768];
        let n =
            unsafe { GetWindowsDirectoryW(windows.as_mut_ptr(), windows.len() as u32) } as usize;
        if n == 0 || n >= windows.len() {
            return Err(fail("windows-directory"));
        }
        let system = String::from_utf16_lossy(&windows[..n]);
        // Windows requires a case-insensitively sorted Unicode environment.
        // wide supplies the last value terminator; push supplies the block terminator.
        let mut env = wide(format!(
            "PATH={system}\\System32\0SystemRoot={system}\0TEMP={}\0TMP={}\0WINDIR={system}",
            cwd.display(),
            cwd.display()
        ));
        env.push(0);
        let executable = wide(&image.path);
        let mut command = wide(
            std::iter::once(image.path.to_string_lossy().into_owned())
                .chain(args.iter().cloned())
                .map(|s| quote(&s))
                .collect::<Vec<_>>()
                .join(" "),
        );
        let mut process = unsafe { zeroed::<PROCESS_INFORMATION>() };
        unsafe {
            check(
                CreateProcessAsUserW(
                    token.0,
                    executable.as_ptr(),
                    command.as_mut_ptr(),
                    null(),
                    null(),
                    1,
                    CREATE_SUSPENDED
                        | CREATE_UNICODE_ENVIRONMENT
                        | EXTENDED_STARTUPINFO_PRESENT
                        | DETACHED_PROCESS,
                    env.as_ptr().cast(),
                    wide(cwd).as_ptr(),
                    &startup.StartupInfo,
                    &mut process,
                ),
                "create-suspended-probe",
            )?;
        }
        let process_handle = Handle::new(process.hProcess, "child-process")?;
        let thread_handle = Handle::new(process.hThread, "child-thread")?;
        // Every error after creation closes this own Job and kills its own tree.
        let mut inside = 0;
        unsafe {
            check(
                IsProcessInJob(process_handle.0, job.0, &mut inside),
                "child-job-membership",
            )?;
        }
        if inside == 0 {
            return Err(Error {
                operation: "child-outside-job",
                win32: 0,
            });
        }
        let mut actual_token = null_mut();
        unsafe {
            check(
                OpenProcessToken(process_handle.0, TOKEN_QUERY, &mut actual_token),
                "child-token",
            )?;
        }
        let actual_token = Handle::new(actual_token, "child-token-handle")?;
        let facts = inspect_token(actual_token.0)?;
        if !facts.admissible() {
            return Err(Error {
                operation: "child-effective-token-denied",
                win32: 0,
            });
        }
        let mut actual_policy =
            unsafe { zeroed::<PROCESS_MITIGATION_SYSTEM_CALL_DISABLE_POLICY>() };
        unsafe {
            check(
                GetProcessMitigationPolicy(
                    process_handle.0,
                    ProcessSystemCallDisablePolicy,
                    (&mut actual_policy as *mut PROCESS_MITIGATION_SYSTEM_CALL_DISABLE_POLICY)
                        .cast(),
                    size_of_val(&actual_policy),
                ),
                "child-mitigation",
            )?;
        }
        if unsafe { actual_policy.Anonymous.Flags } & 1 == 0 {
            return Err(Error {
                operation: "child-mitigation-missing",
                win32: 0,
            });
        }
        // Borrowed thread-desktop handles must not be closed by this process.
        unsafe {
            SetLastError(ERROR_SUCCESS);
        }
        let actual_desktop = unsafe { GetThreadDesktop(process.dwThreadId) };
        let child_desktop_query_win32 = if actual_desktop.is_null() {
            Some(unsafe { GetLastError() })
        } else {
            None
        };
        let child_connected_desktop = if actual_desktop.is_null() {
            None
        } else {
            let actual_name = object_name(actual_desktop)?;
            let info =
                OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION | LABEL_SECURITY_INFORMATION;
            if actual_name != object_name(desktop.desktop)?
                || desktop_input(actual_desktop)?
                || object_security(actual_desktop, info)? != object_security(desktop.desktop, info)?
            {
                return Err(Error {
                    operation: "child-desktop-mismatch-or-input",
                    win32: 0,
                });
            }
            Some(actual_name)
        };
        let mut path_buf = vec![0u16; 32768];
        let mut len = path_buf.len() as u32;
        unsafe {
            check(
                QueryFullProcessImageNameW(process_handle.0, 0, path_buf.as_mut_ptr(), &mut len),
                "child-image-name",
            )?;
        }
        let actual_image = File::open(String::from_utf16_lossy(&path_buf[..len as usize]))
            .map_err(|_| fail("child-image-open"))?;
        if file_id(&actual_image)? != image.id || file_id(&image.file)? != image.id {
            return Err(Error {
                operation: "child-image-identity",
                win32: 0,
            });
        }
        let mut creation = unsafe { zeroed::<FILETIME>() };
        let mut exit = creation;
        let mut kernel = creation;
        let mut user = creation;
        unsafe {
            check(
                GetProcessTimes(
                    process_handle.0,
                    &mut creation,
                    &mut exit,
                    &mut kernel,
                    &mut user,
                ),
                "child-birth",
            )?;
        }
        desktop.verify_parent()?;
        if unsafe { ResumeThread(thread_handle.0) } == u32::MAX {
            return Err(fail("resume-probe"));
        }
        drop(stdout_write);
        drop(stderr_write);
        Ok(Self {
            job,
            process: process_handle,
            _desktop: desktop,
            _image: image,
            stdout: Some(capture(stdout_read)),
            stderr: Some(capture(stderr_read)),
            pid: process.dwProcessId,
            birth: ((creation.dwHighDateTime as u64) << 32) | creation.dwLowDateTime as u64,
            token: facts,
            child_connected_desktop,
            child_desktop_query_win32,
        })
    }
    pub fn wait(mut self, timeout: Duration, cancel: &AtomicBool) -> Result<Observation> {
        let start = Instant::now();
        let end;
        loop {
            if cancel.load(Ordering::SeqCst) {
                end = End::Cancelled;
                break;
            }
            if start.elapsed() >= timeout {
                end = End::TimedOut;
                break;
            }
            let result = unsafe { WaitForSingleObject(self.process.0, 10) };
            if result == WAIT_OBJECT_0 {
                let mut code = 0;
                unsafe {
                    check(GetExitCodeProcess(self.process.0, &mut code), "child-exit")?;
                }
                end = if has_descendants(self.job.0, self.pid)? {
                    End::DescendantsRemaining
                } else {
                    End::Exited(code)
                };
                break;
            }
            if result != WAIT_TIMEOUT {
                return Err(fail("wait-child"));
            }
        }
        if !matches!(end, End::Exited(_)) {
            unsafe {
                check(
                    TerminateJobObject(self.job.0, 0x4d5353),
                    "terminate-own-job",
                )?;
            }
        }
        let cleanup_start = Instant::now();
        while active(self.job.0)? > 0 && cleanup_start.elapsed() < Duration::from_secs(3) {
            thread::sleep(Duration::from_millis(10));
        }
        let cleanup_confirmed = active(self.job.0)? == 0;
        if !cleanup_confirmed {
            return Err(Error {
                operation: "owned-cleanup-unknown",
                win32: 0,
            });
        }
        let (stdout, a) = self.stdout.take().unwrap().join().map_err(|_| Error {
            operation: "stdout-reader",
            win32: 0,
        })?;
        let (stderr, b) = self.stderr.take().unwrap().join().map_err(|_| Error {
            operation: "stderr-reader",
            win32: 0,
        })?;
        self._desktop.verify_parent()?;
        let desktop_name =
            String::from_utf16_lossy(&self._desktop.name[..self._desktop.name.len() - 1]);
        self._desktop.close_checked()?;
        Ok(Observation {
            end,
            stdout,
            stderr,
            output_incomplete: a || b,
            cleanup_confirmed,
            token: TokenFacts {
                restricted: self.token.restricted,
                elevated: self.token.elevated,
                enabled_admin: self.token.enabled_admin,
                low_integrity: self.token.low_integrity,
                unexpected_enabled_privilege: self.token.unexpected_enabled_privilege,
            },
            pid: self.pid,
            birth: self.birth,
            desktop: desktop_name,
            desktop_receives_input: false,
            parent_desktop_unchanged: true,
            station_acl_unchanged: true,
            child_connected_desktop: self.child_connected_desktop.take(),
            child_desktop_query_win32: self.child_desktop_query_win32,
            desktop_cleanup_confirmed: true,
        })
    }
}
impl Drop for Run {
    fn drop(&mut self) {
        unsafe {
            TerminateJobObject(self.job.0, 0x4d5353);
        }
    }
}

/// Durable consume-once fence. The caller must supply a controller-owned private
/// root; this helper does not authenticate stdin or qualify that root's ACL.
/// Records are never removed on errors, cancellation, panic, or Drop.
pub struct AttemptFence {
    _file: File,
    _directories: Vec<File>,
}
impl AttemptFence {
    pub fn claim(root: &Path, goal: &str, attempt: &str, request_sha256: &str) -> Result<Self> {
        use std::io::Write;
        use std::os::windows::fs::MetadataExt;
        if goal.len() != 7
            || !goal.starts_with("MSS-")
            || !goal[4..].bytes().all(|b| b.is_ascii_digit())
            || goal == "MSS-000"
            || attempt
                .parse::<u64>()
                .ok()
                .is_none_or(|n| n == 0 || n.to_string() != attempt)
            || request_sha256.len() != 64
            || !request_sha256
                .bytes()
                .all(|b| b.is_ascii_hexdigit() && !b.is_ascii_uppercase())
            || !root.is_absolute()
            || root
                .components()
                .any(|c| matches!(c, std::path::Component::ParentDir))
        {
            return Err(Error {
                operation: "fence-binding",
                win32: 0,
            });
        }
        let mut directories = Vec::new();
        for ancestor in root.ancestors().collect::<Vec<_>>().into_iter().rev() {
            let file = OpenOptions::new()
                .read(true)
                .share_mode(FILE_SHARE_READ | FILE_SHARE_WRITE)
                .custom_flags(FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT)
                .open(ancestor)
                .map_err(|_| fail("fence-root-open"))?;
            let metadata = file.metadata().map_err(|_| fail("fence-root-metadata"))?;
            if !metadata.is_dir() || metadata.file_attributes() & FILE_ATTRIBUTE_REPARSE_POINT != 0
            {
                return Err(Error {
                    operation: "fence-root-reparse",
                    win32: 0,
                });
            }
            directories.push(file);
        }
        let mut file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .share_mode(0)
            .custom_flags(FILE_FLAG_OPEN_REPARSE_POINT)
            .open(root.join(format!("{goal}-{attempt}.consumed")))
            .map_err(|_| fail("attempt-already-consumed-or-unavailable"))?;
        let value = serde_json::json!({"schema":"mss-probe-attempt-fence-v1","goal":goal,"attempt":attempt,"request_sha256":request_sha256,"outcome":"CONSUMED_NO_AUTOMATIC_REPLAY"});
        file.write_all(value.to_string().as_bytes())
            .map_err(|_| fail("fence-write-unknown"))?;
        file.sync_all().map_err(|_| fail("fence-flush-unknown"))?;
        Ok(Self {
            _file: file,
            _directories: directories,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn default_aces(token: HANDLE) -> Vec<Vec<u8>> {
        let data = token_buffer(token, TokenDefaultDacl).unwrap();
        let acl = unsafe { (*(data.as_ptr().cast::<TOKEN_DEFAULT_DACL>())).DefaultDacl };
        assert!(!acl.is_null());
        (0..unsafe { (*acl).AceCount } as u32)
            .map(|index| {
                let mut ace = null_mut();
                unsafe {
                    check(GetAce(acl, index, &mut ace), "test-default-ace").unwrap();
                    std::slice::from_raw_parts(
                        ace.cast::<u8>(),
                        (*(ace.cast::<ACE_HEADER>())).AceSize as usize,
                    )
                    .to_vec()
                }
            })
            .collect()
    }

    #[test]
    fn nonce_default_dacl_preserves_source_and_existing_restrictions() {
        let source = own_token().unwrap();
        let before = default_aces(source.0);
        let (_, marker) = desktop_identity().unwrap();
        let token = restricted_token_for_desktop(Some(&marker)).unwrap();
        assert!(inspect_token(token.0).unwrap().admissible());
        assert_eq!(
            default_aces(source.0),
            before,
            "source token must never be reconfigured"
        );
        let mut added = default_aces(token.0);
        for ace in before {
            let at = added
                .iter()
                .position(|candidate| *candidate == ace)
                .expect("preserve every original ACE");
            added.remove(at);
        }
        assert_eq!(added.len(), 1, "only the per-run nonce grant may be added");
        // Copy to aligned storage before reading the OS ACE structure.
        let mut ace = vec![0usize; added[0].len().div_ceil(size_of::<usize>())];
        unsafe {
            std::ptr::copy_nonoverlapping(
                added[0].as_ptr(),
                ace.as_mut_ptr().cast(),
                added[0].len(),
            );
        }
        let ace = unsafe { &*(ace.as_ptr().cast::<ACCESS_ALLOWED_ACE>()) };
        assert_eq!(ace.Header.AceType, 0); // ACCESS_ALLOWED_ACE_TYPE
        assert_eq!(ace.Header.AceFlags, 0);
        assert_eq!(ace.Mask, GENERIC_ALL);
        let mut marker_sid = null_mut();
        unsafe {
            check(
                ConvertStringSidToSidW(wide(marker).as_ptr(), &mut marker_sid),
                "test-marker-sid",
            )
            .unwrap();
        }
        let marker_sid = Descriptor(marker_sid);
        assert_ne!(
            unsafe {
                EqualSid(
                    (&ace.SidStart as *const u32).cast_mut().cast(),
                    marker_sid.0,
                )
            },
            0
        );
        let data = token_buffer(token.0, TokenRestrictedSids).unwrap();
        let groups = unsafe { &*(data.as_ptr().cast::<TOKEN_GROUPS>()) };
        let groups = unsafe {
            std::slice::from_raw_parts(groups.Groups.as_ptr(), groups.GroupCount as usize)
        };
        assert_eq!(groups.len(), 4);
        for expected in [
            sid(WinRestrictedCodeSid).unwrap(),
            sid(WinWorldSid).unwrap(),
            sid(WinBuiltinUsersSid).unwrap(),
        ] {
            assert!(
                groups
                    .iter()
                    .any(|g| unsafe { EqualSid(g.Sid, expected.as_ptr().cast_mut().cast()) != 0 })
            );
        }
        assert!(
            groups
                .iter()
                .any(|g| unsafe { EqualSid(g.Sid, marker_sid.0) != 0 })
        );
    }

    #[test]
    fn private_desktop_is_noninput_owned_and_closed_without_changing_parent() {
        let desktop = Desktop::create().expect("create a fresh noninput desktop");
        desktop.verify_parent().unwrap();
        let name = object_name(desktop.desktop).unwrap();
        assert!(name.starts_with("mss-probe-"));
        assert!(!name.eq_ignore_ascii_case("Default"));
        assert!(!desktop_input(desktop.desktop).unwrap());
        let security = object_security(desktop.desktop, LABEL_SECURITY_INFORMATION).unwrap();
        assert_eq!(
            security_text(
                security.as_ptr().cast_mut().cast(),
                LABEL_SECURITY_INFORMATION
            )
            .unwrap(),
            "S:AI(ML;;NW;;;LW)"
        );
        drop(desktop);
        let reopened = unsafe { OpenDesktopW(wide(name).as_ptr(), 0, 0, READ_CONTROL) };
        let error = unsafe { GetLastError() };
        if !reopened.is_null() {
            unsafe {
                CloseDesktop(reopened);
            }
        }
        assert!(
            reopened.is_null(),
            "owned desktop must disappear after its last handle closes"
        );
        assert_eq!(error, ERROR_FILE_NOT_FOUND);
    }

    #[test]
    fn existing_desktop_collision_is_refused_without_acl_changes() {
        let original = Desktop::create().unwrap();
        let name = object_name(original.desktop).unwrap();
        let info =
            OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION | LABEL_SECURITY_INFORMATION;
        let before = object_security(original.desktop, info).unwrap();
        let (_, fresh_marker) = desktop_identity().unwrap();
        let result = Desktop::create_named(name, fresh_marker);
        assert!(matches!(
            result,
            Err(Error {
                operation: "private-desktop-collision",
                win32: ERROR_ALREADY_EXISTS
            })
        ));
        assert_eq!(object_security(original.desktop, info).unwrap(), before);
        original.verify_parent().unwrap();
    }
    use std::sync::atomic::AtomicU64;
    static SERIAL: Mutex<()> = Mutex::new(());
    static SEQUENCE: AtomicU64 = AtomicU64::new(0);

    #[test]
    fn effective_restricted_token_has_observed_privilege_and_integrity_limits() {
        let token = restricted_token().expect("create own restricted token");
        assert!(inspect_token(token.0).unwrap().admissible());
        let restrictions = token_buffer(token.0, TokenRestrictedSids).unwrap();
        let groups = unsafe { &*(restrictions.as_ptr().cast::<TOKEN_GROUPS>()) };
        assert_eq!(groups.GroupCount, 3);
    }

    #[test]
    fn os_access_checks_deny_private_fixture_reads_and_writes_under_restricted_token() {
        let _serial = SERIAL.lock().unwrap();
        let temp = std::fs::canonicalize(std::env::temp_dir()).unwrap();
        let root = temp.join(format!(
            "mss-token-acl-{}-{}-{}",
            std::process::id(),
            unsafe { GetTickCount64() },
            SEQUENCE.fetch_add(1, Ordering::SeqCst)
        ));
        std::fs::create_dir(&root).unwrap();
        struct Cleanup {
            root: PathBuf,
            parent: PathBuf,
        }
        impl Drop for Cleanup {
            fn drop(&mut self) {
                assert_eq!(self.root.parent(), Some(self.parent.as_path()));
                assert!(
                    !std::fs::symlink_metadata(&self.root)
                        .unwrap()
                        .file_type()
                        .is_symlink()
                );
                std::fs::remove_dir_all(&self.root).expect("cleanup only own ACL fixture");
            }
        }
        let _cleanup = Cleanup {
            root: root.clone(),
            parent: temp,
        };
        fixture_acl(&root, true, true).unwrap();
        let allowed = root.join("allowed.txt");
        let private = root.join("private.txt");
        let sibling = root.join("sibling.txt");
        for p in [&allowed, &private, &sibling] {
            std::fs::write(p, b"owned synthetic sentinel").unwrap();
        }
        fixture_acl(&allowed, true, true).unwrap();
        fixture_acl(&private, false, false).unwrap();
        fixture_acl(&sibling, false, false).unwrap();
        let token = restricted_token().unwrap();
        unsafe {
            check(
                ImpersonateLoggedOnUser(token.0),
                "impersonate-own-restricted-token",
            )
            .unwrap();
        }
        struct Revert;
        impl Drop for Revert {
            fn drop(&mut self) {
                if unsafe { RevertToSelf() } == 0 {
                    std::process::abort();
                }
            }
        }
        let revert = Revert;
        let allowed_read = std::fs::read(&allowed);
        let allowed_write = std::fs::write(&allowed, b"owned changed fixture");
        let private_read = std::fs::read(&private);
        let sibling_read = std::fs::read(&sibling);
        let private_write = std::fs::write(&private, b"must be denied");
        drop(revert);
        assert!(allowed_read.is_ok());
        assert!(allowed_write.is_ok());
        assert_eq!(private_read.unwrap_err().raw_os_error(), Some(5));
        assert_eq!(sibling_read.unwrap_err().raw_os_error(), Some(5));
        assert_eq!(private_write.unwrap_err().raw_os_error(), Some(5));
        assert_eq!(
            std::fs::read(&private).unwrap(),
            b"owned synthetic sentinel"
        );
    }

    #[test]
    fn job_limits_are_read_back_from_the_real_kernel_object() {
        let job = create_job().unwrap();
        let mut limits = unsafe { zeroed::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() };
        unsafe {
            check(
                QueryInformationJobObject(
                    job.0,
                    JobObjectExtendedLimitInformation,
                    (&mut limits as *mut JOBOBJECT_EXTENDED_LIMIT_INFORMATION).cast(),
                    size_of_val(&limits) as u32,
                    null_mut(),
                ),
                "read-job-limits",
            )
            .unwrap();
        }
        assert_ne!(
            limits.BasicLimitInformation.LimitFlags & JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
            0
        );
        assert_eq!(
            limits.BasicLimitInformation.LimitFlags
                & (JOB_OBJECT_LIMIT_BREAKAWAY_OK | JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK),
            0
        );
        assert_eq!(limits.BasicLimitInformation.ActiveProcessLimit, 4);
        assert_eq!(limits.ProcessMemoryLimit, 128 * 1024 * 1024);
        assert_eq!(limits.JobMemoryLimit, 256 * 1024 * 1024);
        let mut cpu = unsafe { zeroed::<JOBOBJECT_CPU_RATE_CONTROL_INFORMATION>() };
        unsafe {
            check(
                QueryInformationJobObject(
                    job.0,
                    JobObjectCpuRateControlInformation,
                    (&mut cpu as *mut JOBOBJECT_CPU_RATE_CONTROL_INFORMATION).cast(),
                    size_of_val(&cpu) as u32,
                    null_mut(),
                ),
                "read-job-cpu",
            )
            .unwrap();
        }
        assert_eq!(unsafe { cpu.Anonymous.CpuRate }, 1000);
        assert_eq!(active(job.0).unwrap(), 0);
    }

    #[test]
    fn consumed_attempt_is_denied_by_create_new_before_and_after_handle_loss() {
        let temp = std::fs::canonicalize(std::env::temp_dir()).unwrap();
        let root = temp.join(format!(
            "mss-attempt-fence-{}-{}-{}",
            std::process::id(),
            unsafe { GetTickCount64() },
            SEQUENCE.fetch_add(1, Ordering::SeqCst)
        ));
        std::fs::create_dir(&root).unwrap();
        let digest = "a".repeat(64);
        let first = AttemptFence::claim(&root, "MSS-008", "123", &digest).unwrap();
        assert!(AttemptFence::claim(&root, "MSS-008", "123", &digest).is_err());
        drop(first);
        assert!(AttemptFence::claim(&root, "MSS-008", "123", &"b".repeat(64)).is_err());
        let bytes = std::fs::read(root.join("MSS-008-123.consumed")).unwrap();
        assert!(String::from_utf8(bytes).unwrap().contains(&digest));
        assert_eq!(root.parent(), Some(temp.as_path()));
        assert!(
            !std::fs::symlink_metadata(&root)
                .unwrap()
                .file_type()
                .is_symlink()
        );
        std::fs::remove_dir_all(root).unwrap();
    }
}
