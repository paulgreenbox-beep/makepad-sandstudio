//! Trusted parent-side test helper. This binary is never a restricted child.
#[cfg(windows)]
mod supervisor_probe {
    use mss_native_check_broker::native::{End, PinnedImage, Run};
    use serde_json::json;
    use sha2::{Digest, Sha256};
    use std::{
        fs,
        io::{self, Write},
        path::Path,
        sync::atomic::AtomicBool,
        time::Duration,
    };

    pub fn main() {
        let args: Vec<String> = std::env::args().skip(1).collect();
        let child_mode = match args.first().map(String::as_str) {
            Some("supervise-facts") if args.len() == 3 => "facts",
            Some("supervise-sleep") if args.len() == 3 => "sleep",
            _ => {
                eprintln!("TRUSTED_SUPERVISOR_ARGUMENTS_INVALID");
                std::process::exit(2);
            }
        };
        let executable = fs::canonicalize(Path::new(&args[1])).expect("resolve own child fixture");
        let root = fs::canonicalize(Path::new(&args[2])).expect("resolve own fixture root");
        assert_eq!(
            executable.parent(),
            Some(root.as_path()),
            "child belongs to fixture root"
        );
        assert_eq!(
            executable.file_name().and_then(|s| s.to_str()),
            Some("probe.exe")
        );
        assert!(
            root.file_name()
                .unwrap()
                .to_string_lossy()
                .starts_with("mss-native-probe-")
        );
        assert_ne!(
            executable,
            fs::canonicalize(std::env::current_exe().expect("own supervisor image")).unwrap(),
            "supervisor must never run itself as restricted child"
        );
        let hash = format!(
            "{:x}",
            Sha256::digest(fs::read(&executable).expect("own child fixture bytes"))
        );
        let image = PinnedImage::open(&executable, &hash).expect("pin own compiled child fixture");
        let child_args = if child_mode == "sleep" {
            // Emit actual child facts before holding the process alive for the
            // crash test. Supervisor EOF does not release this fixed hold.
            vec!["child-marker".to_owned()]
        } else {
            vec![child_mode.to_owned()]
        };
        let run = Run::launch(image, &child_args, &root).expect("launch own restricted probe");
        if child_mode == "sleep" {
            let line = run
                .first_stdout_line(Duration::from_secs(5))
                .expect("bounded running-child readiness report");
            let facts: serde_json::Value =
                serde_json::from_slice(&line).expect("typed running-child readiness report");
            let desktop = run
                .desktop_snapshot()
                .expect("read exact owned desktop snapshot");
            assert_eq!(facts["kind"], "facts");
            assert_eq!(facts["pid"], run.pid);
            assert_eq!(facts["thread_id"], run.thread_id);
            assert_eq!(facts["in_job"], true);
            assert_eq!(facts["token"]["restricted"], true);
            assert_eq!(facts["token"]["low_integrity"], true);
            assert_eq!(facts["token"]["elevated"], false);
            assert_eq!(facts["token"]["enabled_admin"], false);
            assert_eq!(facts["token"]["unexpected_enabled_privilege"], false);
            assert_eq!(facts["forbidden_env"], json!([]));
            assert_eq!(facts["win32k_disabled"], true);
            assert_eq!(
                facts["startup_desktop"].as_str(),
                Some(desktop.full_name.as_str())
            );
            let child_desktop_observation = run
                .observe_running_child_desktop()
                .expect("query only the retained running child thread");
            let association_required_result =
                if child_desktop_observation.require_observed().is_ok() {
                    "PASS"
                } else {
                    "BLOCKED"
                };
            println!(
                "{}",
                json!({"kind":"supervised-child", "pid":run.pid, "birth":run.birth,
                    "thread_id":run.thread_id, "child_ready":true, "desktop":desktop,
                    "child_desktop_observation":child_desktop_observation,
                    "association_required_result":association_required_result})
            );
            io::stdout().flush().expect("flush own child identity");
        }
        let observation = run
            .wait(Duration::from_secs(25), &AtomicBool::new(false))
            .expect("wait own restricted probe");
        assert_eq!(
            observation.end,
            End::Exited(0),
            "restricted child failed: {observation:?}"
        );
        assert!(
            observation.cleanup_confirmed,
            "owned child cleanup must be confirmed"
        );
        assert!(
            !observation.output_incomplete,
            "child report must be complete"
        );
        assert!(observation.token.admissible());
        assert!(!observation.desktop_receives_input);
        assert!(observation.parent_desktop_unchanged);
        assert!(observation.station_acl_unchanged);
        assert!(observation.desktop_cleanup_confirmed);
        let (station, desktop) = observation
            .desktop
            .split_once('\\')
            .expect("explicit station and private desktop must be observed");
        assert!(!station.is_empty());
        assert!(!desktop.is_empty());
        assert!(!desktop.eq_ignore_ascii_case("Default"));
        if child_mode != "sleep" {
            io::stdout()
                .write_all(&observation.stdout)
                .expect("forward probe report");
            io::stdout().flush().expect("flush probe report");
        }
    }
}

#[cfg(windows)]
fn main() {
    supervisor_probe::main();
}

#[cfg(not(windows))]
fn main() {
    eprintln!("BLOCKED: NATIVE_WINDOWS_SUPERVISOR_PROBE_ONLY");
    std::process::exit(3);
}
