//! Fail-closed native check broker protocol foundation.
//! NO EXECUTION: this binary never starts Cargo, Git, shell, or generated code.
//! Qualification and OS isolation are deliberately outside this initial slice.
use serde::Deserialize;
use std::io::{self, Read};

const MAX_BYTES: usize = 64 * 1024;

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct Request {
    schema: String,
    goal: String,
    attempt: String,
    source_commit: String,
    workspace: String,
    checkout_mode: String,
    checks: Vec<Check>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct Check {
    id: String,
    description: String,
    command: Vec<String>,
    requires: Vec<String>,
}

const APPROVED: &[(&str, &[&str])] = &[
    ("RUST_METADATA", &["cargo", "metadata", "--no-deps", "--format-version", "1"]),
    ("RUST_FMT", &["cargo", "fmt", "--all", "--", "--check"]),
    ("RUST_CHECK", &["cargo", "check", "--workspace", "--all-targets"]),
    ("RUST_TEST", &["cargo", "test", "--workspace"]),
    ("RUST_CORE_TEST", &["cargo", "test", "-p", "mss-core"]),
];

fn valid_sha(s: &str) -> bool {
    s.len() == 40 && s.bytes().all(|c| c.is_ascii_hexdigit() && !c.is_ascii_uppercase())
}
fn valid_attempt(s: &str) -> bool {
    !s.is_empty() && s.len() <= 20 && s.bytes().all(|c| c.is_ascii_digit()) && s != "0"
}
fn validate(raw: &[u8]) -> Result<Request, &'static str> {
    let r: Request = serde_json::from_slice(raw).map_err(|_| "REQUEST_SCHEMA_INVALID")?;
    if r.schema != "mss-native-check-request-v1" || r.checkout_mode != "fresh-exact-commit" {
        return Err("REQUEST_PROTOCOL_INVALID");
    }
    if !(r.goal.len() == 7 && r.goal.starts_with("MSS-")
        && r.goal[4..].bytes().all(|c| c.is_ascii_digit())) {
        return Err("GOAL_INVALID");
    }
    if !valid_attempt(&r.attempt) || !valid_sha(&r.source_commit) {
        return Err("SOURCE_IDENTITY_INVALID");
    }
    // The workspace is always data, never launch authority. Any future executor
    // must independently resolve it under a protected, operator-approved root.
    if r.workspace.is_empty() || r.workspace.len() > 1024 || r.workspace.chars().any(char::is_control) {
        return Err("WORKSPACE_INVALID");
    }
    if r.checks.is_empty() || r.checks.len() > APPROVED.len() {
        return Err("CHECK_COUNT_INVALID");
    }
    let mut seen = std::collections::BTreeSet::new();
    for c in &r.checks {
        if !seen.insert(c.id.as_str()) { return Err("DUPLICATE_CHECK"); }
        if c.description.len() > 512 || c.description.is_empty() { return Err("DESCRIPTION_INVALID"); }
        if c.requires.is_empty() || c.requires.len() > 16
            || c.requires.iter().any(|v| v.len() > 64 || v.is_empty()) {
            return Err("REQUIREMENTS_INVALID");
        }
        let Some((_, literal)) = APPROVED.iter().find(|(id, _)| *id == c.id) else {
            return Err("UNAPPROVED_CHECK");
        };
        if c.command.iter().map(String::as_str).collect::<Vec<_>>() != *literal {
            return Err("COMMAND_MISMATCH");
        }
    }
    Ok(r)
}

fn main() {
    // stdout is reserved for valid receipt arrays. Refusals go to stderr.
    if std::env::args_os().len() != 1 {
        eprintln!("BLOCKED: BROKER_ARGUMENTS_FORBIDDEN");
        std::process::exit(2);
    }
    let mut raw = Vec::new();
    if io::stdin().take((MAX_BYTES + 1) as u64).read_to_end(&mut raw).is_err()
        || raw.len() > MAX_BYTES {
        eprintln!("BLOCKED: REQUEST_TOO_LARGE_OR_UNREADABLE");
        std::process::exit(2);
    }
    match validate(&raw) {
        Err(code) => eprintln!("BLOCKED: {code}"),
        Ok(_) => eprintln!("BLOCKED: NATIVE_ISOLATION_AND_CLEAN_CHECKOUT_NOT_QUALIFIED"),
    }
    // Never emit fabricated receipts or PASS, even when request syntax is valid.
    std::process::exit(3);
}

#[cfg(test)]
mod tests {
    use super::*;
    fn request() -> Vec<u8> {
        format!(r#"{{"schema":"mss-native-check-request-v1","goal":"MSS-004","attempt":"123","source_commit":"{}","workspace":"C:\\MSS-Runner\\work\\agent","checkout_mode":"fresh-exact-commit","checks":[{{"id":"RUST_FMT","description":"Rust formatting","command":["cargo","fmt","--all","--","--check"],"requires":["exit_code","commit_sha"]}}]}}"#, "a".repeat(40)).into_bytes()
    }
    #[test] fn valid_shape_but_not_execution_authority() { assert!(validate(&request()).is_ok()); }
    #[test] fn rejects_duplicate_request_keys() {
        let mut s = String::from_utf8(request()).unwrap();
        s = s.replace("\"attempt\":\"123\"", "\"attempt\":\"123\",\"attempt\":\"124\"");
        assert!(validate(s.as_bytes()).is_err());
    }
    #[test] fn rejects_unknown_fields() {
        let mut s = String::from_utf8(request()).unwrap();
        s = s.replace("\"checkout_mode\"", "\"shell\":\"powershell\",\"checkout_mode\"");
        assert!(validate(s.as_bytes()).is_err());
    }
    #[test] fn rejects_shell_substitution() {
        let mut s = String::from_utf8(request()).unwrap();
        s = s.replace("\"cargo\",\"fmt\"", "\"powershell\",\"fmt\"");
        assert!(validate(s.as_bytes()).is_err());
    }
    #[test] fn rejects_unpinned_ref() {
        let mut s = String::from_utf8(request()).unwrap();
        s = s.replace(&"a".repeat(40), "main");
        assert!(validate(s.as_bytes()).is_err());
    }
    #[test] fn rejects_duplicate_checks() {
        let mut s: serde_json::Value = serde_json::from_slice(&request()).unwrap();
        let c = s["checks"][0].clone();
        s["checks"].as_array_mut().unwrap().push(c);
        assert!(validate(serde_json::to_string(&s).unwrap().as_bytes()).is_err());
    }
}
