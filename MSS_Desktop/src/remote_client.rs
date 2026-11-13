//! Desktop client of the existing local MSS MCP stdio server.
use crate::human_input::Input;
use crate::recording::{self, Evidence, ExportOptions, HandoffPackage, Recording};
use makepad_widgets::makepad_draw::image_cache::ImageBuffer;
use makepad_widgets::makepad_platform::makepad_micro_serde::{DeJson, JsonValue, SerJson};
use makepad_widgets::makepad_platform::makepad_network::digest::sha256_hash;
use makepad_widgets::{DVec2, KeyModifiers, SignalToUI};
use std::{
    collections::HashMap,
    fs,
    io::{BufRead, BufReader, Read, Write},
    path::{Path, PathBuf},
    process::{Child, ChildStdin, ChildStdout, Command, Stdio},
    sync::mpsc::{self, Receiver, Sender},
    thread,
    time::{SystemTime, UNIX_EPOCH},
};

const MAX_REPLY_BYTES: u64 = 1024 * 1024;
const MAX_PNG_BYTES: u64 = 16 * 1024 * 1024;

#[derive(Clone)]
pub struct Session {
    pub id: String,
    window: u64,
    pub pid: u64,
    pub owner: bool,
    pub resize_allowed: bool,
    artifacts: PathBuf,
}

#[derive(Clone, Copy, PartialEq)]
pub struct ResizeGeometry {
    pub requested: [u32; 2],
    pub layout: [f64; 2],
    pub dpi: f64,
}

#[derive(Clone, Copy, PartialEq)]
pub struct InputGeometry {
    pub resize: ResizeGeometry,
    pub pixels: [u32; 2],
}

impl InputGeometry {
    fn matches(self, status: &JsonValue, session: &Session) -> bool {
        if status.get("pid").and_then(JsonValue::as_u64) != Some(session.pid) {
            return false;
        }
        status
            .get("w")
            .and_then(JsonValue::as_array)
            .and_then(|windows| {
                windows.iter().find(|window| {
                    window.get("i").and_then(JsonValue::as_u64) == Some(session.window)
                })
            })
            .is_some_and(|window| {
                pair(window, "sz", JsonValue::as_f64) == Some(self.resize.layout)
                    && pair(window, "px", |value| u32::try_from(value.as_u64()?).ok())
                        == Some(self.pixels)
                    && window.get("dpi").and_then(JsonValue::as_f64) == Some(self.resize.dpi)
            })
    }
}

pub struct Frame {
    pub resize: Option<ResizeGeometry>,
    pub pixels: [u32; 2],
    pub sha256: String,
}

pub enum RecordingCommand {
    Start,
    Stop,
    Screenshot,
    Export {
        directory: PathBuf,
        description: String,
        options: ExportOptions,
    },
}

pub struct RecordingStatus {
    pub active: bool,
    pub message: String,
    pub directory: Option<PathBuf>,
    pub recording_directory: Option<PathBuf>,
}

pub enum Job {
    Launch(&'static str),
    Attach {
        id: String,
        profile: Option<&'static str>,
    },
    Discover(Option<&'static str>),
    Detach(Session),
    Resize {
        session: Session,
        size: [u32; 2],
    },
    Preview {
        session: Session,
        previous_sha256: Option<String>,
        previous_resize: Option<(ResizeGeometry, [u32; 2])>,
    },
    Input {
        session: Session,
        geometry: InputGeometry,
        event: Input,
    },
    Recording {
        session: Option<Session>,
        command: RecordingCommand,
    },
    Close(Session),
}

pub enum Reply {
    Connected(Session),
    Discovered(Vec<(String, u64)>),
    Frame(Frame, ImageBuffer),
    PreviewUnchanged,
    Input {
        result: Result<(), String>,
        recording: Option<RecordingStatus>,
        refresh: bool,
    },
    Recording(Result<RecordingStatus, String>),
    Prepared {
        status: RecordingStatus,
        package: HandoffPackage,
    },
    Disconnected(Option<RecordingStatus>),
    SessionError {
        error: String,
        recording: Option<RecordingStatus>,
    },
}

pub struct Completion {
    pub slot: usize,
    pub result: Result<Reply, String>,
}

pub struct Worker {
    jobs: Sender<(usize, Job)>,
    completions: Receiver<Completion>,
}

impl Worker {
    pub fn start() -> Self {
        let (jobs, requests) = mpsc::channel();
        let (results, completions) = mpsc::channel();
        thread::spawn(move || {
            let mut peer = Peer::start();
            while let Ok((slot, job)) = requests.recv() {
                let result = match &mut peer {
                    Ok(peer) => peer.perform(slot, job),
                    Err(error) => Err(error.clone()),
                };
                if results.send(Completion { slot, result }).is_err() {
                    break;
                }
                SignalToUI::set_ui_signal();
            }
            if let Ok(peer) = peer {
                peer.close();
            }
        });
        Self { jobs, completions }
    }

    pub fn send(&self, slot: usize, job: Job) -> bool {
        self.jobs.send((slot, job)).is_ok()
    }

    pub fn try_receive(&self) -> Option<Completion> {
        self.completions.try_recv().ok()
    }
}

struct Peer {
    child: Child,
    input: ChildStdin,
    output: BufReader<ChildStdout>,
    sequence: u64,
    recording_root: PathBuf,
    recordings: HashMap<usize, (String, Recording)>,
}

impl Peer {
    fn start() -> Result<Self, String> {
        let runtime = crate::runtime_paths::RuntimePaths::resolve()?;
        let python = runtime.python()?;
        let recording_root = runtime.proof("human-action-recording")?;
        let root = &runtime.code;
        let mut command = Command::new(python);
        command
            .args(["-I", "-B"])
            .arg(root.join("MSS_MCP/tools/mss_universal.py"))
            .current_dir(root)
            .env("MSS_DATA_ROOT", &runtime.data)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped());
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            command.creation_flags(0x08000000); // CREATE_NO_WINDOW
        }
        let mut child = command
            .spawn()
            .map_err(|error| format!("MSS MCP start: {error}"))?;
        let input = child.stdin.take().ok_or("MSS MCP stdin unavailable")?;
        let output = BufReader::new(child.stdout.take().ok_or("MSS MCP stdout unavailable")?);
        let mut peer = Self {
            child,
            input,
            output,
            sequence: 0,
            recording_root,
            recordings: HashMap::new(),
        };
        let initialized = peer
            .request(
                "initialize",
                r#"{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"MSS Desktop","version":"0.1"}}"#,
            )
            .and_then(|_| peer.write(r#"{"jsonrpc":"2.0","method":"notifications/initialized"}"#));
        if let Err(error) = initialized {
            peer.close();
            return Err(error);
        }
        Ok(peer)
    }

    fn write(&mut self, message: &str) -> Result<(), String> {
        writeln!(self.input, "{message}")
            .and_then(|_| self.input.flush())
            .map_err(|error| format!("MSS MCP write: {error}"))
    }

    fn request(&mut self, method: &str, params: &str) -> Result<JsonValue, String> {
        self.request_bounded(method, params, MAX_REPLY_BYTES)
    }

    fn request_bounded(
        &mut self,
        method: &str,
        params: &str,
        limit: u64,
    ) -> Result<JsonValue, String> {
        self.sequence += 1;
        let id = self.sequence;
        self.write(&format!(
            r#"{{"jsonrpc":"2.0","id":{id},"method":"{method}","params":{params}}}"#
        ))?;
        loop {
            let mut line = String::new();
            (&mut self.output)
                .take(limit)
                .read_line(&mut line)
                .map_err(|error| format!("MSS MCP read: {error}"))?;
            if !line.ends_with('\n') {
                return Err("MSS MCP closed or returned an oversized response".into());
            }
            let reply = JsonValue::deserialize_json_strict(&line)
                .map_err(|_| "MSS MCP returned invalid JSON")?;
            if reply.get("id").is_none()
                && reply
                    .get("method")
                    .and_then(JsonValue::as_str)
                    .is_some_and(|method| method.starts_with("notifications/"))
            {
                continue;
            }
            if reply.get("id").and_then(JsonValue::as_u64) != Some(id)
                || reply.get("jsonrpc").and_then(JsonValue::as_str) != Some("2.0")
            {
                return Err("MSS MCP response ID did not match the request".into());
            }
            return reply
                .get("result")
                .cloned()
                .ok_or_else(|| "MSS MCP rejected the request".into());
        }
    }

    fn tool(&mut self, name: &str, arguments: &str) -> Result<JsonValue, String> {
        let limit = if name == "mss_grab" {
            MAX_REPLY_BYTES + MAX_PNG_BYTES.div_ceil(3) * 4
        } else {
            MAX_REPLY_BYTES
        };
        let reply = self.request_bounded(
            "tools/call",
            &format!(r#"{{"name":"{name}","arguments":{arguments}}}"#),
            limit,
        )?;
        let value = if let Some(value) = reply.get("structuredContent") {
            value.clone()
        } else {
            let text = reply
                .get("content")
                .and_then(JsonValue::as_array)
                .and_then(|parts| parts.iter().find_map(|part| part.get("text")?.as_str()))
                .ok_or("MSS MCP response has no structured result")?;
            JsonValue::deserialize_json_strict(text).map_err(|_| "MSS MCP result is not JSON")?
        };
        if matches!(reply.get("isError"), Some(JsonValue::Bool(true))) {
            return Err(format!(
                "MSS · {}",
                value
                    .get("code")
                    .and_then(JsonValue::as_str)
                    .unwrap_or("TOOL_ERROR")
            ));
        }
        Ok(value)
    }

    fn perform(&mut self, slot: usize, job: Job) -> Result<Reply, String> {
        match job {
            Job::Launch(profile) => self.launch(profile).map(Reply::Connected),
            Job::Attach { id, profile } => self.attach(&id, profile).map(Reply::Connected),
            Job::Discover(profile) => self.discover(profile).map(Reply::Discovered),
            Job::Detach(session) => Ok(self.disconnect(slot, &session, false)),
            Job::Resize { session, size } => {
                let result = self.resize(&session, size);
                Ok(self.recording_session_reply(slot, &session, result))
            }
            Job::Preview {
                session,
                previous_sha256,
                previous_resize,
            } => {
                let result = self.preview(&session, previous_sha256.as_deref(), previous_resize);
                Ok(self.recording_session_reply(slot, &session, result))
            }
            Job::Input {
                session,
                geometry,
                event,
            } => Ok(self.input_with_recording(slot, &session, geometry, event)),
            Job::Recording { session, command } => Ok(match self.record(slot, session, command) {
                Ok(reply) => reply,
                Err(error) => Reply::Recording(Err(error)),
            }),
            Job::Close(session) => Ok(self.disconnect(slot, &session, true)),
        }
    }

    fn disconnect(&mut self, slot: usize, session: &Session, close: bool) -> Reply {
        let after = self
            .active_recording(slot, session)
            .then(|| self.collect_evidence(session));
        let result = if close {
            self.close_app(&session.id)
        } else {
            self.detach(&session.id)
        };
        let recording = after.and_then(|mut evidence| {
            let reason = match &result {
                Ok(()) if close => "APP_CLOSED",
                Ok(()) => "VIEW_DETACHED",
                Err(error) => {
                    evidence.errors.push(error.clone());
                    "DISCONNECT_UNVERIFIED"
                }
            };
            self.finalize_recording(slot, evidence, reason)
        });
        match result {
            Ok(()) => Reply::Disconnected(recording),
            Err(error) => Reply::SessionError { error, recording },
        }
    }

    fn recording_session_reply(
        &mut self,
        slot: usize,
        session: &Session,
        result: Result<Reply, String>,
    ) -> Reply {
        match result {
            Ok(reply) => reply,
            Err(error) => {
                let recording =
                    self.finish_recording(slot, session, "REMOTE_UNAVAILABLE", Some(&error));
                Reply::SessionError { error, recording }
            }
        }
    }

    fn launch(&mut self, profile: &str) -> Result<Session, String> {
        let app = self.tool(
            "mss_launch_app",
            &format!(r#"{{"profile":{}}}"#, profile.serialize_json()),
        )?;
        let id = app
            .get("app_id")
            .and_then(JsonValue::as_str)
            .filter(|id| {
                id.strip_prefix("app_").is_some_and(|suffix| {
                    suffix.len() == 32 && suffix.bytes().all(|byte| byte.is_ascii_hexdigit())
                })
            })
            .ok_or("MSS launch did not return an owned app ID")?
            .to_owned();
        let session =
            self.session_from_record(&app, &id, Some(profile), true, profile == "rudraoffice");
        if session.is_err() {
            self.close_app(&id)?;
        }
        session
    }

    fn attach(&mut self, id: &str, profile: Option<&str>) -> Result<Session, String> {
        if !valid_app_id(id) {
            return Err("Enter a valid MSS App ID".into());
        }
        let app = self.tool("mss_attach_app", &app_argument(id))?;
        if app.get("owner") != Some(&JsonValue::Bool(false)) {
            return Err("MSS did not confirm participant ownership".into());
        }
        let mode = app.get("mode").and_then(JsonValue::as_str);
        if !matches!(mode, Some("read" | "control")) {
            self.detach(id)?;
            return Err("MSS did not confirm sharing permission".into());
        }
        let resize_allowed = app.get("profile").and_then(JsonValue::as_str) == Some("rudraoffice")
            && mode == Some("control");
        let session = self.session_from_record(&app, id, profile, false, resize_allowed);
        if session.is_err() {
            self.detach(id)?;
        }
        session
    }

    fn discover(&mut self, profile: Option<&str>) -> Result<Vec<(String, u64)>, String> {
        let result = self.tool("mss_list_instances", "{}")?;
        let rows = result
            .get("instances")
            .and_then(JsonValue::as_array)
            .ok_or("MSS instance list is unavailable")?;
        Ok(rows
            .iter()
            .filter_map(|row| {
                if profile.is_some_and(|profile| {
                    row.get("profile").and_then(JsonValue::as_str) != Some(profile)
                }) || row.get("state")?.as_str()? != "READY"
                    || !matches!(row.get("share_mode")?.as_str()?, "read" | "control")
                {
                    return None;
                }
                let id = row.get("app_id")?.as_str()?;
                valid_app_id(id).then_some((id.to_owned(), row.get("pid")?.as_u64()?))
            })
            .collect())
    }

    fn detach(&mut self, id: &str) -> Result<(), String> {
        let result = self.tool("mss_detach_app", &app_argument(id))?;
        if result.get("app_id").and_then(JsonValue::as_str) == Some(id)
            && result.get("state").and_then(JsonValue::as_str) == Some("DETACHED")
            && result.get("app_closed") == Some(&JsonValue::Bool(false))
        {
            Ok(())
        } else {
            Err("MSS did not confirm detaching the view".into())
        }
    }

    fn session_from_record(
        &mut self,
        app: &JsonValue,
        id: &str,
        profile: Option<&str>,
        owner: bool,
        resize_allowed: bool,
    ) -> Result<Session, String> {
        if app.get("app_id").and_then(JsonValue::as_str) != Some(id)
            || profile.is_some_and(|profile| {
                app.get("profile").and_then(JsonValue::as_str) != Some(profile)
            })
            || app.get("state").and_then(JsonValue::as_str) != Some("READY")
        {
            return Err("App ID or profile does not match this tab".into());
        }
        let pid = app
            .get("pid")
            .and_then(JsonValue::as_u64)
            .ok_or("Missing app PID")?;
        let artifacts = app
            .get("artifact_dir")
            .and_then(JsonValue::as_str)
            .and_then(|path| fs::canonicalize(path).ok())
            .ok_or("Missing app artifact directory")?;
        let status = self.tool(
            "mss_status",
            &format!(r#"{{"app_id":{}}}"#, id.serialize_json()),
        )?;
        if status.get("pid").and_then(JsonValue::as_u64) != Some(pid) {
            return Err("MSS launch and status process identities differ".into());
        }
        let window = status
            .get("w")
            .and_then(JsonValue::as_array)
            .and_then(|windows| windows.first())
            .and_then(|window| window.get("i")?.as_u64())
            .ok_or("App does not have a window available for this tab")?;
        Ok(Session {
            id: id.into(),
            pid,
            window,
            artifacts,
            owner,
            resize_allowed,
        })
    }

    fn input(
        &mut self,
        session: &Session,
        geometry: InputGeometry,
        tool: &str,
        args: &str,
    ) -> Result<(), String> {
        if !session.resize_allowed {
            return Err("MSS · CONTROL_REQUIRED".into());
        }
        let id = session.id.serialize_json();
        let window = session.window;
        let status = self.tool("mss_status", &app_argument(&session.id))?;
        if !geometry.matches(&status, session) {
            return Err("MSS · STALE_GEOMETRY".into());
        }
        let user_seq = status
            .get("activity")
            .and_then(|activity| activity.get("user_seq"))
            .and_then(JsonValue::as_u64)
            .ok_or("MSS · ACTIVITY_UNVERIFIED")?;
        let [width, height] = geometry.resize.layout;
        let dpi = geometry.resize.dpi;
        let base = format!(
            r#""app_id":{id},"w":{window},"wait":true,"if_user_seq":{user_seq},"if_layout_width":{width},"if_layout_height":{height},"if_dpi":{dpi}"#,
        );
        self.tool(tool, &format!(r#"{{{base},{args}}}"#))?;
        Ok(())
    }

    fn recording_status(&self, slot: usize, label: &str) -> Option<RecordingStatus> {
        self.recordings
            .get(&slot)
            .map(|(_, recording)| RecordingStatus {
                active: recording.active,
                directory: Some(recording.directory.clone()),
                recording_directory: Some(recording.directory.clone()),
                message: format!("{label} · {}", recording.directory.display()),
            })
    }

    fn active_recording(&self, slot: usize, session: &Session) -> bool {
        self.recordings
            .get(&slot)
            .is_some_and(|(id, recording)| id == &session.id && recording.active)
    }

    fn finish_recording(
        &mut self,
        slot: usize,
        session: &Session,
        reason: &str,
        failure: Option<&str>,
    ) -> Option<RecordingStatus> {
        if !self.active_recording(slot, session) {
            return None;
        }
        let after = if let Some(error) = failure {
            Evidence {
                errors: vec![error.to_owned()],
                ..Evidence::default()
            }
        } else {
            self.collect_evidence(session)
        };
        self.finalize_recording(slot, after, reason)
    }

    fn finalize_recording(
        &mut self,
        slot: usize,
        after: Evidence,
        reason: &str,
    ) -> Option<RecordingStatus> {
        let (_, recording) = self.recordings.get_mut(&slot)?;
        let label = match recording.finish(after, reason) {
            Ok(()) if reason == "STOPPED" => "Stopped".into(),
            Ok(()) => format!("Stopped ({reason})"),
            Err(error) => format!("Recording error: {error}"),
        };
        self.recording_status(slot, &label)
    }

    fn record(
        &mut self,
        slot: usize,
        session: Option<Session>,
        command: RecordingCommand,
    ) -> Result<Reply, String> {
        if let RecordingCommand::Export {
            directory,
            description,
            options,
        } = command
        {
            let (_, recording) = self
                .recordings
                .get(&slot)
                .filter(|(app_id, recording)| {
                    recording.directory == directory
                        && session.as_ref().is_none_or(|session| &session.id == app_id)
                })
                .ok_or("Select the recording to prepare")?;
            let path = recording.export(&description, options)?;
            let package = recording::prepare_handoff(&path)?;
            let status = RecordingStatus {
                active: false,
                directory: Some(path.clone()),
                recording_directory: Some(directory),
                message: format!("READY · {}", path.display()),
            };
            return Ok(Reply::Prepared { status, package });
        }
        let session = session.as_ref().ok_or("Connect a guest app first")?;
        let active = self.active_recording(slot, session);
        let status = match command {
            RecordingCommand::Start => {
                if !session.resize_allowed || active {
                    return Err("Recording requires a connected RudraOffice with control".into());
                }
                let before = self.collect_evidence(session);
                if before.png.is_none() && before.tree.is_none() {
                    return Err(format!(
                        "Recording unavailable: {}",
                        before.errors.join(", ")
                    ));
                }
                let recording = Recording::start(
                    &self.recording_root,
                    &session.id,
                    session.pid,
                    session.window,
                    before,
                )?;
                self.recordings
                    .insert(slot, (session.id.clone(), recording));
                self.recording_status(slot, "Recording")
                    .ok_or_else(|| "Recording unavailable".into())
            }
            RecordingCommand::Stop => self
                .finish_recording(slot, session, "STOPPED", None)
                .ok_or_else(|| "No active recording".into()),
            RecordingCommand::Screenshot => {
                let png = self.capture_png(session)?;
                let path = if active {
                    self.recordings
                        .get_mut(&slot)
                        .expect("active recording")
                        .1
                        .screenshot(&png)?
                } else {
                    recording::screenshot(
                        &self.recording_root,
                        &session.id,
                        session.pid,
                        session.window,
                        &png,
                    )?
                };
                Ok(RecordingStatus {
                    active,
                    directory: path.parent().map(Path::to_path_buf),
                    recording_directory: if active {
                        path.parent().map(Path::to_path_buf)
                    } else {
                        None
                    },
                    message: format!("Screenshot · {}", path.display()),
                })
            }
            RecordingCommand::Export { .. } => unreachable!(),
        };
        Ok(Reply::Recording(status))
    }

    fn collect_evidence(&mut self, session: &Session) -> Evidence {
        let mut evidence = Evidence::default();
        match self.capture_png(session) {
            Ok(png) => evidence.png = Some(png),
            Err(error) => evidence.errors.push(format!("PNG: {error}")),
        }
        match self.guest_tree(session) {
            Ok(tree) => evidence.tree = Some(tree),
            Err(error) => evidence.errors.push(format!("UI tree: {error}")),
        }
        evidence
    }

    fn capture_png(&mut self, session: &Session) -> Result<Vec<u8>, String> {
        let id = session.id.serialize_json();
        let window = session.window;
        let result = self.tool("mss_grab", &format!(r#"{{"app_id":{id},"w":{window}}}"#))?;
        let path = result
            .get("png")
            .and_then(JsonValue::as_str)
            .and_then(|path| fs::canonicalize(path).ok())
            .filter(|path| path.parent() == Some(session.artifacts.as_path()))
            .ok_or("Screenshot is outside the admitted guest artifact directory")?;
        let receipt = path.with_extension("json");
        if fs::symlink_metadata(&receipt)
            .map_err(|error| error.to_string())?
            .len()
            > MAX_REPLY_BYTES
            || fs::canonicalize(&receipt)
                .map_err(|error| error.to_string())?
                .parent()
                != Some(session.artifacts.as_path())
        {
            return Err(
                "Screenshot receipt is outside the admitted artifact directory or oversized".into(),
            );
        }
        let receipt = fs::read_to_string(receipt).map_err(|error| error.to_string())?;
        let receipt = JsonValue::deserialize_json_strict(&receipt)
            .map_err(|_| "Invalid screenshot receipt")?;
        if receipt.get("pid").and_then(JsonValue::as_u64) != Some(session.pid)
            || receipt.get("app_id").and_then(JsonValue::as_str) != Some(session.id.as_str())
            || receipt.get("w").and_then(JsonValue::as_u64) != Some(window)
            || result.get("w").and_then(JsonValue::as_u64) != Some(window)
            || result.get("capture_kind").and_then(JsonValue::as_str) != Some("pixels")
            || receipt.get("sz") != result.get("sz")
        {
            return Err("Screenshot receipt does not match the selected guest window".into());
        }
        let pixels = pair(&result, "sz", |value| u32::try_from(value.as_u64()?).ok())
            .filter(|[width, height]| u64::from(*width) * u64::from(*height) <= 16 * 1024 * 1024)
            .ok_or("Screenshot pixel limit exceeded")?;
        let png = read_png(&path, pixels)?;
        let actual = sha256_hash(&png)
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect::<String>();
        if receipt.get("sha256").and_then(JsonValue::as_str) != Some(actual.as_str()) {
            return Err("Screenshot bytes do not match the verified receipt".into());
        }
        ImageBuffer::from_png(&png).map_err(|error| format!("Screenshot PNG decode: {error}"))?;
        Ok(png)
    }

    fn guest_tree(&mut self, session: &Session) -> Result<JsonValue, String> {
        let response = self.tool("mss_ui_tree", &app_argument(&session.id))?;
        let windows = response
            .get("trees")
            .and_then(JsonValue::as_array)
            .ok_or("No guest semantic tree")?;
        let mut matches = windows.iter().filter(|window| {
            window
                .get("window")
                .and_then(JsonValue::as_str)
                .and_then(|key| key.rsplit(':').next())
                .and_then(|id| id.parse().ok())
                == Some(session.window)
        });
        let tree = matches
            .next()
            .filter(|_| matches.next().is_none())
            .ok_or("No unique guest semantic window")?;
        Ok(object([("trees", JsonValue::Array(vec![tree.clone()]))]))
    }

    fn input_with_recording(
        &mut self,
        slot: usize,
        session: &Session,
        geometry: InputGeometry,
        event: Input,
    ) -> Reply {
        let active = self.active_recording(slot, session);
        let motion = matches!(event, Input::Move { .. });
        let before = if active && !motion {
            self.guest_tree(session).ok()
        } else {
            None
        };
        let (tool, args, kind) = input_args(&event);
        let requested_at = SystemTime::now().duration_since(UNIX_EPOCH).ok();
        let result = self.input(session, geometry, tool, &args);
        let mut recording_status = None;
        if active {
            let after = if !motion && result.is_ok() {
                self.guest_tree(session).ok()
            } else {
                None
            };
            let observation = observation(&event, before.as_ref(), after.as_ref());
            let outcome = result
                .as_ref()
                .err()
                .map(String::as_str)
                .unwrap_or("REMOTE_ACKNOWLEDGED");
            let mut entry = JsonValue::deserialize_json_strict(&format!("{{{args}}}"))
                .unwrap_or_else(|_| object([]));
            if let Some(fields) = entry.as_object_mut() {
                fields.insert("kind".into(), JsonValue::String(kind.into()));
                if let Some(time) = requested_at {
                    fields.insert(
                        "dispatch_utc_unix_ms".into(),
                        JsonValue::U64(time.as_millis() as u64),
                    );
                }
                if let Some(text) = fields.remove("t") {
                    fields.insert("text".into(), text);
                }
                let phases: &[_] = match kind {
                    "click" => &["mouse_down", "mouse_up"],
                    "drag" => &["mouse_down", "move", "mouse_up"],
                    "key" => &["key_down", "key_up"],
                    _ => &[],
                };
                if !phases.is_empty() {
                    fields.insert(
                        "phases".into(),
                        JsonValue::Array(
                            phases
                                .iter()
                                .map(|phase| JsonValue::String((*phase).into()))
                                .collect(),
                        ),
                    );
                }
            }
            let (_, recording) = self.recordings.get_mut(&slot).expect("active recording");
            if let Err(error) = recording.action(entry, outcome, observation) {
                recording_status = self
                    .finish_recording(slot, session, "WRITE_FAILED", Some(&error))
                    .or_else(|| self.recording_status(slot, &format!("Recording error: {error}")));
            } else if let Err(error) = &result
                && remote_unavailable(error)
            {
                recording_status =
                    self.finish_recording(slot, session, "REMOTE_UNAVAILABLE", Some(error));
            }
        }
        Reply::Input {
            result,
            recording: recording_status,
            refresh: !motion,
        }
    }

    fn resize(&mut self, session: &Session, size: [u32; 2]) -> Result<Reply, String> {
        let [width, height] = size;
        let id = session.id.serialize_json();
        let window = session.window;
        let result = self.tool(
            "mss_resize",
            &format!(r#"{{"app_id":{id},"w":{window},"width":{width},"height":{height}}}"#),
        )?;
        let layout =
            pair(&result, "layout_size", JsonValue::as_f64).ok_or("Invalid layout size")?;
        let dpi = result
            .get("dpi")
            .and_then(JsonValue::as_f64)
            .filter(|dpi| *dpi > 0.0)
            .ok_or("Invalid app DPI")?;
        let geometry = ResizeGeometry {
            requested: size,
            layout,
            dpi,
        };
        Self::load_frame(session, &result, Some(geometry), None)
    }

    fn preview(
        &mut self,
        session: &Session,
        previous_sha256: Option<&str>,
        previous_resize: Option<(ResizeGeometry, [u32; 2])>,
    ) -> Result<Reply, String> {
        let id = session.id.serialize_json();
        let window = session.window;
        let result = self.tool(
            "mss_grab",
            &format!(r#"{{"app_id":{id},"w":{window},"preview":true}}"#),
        )?;
        if result.get("pid").and_then(JsonValue::as_u64) != Some(session.pid) {
            return Err("MSS preview process identity changed".into());
        }
        let pixels = pair(&result, "sz", |value| u32::try_from(value.as_u64()?).ok());
        let resize = previous_resize
            .filter(|(_, previous_pixels)| pixels == Some(*previous_pixels))
            .map(|(geometry, _)| geometry);
        Self::load_frame(session, &result, resize, previous_sha256)
    }

    fn load_frame(
        session: &Session,
        result: &JsonValue,
        resize: Option<ResizeGeometry>,
        previous_sha256: Option<&str>,
    ) -> Result<Reply, String> {
        if result.get("app_id").and_then(JsonValue::as_str) != Some(session.id.as_str())
            || result.get("w").and_then(JsonValue::as_u64) != Some(session.window)
            || result.get("capture_kind").and_then(JsonValue::as_str) != Some("pixels")
        {
            return Err("MSS frame is not bound to this tab".into());
        }
        let pixels = pair(result, "sz", |value| u32::try_from(value.as_u64()?).ok())
            .filter(|size| size.iter().all(|value| *value > 0))
            .ok_or("Invalid pixel dimensions")?;
        if resize.is_none() && u64::from(pixels[0]) * u64::from(pixels[1]) > 16 * 1024 * 1024 {
            return Err("MSS preview exceeds the pixel limit".into());
        }
        let png = result
            .get("png")
            .and_then(JsonValue::as_str)
            .and_then(|path| fs::canonicalize(path).ok())
            .filter(|path| path.parent() == Some(session.artifacts.as_path()))
            .ok_or("PNG is outside the app artifact directory")?;
        let sha256 = result
            .get("sha256")
            .and_then(JsonValue::as_str)
            .filter(|digest| {
                digest.len() == 64 && digest.bytes().all(|byte| byte.is_ascii_hexdigit())
            })
            .ok_or("Missing verified PNG digest")?;
        if Some(sha256) == previous_sha256 {
            return Ok(Reply::PreviewUnchanged);
        }
        let image = ImageBuffer::from_png(&read_png(&png, pixels)?)
            .map_err(|error| format!("PNG decode: {error}"))?;
        Ok(Reply::Frame(
            Frame {
                resize,
                pixels,
                sha256: sha256.to_owned(),
            },
            image,
        ))
    }

    fn close_app(&mut self, id: &str) -> Result<(), String> {
        let result = self.tool(
            "mss_close_app",
            &format!(r#"{{"app_id":{}}}"#, id.serialize_json()),
        )?;
        if result.get("state").and_then(JsonValue::as_str) == Some("CLOSED") {
            Ok(())
        } else {
            Err("MSS did not confirm that the app closed".into())
        }
    }

    fn close(mut self) {
        for (_, recording) in self
            .recordings
            .values_mut()
            .filter(|(_, recording)| recording.active)
        {
            let _ = recording.finish(Evidence::default(), "VIEWER_SHUTDOWN");
        }
        let Self {
            mut child,
            input,
            output,
            ..
        } = self;
        drop(input);
        drop(output);
        let _ = child.wait();
    }
}

fn remote_unavailable(error: &str) -> bool {
    [
        "TRANSPORT_LOST",
        "OUTCOME_UNKNOWN",
        "APP_UNAVAILABLE",
        "IDENTITY_UNVERIFIED",
        "MSS MCP",
    ]
    .iter()
    .any(|code| error.contains(code))
}

fn object<const N: usize>(fields: [(&str, JsonValue); N]) -> JsonValue {
    JsonValue::Object(
        fields
            .into_iter()
            .map(|(key, value)| (key.into(), value))
            .collect(),
    )
}

fn tree_window(tree: &JsonValue) -> Option<&JsonValue> {
    tree.get("trees")?.as_array()?.first()
}

fn focused(window: &JsonValue) -> Option<&JsonValue> {
    let id = window.get("focus")?.as_str()?;
    window
        .get("nodes")?
        .as_array()?
        .iter()
        .find(|node| node.get("id").and_then(JsonValue::as_str) == Some(id))
}

fn semantic_fields(node: &JsonValue) -> JsonValue {
    let keys = [
        "id",
        "role",
        "path",
        "state",
        "value",
        "text",
        "selection",
        "name",
    ];
    JsonValue::Object(
        keys.into_iter()
            .filter_map(|key| Some((key.into(), node.get(key)?.clone())))
            .collect(),
    )
}

fn observation(
    event: &Input,
    before: Option<&JsonValue>,
    after: Option<&JsonValue>,
) -> Option<JsonValue> {
    let after = tree_window(after?)?;
    let node = focused(after)?;
    let id = node.get("id")?.as_str()?;
    if let Input::Click { point, .. } | Input::Drag { end: point, .. } = event {
        let [x, y, width, height] = node.get("bounds")?.as_array()?.as_slice() else {
            return None;
        };
        let (x, y, width, height) = (x.as_f64()?, y.as_f64()?, width.as_f64()?, height.as_f64()?);
        if !(x..x + width).contains(&point.x) || !(y..y + height).contains(&point.y) {
            return None;
        }
    } else if !matches!(event, Input::Text(_) | Input::Key { .. }) {
        return None;
    }
    let previous = before.and_then(tree_window).and_then(|window| {
        window
            .get("nodes")?
            .as_array()?
            .iter()
            .find(|node| node.get("id").and_then(JsonValue::as_str) == Some(id))
    });
    let old = previous.map(semantic_fields);
    let new = semantic_fields(node);
    let verified_change = old.as_ref().is_some_and(|previous| previous != &new);
    Some(object([
        ("binding", JsonValue::String("GUEST_FOCUS_OBSERVED".into())),
        ("before", old.unwrap_or(JsonValue::Null)),
        ("after", new),
        ("observed_change", JsonValue::Bool(verified_change)),
    ]))
}

fn input_args(event: &Input) -> (&'static str, String, &'static str) {
    let point_args = |point: DVec2| format!(r#""x":{},"y":{}"#, point.x, point.y);
    match event {
        Input::Move { point, modifiers } => (
            "mss_ui_mouse",
            format!(
                r#""k":"move",{},{}"#,
                point_args(*point),
                modifier_args(*modifiers)
            ),
            "move",
        ),
        Input::Click {
            point,
            button,
            modifiers,
        } => (
            "mss_ui_mouse",
            format!(
                r#""k":"click",{},"b":{button},{}"#,
                point_args(*point),
                modifier_args(*modifiers)
            ),
            "click",
        ),
        Input::Drag {
            start,
            end,
            button,
            modifiers,
        } => (
            "mss_ui_mouse",
            format!(
                r#""k":"drag",{},"x1":{},"y1":{},"b":{button},{}"#,
                point_args(*start),
                end.x,
                end.y,
                modifier_args(*modifiers)
            ),
            "drag",
        ),
        Input::Scroll {
            point,
            delta,
            modifiers,
        } => (
            "mss_ui_mouse",
            format!(
                r#""k":"scroll",{},"dx":{},"dy":{},{}"#,
                point_args(*point),
                delta.x,
                delta.y,
                modifier_args(*modifiers)
            ),
            "scroll",
        ),
        Input::Key { code, modifiers } => (
            "mss_ui_key",
            format!(r#""c":"{code}","k":"press",{}"#, modifier_args(*modifiers)),
            "key",
        ),
        Input::Text(text) => (
            "mss_ui_key",
            format!(r#""t":{}"#, text.serialize_json()),
            "text",
        ),
    }
}

fn modifier_args(modifiers: KeyModifiers) -> String {
    let KeyModifiers {
        control,
        shift,
        alt,
        ..
    } = modifiers;
    format!(r#""ctrl":{control},"shift":{shift},"alt":{alt}"#)
}

fn valid_app_id(id: &str) -> bool {
    id.strip_prefix("app_").is_some_and(|suffix| {
        suffix.len() == 32 && suffix.bytes().all(|byte| byte.is_ascii_hexdigit())
    })
}

fn app_argument(id: &str) -> String {
    format!(r#"{{"app_id":{}}}"#, id.serialize_json())
}

fn pair<T>(
    value: &JsonValue,
    key: &str,
    parse: impl Fn(&JsonValue) -> Option<T>,
) -> Option<[T; 2]> {
    let [first, second] = value.get(key)?.as_array()?.as_slice() else {
        return None;
    };
    Some([parse(first)?, parse(second)?])
}

fn read_png(path: &Path, pixels: [u32; 2]) -> Result<Vec<u8>, String> {
    let mut data = Vec::new();
    fs::File::open(path)
        .and_then(|file| file.take(MAX_PNG_BYTES + 1).read_to_end(&mut data))
        .map_err(|error| format!("PNG read: {error}"))?;
    if data.len() as u64 > MAX_PNG_BYTES
        || data.get(..8) != Some(b"\x89PNG\r\n\x1a\n")
        || data.get(12..16) != Some(b"IHDR")
        || data.get(16..20) != Some(&pixels[0].to_be_bytes())
        || data.get(20..24) != Some(&pixels[1].to_be_bytes())
    {
        return Err("PNG dimensions disagree with the verified frame".into());
    }
    Ok(data)
}
