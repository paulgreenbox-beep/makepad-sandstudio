#![cfg(windows)]

use std::env;
use std::fs;
use std::io::Write;
use std::path::Path;
use std::process::{Command, Stdio};
use std::time::{SystemTime, UNIX_EPOCH};

#[test]
fn gui_tools_require_owned_app_and_explicit_window() {
    let python = env::var_os("MSS_TEST_PYTHON").unwrap_or_else(|| "python".into());
    let fixture = env::temp_dir().join(format!(
        "mss-gui-contract-{}-{}",
        std::process::id(),
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    let source = Path::new(env!("CARGO_MANIFEST_DIR")).join("tools");
    let tools = fixture.join("MSS_MCP/tools");
    let profiles = fixture.join("MSS_MCP/profiles");
    fs::create_dir_all(&tools).unwrap();
    fs::create_dir_all(&profiles).unwrap();
    for name in [
        "mss_universal.py",
        "mss_profiles.py",
        "mss_builds.py",
        "mss_shared.py",
        "mss_process.py",
        "Start-MakepadMcp.ps1",
    ] {
        fs::copy(source.join(name), tools.join(name)).unwrap();
    }
    fs::write(
        profiles.join("local.apps.json"),
        r#"{"schema_version":1,"launcher_sha256":"","pwsh_sha256":"","profiles":[]}"#,
    )
    .unwrap();

    let mut router = Command::new(python)
        .arg("-B")
        .arg(tools.join("mss_universal.py"))
        .current_dir(&fixture)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("Launch the MSS router with the approved Python runtime");
    let mut requests = router.stdin.take().unwrap();
    writeln!(
        requests,
        r#"{{"jsonrpc":"2.0","id":0,"method":"initialize"}}"#
    )
    .unwrap();
    writeln!(
        requests,
        r#"{{"jsonrpc":"2.0","id":1,"method":"tools/list"}}"#
    )
    .unwrap();
    let cases = [
        (
            "mss_recheck_cleanup",
            r#"{"app_id":"foreign"}"#,
            "INVALID_ARGUMENT",
        ),
        (
            "mss_ui_type",
            r#"{"app_id":[],"node":"1","w":"1:0","t":"x"}"#,
            "INVALID_ARGUMENT",
        ),
        (
            "mss_ui_act",
            r#"{"app_id":"foreign","node":"1","w":"1:0","action":"press","queue_timeout_ms":0}"#,
            "INVALID_ARGUMENT",
        ),
        (
            "mss_ui_key",
            r#"{"app_id":"foreign","w":0,"c":"Tab"}"#,
            "UNKNOWN_APP",
        ),
        (
            "mss_ui_mouse",
            r#"{"app_id":"foreign","w":0,"k":"click","x":1,"y":1}"#,
            "UNKNOWN_APP",
        ),
        (
            "mss_ui_drop",
            r#"{"app_id":"foreign","w":0,"file":"fixture.txt","x":1,"y":1}"#,
            "UNKNOWN_APP",
        ),
        (
            "mss_ui_key",
            r#"{"app_id":"foreign","c":"Tab"}"#,
            "INVALID_ARGUMENT",
        ),
        (
            "mss_ui_mouse",
            r#"{"app_id":"foreign","w":0,"k":"click","x":1,"y":1,"native":true}"#,
            "INVALID_ARGUMENT",
        ),
        (
            "mss_ui_mouse",
            r#"{"app_id":"foreign","w":0,"k":"click","x":true,"y":1}"#,
            "INVALID_ARGUMENT",
        ),
        (
            "mss_ui_drop",
            r#"{"app_id":"foreign","w":0,"path":"fixture.txt","x":1,"y":1}"#,
            "INVALID_ARGUMENT",
        ),
        (
            "mss_ui_key",
            r#"{"app_id":"foreign","w":0,"c":"C","ctrl":true}"#,
            "SHARED_CLIPBOARD",
        ),
        (
            "mss_ui_key",
            r#"{"app_id":"foreign","w":0,"c":"KeyV","ctrl":true}"#,
            "SHARED_CLIPBOARD",
        ),
        (
            "mss_ui_drop",
            r#"{"app_id":"foreign","w":0,"file":"../fixture.txt","x":1,"y":1}"#,
            "INVALID_ARGUMENT",
        ),
        (
            "mss_ui_mouse",
            r#"{"app_id":"foreign","w":0,"k":"drag","x":1,"y":1,"x1":2,"y1":2,"steps":61}"#,
            "INVALID_ARGUMENT",
        ),
    ];
    for (index, (tool, arguments, _)) in cases.iter().enumerate() {
        writeln!(
            requests,
            r#"{{"jsonrpc":"2.0","id":{},"method":"tools/call","params":{{"name":"{tool}","arguments":{arguments}}}}}"#,
            index + 2,
        )
        .unwrap();
    }
    drop(requests);
    let output = router.wait_with_output().unwrap();
    assert!(
        output.status.success(),
        "MSS router exited {:?}: {}",
        output.status,
        String::from_utf8_lossy(&output.stderr)
    );
    let stdout = String::from_utf8(output.stdout).unwrap();
    let replies: Vec<_> = stdout.lines().collect();
    assert_eq!(replies.len(), cases.len() + 2, "{stdout}");
    for name in [
        "mss_ui_key",
        "mss_ui_mouse",
        "mss_ui_drop",
        "mss_list_instances",
        "mss_share_app",
        "mss_attach_app",
        "mss_detach_app",
        "mss_app_participants",
        "mss_operations_list",
        "mss_operation_status",
        "mss_cancel_operation",
        "mss_server_info",
        "mss_recheck_cleanup",
    ] {
        assert!(
            replies[1].contains(&format!(r#""name":"{name}""#)),
            "Missing MCP tool {name}"
        );
    }
    for (index, ((tool, _, expected), response)) in cases.iter().zip(&replies[2..]).enumerate() {
        assert!(
            response.starts_with(&format!(
                r#"{{"jsonrpc":"2.0","id":{},"result":"#,
                index + 2
            )) && response.contains(&format!(r#""structuredContent":{{"code":"{expected}""#))
                && response.ends_with(r#""isError":true}}"#),
            "{tool} expected {expected}, received {response}"
        );
    }
    assert!(
        !fixture.join("proof").exists(),
        "A rejected call created session evidence"
    );
}
