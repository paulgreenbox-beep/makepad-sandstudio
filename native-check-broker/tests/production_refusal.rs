//! Blackbox v1 compatibility: the unqualified production binary cannot execute
//! a request or mint receipts, even when environment variables claim authority.
use std::{
    io::Write,
    process::{Command, Output, Stdio},
};

fn invoke(input: &[u8], args: &[&str]) -> Output {
    let mut child = Command::new(env!("CARGO_BIN_EXE_mss-native-check-broker"))
        .args(args)
        .env("MSS_QUALIFIED", "true")
        .env("GITHUB_ACTOR", "paulgreenbox-beep")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();
    if let Some(mut stdin) = child.stdin.take() {
        let _ = stdin.write_all(input);
    }
    child.wait_with_output().unwrap()
}
fn request(id: &str) -> Vec<u8> {
    let catalog: serde_json::Value =
        serde_json::from_str(include_str!("../../goals/checks/catalog.json")).unwrap();
    let check = catalog["checks"]
        .as_array()
        .unwrap()
        .iter()
        .find(|c| c["id"] == id)
        .unwrap();
    serde_json::to_vec(&serde_json::json!({"schema":"mss-native-check-request-v1","goal":"MSS-008","attempt":"123","source_commit":"a".repeat(40),"workspace":"C:\\MSS-Runner\\work\\agent","checkout_mode":"fresh-exact-commit","checks":[check]})).unwrap()
}
#[test]
fn real_dispatcher_catalog_ids_parse_but_do_not_grant_execution() {
    for id in ["CORE_TEST", "WORKSPACE_CHECK", "RUST_FMT"] {
        let output = invoke(&request(id), &[]);
        assert_eq!(output.status.code(), Some(3));
        assert!(
            output.stdout.is_empty(),
            "unqualified broker must not emit receipts"
        );
        assert!(
            String::from_utf8(output.stderr)
                .unwrap()
                .contains("BLOCKED")
        );
    }
}
#[test]
fn unknown_fields_and_argument_authority_are_rejected_without_receipts() {
    let mut value: serde_json::Value = serde_json::from_slice(&request("CORE_TEST")).unwrap();
    value["shell"] = serde_json::json!("cmd.exe /c whoami");
    let invalid = invoke(&serde_json::to_vec(&value).unwrap(), &[]);
    assert!(!invalid.status.success());
    assert!(invalid.stdout.is_empty());
    let override_attempt = invoke(&request("CORE_TEST"), &["--execute"]);
    assert!(!override_attempt.status.success());
    assert!(override_attempt.stdout.is_empty());
}
#[test]
fn oversized_input_is_refused_without_a_partial_receipt() {
    let output = invoke(&vec![b' '; 65537], &[]);
    assert!(!output.status.success());
    assert!(output.stdout.is_empty());
}
