//! Dispatcher-v1 data validation. Parsing never authenticates a controller,
//! qualifies filesystem/network containment, or authorizes execution.
use serde::Deserialize;
use serde::de::DeserializeOwned;
use std::collections::BTreeSet;

pub const MAX_BYTES: usize = 64 * 1024;
const MAX_CHECKS: usize = 16;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Request {
    pub schema: String,
    pub goal: String,
    pub attempt: String,
    pub source_commit: String,
    pub workspace: String,
    pub checkout_mode: String,
    pub checks: Vec<Check>,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Check {
    pub id: String,
    pub description: String,
    pub command: Vec<String>,
    pub requires: Vec<String>,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Catalog {
    pub schema: String,
    pub checks: Vec<CatalogCheck>,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CatalogCheck {
    pub id: String,
    pub description: String,
    /// Existing manual check obligations have command:null, never an empty argv.
    pub command: Option<Vec<String>>,
    pub requires: Vec<String>,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct GoalManifest {
    pub schema: String,
    pub goals: Vec<GoalIndexEntry>,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct GoalIndexEntry {
    pub id: String,
    pub path: String,
}

/// Existing mss-goal-v1 shape, not an alternative task registry.
#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Goal {
    pub schema: String,
    pub id: String,
    pub title: String,
    pub module_ids: Vec<String>,
    pub status: String,
    pub branch: Option<String>,
    pub pr_url: Option<String>,
    pub owner_agent: Option<String>,
    pub source_commit: Option<String>,
    pub dependencies: Vec<String>,
    pub acceptance: Vec<String>,
    pub required_checks: Vec<GoalCheck>,
    pub notes: String,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct GoalCheck {
    pub id: String,
    pub status: String,
    pub evidence_ref: Option<String>,
}

/// Must be obtained from an authenticated protected controller grant.
/// Copying stdin into this struct establishes no authority.
#[derive(Clone, Debug)]
pub struct ExecutionBinding {
    pub goal: String,
    pub attempt: String,
    pub source_commit: String,
    pub workspace: String,
    pub branch: String,
    pub owner_agent: String,
}

/// Projection of independently trusted dispatcher policy, not Issue/model input.
#[derive(Clone, Debug)]
pub struct ApprovedScope {
    pub checks: Vec<String>,
    pub allowed_commands: Vec<Vec<String>>,
}

/// A validated data binding with deliberately no execution or receipt method.
pub struct BoundRequest<'a> {
    request: &'a Request,
    checks: Vec<&'a CatalogCheck>,
}

impl<'a> BoundRequest<'a> {
    pub fn request(&self) -> &'a Request {
        self.request
    }
    pub fn checks(&self) -> &[&'a CatalogCheck] {
        &self.checks
    }
}

fn valid_goal(value: &str) -> bool {
    value.len() == 7
        && value.starts_with("MSS-")
        && value.as_bytes()[4..].iter().all(u8::is_ascii_digit)
        && value != "MSS-000"
}

fn valid_sha(value: &str) -> bool {
    value.len() == 40
        && value
            .bytes()
            .all(|c| c.is_ascii_hexdigit() && !c.is_ascii_uppercase())
        && value.bytes().any(|c| c != b'0')
}

fn valid_attempt(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 20
        && value.bytes().all(|c| c.is_ascii_digit())
        && value
            .parse::<u64>()
            .is_ok_and(|n| n > 0 && n.to_string() == value)
}

fn valid_check_id(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 64
        && value.as_bytes()[0].is_ascii_uppercase()
        && value
            .bytes()
            .all(|c| c.is_ascii_uppercase() || c.is_ascii_digit() || c == b'_')
}

/// Lexical full Win32 drive path only. Actual canonical file handles, reparse
/// checks, ACL and ownership must be established by the qualified executor.
fn valid_workspace(value: &str) -> bool {
    let bytes = value.as_bytes();
    if bytes.len() <= 3
        || bytes.len() > 1024
        || !bytes[0].is_ascii_uppercase()
        || bytes[1] != b':'
        || bytes[2] != b'\\'
    {
        return false;
    }
    value[3..].split('\\').all(|part| {
        if part.is_empty()
            || part == "."
            || part == ".."
            || part.ends_with(['.', ' '])
            || part
                .chars()
                .any(|c| c.is_control() || "/:*?\"<>|".contains(c))
        {
            return false;
        }
        let stem = part
            .split('.')
            .next()
            .unwrap_or_default()
            .to_ascii_uppercase();
        !matches!(
            stem.as_str(),
            "CON" | "PRN" | "AUX" | "NUL" | "CONIN$" | "CONOUT$"
        ) && !(stem.len() == 4
            && (stem.starts_with("COM") || stem.starts_with("LPT"))
            && matches!(stem.as_bytes()[3], b'1'..=b'9'))
            && !["COM¹", "COM²", "COM³", "LPT¹", "LPT²", "LPT³"].contains(&stem.as_str())
    })
}

fn validate_check_shape(check: &Check) -> Result<(), &'static str> {
    if !valid_check_id(&check.id) {
        return Err("CHECK_ID_INVALID");
    }
    if check.description.is_empty()
        || check.description.len() > 512
        || check.description.chars().any(char::is_control)
    {
        return Err("DESCRIPTION_INVALID");
    }
    let mut requirements = BTreeSet::new();
    if check.requires.is_empty()
        || check.requires.len() > 16
        || check.requires.iter().any(|r| {
            r.is_empty()
                || r.len() > 64
                || !r.bytes().all(|c| c.is_ascii_alphanumeric() || c == b'_')
                || !requirements.insert(r)
        })
    {
        return Err("REQUIREMENTS_INVALID");
    }
    // Logical current catalog tool names only, never an executable path or PATH authority.
    if !matches!(
        check.command.first().map(String::as_str),
        Some("cargo" | "node")
    ) || check.command.len() > 32
        || check
            .command
            .iter()
            .any(|arg| arg.is_empty() || arg.len() > 1024 || arg.chars().any(char::is_control))
    {
        return Err("COMMAND_SHAPE_INVALID");
    }
    Ok(())
}

fn decode<T: DeserializeOwned>(raw: &[u8]) -> Result<T, &'static str> {
    if raw.len() > MAX_BYTES {
        return Err("DOCUMENT_TOO_LARGE");
    }
    serde_json::from_slice(raw).map_err(|_| "DOCUMENT_SCHEMA_INVALID")
}

pub fn parse_catalog(raw: &[u8]) -> Result<Catalog, &'static str> {
    let catalog = decode(raw)?;
    validate_catalog(&catalog)?;
    Ok(catalog)
}

pub fn parse_manifest(raw: &[u8]) -> Result<GoalManifest, &'static str> {
    let manifest = decode(raw)?;
    validate_manifest(&manifest)?;
    Ok(manifest)
}

pub fn parse_goal(raw: &[u8]) -> Result<Goal, &'static str> {
    let goal = decode(raw)?;
    validate_goal(&goal)?;
    Ok(goal)
}

fn validate_catalog(catalog: &Catalog) -> Result<(), &'static str> {
    if catalog.schema != "mss-check-catalog-v1"
        || catalog.checks.is_empty()
        || catalog.checks.len() > 256
        || catalog
            .checks
            .iter()
            .map(|c| &c.id)
            .collect::<BTreeSet<_>>()
            .len()
            != catalog.checks.len()
    {
        return Err("CATALOG_INVALID");
    }
    for entry in &catalog.checks {
        // A dummy logical name validates metadata without making a null/manual
        // command executable. bind_request rejects the selected null command.
        validate_check_shape(&Check {
            id: entry.id.clone(),
            description: entry.description.clone(),
            command: entry
                .command
                .clone()
                .unwrap_or_else(|| vec!["cargo".into()]),
            requires: entry.requires.clone(),
        })?;
    }
    Ok(())
}

fn validate_manifest(manifest: &GoalManifest) -> Result<(), &'static str> {
    if manifest.schema != "mss-goal-index-v1"
        || manifest.goals.is_empty()
        || manifest.goals.len() > 256
        || manifest
            .goals
            .iter()
            .map(|g| &g.id)
            .collect::<BTreeSet<_>>()
            .len()
            != manifest.goals.len()
        || manifest
            .goals
            .iter()
            .any(|g| !valid_goal(&g.id) || g.path != format!("goals/{}.json", g.id))
    {
        return Err("GOAL_NOT_INDEXED");
    }
    Ok(())
}

fn validate_goal(goal: &Goal) -> Result<(), &'static str> {
    if goal.schema != "mss-goal-v1"
        || !valid_goal(&goal.id)
        || goal.title.is_empty()
        || goal.title.len() > 512
        || goal.title.chars().any(char::is_control)
        || goal.module_ids.is_empty()
        || goal.module_ids.len() > 16
        || goal.module_ids.iter().any(|id| {
            !id.starts_with("mss.")
                || id.len() > 64
                || !id
                    .bytes()
                    .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || b"._".contains(&c))
        })
        || goal.module_ids.iter().collect::<BTreeSet<_>>().len() != goal.module_ids.len()
        || ![
            "TODO",
            "IN_PROGRESS",
            "IN_REVIEW",
            "VERIFIED",
            "BLOCKED",
            "FAILED",
        ]
        .contains(&goal.status.as_str())
        || goal.source_commit.as_deref().is_some_and(|s| !valid_sha(s))
        || goal.dependencies.len() > 32
        || goal.dependencies.iter().any(|id| !valid_goal(id))
        || goal.dependencies.iter().collect::<BTreeSet<_>>().len() != goal.dependencies.len()
        || goal.acceptance.is_empty()
        || goal.acceptance.len() > 32
        || goal
            .acceptance
            .iter()
            .any(|s| s.is_empty() || s.len() > 4096)
        || goal.required_checks.is_empty()
        || goal.required_checks.len() > MAX_CHECKS
        || goal
            .required_checks
            .iter()
            .map(|c| &c.id)
            .collect::<BTreeSet<_>>()
            .len()
            != goal.required_checks.len()
        || goal.required_checks.iter().any(|c| {
            !valid_check_id(&c.id)
                || !["NOT_RUN", "PASS", "FAIL", "BLOCKED", "UNKNOWN"].contains(&c.status.as_str())
        })
        || goal.notes.len() > 8192
    {
        return Err("GOAL_DOCUMENT_INVALID");
    }
    Ok(())
}

pub fn parse_request(raw: &[u8]) -> Result<Request, &'static str> {
    if raw.len() > MAX_BYTES {
        return Err("REQUEST_TOO_LARGE");
    }
    // Derived struct visitors reject duplicate known keys, including nested Check keys.
    let request: Request = serde_json::from_slice(raw).map_err(|_| "REQUEST_SCHEMA_INVALID")?;
    validate_request_shape(&request)?;
    Ok(request)
}

fn validate_request_shape(request: &Request) -> Result<(), &'static str> {
    if request.schema != "mss-native-check-request-v1"
        || request.checkout_mode != "fresh-exact-commit"
    {
        return Err("REQUEST_PROTOCOL_INVALID");
    }
    if !valid_goal(&request.goal) {
        return Err("GOAL_INVALID");
    }
    if !valid_attempt(&request.attempt) || !valid_sha(&request.source_commit) {
        return Err("SOURCE_IDENTITY_INVALID");
    }
    if !valid_workspace(&request.workspace) {
        return Err("WORKSPACE_INVALID");
    }
    if request.checks.is_empty() || request.checks.len() > MAX_CHECKS {
        return Err("CHECK_COUNT_INVALID");
    }
    let mut seen = BTreeSet::new();
    for check in &request.checks {
        if !seen.insert(&check.id) {
            return Err("DUPLICATE_CHECK");
        }
        validate_check_shape(check)?;
    }
    Ok(())
}

pub fn bind_request<'a>(
    request: &'a Request,
    manifest: &GoalManifest,
    goal: &Goal,
    catalog: &'a Catalog,
    scope: &ApprovedScope,
    expected: &ExecutionBinding,
) -> Result<BoundRequest<'a>, &'static str> {
    validate_request_shape(request)?;
    validate_manifest(manifest)?;
    validate_goal(goal)?;
    validate_catalog(catalog)?;
    if !valid_goal(&expected.goal)
        || !valid_attempt(&expected.attempt)
        || !valid_sha(&expected.source_commit)
        || !valid_workspace(&expected.workspace)
        || request.goal != expected.goal
        || request.attempt != expected.attempt
        || request.source_commit != expected.source_commit
        || request.workspace != expected.workspace
    {
        return Err("EXECUTION_BINDING_MISMATCH");
    }
    if manifest.schema != "mss-goal-index-v1"
        || manifest
            .goals
            .iter()
            .filter(|entry| entry.id == request.goal)
            .count()
            != 1
        || !manifest.goals.iter().any(|entry| {
            entry.id == request.goal && entry.path == format!("goals/{}.json", request.goal)
        })
    {
        return Err("GOAL_NOT_INDEXED");
    }
    if goal.schema != "mss-goal-v1"
        || goal.id != request.goal
        || goal.status != "IN_PROGRESS"
        || goal.branch.as_deref() != Some(expected.branch.as_str())
        || goal.owner_agent.as_deref() != Some(expected.owner_agent.as_str())
        || !expected
            .branch
            .strip_prefix("codex/issue-")
            .is_some_and(valid_attempt)
        || expected.owner_agent.is_empty()
    {
        return Err("GOAL_BINDING_MISMATCH");
    }
    if catalog.schema != "mss-check-catalog-v1"
        || catalog.checks.len() > 256
        || catalog
            .checks
            .iter()
            .map(|c| &c.id)
            .collect::<BTreeSet<_>>()
            .len()
            != catalog.checks.len()
    {
        return Err("CATALOG_INVALID");
    }
    if goal.required_checks.len() != request.checks.len()
        || goal
            .required_checks
            .iter()
            .map(|c| &c.id)
            .collect::<BTreeSet<_>>()
            .len()
            != goal.required_checks.len()
    {
        return Err("GOAL_CHECK_SET_MISMATCH");
    }
    let mut selected = Vec::new();
    for (requested, required) in request.checks.iter().zip(&goal.required_checks) {
        validate_check_shape(requested)?;
        if requested.id != required.id || !scope.checks.contains(&requested.id) {
            return Err("GOAL_CHECK_SET_MISMATCH");
        }
        let check = catalog
            .checks
            .iter()
            .find(|c| c.id == requested.id)
            .ok_or("UNAPPROVED_CHECK")?;
        let command = check.command.as_ref().ok_or("MANUAL_CHECK_REQUIRED")?;
        if requested.description != check.description
            || requested.requires != check.requires
            || requested.command != *command
            || !scope.allowed_commands.contains(command)
        {
            return Err("CATALOG_OR_POLICY_MISMATCH");
        }
        selected.push(check);
    }
    Ok(BoundRequest {
        request,
        checks: selected,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::{Value, json};

    fn request() -> Vec<u8> {
        format!(r#"{{"schema":"mss-native-check-request-v1","goal":"MSS-004","attempt":"123","source_commit":"{}","workspace":"C:\\MSS-Runner\\work\\agent","checkout_mode":"fresh-exact-commit","checks":[{{"id":"RUST_FMT","description":"Rust formatting","command":["cargo","fmt","--all","--","--check"],"requires":["exit_code","commit_sha"]}}]}}"#, "a".repeat(40)).into_bytes()
    }
    fn mutate(key: &str, value: Value) -> Vec<u8> {
        let mut raw: Value = serde_json::from_slice(&request()).unwrap();
        raw[key] = value;
        serde_json::to_vec(&raw).unwrap()
    }
    fn fixtures() -> (
        Request,
        GoalManifest,
        Goal,
        Catalog,
        ApprovedScope,
        ExecutionBinding,
    ) {
        let request = parse_request(&request()).unwrap();
        let check = request.checks[0].clone();
        let manifest = GoalManifest {
            schema: "mss-goal-index-v1".into(),
            goals: vec![GoalIndexEntry {
                id: request.goal.clone(),
                path: "goals/MSS-004.json".into(),
            }],
        };
        let goal: Goal = serde_json::from_value(json!({"schema":"mss-goal-v1","id":"MSS-004","title":"Fixture","module_ids":["mss.skills"],"status":"IN_PROGRESS","branch":"codex/issue-8","pr_url":null,"owner_agent":"codex-issue-worker","source_commit":"b".repeat(40),"dependencies":[],"acceptance":["Exact check"],"required_checks":[{"id":"RUST_FMT","status":"NOT_RUN","evidence_ref":null}],"notes":"Protocol fixture only"})).unwrap();
        let catalog = Catalog {
            schema: "mss-check-catalog-v1".into(),
            checks: vec![CatalogCheck {
                id: check.id.clone(),
                description: check.description,
                command: Some(check.command.clone()),
                requires: check.requires,
            }],
        };
        let scope = ApprovedScope {
            checks: vec![check.id],
            allowed_commands: vec![check.command],
        };
        let binding = ExecutionBinding {
            goal: request.goal.clone(),
            attempt: request.attempt.clone(),
            source_commit: request.source_commit.clone(),
            workspace: request.workspace.clone(),
            branch: "codex/issue-8".into(),
            owner_agent: "codex-issue-worker".into(),
        };
        (request, manifest, goal, catalog, scope, binding)
    }
    #[test]
    fn valid_shape_but_not_execution_authority() {
        assert!(parse_request(&request()).is_ok());
    }
    #[test]
    fn rejects_duplicate_request_keys() {
        let raw = String::from_utf8(request()).unwrap().replace(
            "\"attempt\":\"123\"",
            "\"attempt\":\"123\",\"attempt\":\"124\"",
        );
        assert_eq!(parse_request(raw.as_bytes()), Err("REQUEST_SCHEMA_INVALID"));
    }
    #[test]
    fn rejects_unknown_fields() {
        assert!(parse_request(&mutate("shell", json!("powershell"))).is_err());
        let raw = String::from_utf8(request())
            .unwrap()
            .replace("\"description\"", "\"extra\":1,\"description\"");
        assert!(parse_request(raw.as_bytes()).is_err());
    }
    #[test]
    fn rejects_shell_substitution() {
        let raw = String::from_utf8(request())
            .unwrap()
            .replace("\"cargo\",\"fmt\"", "\"powershell\",\"fmt\"");
        assert_eq!(parse_request(raw.as_bytes()), Err("COMMAND_SHAPE_INVALID"));
    }
    #[test]
    fn rejects_unpinned_ref() {
        assert_eq!(
            parse_request(&mutate("source_commit", json!("main"))),
            Err("SOURCE_IDENTITY_INVALID")
        );
    }
    #[test]
    fn rejects_duplicate_checks() {
        let check = serde_json::from_slice::<Value>(&request()).unwrap()["checks"][0].clone();
        assert_eq!(
            parse_request(&mutate("checks", json!([check.clone(), check]))),
            Err("DUPLICATE_CHECK")
        );
    }
    #[test]
    fn rejects_nested_duplicate_keys_and_oversized_input() {
        let raw = String::from_utf8(request()).unwrap().replace(
            "\"id\":\"RUST_FMT\"",
            "\"id\":\"RUST_FMT\",\"id\":\"CORE_TEST\"",
        );
        assert_eq!(parse_request(raw.as_bytes()), Err("REQUEST_SCHEMA_INVALID"));
        assert_eq!(
            parse_request(&vec![b' '; MAX_BYTES + 1]),
            Err("REQUEST_TOO_LARGE")
        );
    }
    #[test]
    fn rejects_noncanonical_identifiers() {
        for attempt in ["", "0", "00", "01", "+1", " 1", "18446744073709551616"] {
            assert!(parse_request(&mutate("attempt", json!(attempt))).is_err());
        }
        for goal in ["MSS-000", "mss-001", "MSS-1", "MSS-001 ", "MSS-€"] {
            assert!(parse_request(&mutate("goal", json!(goal))).is_err());
        }
        for sha in ["0".repeat(40), "A".repeat(40), "a".repeat(39)] {
            assert!(parse_request(&mutate("source_commit", json!(sha))).is_err());
        }
    }
    #[test]
    fn rejects_windows_path_aliases_without_claiming_filesystem_proof() {
        for workspace in [
            "work",
            "C:work",
            "c:\\work",
            "C:\\",
            "C:/work",
            "\\\\server\\share\\work",
            "\\\\?\\C:\\work",
            "C:\\work\\..\\other",
            "C:\\work\\file:stream",
            "C:\\work\\NUL.txt",
            "C:\\work\\COM1",
            "C:\\work\\name.",
            "C:\\work\\name ",
            "C:\\work\\\\other",
        ] {
            assert!(
                parse_request(&mutate("workspace", json!(workspace))).is_err(),
                "{workspace}"
            );
        }
    }
    #[test]
    fn exact_trusted_catalog_and_goal_binding_preserves_dispatcher_shape() {
        let (request, manifest, goal, catalog, scope, expected) = fixtures();
        let bound = bind_request(&request, &manifest, &goal, &catalog, &scope, &expected).unwrap();
        assert_eq!(bound.request(), &request);
        assert_eq!(bound.checks()[0].id, "RUST_FMT");
    }
    #[test]
    fn real_catalog_ids_are_supported_without_invented_aliases() {
        let catalog: Catalog =
            serde_json::from_str(include_str!("../../goals/checks/catalog.json")).unwrap();
        for id in ["CORE_TEST", "WORKSPACE_CHECK"] {
            let (mut request, manifest, mut goal, _, mut scope, expected) = fixtures();
            let check = catalog.checks.iter().find(|c| c.id == id).unwrap();
            request.checks = vec![Check {
                id: check.id.clone(),
                description: check.description.clone(),
                command: check.command.clone().unwrap(),
                requires: check.requires.clone(),
            }];
            goal.required_checks[0].id = id.into();
            scope.checks = vec![id.into()];
            scope.allowed_commands = vec![request.checks[0].command.clone()];
            assert!(bind_request(&request, &manifest, &goal, &catalog, &scope, &expected).is_ok());
        }
    }
    #[test]
    fn rejects_stale_foreign_or_unindexed_binding() {
        let (request, mut manifest, goal, catalog, scope, expected) = fixtures();
        for change in 0..4 {
            let mut foreign = expected.clone();
            match change {
                0 => foreign.goal = "MSS-003".into(),
                1 => foreign.attempt = "124".into(),
                2 => foreign.source_commit = "b".repeat(40),
                _ => foreign.workspace = "C:\\MSS-Runner\\work\\other".into(),
            }
            assert!(bind_request(&request, &manifest, &goal, &catalog, &scope, &foreign).is_err());
        }
        manifest.goals.push(manifest.goals[0].clone());
        assert!(bind_request(&request, &manifest, &goal, &catalog, &scope, &expected).is_err());
    }
    #[test]
    fn rejects_metadata_tampering_manual_checks_and_shell_arguments() {
        let (request, manifest, goal, mut catalog, scope, expected) = fixtures();
        for change in 0..4 {
            let mut altered = request.clone();
            match change {
                0 => altered.checks[0].description.push_str(" altered"),
                1 => altered.checks[0].requires.push("invented".into()),
                2 => altered.checks[0].command.push(";calc.exe".into()),
                _ => altered.checks[0].id = "RUST_CORE_TEST".into(),
            }
            assert!(bind_request(&altered, &manifest, &goal, &catalog, &scope, &expected).is_err());
        }
        catalog.checks[0].command = None;
        assert!(matches!(
            bind_request(&request, &manifest, &goal, &catalog, &scope, &expected),
            Err("MANUAL_CHECK_REQUIRED")
        ));
    }
    #[test]
    fn required_check_set_and_policy_cannot_be_weakened() {
        let (request, manifest, mut goal, catalog, mut scope, expected) = fixtures();
        scope.allowed_commands.clear();
        assert!(bind_request(&request, &manifest, &goal, &catalog, &scope, &expected).is_err());
        scope.allowed_commands = vec![request.checks[0].command.clone()];
        goal.required_checks.push(GoalCheck {
            id: "CORE_TEST".into(),
            status: "NOT_RUN".into(),
            evidence_ref: None,
        });
        assert!(bind_request(&request, &manifest, &goal, &catalog, &scope, &expected).is_err());
        goal.required_checks.pop();
        goal.status = "VERIFIED".into();
        assert!(bind_request(&request, &manifest, &goal, &catalog, &scope, &expected).is_err());
    }

    #[test]
    fn typed_documents_reject_unknown_and_duplicate_fields() {
        let catalog = include_str!("../../goals/checks/catalog.json");
        assert!(parse_catalog(catalog.as_bytes()).is_ok());
        let duplicate = catalog.replacen(
            "\"schema\":",
            "\"schema\":\"mss-check-catalog-v1\",\"schema\":",
            1,
        );
        assert!(parse_catalog(duplicate.as_bytes()).is_err());
        let manifest = include_str!("../../goals/manifest.json");
        assert!(parse_manifest(manifest.as_bytes()).is_ok());
        let unknown = manifest.replacen("\"schema\":", "\"shell\":\"cmd\",\"schema\":", 1);
        assert!(parse_manifest(unknown.as_bytes()).is_err());
        let goal = include_str!("../../goals/MSS-004.json");
        assert!(parse_goal(goal.as_bytes()).is_ok());
        let duplicate = goal.replacen("\"status\":", "\"status\":\"TODO\",\"status\":", 1);
        assert!(parse_goal(duplicate.as_bytes()).is_err());
    }

    #[test]
    fn real_null_command_catalog_entries_cannot_be_executed() {
        let catalog = parse_catalog(include_bytes!("../../goals/checks/catalog.json")).unwrap();
        for id in ["WINDOWS_DESKTOP", "TOOLKIT_PARITY"] {
            let (mut request, manifest, mut goal, _, mut scope, expected) = fixtures();
            let entry = catalog.checks.iter().find(|check| check.id == id).unwrap();
            request.checks = vec![Check {
                id: id.into(),
                description: entry.description.clone(),
                command: vec!["cargo".into()],
                requires: entry.requires.clone(),
            }];
            goal.required_checks[0].id = id.into();
            scope.checks = vec![id.into()];
            assert!(matches!(
                bind_request(&request, &manifest, &goal, &catalog, &scope, &expected),
                Err("MANUAL_CHECK_REQUIRED")
            ));
        }
    }

    #[test]
    fn constructed_requests_cannot_bypass_raw_parser_invariants() {
        let (mut request, manifest, goal, catalog, scope, expected) = fixtures();
        request.schema = "other-protocol".into();
        assert!(bind_request(&request, &manifest, &goal, &catalog, &scope, &expected).is_err());
        let (request, manifest, goal, catalog, scope, mut expected) = fixtures();
        expected.branch = "main".into();
        assert!(bind_request(&request, &manifest, &goal, &catalog, &scope, &expected).is_err());
    }
}
