//! Real OS probes, not mocks or authorization for repository-code execution.
#![cfg(all(windows, feature = "native-probes"))]

use mss_native_check_broker::native::{End, Observation, PinnedImage, Run, fixture_acl};
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::{
    fs::{self, File, OpenOptions},
    io::{BufRead, BufReader, Read},
    os::windows::io::AsRawHandle,
    path::{Path, PathBuf},
    process::{Command, Stdio},
    sync::{
        Mutex,
        atomic::{AtomicBool, AtomicU64, Ordering},
    },
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};
use windows_sys::Win32::{
    Foundation::*,
    Security::{Authorization::ConvertSecurityDescriptorToStringSecurityDescriptorW, *},
    Storage::FileSystem::READ_CONTROL,
    System::{StationsAndDesktops::*, Threading::*},
};

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

struct DesktopWitness(HDESK);
impl DesktopWitness {
    fn close_checked(mut self) {
        assert_ne!(
            unsafe { CloseDesktop(self.0) },
            0,
            "close only our desktop witness"
        );
        self.0 = std::ptr::null_mut();
    }
}
impl Drop for DesktopWitness {
    fn drop(&mut self) {
        if !self.0.is_null() {
            unsafe { CloseDesktop(self.0) };
        }
    }
}

fn user_object_name(object: HANDLE) -> String {
    let mut bytes = 0;
    unsafe { GetUserObjectInformationW(object, UOI_NAME, std::ptr::null_mut(), 0, &mut bytes) };
    assert!(
        bytes > 0 && bytes <= 65_536,
        "bounded owned user-object name"
    );
    let mut name = vec![0u16; (bytes as usize).div_ceil(2)];
    assert_ne!(
        unsafe {
            GetUserObjectInformationW(
                object,
                UOI_NAME,
                name.as_mut_ptr().cast(),
                bytes,
                &mut bytes,
            )
        },
        0,
        "read owned user-object name"
    );
    let length = name
        .iter()
        .position(|c| *c == 0)
        .expect("terminated owned object name");
    String::from_utf16(&name[..length]).expect("owned object name UTF-16")
}

fn user_object_security_sha256(object: HANDLE) -> String {
    let info = OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION | LABEL_SECURITY_INFORMATION;
    let mut bytes = 0;
    unsafe { GetUserObjectSecurity(object, &info, std::ptr::null_mut(), 0, &mut bytes) };
    assert!(
        bytes > 0 && bytes <= 65_536,
        "bounded owned security descriptor"
    );
    let mut descriptor = vec![0usize; (bytes as usize).div_ceil(size_of::<usize>())];
    assert_ne!(
        unsafe {
            GetUserObjectSecurity(
                object,
                &info,
                descriptor.as_mut_ptr().cast(),
                bytes,
                &mut bytes,
            )
        },
        0,
        "read owned object owner, DACL and label"
    );
    let mut text = std::ptr::null_mut();
    let mut length = 0;
    assert_ne!(
        unsafe {
            ConvertSecurityDescriptorToStringSecurityDescriptorW(
                descriptor.as_mut_ptr().cast(),
                1,
                info,
                &mut text,
                &mut length,
            )
        },
        0,
        "canonical owned security descriptor"
    );
    let units = unsafe { std::slice::from_raw_parts(text, length as usize) };
    let value = String::from_utf16_lossy(
        &units[..units.iter().position(|c| *c == 0).unwrap_or(units.len())],
    );
    unsafe { LocalFree(text.cast()) };
    format!("{:x}", Sha256::digest(value.as_bytes()))
}

fn verify_desktop_witness(witness: &DesktopWitness, name: &str, security_sha256: &str) {
    assert!(
        user_object_name(witness.0) == name,
        "desktop witness must have the exact owned name"
    );
    assert!(
        user_object_security_sha256(witness.0) == security_sha256,
        "desktop witness owner, DACL and label must match the owned snapshot"
    );
    let mut input = 0i32;
    assert_ne!(
        unsafe {
            GetUserObjectInformationW(
                witness.0,
                UOI_IO,
                (&mut input as *mut i32).cast(),
                size_of_val(&input) as u32,
                std::ptr::null_mut(),
            )
        },
        0,
        "query owned desktop input state"
    );
    assert_eq!(input, 0, "owned desktop must never receive user input");
}

struct Fixture {
    root: PathBuf,
    temp: PathBuf,
    image: PathBuf,
    supervisor: PathBuf,
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
        let supervisor = root.join("supervisor.exe");
        fs::copy(
            env!("CARGO_BIN_EXE_mss-broker-supervisor-probe"),
            &supervisor,
        )
        .expect("copy own compiled supervisor fixture image");
        fixture_acl(&supervisor, true, true).expect("set owned supervisor image ACL");
        let hash = format!("{:x}", Sha256::digest(fs::read(&image).unwrap()));
        Self {
            root,
            temp,
            image,
            supervisor,
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
        if let Err(error) = fs::remove_dir_all(&self.root) {
            if !std::thread::panicking() {
                panic!(
                    "owned native fixture cleanup failed (win32={:?}); retain evidence and investigate",
                    error.raw_os_error()
                );
            }
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
    private_desktop(observation);
}

fn private_desktop(observation: &Observation) {
    let (station, desktop) = observation
        .desktop
        .split_once('\\')
        .expect("explicit station and private desktop must be observed");
    assert!(!station.is_empty());
    assert!(!desktop.is_empty());
    assert!(
        !desktop.eq_ignore_ascii_case("Default"),
        "never use the user desktop"
    );
    assert!(!observation.desktop_receives_input);
    assert!(observation.parent_desktop_unchanged);
    assert!(observation.station_acl_unchanged);
    assert!(observation.desktop_cleanup_confirmed);
}

fn child_desktop_and_mitigation(observation: &Observation, value: &Value) {
    private_desktop(observation);
    assert_eq!(
        value["startup_desktop"].as_str(),
        Some(observation.desktop.as_str())
    );
    assert_eq!(value["win32k_disabled"], true);
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
    child_desktop_and_mitigation(&observation, &value);
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
    let output = Command::new(&fixture.supervisor)
        .arg("supervise-facts")
        .arg(&fixture.image)
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
    assert_eq!(value["win32k_disabled"], true);
    assert!(
        !value["startup_desktop"]
            .as_str()
            .unwrap()
            .rsplit('\\')
            .next()
            .unwrap()
            .eq_ignore_ascii_case("Default")
    );
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
    private_desktop(&timeout);
    let cancelled = fixture
        .launch(&["sleep", "20000"])
        .wait(Duration::from_secs(5), &AtomicBool::new(true))
        .unwrap();
    assert_eq!(cancelled.end, End::Cancelled);
    assert!(cancelled.cleanup_confirmed);
    private_desktop(&cancelled);
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
    assert!(
        observation.process_handles_waited >= 2,
        "both primary and the held-live descendant must have signalled retained handles"
    );
    assert!(!observation.output_incomplete);
    let child = report(&observation);
    child_desktop_and_mitigation(&observation, &child);
    assert_eq!(child["in_job"], true);
    assert_eq!(child["token"]["restricted"], true);
    assert_eq!(child["token"]["elevated"], false);
    assert_eq!(child["token"]["low_integrity"], true);
    assert_eq!(child["token"]["enabled_admin"], false);
    assert_eq!(child["token"]["unexpected_enabled_privilege"], false);
    assert_eq!(child["forbidden_env"], serde_json::json!([]));
}

#[test]
fn cancellation_does_not_terminate_a_simultaneous_unrelated_owned_job() {
    let _serial = SERIAL
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner());
    let cancelled_fixture = Fixture::new();
    let survivor_fixture = Fixture::new();
    let cancelled_run = cancelled_fixture.launch(&["sleep", "20000"]);
    let survivor_run = survivor_fixture.launch(&["sleep", "20000"]);
    assert_ne!(cancelled_run.pid, survivor_run.pid);
    let raw_survivor = unsafe {
        OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZATION_SYNCHRONIZE,
            0,
            survivor_run.pid,
        )
    };
    assert!(
        !raw_survivor.is_null(),
        "query only our retained Run's process"
    );
    let survivor_handle = ProcessHandle(raw_survivor);
    let mut creation = FILETIME {
        dwLowDateTime: 0,
        dwHighDateTime: 0,
    };
    let mut exit = creation;
    let mut kernel = creation;
    let mut user = creation;
    assert_ne!(
        unsafe {
            GetProcessTimes(
                survivor_handle.0,
                &mut creation,
                &mut exit,
                &mut kernel,
                &mut user,
            )
        },
        0
    );
    assert_eq!(
        ((creation.dwHighDateTime as u64) << 32) | creation.dwLowDateTime as u64,
        survivor_run.birth
    );
    assert_eq!(
        unsafe { WaitForSingleObject(survivor_handle.0, 0) },
        WAIT_TIMEOUT
    );
    let cancelled = cancelled_run
        .wait(Duration::from_secs(5), &AtomicBool::new(true))
        .unwrap();
    assert_eq!(cancelled.end, End::Cancelled);
    assert!(cancelled.cleanup_confirmed);
    private_desktop(&cancelled);
    assert_eq!(
        unsafe { WaitForSingleObject(survivor_handle.0, 0) },
        WAIT_TIMEOUT,
        "a distinct owned Job must remain alive after cancellation of its peer"
    );
    let survivor = survivor_run
        .wait(Duration::from_secs(5), &AtomicBool::new(true))
        .unwrap();
    assert_eq!(survivor.end, End::Cancelled);
    assert!(survivor.cleanup_confirmed);
    assert!(survivor.token.admissible());
    private_desktop(&survivor);
    assert_ne!(
        cancelled.desktop, survivor.desktop,
        "each owned Run has its own desktop"
    );
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
    private_desktop(&observation);
}

#[test]
fn supervisor_loss_closes_job_and_terminates_verified_child() {
    let _serial = SERIAL
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner());
    let fixture = Fixture::new();
    let initial_station = unsafe { GetProcessWindowStation() };
    assert!(
        !initial_station.is_null(),
        "observe only our current station"
    );
    let initial_station_name = user_object_name(initial_station);
    let supervisor_started = Instant::now();
    let mut supervisor = OwnedSupervisor(
        Command::new(&fixture.supervisor)
            .arg("supervise-sleep")
            .arg(&fixture.image)
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
        let result = BufReader::new(stdout).take(8193).read_line(&mut line);
        let _ = send.send((result, line));
    });
    let (read, line) = receive
        .recv_timeout(Duration::from_secs(5))
        .expect("bounded supervisor identity report");
    read.expect("read supervisor identity");
    reader.join().unwrap();
    assert!(
        line.len() <= 8192 && line.ends_with('\n'),
        "supervisor metadata must be bounded and complete"
    );
    let value: Value = serde_json::from_str(&line).expect("owned child identity report");
    assert_eq!(value["kind"], "supervised-child");
    assert_eq!(value["child_ready"], true);
    assert_ne!(
        value["thread_id"].as_u64().expect("owned ready thread ID"),
        0
    );
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
    assert_eq!(
        unsafe { WaitForSingleObject(handle.0, 0) },
        WAIT_TIMEOUT,
        "verified fixture child must still be alive before supervisor loss"
    );

    let snapshot = &value["desktop"];
    let full_name = snapshot["full_name"]
        .as_str()
        .expect("owned full desktop name");
    let (station_name, desktop_name) = full_name
        .split_once('\\')
        .expect("owned desktop must identify its station");
    assert!(
        station_name.eq_ignore_ascii_case(&initial_station_name),
        "open the owned desktop only within our unchanged current station"
    );
    assert!(!desktop_name.eq_ignore_ascii_case("Default"));
    assert!(
        desktop_name
            .strip_prefix("mss-probe-")
            .is_some_and(|nonce| {
                nonce.len() == 32 && nonce.bytes().all(|c| c.is_ascii_hexdigit())
            }),
        "accept only the exact private fixture desktop identity"
    );
    assert_eq!(snapshot["receives_input"], false);
    let security_sha256 = snapshot["security_sha256"]
        .as_str()
        .expect("owned desktop security fingerprint");
    assert!(security_sha256.len() == 64 && security_sha256.bytes().all(|c| c.is_ascii_hexdigit()));

    let association = &value["child_desktop_observation"];
    match association["status"]
        .as_str()
        .expect("typed running desktop query status")
    {
        "OBSERVED" => {
            assert!(
                association["full_name"].as_str() == Some(full_name),
                "actual running desktop must match the owned desktop"
            );
            assert!(
                association["security_sha256"].as_str() == Some(security_sha256),
                "actual running desktop must match the owned security fingerprint"
            );
            assert_eq!(association["receives_input"], false);
            assert_eq!(value["association_required_result"], "PASS");
            println!(
                "MSS_USER32_QUERY status=OBSERVED win32=none association_required_result=PASS"
            );
        }
        "QUERY_UNAVAILABLE" => {
            let win32 = association["win32"]
                .as_u64()
                .expect("raw USER32 query error");
            assert_eq!(value["association_required_result"], "BLOCKED");
            // This verifies refusal, and never establishes GUI association.
            println!(
                "MSS_USER32_QUERY status=QUERY_UNAVAILABLE win32={win32} association_required_result=BLOCKED"
            );
        }
        _ => panic!("unsupported running desktop query status"),
    }

    assert!(
        unsafe { GetProcessWindowStation() } == initial_station,
        "observer station must remain unchanged"
    );
    let desktop_wide: Vec<u16> = desktop_name.encode_utf16().chain(Some(0)).collect();
    let access = READ_CONTROL | DESKTOP_READOBJECTS | DESKTOP_WRITEOBJECTS;
    let witness_raw = unsafe { OpenDesktopW(desktop_wide.as_ptr(), 0, 0, access) };
    let witness_error = unsafe { GetLastError() };
    assert!(
        !witness_raw.is_null(),
        "owned desktop must exist before supervisor loss: win32={witness_error}"
    );
    let witness = DesktopWitness(witness_raw);
    verify_desktop_witness(&witness, desktop_name, security_sha256);
    assert_eq!(
        unsafe { WaitForSingleObject(handle.0, 0) },
        WAIT_TIMEOUT,
        "verified fixture child must remain alive immediately before supervisor loss"
    );
    assert!(
        supervisor_started.elapsed() < Duration::from_secs(10),
        "crash proof must precede the child's fixed twenty-second natural exit"
    );
    // std::process::Child owns the supervisor process handle; never kill by name/PID.
    supervisor
        .0
        .kill()
        .expect("terminate own supervisor via retained handle");
    assert_eq!(
        unsafe { WaitForSingleObject(supervisor.0.as_raw_handle().cast(), 5000) },
        WAIT_OBJECT_0,
        "own supervisor must terminate within the crash proof bound"
    );
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
    assert!(
        supervisor_started.elapsed() < Duration::from_secs(20),
        "child death must precede its fixed twenty-second natural exit"
    );
    // Our witness intentionally keeps the same object alive until child death.
    // Disappearance is tested only after explicitly releasing that last witness.
    verify_desktop_witness(&witness, desktop_name, security_sha256);
    witness.close_checked();
    let cleanup_start = Instant::now();
    loop {
        assert!(
            unsafe { GetProcessWindowStation() } == initial_station,
            "observer station must remain unchanged throughout cleanup proof"
        );
        unsafe { SetLastError(ERROR_SUCCESS) };
        let reopened = unsafe { OpenDesktopW(desktop_wide.as_ptr(), 0, 0, access) };
        let error = unsafe { GetLastError() };
        if reopened.is_null() {
            assert_eq!(
                error, ERROR_FILE_NOT_FOUND,
                "only object absence proves desktop cleanup; access denial is not absence"
            );
            break;
        }
        let transient = DesktopWitness(reopened);
        verify_desktop_witness(&transient, desktop_name, security_sha256);
        transient.close_checked();
        assert!(
            cleanup_start.elapsed() < Duration::from_secs(3),
            "owned desktop remains after supervisor and child death"
        );
        std::thread::sleep(Duration::from_millis(10));
    }
    assert!(
        unsafe { GetProcessWindowStation() } == initial_station,
        "observer station must remain unchanged after cleanup proof"
    );
    println!("MSS_CRASH_DESKTOP before_exists=true after_absent=true");
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
