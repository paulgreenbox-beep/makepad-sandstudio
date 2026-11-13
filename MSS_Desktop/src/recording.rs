use makepad_widgets::makepad_platform::makepad_micro_serde::{DeJson, JsonValue, SerJson};
use makepad_widgets::makepad_platform::makepad_network::digest::sha256_hash;
use std::{
    collections::{HashMap, HashSet},
    fs::{self, File, Metadata, OpenOptions},
    io::{self, Read, Write},
    path::{Component, Path, PathBuf},
    sync::atomic::{AtomicU64, Ordering},
    time::{Instant, SystemTime, UNIX_EPOCH},
};

const ACTIONS: &str = "actions.jsonl";
const DESCRIPTION: &str = "description.md";
const MANIFEST: &str = "manifest.json";
const MAX_PNG: usize = 16 * 1024 * 1024;
const MAX_TREE: usize = 2 * 1024 * 1024;
const MAX_ENTRY: usize = 512 * 1024;
const MAX_LOG: usize = 8 * 1024 * 1024;
const MAX_EVIDENCE: usize = 64 * 1024 * 1024;
const MAX_SCREENSHOTS: u64 = 128;
const MAX_DESCRIPTION: usize = 4096;
static NEXT_DIRECTORY: AtomicU64 = AtomicU64::new(0);

#[derive(Default)]
pub struct Evidence {
    pub png: Option<Vec<u8>>,
    pub tree: Option<JsonValue>,
    pub errors: Vec<String>,
}

#[derive(Clone, Copy, Default)]
pub struct ExportOptions {
    pub text: bool,
    pub frames: bool,
    pub tree: bool,
}

pub struct HandoffFile {
    pub name: String,
    pub bytes: Vec<u8>,
}

pub struct HandoffPackage {
    pub directory: PathBuf,
    pub manifest: String,
    pub description: String,
    pub actions: String,
    pub files: Vec<HandoffFile>,
}

pub struct Recording {
    pub directory: PathBuf,
    pub active: bool,
    identity: Identity,
    log: Option<File>,
    started: Instant,
    sequence: u64,
    log_bytes: usize,
    evidence_bytes: usize,
    next_screenshot: u64,
    missed_entries: u64,
    complete: bool,
    frames: Vec<String>,
    trees: Vec<String>,
}

struct Identity {
    app_id: String,
    pid: u64,
    window: u64,
}

impl Identity {
    fn new(app_id: &str, pid: u64, window: u64) -> Result<Self, String> {
        if pid == 0
            || !app_id.strip_prefix("app_").is_some_and(|suffix| {
                suffix.len() == 32
                    && suffix
                        .bytes()
                        .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
            })
        {
            return Err("Invalid recording app identity".into());
        }
        Ok(Self {
            app_id: app_id.into(),
            pid,
            window,
        })
    }

    fn fields(&self) -> HashMap<String, JsonValue> {
        fields([
            ("app_id", self.app_id.as_str().into()),
            ("pid", self.pid.into()),
            ("window", self.window.into()),
        ])
    }
}

impl Recording {
    pub fn start(
        root: &Path,
        app_id: &str,
        pid: u64,
        window: u64,
        before: Evidence,
    ) -> Result<Self, String> {
        let identity = Identity::new(app_id, pid, window)?;
        let directory = output_dir(root, "recording")?;
        let log = new_file(&directory.join(ACTIONS))?;
        let mut recording = Self {
            directory,
            active: true,
            identity,
            log: Some(log),
            started: Instant::now(),
            sequence: 0,
            log_bytes: 0,
            evidence_bytes: 0,
            next_screenshot: 1,
            missed_entries: 0,
            complete: false,
            frames: Vec::new(),
            trees: Vec::new(),
        };
        let evidence = recording.save_evidence(before, "before");
        recording.append("start", evidence, false)?;
        Ok(recording)
    }

    pub fn action(
        &mut self,
        input: JsonValue,
        outcome: &str,
        observation: Option<JsonValue>,
    ) -> Result<(), String> {
        self.require_active()?;
        let mut entry = fields([("input", input), ("outcome", outcome.into())]);
        if let Some(observation) = observation {
            entry.insert("observation".into(), observation);
        }
        self.append("action", entry, false)
    }

    pub fn screenshot(&mut self, png: &[u8]) -> Result<PathBuf, String> {
        self.require_active()?;
        if self.next_screenshot > MAX_SCREENSHOTS {
            return Err("Recording screenshot limit reached".into());
        }
        let name = format!("screenshot-{:06}.png", self.next_screenshot);
        self.next_screenshot += 1;
        let path = self.save_png(&name, png)?;
        self.append("screenshot", fields([("png", name.into())]), false)?;
        Ok(path)
    }

    pub fn finish(&mut self, after: Evidence, reason: &str) -> Result<(), String> {
        self.require_active()?;
        let mut entry = self.save_evidence(after, "after");
        entry.insert("reason".into(), limited_message(reason).into());
        entry.insert("missed_entries".into(), self.missed_entries.into());
        self.active = false;
        let result = self.append("finish", entry, true);
        self.log.take();
        result?;
        self.complete = true;
        Ok(())
    }

    pub fn export(&self, description: &str, options: ExportOptions) -> Result<PathBuf, String> {
        if !self.complete {
            return Err("Finish the recording before exporting".into());
        }
        if description.len() > MAX_DESCRIPTION || description.contains('\0') {
            return Err("Invalid recording description".into());
        }
        let root = self
            .directory
            .parent()
            .ok_or("Recording directory has no parent")?;
        let log = read_owned_file(&self.directory.join(ACTIONS), MAX_LOG)?;
        let log = std::str::from_utf8(&log).map_err(|_| "Recording log is not UTF-8")?;
        let mut exported = Vec::with_capacity(log.len());
        for line in log.lines() {
            let entry = JsonValue::deserialize_json_strict(line)
                .map_err(|_| "Recording log contains an invalid entry")?;
            let entry = export_entry(entry, options)?;
            exported.extend(json_line(&entry)?);
        }
        if exported.len() > MAX_LOG {
            return Err("Export log exceeds the size limit".into());
        }
        let mut files = vec![
            HandoffFile {
                name: ACTIONS.into(),
                bytes: exported,
            },
            HandoffFile {
                name: DESCRIPTION.into(),
                bytes: description.as_bytes().to_vec(),
            },
        ];
        if options.frames {
            self.export_files(&self.frames, MAX_PNG, &mut files)?;
        }
        if options.tree {
            self.export_files(&self.trees, MAX_TREE, &mut files)?;
        }
        files.sort_by(|left, right| left.name.cmp(&right.name));
        let directory = output_dir(root, "export")?;
        for file in &files {
            write_new(&directory.join(&file.name), &file.bytes)?;
        }
        let mut manifest = self.identity.fields();
        manifest.extend(fields([
            ("schema_version", 1_u64.into()),
            ("status", "READY".into()),
            ("include_text", options.text.into()),
            ("include_frames", options.frames.into()),
            ("include_tree", options.tree.into()),
            (
                "files",
                JsonValue::Array(
                    files
                        .iter()
                        .map(|file| {
                            JsonValue::Object(fields([
                                ("name", file.name.as_str().into()),
                                ("bytes", (file.bytes.len() as u64).into()),
                                ("sha256", digest(&file.bytes).into()),
                            ]))
                        })
                        .collect(),
                ),
            ),
        ]));
        write_new(
            &directory.join(MANIFEST),
            &json_line(&JsonValue::Object(manifest))?,
        )?;
        Ok(directory)
    }

    fn require_active(&self) -> Result<(), String> {
        if self.active {
            Ok(())
        } else {
            Err("Recording is closed".into())
        }
    }

    fn append(
        &mut self,
        event: &str,
        mut entry: HashMap<String, JsonValue>,
        terminal: bool,
    ) -> Result<(), String> {
        self.sequence += 1;
        entry.extend(self.identity.fields());
        entry.extend(fields([
            ("event", event.into()),
            ("sequence", self.sequence.into()),
            ("utc_unix_ms", utc_ms().into()),
            (
                "elapsed_ms",
                (self.started.elapsed().as_millis() as u64).into(),
            ),
        ]));
        let line = json_line(&JsonValue::Object(entry));
        let log_limit = if terminal {
            MAX_LOG
        } else {
            MAX_LOG - MAX_ENTRY
        };
        let line = match line {
            Ok(line) if self.log_bytes + line.len() <= log_limit => line,
            _ => {
                self.missed_entries += 1;
                return Err("Recording event or log exceeds the size limit".into());
            }
        };
        let log = self.log.as_mut().ok_or("Recording log is closed")?;
        if let Err(error) = log.write_all(&line).and_then(|()| log.sync_data()) {
            self.active = false;
            self.log.take();
            return Err(format!("Write recording event: {error}"));
        }
        self.log_bytes += line.len();
        Ok(())
    }

    fn save_evidence(&mut self, mut evidence: Evidence, phase: &str) -> HashMap<String, JsonValue> {
        let mut entry = HashMap::new();
        if let Some(png) = evidence.png {
            let name = format!("screenshot-{phase}.png");
            match self.save_png(&name, &png) {
                Ok(_) => {
                    entry.insert("png".into(), name.into());
                }
                Err(error) => evidence.errors.push(error),
            }
        }
        if let Some(tree) = evidence.tree {
            let name = format!("ui-{phase}.json");
            let tree = tree.serialize_json();
            match self.save_file(&name, tree.as_bytes(), MAX_TREE) {
                Ok(_) => {
                    self.trees.push(name.clone());
                    entry.insert("tree".into(), name.into());
                }
                Err(error) => evidence.errors.push(error),
            }
        }
        if !evidence.errors.is_empty() {
            let errors = evidence
                .errors
                .iter()
                .take(16)
                .map(|error| limited_message(error).into())
                .collect();
            entry.insert("errors".into(), JsonValue::Array(errors));
            entry.insert("error_count".into(), (evidence.errors.len() as u64).into());
        }
        entry
    }

    fn save_png(&mut self, name: &str, png: &[u8]) -> Result<PathBuf, String> {
        validate_png(png)?;
        let path = self.save_file(name, png, MAX_PNG)?;
        self.frames.push(name.into());
        Ok(path)
    }

    fn save_file(&mut self, name: &str, bytes: &[u8], limit: usize) -> Result<PathBuf, String> {
        if bytes.len() > limit || self.evidence_bytes + bytes.len() > MAX_EVIDENCE {
            return Err(format!("Recording evidence exceeds its size limit: {name}"));
        }
        let path = self.directory.join(name);
        write_new(&path, bytes)?;
        self.evidence_bytes += bytes.len();
        Ok(path)
    }

    fn export_files(
        &self,
        names: &[String],
        limit: usize,
        files: &mut Vec<HandoffFile>,
    ) -> Result<(), String> {
        for name in names {
            files.push(HandoffFile {
                name: name.clone(),
                bytes: read_owned_file(&self.directory.join(name), limit)?,
            });
        }
        Ok(())
    }
}

impl HandoffPackage {
    pub fn matches_options(&self, options: ExportOptions) -> bool {
        let Ok(manifest) = JsonValue::deserialize_json_strict(&self.manifest) else {
            return false;
        };
        [
            ("include_text", options.text),
            ("include_frames", options.frames),
            ("include_tree", options.tree),
        ]
        .into_iter()
        .all(|(key, value)| manifest.get(key) == Some(&JsonValue::Bool(value)))
    }
}

pub fn prepare_handoff(directory: &Path) -> Result<HandoffPackage, String> {
    check_directory(directory)?;
    let valid_name = directory
        .file_name()
        .and_then(|name| name.to_str())
        .is_some_and(|name| {
            name.strip_prefix("export-").is_some_and(|suffix| {
                let parts = suffix.split('-').collect::<Vec<_>>();
                parts.len() == 3 && parts.iter().all(|part| part.parse::<u64>().is_ok())
            })
        });
    if !valid_name {
        return Err("Select a prepared recording export".into());
    }
    let manifest = read_text(&directory.join(MANIFEST), MAX_ENTRY)?;
    let header = JsonValue::deserialize_json_strict(&manifest)
        .map_err(|_| "Invalid recording export manifest")?;
    if header.get("schema_version").and_then(JsonValue::as_u64) != Some(1)
        || header.get("status").and_then(JsonValue::as_str) != Some("READY")
        || header.as_object().map(HashMap::len) != Some(9)
        || json_line(&header)? != manifest.as_bytes()
    {
        return Err("Invalid recording export manifest".into());
    }
    let identity = Identity::new(
        header
            .get("app_id")
            .and_then(JsonValue::as_str)
            .ok_or("Missing export App ID")?,
        header
            .get("pid")
            .and_then(JsonValue::as_u64)
            .ok_or("Missing export PID")?,
        header
            .get("window")
            .and_then(JsonValue::as_u64)
            .ok_or("Missing export window")?,
    )?;
    let flag = |key| match header.get(key) {
        Some(JsonValue::Bool(value)) => Ok(*value),
        _ => Err("Missing recording export privacy choice"),
    };
    let options = ExportOptions {
        text: flag("include_text")?,
        frames: flag("include_frames")?,
        tree: flag("include_tree")?,
    };
    let inventory = header
        .get("files")
        .and_then(JsonValue::as_array)
        .ok_or("Missing recording export inventory")?;
    if inventory.len() < 2 || inventory.len() as u64 > MAX_SCREENSHOTS + 6 {
        return Err("Invalid recording export inventory size".into());
    }
    let mut names = HashSet::new();
    let mut description = None;
    let mut actions = None;
    let mut files = Vec::new();
    let mut total = 0;
    for item in inventory {
        let name = item
            .get("name")
            .and_then(JsonValue::as_str)
            .ok_or("Missing export filename")?;
        let limit = export_file_limit(name, options).ok_or("Unapproved recording export file")?;
        let size = item
            .get("bytes")
            .and_then(JsonValue::as_u64)
            .and_then(|size| usize::try_from(size).ok())
            .ok_or("Invalid export file size")?;
        let sha256 = item
            .get("sha256")
            .and_then(JsonValue::as_str)
            .ok_or("Missing export file digest")?;
        if !names.insert(name) || size > limit || item.as_object().map(HashMap::len) != Some(3) {
            return Err("Invalid recording export file entry".into());
        }
        total += size;
        if total > MAX_EVIDENCE + MAX_LOG + MAX_DESCRIPTION {
            return Err("Recording export exceeds its total size limit".into());
        }
        let bytes = read_owned_file(&directory.join(name), limit)?;
        if bytes.len() != size || digest(&bytes) != sha256 {
            return Err(format!("Recording export file changed: {name}"));
        }
        match name {
            ACTIONS => actions = Some(utf8(bytes)?),
            DESCRIPTION => description = Some(utf8(bytes)?),
            _ => {
                if name.ends_with(".png") {
                    validate_png(&bytes)?;
                } else {
                    let tree =
                        std::str::from_utf8(&bytes).map_err(|_| "Export tree is not UTF-8")?;
                    JsonValue::deserialize_json_strict(tree)
                        .map_err(|_| "Invalid recording export tree")?;
                }
                files.push(HandoffFile {
                    name: name.into(),
                    bytes,
                });
            }
        }
    }
    check_export_contents(directory, &names)?;
    let actions = actions.ok_or("Missing recording export actions")?;
    let description = description.ok_or("Missing recording export description")?;
    if description.contains('\0') {
        return Err("Invalid recording export description".into());
    }
    validate_export_actions(&actions, &identity, options, &names)?;
    Ok(HandoffPackage {
        directory: directory.to_path_buf(),
        manifest,
        description,
        actions,
        files,
    })
}

fn export_file_limit(name: &str, options: ExportOptions) -> Option<usize> {
    match name {
        ACTIONS => Some(MAX_LOG),
        DESCRIPTION => Some(MAX_DESCRIPTION),
        "ui-before.json" | "ui-after.json" if options.tree => Some(MAX_TREE),
        "screenshot-before.png" | "screenshot-after.png" if options.frames => Some(MAX_PNG),
        _ if options.frames => {
            let number = name.strip_prefix("screenshot-")?.strip_suffix(".png")?;
            let step = number.parse::<u64>().ok()?;
            (number.len() == 6
                && number.bytes().all(|byte| byte.is_ascii_digit())
                && (1..=MAX_SCREENSHOTS).contains(&step))
            .then_some(MAX_PNG)
        }
        _ => None,
    }
}

fn check_export_contents(directory: &Path, names: &HashSet<&str>) -> Result<(), String> {
    let mut count = 0;
    for entry in
        fs::read_dir(directory).map_err(|error| format!("List recording export: {error}"))?
    {
        let entry = entry.map_err(|error| format!("Read recording export entry: {error}"))?;
        let name = entry.file_name();
        if !name
            .to_str()
            .is_some_and(|name| name == MANIFEST || names.contains(name))
        {
            return Err("Unexpected file in recording export".into());
        }
        count += 1;
    }
    if count != names.len() + 1 {
        return Err("Recording export is incomplete".into());
    }
    Ok(())
}

fn validate_export_actions(
    actions: &str,
    identity: &Identity,
    options: ExportOptions,
    names: &HashSet<&str>,
) -> Result<(), String> {
    let identity = identity.fields();
    if actions.contains('\r') || !actions.ends_with('\n') {
        return Err("Recording export actions are not canonical JSON lines".into());
    }
    let mut previous = 0;
    let mut finished = false;
    let mut references = HashSet::new();
    for line in actions.lines() {
        let entry =
            JsonValue::deserialize_json_strict(line).map_err(|_| "Invalid export action")?;
        let event = entry.get("event").and_then(JsonValue::as_str);
        let sequence = entry
            .get("sequence")
            .and_then(JsonValue::as_u64)
            .ok_or("Missing action sequence")?;
        if finished
            || sequence <= previous
            || identity
                .iter()
                .any(|(name, value)| entry.get(name) != Some(value))
            || !(if previous == 0 {
                event == Some("start") && sequence == 1
            } else {
                matches!(event, Some("action" | "screenshot" | "finish"))
            })
            || entry != export_entry(entry.clone(), options)?
            || json_line(&entry)?.strip_suffix(b"\n") != Some(line.as_bytes())
        {
            return Err("Export action provenance or privacy check failed".into());
        }
        for key in ["png", "tree"] {
            if let Some(value) = entry.get(key) {
                let name = value.as_str().ok_or("Invalid export evidence reference")?;
                if !names.contains(name)
                    || !references.insert(name.to_owned())
                    || (key == "png" && !name.ends_with(".png"))
                    || (key == "tree" && !name.ends_with(".json"))
                {
                    return Err("Recording export evidence reference is inconsistent".into());
                }
            }
        }
        finished = event == Some("finish");
        previous = sequence;
    }
    if !finished || references.len() + 2 != names.len() {
        return Err("Recording export lacks a completed action log or its evidence".into());
    }
    Ok(())
}

fn digest(bytes: &[u8]) -> String {
    sha256_hash(bytes)
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}

fn utf8(bytes: Vec<u8>) -> Result<String, String> {
    String::from_utf8(bytes).map_err(|_| "Recording export text is not UTF-8".into())
}

fn read_text(path: &Path, limit: usize) -> Result<String, String> {
    utf8(read_owned_file(path, limit)?)
}

pub fn screenshot(
    root: &Path,
    app_id: &str,
    pid: u64,
    window: u64,
    png: &[u8],
) -> Result<PathBuf, String> {
    let identity = Identity::new(app_id, pid, window)?;
    validate_png(png)?;
    let directory = output_dir(root, "capture")?;
    let path = directory.join("screenshot.png");
    write_new(&path, png)?;
    let mut manifest = identity.fields();
    manifest.extend(fields([
        ("png", "screenshot.png".into()),
        ("utc_unix_ms", utc_ms().into()),
    ]));
    write_new(
        &directory.join("manifest.json"),
        &json_line(&JsonValue::Object(manifest))?,
    )?;
    Ok(path)
}

fn fields<const N: usize>(entries: [(&str, JsonValue); N]) -> HashMap<String, JsonValue> {
    entries
        .into_iter()
        .map(|(key, value)| (key.into(), value))
        .collect()
}

fn utc_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |elapsed| elapsed.as_millis() as u64)
}

fn limited_message(value: &str) -> String {
    value.chars().take(512).collect()
}

fn json_line(value: &JsonValue) -> Result<Vec<u8>, String> {
    let mut line = value.serialize_json().into_bytes();
    if line.len() >= MAX_ENTRY {
        return Err("Recording JSON entry exceeds its size limit".into());
    }
    line.push(b'\n');
    Ok(line)
}

fn export_entry(entry: JsonValue, options: ExportOptions) -> Result<JsonValue, String> {
    let JsonValue::Object(mut entry) = entry else {
        return Err("Recording log entry is not an object".into());
    };
    if !options.text {
        entry.retain(|key, _| {
            matches!(
                key.as_str(),
                "event"
                    | "app_id"
                    | "pid"
                    | "window"
                    | "sequence"
                    | "utc_unix_ms"
                    | "elapsed_ms"
                    | "input"
                    | "outcome"
                    | "reason"
                    | "missed_entries"
                    | "error_count"
                    | "png"
                    | "tree"
            )
        });
        if let Some(input) = entry.remove("input") {
            entry.insert("input".into(), redacted_input(input));
        }
        for key in [
            "pid",
            "window",
            "sequence",
            "utc_unix_ms",
            "elapsed_ms",
            "missed_entries",
            "error_count",
        ] {
            if entry.get(key).is_some_and(|value| value.as_u64().is_none()) {
                return Err("Invalid recording metadata".into());
            }
        }
        for key in ["outcome", "reason"] {
            if let Some(value) = entry.get_mut(key)
                && !value.as_str().is_some_and(|value| {
                    matches!(
                        value,
                        "DISPATCHED"
                            | "REMOTE_ACKNOWLEDGED"
                            | "APP_CLOSED"
                            | "VIEW_DETACHED"
                            | "DISCONNECT_UNVERIFIED"
                            | "APPLIED"
                            | "NOT_DISPATCHED"
                            | "OUTCOME_UNKNOWN"
                            | "STALE_GEOMETRY"
                            | "CONTROL_REQUIRED"
                            | "REMOTE_UNAVAILABLE"
                            | "STOPPED"
                            | "DETACHED"
                            | "CLOSED"
                            | "FAILED"
                            | "ERROR"
                    )
                })
            {
                *value = "REDACTED".into();
            }
        }
    }
    if !options.frames {
        entry.remove("png");
    }
    if !options.tree {
        entry.remove("tree");
    }
    Ok(JsonValue::Object(entry))
}

fn redacted_input(input: JsonValue) -> JsonValue {
    let JsonValue::Object(mut input) = input else {
        return JsonValue::Null;
    };
    input.retain(|key, value| match key.as_str() {
        "kind" => value.as_str().is_some_and(|kind| {
            matches!(kind, "click" | "drag" | "scroll" | "key" | "text" | "move")
        }),
        "x" | "y" | "x1" | "y1" | "dx" | "dy" | "b" | "steps" | "dispatch_utc_unix_ms" => {
            value.as_f64().is_some_and(f64::is_finite)
        }
        "ctrl" | "alt" | "shift" => matches!(value, JsonValue::Bool(_)),
        "phases" => value.as_array().is_some_and(|items| {
            items.len() <= 3
                && items.iter().all(|item| {
                    item.as_str().is_some_and(|phase| {
                        matches!(
                            phase,
                            "mouse_down" | "mouse_up" | "move" | "key_down" | "key_up"
                        )
                    })
                })
        }),
        _ => false,
    });
    JsonValue::Object(input)
}

fn validate_png(png: &[u8]) -> Result<(), String> {
    if png.len() > MAX_PNG
        || png.len() < 24
        || !png.starts_with(b"\x89PNG\r\n\x1a\n\0\0\0\rIHDR")
        || png[16..20] == [0; 4]
        || png[20..24] == [0; 4]
    {
        return Err("Recording capture is not a bounded PNG".into());
    }
    Ok(())
}

fn validate_path_shape(path: &Path) -> Result<(), String> {
    if !path.is_absolute() {
        return Err("Use an absolute recording directory".into());
    }
    for part in path.components() {
        match part {
            Component::ParentDir => return Err("Recording paths cannot traverse parents".into()),
            #[cfg(windows)]
            Component::Prefix(prefix) if !matches!(prefix.kind(), std::path::Prefix::Disk(_)) => {
                return Err("Use a local drive recording directory".into());
            }
            _ => {}
        }
    }
    Ok(())
}

fn is_reparse(metadata: &Metadata) -> bool {
    #[cfg(windows)]
    {
        use std::os::windows::fs::MetadataExt;
        metadata.file_attributes() & 0x400 != 0
    }
    #[cfg(not(windows))]
    {
        metadata.file_type().is_symlink()
    }
}

fn check_directory(path: &Path) -> Result<(), String> {
    validate_path_shape(path)?;
    for part in path.ancestors() {
        let metadata = fs::symlink_metadata(part)
            .map_err(|error| format!("Read recording directory: {error}"))?;
        if !metadata.is_dir() || is_reparse(&metadata) {
            return Err("Recording directory contains an untrusted path".into());
        }
    }
    Ok(())
}

fn private_dir(path: &Path) -> io::Result<()> {
    #[cfg(unix)]
    {
        use std::os::unix::fs::DirBuilderExt;
        fs::DirBuilder::new().mode(0o700).create(path)
    }
    #[cfg(not(unix))]
    {
        fs::create_dir(path)
    }
}

fn output_dir(root: &Path, prefix: &str) -> Result<PathBuf, String> {
    validate_path_shape(root)?;
    if let Err(error) = fs::symlink_metadata(root) {
        if error.kind() != io::ErrorKind::NotFound {
            return Err(format!("Read recording root: {error}"));
        }
        check_directory(root.parent().ok_or("Recording root has no parent")?)?;
        match private_dir(root) {
            Ok(()) => {}
            Err(error) if error.kind() == io::ErrorKind::AlreadyExists => {}
            Err(error) => return Err(format!("Create recording root: {error}")),
        }
    }
    check_directory(root)?;
    for _ in 0..16 {
        let sequence = NEXT_DIRECTORY.fetch_add(1, Ordering::Relaxed);
        let path = root.join(format!(
            "{prefix}-{}-{}-{sequence}",
            utc_ms(),
            std::process::id()
        ));
        match private_dir(&path) {
            Ok(()) => return Ok(path),
            Err(error) if error.kind() == io::ErrorKind::AlreadyExists => {}
            Err(error) => return Err(format!("Create recording directory: {error}")),
        }
    }
    Err("Could not allocate an unused recording directory".into())
}

fn new_file(path: &Path) -> Result<File, String> {
    check_directory(path.parent().ok_or("Recording file has no directory")?)?;
    let mut options = OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    options
        .open(path)
        .map_err(|error| format!("Create recording file: {error}"))
}

fn write_new(path: &Path, data: &[u8]) -> Result<(), String> {
    let mut file = new_file(path)?;
    file.write_all(data)
        .and_then(|()| file.sync_data())
        .map_err(|error| format!("Write recording file: {error}"))
}

fn read_owned_file(path: &Path, limit: usize) -> Result<Vec<u8>, String> {
    check_directory(path.parent().ok_or("Recording file has no directory")?)?;
    let metadata =
        fs::symlink_metadata(path).map_err(|error| format!("Read recording file: {error}"))?;
    if !metadata.is_file() || is_reparse(&metadata) || metadata.len() > limit as u64 {
        return Err("Recording file is unsafe or exceeds its size limit".into());
    }
    let mut bytes = Vec::new();
    File::open(path)
        .and_then(|file| file.take(limit as u64 + 1).read_to_end(&mut bytes))
        .map_err(|error| format!("Read recording file: {error}"))?;
    if bytes.len() > limit {
        return Err("Recording file exceeds its size limit".into());
    }
    Ok(bytes)
}

#[cfg(test)]
mod tests {
    use super::*;

    const APP_ID: &str = "app_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
    const PNG: &[u8] = &[
        0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0, 0, 0, 13, 0x49, 0x48, 0x44, 0x52, 0, 0,
        0, 1, 0, 0, 0, 1, 8, 4, 0, 0, 0, 0xb5, 0x1c, 0x0c, 2, 0, 0, 0, 11, 0x49, 0x44, 0x41, 0x54,
        0x78, 0xda, 0x63, 0xfc, 0xff, 0x1f, 0, 3, 3, 2, 0, 0xef, 0x9a, 0x63, 0x6c, 0, 0, 0, 0,
        0x49, 0x45, 0x4e, 0x44, 0xae, 0x42, 0x60, 0x82,
    ];
    const PRIVATE: &str = "Private \u{041f}\u{0440}\u{0438}\u{0432}\u{0435}\u{0442}";

    struct Fixture(PathBuf);

    impl Fixture {
        fn new() -> Self {
            Self(output_dir(&std::env::temp_dir(), "mss-recording-test").unwrap())
        }

        fn recording(&self) -> Recording {
            Recording::start(
                &self.0,
                APP_ID,
                123,
                7,
                Evidence {
                    png: Some(PNG.into()),
                    tree: Some(JsonValue::Object(fields([("value", PRIVATE.into())]))),
                    errors: vec![],
                },
            )
            .unwrap()
        }
    }

    impl Drop for Fixture {
        fn drop(&mut self) {
            fs::remove_dir_all(&self.0).expect("remove owned recording test fixture");
        }
    }

    fn log(directory: &Path) -> Vec<JsonValue> {
        fs::read_to_string(directory.join(ACTIONS))
            .unwrap()
            .lines()
            .map(|line| JsonValue::deserialize_json_strict(line).unwrap())
            .collect()
    }

    fn record_text(recording: &mut Recording) {
        let input = JsonValue::Object(fields([("kind", "text".into()), ("text", PRIVATE.into())]));
        recording
            .action(input, "OUTCOME_UNKNOWN", Some(PRIVATE.into()))
            .unwrap();
    }

    #[test]
    fn recording_appends_immediately_and_preserves_missing_after_evidence() {
        let fixture = Fixture::new();
        let mut recording = fixture.recording();
        assert!(recording.export("", ExportOptions::default()).is_err());
        record_text(&mut recording);
        let step = recording.screenshot(PNG).unwrap();
        assert!(step.is_file());
        let rows = log(&recording.directory);
        assert_eq!(rows.len(), 3);
        assert_eq!(
            rows[1].get("app_id").and_then(JsonValue::as_str),
            Some(APP_ID)
        );
        assert_eq!(rows[1].get("pid").and_then(JsonValue::as_u64), Some(123));
        assert_eq!(rows[1].get("window").and_then(JsonValue::as_u64), Some(7));
        assert_eq!(rows[1].get("sequence").and_then(JsonValue::as_u64), Some(2));
        assert_eq!(
            rows[1].get("observation").and_then(JsonValue::as_str),
            Some(PRIVATE)
        );
        assert!(
            rows[1]
                .get("utc_unix_ms")
                .and_then(JsonValue::as_u64)
                .unwrap()
                > 0
        );
        recording
            .finish(
                Evidence {
                    errors: vec!["capture missing".into()],
                    ..Evidence::default()
                },
                "REMOTE_UNAVAILABLE",
            )
            .unwrap();
        assert!(!recording.active);
        assert!(!recording.directory.join("screenshot-after.png").exists());
        assert!(!recording.directory.join("ui-after.json").exists());
        let rows = log(&recording.directory);
        assert_eq!(
            rows[3].get("reason").and_then(JsonValue::as_str),
            Some("REMOTE_UNAVAILABLE")
        );
        assert_eq!(
            rows[3].get("error_count").and_then(JsonValue::as_u64),
            Some(1)
        );
        assert!(recording.screenshot(PNG).is_err());
    }

    #[test]
    fn export_flags_default_private_and_can_be_selected_independently() {
        let fixture = Fixture::new();
        let mut recording = fixture.recording();
        record_text(&mut recording);
        recording.finish(Evidence::default(), "STOPPED").unwrap();
        let minimal = recording
            .export("Reviewed description", ExportOptions::default())
            .unwrap();
        let rows = log(&minimal);
        assert_eq!(
            rows[1].get("outcome").and_then(JsonValue::as_str),
            Some("OUTCOME_UNKNOWN")
        );
        assert!(rows[1].get("observation").is_none());
        assert!(rows[1].get("input").unwrap().get("text").is_none());
        assert!(!minimal.join("screenshot-before.png").exists());
        assert!(!minimal.join("ui-before.json").exists());
        let manifest = fs::read_to_string(minimal.join("manifest.json")).unwrap();
        assert!(manifest.contains("\"READY\""));
        assert_eq!(
            fs::read_to_string(minimal.join("description.md")).unwrap(),
            "Reviewed description"
        );
        let frames = recording
            .export(
                "",
                ExportOptions {
                    frames: true,
                    ..ExportOptions::default()
                },
            )
            .unwrap();
        assert_eq!(fs::read(frames.join("screenshot-before.png")).unwrap(), PNG);
        assert!(!frames.join("ui-before.json").exists());
        assert!(log(&frames)[1].get("observation").is_none());
        let tree = recording
            .export(
                "",
                ExportOptions {
                    tree: true,
                    ..ExportOptions::default()
                },
            )
            .unwrap();
        assert!(tree.join("ui-before.json").is_file());
        assert!(!tree.join("screenshot-before.png").exists());
        assert!(log(&tree)[1].get("observation").is_none());
        let text = recording
            .export(
                "",
                ExportOptions {
                    text: true,
                    ..ExportOptions::default()
                },
            )
            .unwrap();
        assert_eq!(
            log(&text)[1].get("observation").and_then(JsonValue::as_str),
            Some(PRIVATE)
        );
        assert!(!text.join("ui-before.json").exists());
        assert!(!text.join("screenshot-before.png").exists());
        assert_ne!(text, minimal);
    }

    #[test]
    fn standalone_capture_and_identity_validation_do_not_reuse_paths() {
        let fixture = Fixture::new();
        assert!(screenshot(&fixture.0, "../escape", 123, 7, PNG).is_err());
        assert!(screenshot(&fixture.0, APP_ID, 123, 7, b"not a PNG").is_err());
        let a = screenshot(&fixture.0, APP_ID, 123, 7, PNG).unwrap();
        let b = screenshot(&fixture.0, APP_ID, 123, 7, PNG).unwrap();
        assert_ne!(a, b);
        assert_eq!(fs::read(a).unwrap(), PNG);
        assert_eq!(fs::read(b).unwrap(), PNG);
    }

    #[test]
    fn handoff_reads_verified_export_only_and_freezes_selected_bytes() {
        let fixture = Fixture::new();
        let mut recording = fixture.recording();
        record_text(&mut recording);
        recording.screenshot(PNG).unwrap();
        recording.finish(Evidence::default(), "STOPPED").unwrap();
        assert!(prepare_handoff(&recording.directory).is_err());
        let directory = recording
            .export(
                "Explicitly reviewed",
                ExportOptions {
                    text: true,
                    frames: true,
                    tree: true,
                },
            )
            .unwrap();
        let package = prepare_handoff(&directory).unwrap();
        assert_eq!(package.directory, directory);
        assert!(package.manifest.contains("\"READY\""));
        assert_eq!(package.description, "Explicitly reviewed");
        assert!(package.actions.contains(PRIVATE));
        assert_eq!(
            package
                .files
                .iter()
                .map(|file| file.name.as_str())
                .collect::<Vec<_>>(),
            [
                "screenshot-000001.png",
                "screenshot-before.png",
                "ui-before.json"
            ]
        );
        fs::write(directory.join("screenshot-before.png"), b"changed").unwrap();
        assert!(prepare_handoff(&directory).is_err());
        assert_eq!(package.files[1].bytes, PNG);
    }

    #[test]
    fn handoff_rejects_missing_and_unapproved_export_files() {
        let fixture = Fixture::new();
        let mut recording = fixture.recording();
        recording.finish(Evidence::default(), "STOPPED").unwrap();
        let chosen = recording
            .export(
                "",
                ExportOptions {
                    tree: true,
                    ..ExportOptions::default()
                },
            )
            .unwrap();
        fs::remove_file(chosen.join("ui-before.json")).unwrap();
        assert!(prepare_handoff(&chosen).is_err());
        let minimal = recording.export("", ExportOptions::default()).unwrap();
        fs::write(minimal.join("ui-before.json"), b"unexpected").unwrap();
        assert!(prepare_handoff(&minimal).is_err());
    }

    #[test]
    fn handoff_rejects_disallowed_text_even_with_matching_inventory_digest() {
        let fixture = Fixture::new();
        let mut recording = fixture.recording();
        record_text(&mut recording);
        recording.finish(Evidence::default(), "STOPPED").unwrap();
        let directory = recording.export("", ExportOptions::default()).unwrap();
        let package = prepare_handoff(&directory).unwrap();
        assert!(!package.actions.contains(PRIVATE));
        assert!(package.files.is_empty());
        let mut entries = log(&directory);
        entries[1]
            .as_object_mut()
            .unwrap()
            .insert("observation".into(), PRIVATE.into());
        let changed = entries
            .iter()
            .flat_map(|entry| json_line(entry).unwrap())
            .collect::<Vec<_>>();
        fs::write(directory.join(ACTIONS), &changed).unwrap();
        let mut manifest = JsonValue::deserialize_json_strict(&package.manifest).unwrap();
        let files = manifest
            .as_object_mut()
            .unwrap()
            .get_mut("files")
            .unwrap()
            .as_array_mut()
            .unwrap();
        let action = files
            .iter_mut()
            .find(|file| file.get("name").and_then(JsonValue::as_str) == Some(ACTIONS))
            .unwrap();
        let fields = action.as_object_mut().unwrap();
        fields.insert("sha256".into(), digest(&changed).into());
        fields.insert("bytes".into(), (changed.len() as u64).into());
        fs::write(directory.join(MANIFEST), json_line(&manifest).unwrap()).unwrap();
        assert!(prepare_handoff(&directory).is_err());
    }

    #[test]
    fn handoff_rejects_duplicate_manifest_keys_with_hidden_text() {
        let fixture = Fixture::new();
        let mut recording = fixture.recording();
        recording.finish(Evidence::default(), "STOPPED").unwrap();
        let directory = recording.export("", ExportOptions::default()).unwrap();
        let package = prepare_handoff(&directory).unwrap();
        let hidden = format!(
            "{{\"status\":{},{}",
            PRIVATE.serialize_json(),
            &package.manifest[1..]
        );
        fs::write(directory.join(MANIFEST), hidden).unwrap();
        assert!(prepare_handoff(&directory).is_err());
    }
}
