//! Compiled, owner-controlled qualification fixture. Never accept repository code.
#[cfg(windows)]
mod windows_probe {
    use serde_json::json;
    use std::{
        fs,
        io::{self, BufRead, Write},
        net::{SocketAddr, TcpStream},
        os::windows::{
            ffi::OsStrExt,
            io::{AsRawHandle, FromRawHandle},
        },
        thread,
        time::Duration,
    };
    use windows_sys::Win32::{
        Foundation::{
            CloseHandle, GetLastError, HANDLE, HANDLE_FLAG_INHERIT, SetHandleInformation,
        },
        Security::*,
        System::{
            JobObjects::IsProcessInJob,
            Pipes::CreatePipe,
            SystemServices::{PROCESS_MITIGATION_SYSTEM_CALL_DISABLE_POLICY, SE_GROUP_ENABLED},
            Threading::*,
        },
    };

    struct Token(HANDLE);
    impl Drop for Token {
        fn drop(&mut self) {
            unsafe { CloseHandle(self.0) };
        }
    }

    // Keep the restricted child independent from the broker library and USER32.
    // These queries observe the child's effective token rather than echoing a
    // parent-side launch request. u64 storage supplies alignment for token data.
    fn token_data(token: HANDLE, class: TOKEN_INFORMATION_CLASS) -> Vec<u64> {
        let mut required = 0;
        unsafe { GetTokenInformation(token, class, std::ptr::null_mut(), 0, &mut required) };
        let size_error = unsafe { GetLastError() };
        assert_ne!(
            required, 0,
            "probe token query size: class={class}, win32={size_error}"
        );
        let mut data = vec![0u64; (required as usize).div_ceil(size_of::<u64>())];
        let ok = unsafe {
            GetTokenInformation(
                token,
                class,
                data.as_mut_ptr().cast(),
                required,
                &mut required,
            )
        };
        let query_error = unsafe { GetLastError() };
        assert_ne!(
            ok, 0,
            "probe token query: class={class}, win32={query_error}, required={required}"
        );
        data
    }

    fn token_facts() -> serde_json::Value {
        let mut token = std::ptr::null_mut();
        assert_ne!(
            unsafe { OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &mut token) },
            0,
            "probe own token"
        );
        let token = Token(token);
        let elevation = token_data(token.0, TokenElevation);
        let elevated =
            unsafe { (*elevation.as_ptr().cast::<TOKEN_ELEVATION>()).TokenIsElevated != 0 };
        let mut admin = [0u64; 9];
        let mut admin_size = size_of_val(&admin) as u32;
        assert_ne!(
            unsafe {
                CreateWellKnownSid(
                    WinBuiltinAdministratorsSid,
                    std::ptr::null_mut(),
                    admin.as_mut_ptr().cast(),
                    &mut admin_size,
                )
            },
            0,
            "probe admin SID"
        );
        let group_data = token_data(token.0, TokenGroups);
        let groups = unsafe { &*group_data.as_ptr().cast::<TOKEN_GROUPS>() };
        let groups = unsafe {
            std::slice::from_raw_parts(groups.Groups.as_ptr(), groups.GroupCount as usize)
        };
        let enabled_admin = groups.iter().any(|group| {
            (unsafe { EqualSid(group.Sid, admin.as_ptr().cast_mut().cast()) != 0 })
                && group.Attributes & SE_GROUP_ENABLED as u32 != 0
        });
        let integrity = token_data(token.0, TokenIntegrityLevel);
        let label = unsafe { &*integrity.as_ptr().cast::<TOKEN_MANDATORY_LABEL>() };
        let count = unsafe { *GetSidSubAuthorityCount(label.Label.Sid) };
        assert_ne!(count, 0, "probe integrity SID");
        let rid = unsafe { *GetSidSubAuthority(label.Label.Sid, (count - 1) as u32) };
        let mut notify = unsafe { std::mem::zeroed() };
        let notify_name: Vec<u16> = "SeChangeNotifyPrivilege"
            .encode_utf16()
            .chain(Some(0))
            .collect();
        assert_ne!(
            unsafe { LookupPrivilegeValueW(std::ptr::null(), notify_name.as_ptr(), &mut notify) },
            0,
            "probe privilege LUID"
        );
        let privilege_data = token_data(token.0, TokenPrivileges);
        let privileges = unsafe { &*privilege_data.as_ptr().cast::<TOKEN_PRIVILEGES>() };
        let privileges = unsafe {
            std::slice::from_raw_parts(
                privileges.Privileges.as_ptr(),
                privileges.PrivilegeCount as usize,
            )
        };
        let unexpected_enabled_privilege = privileges.iter().any(|privilege| {
            privilege.Attributes & SE_PRIVILEGE_ENABLED != 0
                && (privilege.Luid.LowPart != notify.LowPart
                    || privilege.Luid.HighPart != notify.HighPart)
        });
        json!({
            "restricted":unsafe { IsTokenRestricted(token.0) != 0 },
            "elevated":elevated,
            "enabled_admin":enabled_admin,
            "low_integrity":rid == 4096,
            "unexpected_enabled_privilege":unexpected_enabled_privilege,
        })
    }

    fn startup_desktop() -> String {
        let mut startup = unsafe { std::mem::zeroed::<STARTUPINFOW>() };
        unsafe { GetStartupInfoW(&mut startup) };
        assert!(
            !startup.lpDesktop.is_null(),
            "probe explicit startup desktop"
        );
        let mut length = 0;
        while length < 32_768 && unsafe { *startup.lpDesktop.add(length) } != 0 {
            length += 1;
        }
        assert!(length < 32_768, "probe bounded startup desktop");
        String::from_utf16(unsafe { std::slice::from_raw_parts(startup.lpDesktop, length) })
            .expect("probe startup desktop UTF-16")
    }

    fn win32k_disabled() -> bool {
        let mut policy =
            unsafe { std::mem::zeroed::<PROCESS_MITIGATION_SYSTEM_CALL_DISABLE_POLICY>() };
        assert_ne!(
            unsafe {
                GetProcessMitigationPolicy(
                    GetCurrentProcess(),
                    ProcessSystemCallDisablePolicy,
                    (&mut policy as *mut PROCESS_MITIGATION_SYSTEM_CALL_DISABLE_POLICY).cast(),
                    size_of_val(&policy),
                )
            },
            0,
            "probe actual Win32k mitigation"
        );
        unsafe { policy.Anonymous.Flags & 1 != 0 }
    }

    fn spawn_owned_descendant() {
        // std::process::Command leaves lpDesktop null. Supply an explicit startup
        // desktop so the descendant can independently report the actual creation
        // contract, while retaining inherited token, Job and Win32k restrictions.
        let executable = std::env::current_exe().expect("own probe image");
        let image: Vec<u16> = executable
            .as_os_str()
            .encode_wide()
            .chain(Some(0))
            .collect();
        let mut command: Vec<u16> = format!("\"{}\" child-marker", executable.display())
            .encode_utf16()
            .chain(Some(0))
            .collect();
        let mut desktop: Vec<u16> = startup_desktop().encode_utf16().chain(Some(0)).collect();
        let mut read = std::ptr::null_mut();
        let mut write = std::ptr::null_mut();
        let security = SECURITY_ATTRIBUTES {
            nLength: size_of::<SECURITY_ATTRIBUTES>() as u32,
            lpSecurityDescriptor: std::ptr::null_mut(),
            bInheritHandle: 1,
        };
        assert_ne!(
            unsafe { CreatePipe(&mut read, &mut write, &security, 0) },
            0,
            "owned descendant pipe"
        );
        let read = Token(read);
        let write = Token(write);
        assert_ne!(
            unsafe { SetHandleInformation(read.0, HANDLE_FLAG_INHERIT, 0) },
            0,
            "parent pipe not inherited"
        );
        let input = fs::File::open("NUL").expect("own descendant null input");
        assert_ne!(
            unsafe {
                SetHandleInformation(
                    input.as_raw_handle().cast(),
                    HANDLE_FLAG_INHERIT,
                    HANDLE_FLAG_INHERIT,
                )
            },
            0,
            "own null input inheritance"
        );
        let handles: [HANDLE; 2] = [input.as_raw_handle().cast(), write.0];
        let mut bytes = 0;
        unsafe { InitializeProcThreadAttributeList(std::ptr::null_mut(), 1, 0, &mut bytes) };
        assert_ne!(bytes, 0, "owned descendant attribute size");
        struct Attributes(Vec<usize>);
        impl Drop for Attributes {
            fn drop(&mut self) {
                unsafe { DeleteProcThreadAttributeList(self.0.as_mut_ptr().cast()) };
            }
        }
        let mut storage = vec![0usize; bytes.div_ceil(size_of::<usize>())];
        assert_ne!(
            unsafe {
                InitializeProcThreadAttributeList(storage.as_mut_ptr().cast(), 1, 0, &mut bytes)
            },
            0,
            "owned descendant attributes"
        );
        let mut attributes = Attributes(storage);
        assert_ne!(
            unsafe {
                UpdateProcThreadAttribute(
                    attributes.0.as_mut_ptr().cast(),
                    0,
                    PROC_THREAD_ATTRIBUTE_HANDLE_LIST as usize,
                    handles.as_ptr().cast(),
                    size_of_val(&handles),
                    std::ptr::null_mut(),
                    std::ptr::null(),
                )
            },
            0,
            "owned descendant handles"
        );
        let mut startup = unsafe { std::mem::zeroed::<STARTUPINFOEXW>() };
        startup.StartupInfo.cb = size_of::<STARTUPINFOEXW>() as u32;
        startup.StartupInfo.lpDesktop = desktop.as_mut_ptr();
        startup.StartupInfo.dwFlags = STARTF_USESTDHANDLES;
        startup.StartupInfo.hStdInput = handles[0];
        startup.StartupInfo.hStdOutput = handles[1];
        startup.StartupInfo.hStdError = handles[1];
        startup.lpAttributeList = attributes.0.as_mut_ptr().cast();
        let mut process = unsafe { std::mem::zeroed::<PROCESS_INFORMATION>() };
        assert_ne!(
            unsafe {
                CreateProcessW(
                    image.as_ptr(),
                    command.as_mut_ptr(),
                    std::ptr::null(),
                    std::ptr::null(),
                    1,
                    DETACHED_PROCESS | EXTENDED_STARTUPINFO_PRESENT,
                    std::ptr::null(),
                    std::ptr::null(),
                    &startup.StartupInfo,
                    &mut process,
                )
            },
            0,
            "spawn only owned fixture descendant"
        );
        let _process = Token(process.hProcess);
        let _thread = Token(process.hThread);
        drop(write);
        let file = unsafe { fs::File::from_raw_handle(read.0.cast()) };
        std::mem::forget(read);
        let mut line = String::new();
        io::BufReader::new(file)
            .read_line(&mut line)
            .expect("read own child facts");
        print!("{line}");
        io::stdout().flush().expect("forward child facts");
        // Deliberately leave only this owned fixture descendant alive; the
        // supervisor must observe and contain it through the Job.
    }

    fn emit(value: serde_json::Value) {
        println!("{value}");
        io::stdout().flush().expect("probe stdout");
    }

    fn facts() -> serde_json::Value {
        let mut in_job = 0;
        let ok = unsafe { IsProcessInJob(GetCurrentProcess(), std::ptr::null_mut(), &mut in_job) };
        assert_ne!(ok, 0, "probe job query");
        let forbidden_env: Vec<_> = [
            "OPENAI_API_KEY",
            "CODEX_API_KEY",
            "GH_TOKEN",
            "GITHUB_TOKEN",
            "USERPROFILE",
            "MSS_SENTINEL_SECRET",
        ]
        .into_iter()
        .filter(|key| std::env::var_os(key).is_some())
        .collect();
        json!({"kind":"facts", "token":token_facts(), "in_job":in_job != 0,
            "forbidden_env":forbidden_env, "startup_desktop":startup_desktop(),
            "win32k_disabled":win32k_disabled()})
    }

    pub fn main() {
        let args: Vec<String> = std::env::args().skip(1).collect();
        match args.first().map(String::as_str) {
            Some("facts") => emit(facts()),
            Some("files") if args.len() == 5 => {
                let allowed_read = fs::read(&args[1]).is_ok();
                let allowed_write = fs::write(&args[1], b"owned allowed output").is_ok();
                let secret_read_error = fs::read(&args[2]).err().and_then(|e| e.raw_os_error());
                let sibling_read_error = fs::read(&args[3]).err().and_then(|e| e.raw_os_error());
                let outside_write_error = fs::write(&args[4], b"must not be written")
                    .err()
                    .and_then(|e| e.raw_os_error());
                emit(
                    json!({"kind":"files", "allowed_read":allowed_read, "allowed_write":allowed_write, "secret_read_error":secret_read_error, "sibling_read_error":sibling_read_error, "outside_write_error":outside_write_error}),
                );
            }
            Some("handle") if args.len() == 2 => {
                use windows_sys::Win32::Foundation::{GetHandleInformation, GetLastError};
                let handle = args[1].parse::<usize>().expect("numeric fixture handle") as HANDLE;
                let mut flags = 0;
                let ok = unsafe { GetHandleInformation(handle, &mut flags) };
                let error = if ok == 0 {
                    unsafe { GetLastError() }
                } else {
                    0
                };
                emit(json!({"kind":"handle", "query_succeeded":ok != 0, "win32_error":error}));
            }
            Some("sleep") if args.len() == 2 => {
                let millis = args[1].parse::<u64>().expect("fixture sleep").min(20_000);
                thread::sleep(Duration::from_millis(millis));
            }
            Some("child-marker") => {
                emit(facts());
                thread::sleep(Duration::from_secs(20));
            }
            Some("spawn-child") => {
                spawn_owned_descendant();
            }
            Some("flood") => {
                let bytes = vec![b'x'; 131_072];
                io::stdout()
                    .write_all(&bytes)
                    .expect("bounded fixture flood");
            }
            Some("connect") if args.len() == 2 => {
                let address: SocketAddr = args[1].parse().expect("owned loopback endpoint");
                assert!(address.ip().is_loopback(), "probe never connects remotely");
                let result = TcpStream::connect_timeout(&address, Duration::from_secs(2));
                let connected = result.is_ok();
                let error = result.err().and_then(|e| e.raw_os_error());
                emit(json!({"kind":"connect", "connected":connected, "win32_error":error}));
            }
            _ => {
                eprintln!("TRUSTED_PROBE_ARGUMENTS_INVALID");
                std::process::exit(2);
            }
        }
    }
}

#[cfg(windows)]
fn main() {
    windows_probe::main();
}

#[cfg(not(windows))]
fn main() {
    eprintln!("BLOCKED: NATIVE_WINDOWS_PROBE_ONLY");
    std::process::exit(3);
}
