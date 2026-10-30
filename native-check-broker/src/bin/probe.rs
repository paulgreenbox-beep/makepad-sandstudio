//! Compiled, owner-controlled qualification fixture. Never accept repository code.
#[cfg(windows)]
mod windows_probe {
    use mss_native_check_broker::native::{PinnedImage, Run, current_token_facts};
    use serde_json::json;
    use sha2::{Digest, Sha256};
    use std::{
        fs,
        io::{self, BufRead, Write},
        net::{SocketAddr, TcpStream},
        path::Path,
        process::{Command, Stdio},
        sync::atomic::AtomicBool,
        thread,
        time::Duration,
    };
    use windows_sys::Win32::{
        Foundation::HANDLE,
        System::{JobObjects::IsProcessInJob, Threading::GetCurrentProcess},
    };

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
        json!({"kind":"facts", "token":current_token_facts().expect("probe token"), "in_job":in_job != 0, "forbidden_env":forbidden_env})
    }

    fn supervise(cwd: &Path, child_mode: &str) {
        let executable = std::env::current_exe().expect("own probe image");
        let hash = format!(
            "{:x}",
            Sha256::digest(fs::read(&executable).expect("own probe bytes"))
        );
        let image = PinnedImage::open(&executable, &hash).expect("pin own probe image");
        let args = if child_mode == "sleep" {
            vec!["sleep".to_owned(), "20000".to_owned()]
        } else {
            vec![child_mode.to_owned()]
        };
        let run = Run::launch(image, &args, cwd).expect("launch own restricted probe");
        if child_mode == "sleep" {
            emit(json!({"kind":"supervised-child", "pid":run.pid, "birth":run.birth}));
        }
        let observation = run
            .wait(Duration::from_secs(25), &AtomicBool::new(false))
            .expect("wait own restricted probe");
        if child_mode != "sleep" {
            io::stdout()
                .write_all(&observation.stdout)
                .expect("forward probe report");
            io::stdout().flush().expect("flush probe report");
        }
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
                let mut child = Command::new(std::env::current_exe().expect("own probe image"))
                    .arg("child-marker")
                    .stdout(Stdio::piped())
                    .stderr(Stdio::null())
                    .spawn()
                    .expect("spawn own fixture child");
                let mut line = String::new();
                io::BufReader::new(child.stdout.take().expect("own child stdout"))
                    .read_line(&mut line)
                    .expect("read own child facts");
                print!("{line}");
                io::stdout().flush().expect("forward child facts");
                // Deliberately leave only this owned fixture descendant alive;
                // the supervisor must observe and contain it through the Job.
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
            Some("supervise-facts") if args.len() == 2 => supervise(Path::new(&args[1]), "facts"),
            Some("supervise-sleep") if args.len() == 2 => supervise(Path::new(&args[1]), "sleep"),
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
