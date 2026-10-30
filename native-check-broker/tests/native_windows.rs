//! Real OS probes, not mocks or authorization for repository-code execution.
#![cfg(all(windows, feature = "native-probes"))]

use mss_native_check_broker::native::{End, Observation, PinnedImage, Run, fixture_acl};
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::{
    fs::{self, File, OpenOptions},
    io::{BufRead, BufReader},
    os::windows::io::AsRawHandle,
    path::{Path, PathBuf},
    process::{Command, Stdio},
    sync::{
        Mutex,
        atomic::{AtomicBool, AtomicU64, Ordering},
    },
    time::{Duration, SystemTime, UNIX_EPOCH},
};
use windows_sys::Win32::{Foundation::*, System::Threading::*};

static SERIAL: Mutex<()> = Mutex::new(());
static SEQUENCE: AtomicU64 = AtomicU64::new(0);

struct OwnedSupervisor(std::process::Child);
impl Drop for OwnedSupervisor {
    fn drop(&mut self) {
        if !matches!(self.0.try_wait(), Ok(Some(_))) {
            // This Child retains the exact fixture-created supervisor handle.
            let _ = self.0.kill();
            let _ = self.0.wait();
        }
    }
}

struct ProcessHandle(HANDLE);
impl Drop for ProcessHandle {
    fn drop(&mut self) {
        unsafe {
            CloseHandle(self.0);
        }
    }
}

struct Fixture {
    root: PathBuf,
    temp: PathBuf,
    image: PathBuf,
    hash: String,
}

impl Fixture {
    fn new() -> Self {
        let temp = fs::canonicalize(std::env::temp_dir()).expect("resolve owned fixture parent");
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let root = temp.join(format!(
            "mss-native-probe-{}-{nonce}-{}",
            std::process::id(),
            SEQUENCE.fetch_add(1, Ordering::SeqCst)
        ));
        fs::create_dir(&root).expect("create fresh owned fixture");
        fixture_acl(&root, true, true).expect("set owned fixture ACL");
        let image = root.join("probe.exe");
        fs::copy(env!("CARGO_BIN_EXE_mss-broker-probe"), &image)
            .expect("copy own compiled fixture image");
        fixture_acl(&image, true, true).expect("set owned image ACL");
        let hash = format!("{:x}", Sha256::digest(fs::read(&image).unwrap()));
        Self {
            root,
            temp,
            image,
            hash,
        }
    }

    fn pin(&self) -> PinnedImage {
        PinnedImage::open(&self.image, &self.hash).expect("pin exact owned probe bytes")
    }

    fn launch(&self, args: &[&str]) -> Run {
        let args = args.iter().map(|s| (*s).to_owned()).collect::<Vec<_>>();
        Run::launch(self.pin(), &args, &self.root).expect("launch real native restricted fixture")
    }

    fn run(&self, args: &[&str]) -> Observation {
        self.launch(args)
            .wait(Duration::from_secs(8), &AtomicBool::new(false))
            .expect("observe native fixture")
    }

    fn private_file(&self, name: &str) -> PathBuf {
        let path = self.root.join(name);
        fs::write(&path, b"owned synthetic sentinel; never a real credential").unwrap();
        fixture_acl(&path, false, false).expect("set private sentinel ACL");
        path
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        assert_eq!(self.root.parent(), Some(self.temp.as_path()));
        assert!(
            self.root
                .file_name()
                .unwrap()
                .to_string_lossy()
                .starts_with("mss-native-probe-")
        );
        assert!(
            !fs::symlink_metadata(&self.root)
                .unwrap()
                .file_type()
                .is_symlink()
        );
        if fs::remove_dir_all(&self.root).is_err() && !std::thread::panicking() {
            panic!("owned native fixture cleanup failed; retain evidence and investigate");
        }
    }
}

fn report(observation: &Observation) -> Value {
    serde_json::from_slice(&observation.stdout).expect("bounded typed fixture report")
}

fn normal(observation: &Observation) {
    assert_eq!(
        observation.end,
        End::Exited(0),
        "fixture did not exit normally: {observation:?}"
    );
    assert!(observation.cleanup_confirmed);
    assert!(!observation.output_incomplete);
    assert!(observation.token.admissible());
    assert_ne!(observation.pid, 0);
    assert_ne!(observation.birth, 0);
}

#[test]
fn effective_restricted_token_and_job_are_observed_in_the_child() {
    let _serial = SERIAL
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner());
    let fixture = Fixture::new();
    let observation = fixture.run(&["facts"]);
    normal(&observation);
    let value = report(&observation);
    assert_eq!(value["in_job"], true);
    assert_eq!(value["token"]["restricted"], true);
    assert_eq!(value["token"]["low_integrity"], true);
    assert_eq!(value["token"]["elevated"], false);
    assert_eq!(value["token"]["enabled_admin"], false);
    assert_eq!(value["token"]["unexpected_enabled_privilege"], false);
    assert_eq!(value["forbidden_env"], serde_json::json!([]));
}

#[test]
fn os_denies_private_secret_sibling_reads_and_outside_write() {
    let _serial = SERIAL
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner());
    let fixture = Fixture::new();
    let allowed = fixture.root.join("allowed.txt");
    fs::write(&allowed, b"owned allowed input").unwrap();
    fixture_acl(&allowed, true, true).unwrap();
    let secret = fixture.private_file("private-secret.txt");
    let sibling = fixture.private_file("sibling-session.txt");
    let outside = fixture.private_file("outside-allowed-root.txt");
    let outside_before = fs::read(&outside).unwrap();
    let args = [
        "files",
        allowed.to_str().unwrap(),
        secret.to_str().unwrap(),
        sibling.to_str().unwrap(),
        outside.to_str().unwrap(),
    ];
    let observation = fixture.run(&args);
    normal(&observation);
    let value = report(&observation);
    assert_eq!(value["allowed_read"], true);
    assert_eq!(value["allowed_write"], true);
    // ERROR_ACCESS_DENIED from the actual Windows file operations, not parser refusal.
    assert_eq!(value["secret_read_error"], 5);
    assert_eq!(value["sibling_read_error"], 5);
    assert_eq!(value["outside_write_error"], 5);
    assert_eq!(fs::read(&outside).unwrap(), outside_before);
}

#[test]
fn image_digest_and_held_file_object_prevent_replacement() {
    let _serial = SERIAL
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner());
    let fixture = Fixture::new();
    let error = PinnedImage::open(&fixture.image, &"0".repeat(64))
        .err()
        .expect("wrong image digest must be rejected");
    assert_eq!(error.operation, "image-hash-mismatch");
    let pin = fixture.pin();
    assert_eq!(
        OpenOptions::new()
            .write(true)
            .open(&fixture.image)
            .err()
            .unwrap()
            .raw_os_error(),
        Some(32)
    );
    assert_eq!(
        fs::remove_file(&fixture.image)
            .err()
            .unwrap()
            .raw_os_error(),
        Some(32)
    );
    drop(pin);
    assert!(OpenOptions::new().write(true).open(&fixture.image).is_ok());
}

#[test]
fn unrelated_inheritable_secret_handle_is_not_passed_to_child() {
    let _serial = SERIAL
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner());
    let fixture = Fixture::new();
    let secret = fixture.private_file("handle-secret.txt");
    let handle = File::open(secret).unwrap();
    assert_ne!(
        unsafe {
            SetHandleInformation(
                handle.as_raw_handle().cast(),
                HANDLE_FLAG_INHERIT,
                HANDLE_FLAG_INHERIT,
            )
        },
        0
    );
    let number = (handle.as_raw_handle() as usize).to_string();
    let observation = fixture.run(&["handle", &number]);
    normal(&observation);
    let value = report(&observation);
    assert_eq!(value["query_succeeded"], false);
    assert_eq!(value["win32_error"], 6); // ERROR_INVALID_HANDLE
}

#[test]
fn synthetic_parent_secret_environment_and_profile_do_not_reach_child() {
    let _serial = SERIAL
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner());
    let fixture = Fixture::new();
    let output = Command::new(&fixture.image)
        .arg("supervise-facts")
        .arg(&fixture.root)
        .env_clear()
        .env("SystemRoot", std::env::var_os("SystemRoot").unwrap())
        .env(
            "MSS_SENTINEL_SECRET",
            "owned-synthetic-value-not-a-real-secret",
        )
        .env("USERPROFILE", &fixture.root)
        .output()
        .expect("launch own trusted supervisor fixture");
    assert!(output.status.success(), "trusted supervisor fixture failed");
    let value: Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(value["forbidden_env"], serde_json::json!([]));
    assert_eq!(value["token"]["restricted"], true);
}

#[test]
fn timeout_and_cancellation_terminate_only_owned_job() {
    let _serial = SERIAL
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner());
    let fixture = Fixture::new();
    let timeout = fixture
        .launch(&["sleep", "20000"])
        .wait(Duration::from_millis(150), &AtomicBool::new(false))
        .unwrap();
    assert_eq!(timeout.end, End::TimedOut);
    assert!(timeout.cleanup_confirmed);
    let cancelled = fixture
        .launch(&["sleep", "20000"])
        .wait(Duration::from_secs(5), &AtomicBool::new(true))
        .unwrap();
    assert_eq!(cancelled.end, End::Cancelled);
    assert!(cancelled.cleanup_confirmed);
    normal(&fixture.run(&["facts"])); // A separate owned session remains usable.
}

#[test]
fn descendant_outlives_primary_then_job_cleanup_is_verified() {
    let _serial = SERIAL
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner());
    let fixture = Fixture::new();
    let observation = fixture.run(&["spawn-child"]);
    assert_eq!(observation.end, End::DescendantsRemaining);
    assert!(observation.cleanup_confirmed);
    assert!(!observation.output_incomplete);
    let child = report(&observation);
    assert_eq!(child["in_job"], true);
    assert_eq!(child["token"]["restricted"], true);
    assert_eq!(child["token"]["elevated"], false);
}

#[test]
fn bounded_output_is_marked_incomplete_instead_of_accepted() {
    let _serial = SERIAL
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner());
    let fixture = Fixture::new();
    let observation = fixture.run(&["flood"]);
    assert_eq!(observation.end, End::Exited(0));
    assert!(observation.cleanup_confirmed);
    assert!(observation.output_incomplete);
    assert_eq!(observation.stdout.len(), 65_536);
}

#[test]
fn supervisor_loss_closes_job_and_terminates_verified_child() {
    let _serial = SERIAL
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner());
    let fixture = Fixture::new();
    let mut supervisor = OwnedSupervisor(
        Command::new(&fixture.image)
            .arg("supervise-sleep")
            .arg(&fixture.root)
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
            .expect("launch own supervisor"),
    );
    let stdout = supervisor.0.stdout.take().unwrap();
    let (send, receive) = std::sync::mpsc::channel();
    let reader = std::thread::spawn(move || {
        let mut line = String::new();
        let result = BufReader::new(stdout).read_line(&mut line);
        let _ = send.send((result, line));
    });
    let (read, line) = receive
        .recv_timeout(Duration::from_secs(5))
        .expect("bounded supervisor identity report");
    read.expect("read supervisor identity");
    reader.join().unwrap();
    let value: Value = serde_json::from_str(&line).expect("owned child identity report");
    let pid = value["pid"].as_u64().unwrap() as u32;
    let birth = value["birth"].as_u64().unwrap();
    let raw_handle = unsafe {
        OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_TERMINATE | SYNCHRONIZATION_SYNCHRONIZE,
            0,
            pid,
        )
    };
    assert!(!raw_handle.is_null(), "open only the fixture-created child");
    let handle = ProcessHandle(raw_handle);
    let mut creation = FILETIME {
        dwLowDateTime: 0,
        dwHighDateTime: 0,
    };
    let mut exit = creation;
    let mut kernel = creation;
    let mut user = creation;
    assert_ne!(
        unsafe { GetProcessTimes(handle.0, &mut creation, &mut exit, &mut kernel, &mut user) },
        0
    );
    assert_eq!(
        ((creation.dwHighDateTime as u64) << 32) | creation.dwLowDateTime as u64,
        birth
    );
    let mut image = vec![0u16; 32768];
    let mut len = image.len() as u32;
    assert_ne!(
        unsafe { QueryFullProcessImageNameW(handle.0, 0, image.as_mut_ptr(), &mut len) },
        0
    );
    assert_eq!(
        fs::canonicalize(Path::new(&String::from_utf16_lossy(&image[..len as usize]))).unwrap(),
        fs::canonicalize(&fixture.image).unwrap()
    );
    // std::process::Child owns the supervisor process handle; never kill by name/PID.
    supervisor
        .0
        .kill()
        .expect("terminate own supervisor via retained handle");
    supervisor.0.wait().unwrap();
    let waited = unsafe { WaitForSingleObject(handle.0, 5000) };
    if waited != WAIT_OBJECT_0 {
        // The verified retained handle is the only allowed recovery target.
        unsafe {
            TerminateProcess(handle.0, 0x4d5353);
            WaitForSingleObject(handle.0, 3000);
        }
    }
    assert_eq!(
        waited, WAIT_OBJECT_0,
        "owned child survived supervisor loss"
    );
}

#[test]
#[ignore = "NOT_RUN: requires separately provisioned and qualified WFP denial; no network boundary is supplied by token/Job"]
fn network_policy_denies_an_owned_listening_loopback_endpoint() {
    let _serial = SERIAL
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner());
    let fixture = Fixture::new();
    let listener = std::net::TcpListener::bind((std::net::Ipv4Addr::LOCALHOST, 0)).unwrap();
    let address = listener.local_addr().unwrap();
    // A trusted control can reach a genuinely listening endpoint. A closed port is not evidence.
    let control = std::net::TcpStream::connect(address).unwrap();
    let observation = fixture.run(&["connect", &address.to_string()]);
    normal(&observation);
    let value = report(&observation);
    assert_eq!(value["connected"], false);
    assert_eq!(value["win32_error"], 10013); // WSAEACCES, not WSAECONNREFUSED.
    drop(control);
    drop(listener);
}

#[test]
#[ignore = "NOT_RUN: requires local developer-mode symlink permission; no privilege is enabled automatically"]
fn image_ancestor_symlink_is_rejected_before_execution() {
    let _serial = SERIAL
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner());
    let fixture = Fixture::new();
    let link = fixture.root.join("link");
    std::os::windows::fs::symlink_dir(&fixture.root, &link)
        .expect("create only owned symlink fixture");
    let error = PinnedImage::open(&link.join("probe.exe"), &fixture.hash)
        .err()
        .expect("reparse ancestor must be rejected");
    assert_eq!(error.operation, "reparse-parent");
    fs::remove_dir(&link).expect("remove only owned symlink");
}
