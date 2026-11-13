//! Native viewer for independently owned hidden MSS instances.
pub use makepad_widgets;
use makepad_widgets::*;

mod codex_handoff;
mod human_input;
mod recording;
mod remote_client;
mod runtime_paths;
use human_input::{Input, InputView, Press, committed_text, guest_point, key_code, mouse_button};
use recording::{ExportOptions, HandoffPackage};
use remote_client::{
    Frame, InputGeometry, Job, RecordingCommand, RecordingStatus, Reply, Session, Worker,
};
use std::collections::VecDeque;
use std::time::{Duration, Instant};

app_main!(App);

const TAB_NAMES: [&str; 4] = ["RudraOffice A", "RudraOffice B", "AI CAD", "Shared app"];
const AI_CAD_TAB: usize = 2;
const OTHER_APP_TAB: usize = 3;
const MAX_PENDING_INPUTS: usize = 24;

script_mod! {
    use mod.prelude.widgets.*

    startup() do #(App::script_component(vm)) {
        ui: Root {
            main_window := Window {
                window.inner_size: vec2(1100, 720)
                body +: {
                    View {
                        width: Fill height: Fill flow: Down
                        show_bg: true draw_bg.color: #151b27
                        View {
                            width: Fill height: 52 flow: Right padding: 12 spacing: 14
                            align: Align{y: 0.5}
                            show_bg: true draw_bg.color: #202b3c
                            Label { text: "Makepad SandStudio" draw_text.text_style.font_size: 20 }
                        }
                        SplitPane {
                            width: Fill height: Fill
                            axis: Horizontal
                            align: SplitterAlign.FromA(235.0)
                            min_horizontal: 165.0 max_horizontal: 240.0
                            a: View {
                                width: Fill height: Fill flow: Down padding: 14 spacing: 10
                                show_bg: true draw_bg.color: #202736
                                first_tab := Button { text: "RudraOffice A" }
                                second_tab := Button { text: "RudraOffice B" }
                                cad_tab := Button { text: "AI CAD" }
                                shared_tab := Button { text: "Shared app" }
                                discover_app := Button { text: "Find shared apps" }
                                app_id_input := TextInput { width: Fill empty_text: "MSS App ID" }
                                attach_app := Button { text: "Attach App ID" }
                                detach_view := Button { text: "Detach view" }
                                launch_app := Button { text: "Launch selected app" }
                                close_tab := Button { text: "Close selected app" }
                            }
                            b: View {
                                width: Fill height: Fill flow: Down
                                viewer_status := Label { width: Fill text: "Select a tab and connect an app." }
                                viewer_app_id := Label { width: Fill text: "" }
                                shared_apps := Label { width: Fill text: "" }
                                View {
                                    width: Fill height: Fit flow: Right spacing: 8 padding: 4
                                    screenshot_action := Button { text: "Screenshot" }
                                    record_action := Button { text: "Start recording" }
                                    transfer_action := Button { text: "Prepare for Codex" }
                                    review_recording := Button { text: "Review files" }
                                }
                                recording_description := TextInput { width: Fill empty_text: "What did you demonstrate and what should happen?" }
                                View {
                                    width: Fill height: Fit flow: Right spacing: 10 padding: 4
                                    include_text := CheckBox { text: "Include typed text" }
                                    include_frames := CheckBox { text: "Include screenshots" }
                                    include_tree := CheckBox { text: "Include UI trees and their text" }
                                }
                                recording_status := Label { width: Fill text: "Review the files before sharing a package." }
                                viewport := View {
                                    width: Fill height: Fill
                                    show_bg: true draw_bg.color: #293346
                                    preview := Image {
                                        width: Fill height: Fill fit: ImageFit.Smallest
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

#[derive(Default)]
struct Tab {
    session: Option<Session>,
    frame: Option<Frame>,
    texture: Option<Texture>,
    error: Option<String>,
    input_error: Option<String>,
    resync: bool,
    launch_requested: bool,
    close_requested: bool,
    detach_requested: bool,
    attach_requested: Option<String>,
    discover_requested: bool,
    discovered: Vec<(String, u64)>,
    hidden: bool,
    recording: Option<RecordingStatus>,
    record_request: Option<RecordingCommand>,
    record_busy: bool,
    recording_description: String,
    prepared_handoff: Option<HandoffPackage>,
    handoff: Option<std::sync::mpsc::Receiver<codex_handoff::Delivery>>,
    handoff_result: Option<codex_handoff::Delivery>,
}

#[derive(Script, ScriptHook)]
pub struct App {
    #[live]
    ui: WidgetRef,
    #[rust]
    worker: Option<Worker>,
    #[rust]
    tabs: [Tab; TAB_NAMES.len()],
    #[rust]
    selected: usize,
    #[rust]
    pending: Option<usize>,
    #[rust]
    viewport: Option<[u32; 2]>,
    #[rust]
    debounce: Timer,
    #[rust]
    displayed: Option<(usize, String)>,
    #[rust]
    drawn_input: Option<InputView>,
    #[rust]
    press: Option<Press>,
    #[rust]
    human_inputs: VecDeque<(InputView, Input)>,
    #[rust]
    last_recorded_move: Option<Instant>,
}

impl App {
    fn displayed_input_view(&self) -> Option<InputView> {
        let tab = &self.tabs[self.selected];
        let session = tab.session.as_ref()?;
        let frame = tab.frame.as_ref()?;
        let resize = frame.resize?;
        if !session.resize_allowed
            || tab.hidden
            || tab.close_requested
            || tab.detach_requested
            || tab.error.is_some()
            || Some(resize.requested) != self.viewport
            || !self
                .displayed
                .as_ref()
                .is_some_and(|(slot, hash)| *slot == self.selected && *hash == frame.sha256)
        {
            return None;
        }
        Some(InputView {
            slot: self.selected,
            app_id: session.id.clone(),
            geometry: InputGeometry {
                resize,
                pixels: frame.pixels,
            },
        })
    }

    fn clear_human_focus(&mut self, cx: &mut Cx) {
        self.press = None;
        self.human_inputs.clear();
        let area = self.ui.image(cx, ids!(preview)).area();
        if cx.key_focus() == area {
            cx.set_key_focus(Area::Empty);
        }
    }

    fn handle_human_input(&mut self, cx: &mut Cx, event: &Event) {
        if matches!(event, Event::WindowLostFocus(_)) {
            self.clear_human_focus(cx);
            return;
        }
        if !matches!(
            event,
            Event::MouseDown(_)
                | Event::MouseMove(_)
                | Event::MouseUp(_)
                | Event::FingerCancel(_)
                | Event::Scroll(_)
                | Event::KeyDown(_)
                | Event::KeyFocus(_)
                | Event::TextInput(_)
        ) {
            return;
        }
        let Some(view) = self
            .displayed_input_view()
            .filter(|view| Some(view) == self.drawn_input.as_ref())
        else {
            return;
        };
        let area = self.ui.image(cx, ids!(preview)).area();
        let rect = area.rect(cx);
        let clip = area.clipped_rect(cx);
        let point = |abs| guest_point(abs, rect, clip, view.geometry.resize.layout);
        if let Event::MouseDown(mouse) = event
            && point(mouse.abs).is_none()
        {
            self.clear_human_focus(cx);
            return;
        }
        if let Event::MouseMove(motion) = event {
            if self.tabs[self.selected]
                .recording
                .as_ref()
                .is_some_and(|status| status.active)
                && self.press.is_none()
                && self.human_inputs.is_empty()
                && self
                    .last_recorded_move
                    .is_none_or(|time| time.elapsed() >= Duration::from_millis(75))
                && !motion.modifiers.logo
                && let Some(point) = point(motion.abs)
            {
                self.last_recorded_move = Some(Instant::now());
                self.human_inputs.push_back((
                    view,
                    Input::Move {
                        point,
                        modifiers: motion.modifiers,
                    },
                ));
                self.drive_selected();
            }
            return;
        }
        let input = match event.hits(cx, area) {
            Hit::FingerDown(down) => {
                if let (Some(point), Some(button)) =
                    (point(down.abs), down.mouse_button().and_then(mouse_button))
                    && !down.modifiers.logo
                {
                    self.press = Some(Press {
                        view,
                        point,
                        button,
                        modifiers: down.modifiers,
                    });
                }
                return;
            }
            Hit::FingerUp(up) => {
                let Some(press) = self.press.take() else {
                    return;
                };
                if up.cancelled
                    || !up.is_over
                    || press.view != view
                    || up.mouse_button().and_then(mouse_button) != Some(press.button)
                {
                    return;
                }
                let Some(end) = point(up.abs) else {
                    return;
                };
                cx.set_key_focus(area);
                if (up.abs - up.abs_start).length() < 3.0 {
                    Input::Click {
                        point: end,
                        button: press.button,
                        modifiers: press.modifiers,
                    }
                } else {
                    Input::Drag {
                        start: press.point,
                        end,
                        button: press.button,
                        modifiers: press.modifiers,
                    }
                }
            }
            Hit::FingerScroll(scroll) if !scroll.modifiers.logo => {
                let Some(point) = point(scroll.abs) else {
                    return;
                };
                let delta = scroll.scroll;
                if !delta.x.is_finite()
                    || !delta.y.is_finite()
                    || !(0.0 < delta.x.abs().max(delta.y.abs())
                        && delta.x.abs().max(delta.y.abs()) <= 10000.0)
                {
                    return;
                }
                Input::Scroll {
                    point,
                    delta,
                    modifiers: scroll.modifiers,
                }
            }
            Hit::KeyDown(key) if self.press.is_none() => {
                let Some(code) = key_code(key) else {
                    return;
                };
                Input::Key {
                    code,
                    modifiers: key.modifiers,
                }
            }
            Hit::TextInput(text) if self.press.is_none() => {
                let Some(text) = committed_text(text) else {
                    return;
                };
                Input::Text(text)
            }
            Hit::KeyFocusLost(_) => {
                self.clear_human_focus(cx);
                return;
            }
            _ => return,
        };
        if self.human_inputs.len() == MAX_PENDING_INPUTS {
            self.clear_human_focus(cx);
            self.tabs[self.selected].input_error =
                Some("Input queue full · click the preview to continue".into());
            self.show_selected(cx);
            return;
        }
        self.human_inputs.push_back((view, input));
        self.drive_selected();
    }
    fn show_recording(&mut self, cx: &mut Cx) {
        let tab = &self.tabs[self.selected];
        let active = tab.recording.as_ref().is_some_and(|status| status.active);
        self.ui.button(cx, ids!(record_action)).set_text(
            cx,
            if active {
                "Stop recording"
            } else {
                "Start recording"
            },
        );
        let label = if tab.handoff.is_some() {
            "Sending to Codex…"
        } else if tab.prepared_handoff.is_some() {
            "Send to Codex"
        } else {
            "Prepare for Codex"
        };
        self.ui
            .button(cx, ids!(transfer_action))
            .set_text(cx, label);
        let result_text;
        let text = if tab.handoff.is_some() {
            "SENDING · Codex is reading the reviewed package"
        } else if let Some(result) = &tab.handoff_result {
            result_text = if result.status == "RECEIVED" {
                format!(
                    "RECEIVED · {} · Review files for analysis",
                    result.directory.display()
                )
            } else {
                format!(
                    "{} · {} · {}",
                    result.status,
                    result.message,
                    result.directory.display()
                )
            };
            &result_text
        } else if tab.record_busy {
            "Saving recording data…"
        } else {
            tab.recording
                .as_ref()
                .map_or("Review the files before sharing a package.", |status| {
                    status.message.as_str()
                })
        };
        self.ui.label(cx, ids!(recording_status)).set_text(cx, text);
    }

    fn reset_export_options(&self, cx: &mut Cx) {
        self.ui
            .check_box(cx, ids!(include_text))
            .set_active(cx, false, Animate::No);
        self.ui
            .check_box(cx, ids!(include_frames))
            .set_active(cx, false, Animate::No);
        self.ui
            .check_box(cx, ids!(include_tree))
            .set_active(cx, false, Animate::No);
    }

    fn poll_handoffs(&mut self, cx: &mut Cx) {
        let mut redraw = false;
        for (slot, tab) in self.tabs.iter_mut().enumerate() {
            let Some(receiver) = &tab.handoff else {
                continue;
            };
            match codex_handoff::poll(receiver) {
                Ok(None) => continue,
                Ok(Some(delivery)) => tab.handoff_result = Some(delivery),
                Err(_) => {
                    tab.handoff_result = Some(codex_handoff::Delivery {
                        directory: tab
                            .recording
                            .as_ref()
                            .and_then(|status| status.directory.clone())
                            .unwrap_or_default(),
                        status: "OUTCOME_UNKNOWN",
                        message: "Codex delivery worker ended without a receipt.".into(),
                    })
                }
            }
            tab.handoff = None;
            redraw |= slot == self.selected;
        }
        if redraw {
            self.show_recording(cx);
        }
    }

    fn recording_action(&mut self, cx: &mut Cx, actions: &Actions) -> bool {
        let tab = &self.tabs[self.selected];
        let active = tab.recording.as_ref().is_some_and(|status| status.active);
        let transfer = self.ui.button(cx, ids!(transfer_action)).clicked(actions);
        let review = self.ui.button(cx, ids!(review_recording)).clicked(actions);
        if review && let Some(result) = &tab.handoff_result {
            if let Err(error) = open_recording_folder(&result.directory) {
                self.ui
                    .label(cx, ids!(recording_status))
                    .set_text(cx, &format!("{} · {error}", result.status));
            }
            return true;
        }
        if review {
            if let Some(status) = self.tabs[self.selected].recording.as_mut()
                && let Some(directory) = &status.directory
                && let Err(error) = open_recording_folder(directory)
            {
                status.message = format!("Review files · {} · {error}", directory.display());
                self.show_recording(cx);
            }
            return true;
        }
        if transfer && tab.handoff.is_some() {
            return true;
        }
        let editing = self
            .ui
            .check_box(cx, ids!(include_text))
            .changed(actions)
            .is_some()
            || self
                .ui
                .check_box(cx, ids!(include_frames))
                .changed(actions)
                .is_some()
            || self
                .ui
                .check_box(cx, ids!(include_tree))
                .changed(actions)
                .is_some();
        let description = self.ui.text_input(cx, ids!(recording_description)).text();
        if let Some(package) = &tab.prepared_handoff
            && (editing
                || description.trim() != package.description.trim()
                || !package.matches_options(ExportOptions {
                    text: self.ui.check_box(cx, ids!(include_text)).active(cx),
                    frames: self.ui.check_box(cx, ids!(include_frames)).active(cx),
                    tree: self.ui.check_box(cx, ids!(include_tree)).active(cx),
                }))
        {
            let tab = &mut self.tabs[self.selected];
            tab.prepared_handoff = None;
            if let Some(status) = &mut tab.recording {
                status.message = "Package selection changed · prepare again".into();
            }
            self.show_recording(cx);
        }
        let tab = &mut self.tabs[self.selected];
        if transfer && let Some(package) = tab.prepared_handoff.take() {
            tab.handoff = Some(codex_handoff::start(package));
            self.show_recording(cx);
            return true;
        }
        let command = if self.ui.button(cx, ids!(screenshot_action)).clicked(actions) {
            RecordingCommand::Screenshot
        } else if self.ui.button(cx, ids!(record_action)).clicked(actions) {
            if active {
                RecordingCommand::Stop
            } else {
                RecordingCommand::Start
            }
        } else if transfer {
            if let Some(result) = &tab.handoff_result
                && matches!(result.status, "OUTCOME_UNKNOWN" | "RECEIVED")
            {
                self.show_recording(cx);
                return true;
            }
            let options = ExportOptions {
                text: self.ui.check_box(cx, ids!(include_text)).active(cx),
                frames: self.ui.check_box(cx, ids!(include_frames)).active(cx),
                tree: self.ui.check_box(cx, ids!(include_tree)).active(cx),
            };
            let Some(directory) = tab
                .recording
                .as_ref()
                .and_then(|status| status.recording_directory.clone())
            else {
                self.ui
                    .label(cx, ids!(recording_status))
                    .set_text(cx, "Select a stopped recording to prepare");
                return true;
            };
            RecordingCommand::Export {
                directory,
                description,
                options,
            }
        } else {
            return false;
        };
        if tab.record_busy {
            return true;
        }
        if matches!(command, RecordingCommand::Start) {
            self.reset_export_options(cx);
        }
        self.clear_human_focus(cx);
        let tab = &mut self.tabs[self.selected];
        if matches!(
            command,
            RecordingCommand::Start | RecordingCommand::Export { .. }
        ) {
            tab.prepared_handoff = None;
            tab.handoff_result = None;
        }
        tab.record_busy = true;
        tab.record_request = Some(command);
        self.show_recording(cx);
        self.drive_selected();
        true
    }

    fn queue(&mut self, slot: usize, job: Job) {
        let worker = self.worker.get_or_insert_with(Worker::start);
        if worker.send(slot, job) {
            self.pending = Some(slot);
        } else {
            self.tabs[slot].error = Some("MSS worker unavailable".into());
        }
    }

    fn schedule_refresh(&mut self, cx: &mut Cx) {
        cx.stop_timer(self.debounce);
        let delay = if self.tabs[self.selected].frame.is_some() {
            0.25
        } else {
            0.12
        };
        self.debounce = cx.start_timeout(delay);
    }

    fn drive_selected(&mut self) {
        if self.pending.is_some() {
            return;
        }
        if let Some(slot) = self
            .tabs
            .iter()
            .position(|tab| tab.close_requested || tab.detach_requested)
        {
            let tab = &mut self.tabs[slot];
            let close = std::mem::take(&mut tab.close_requested);
            tab.detach_requested = false;
            if let Some(session) = tab.session.clone() {
                if close && session.owner {
                    self.queue(slot, Job::Close(session));
                } else if !session.owner {
                    self.queue(slot, Job::Detach(session));
                }
                return;
            }
        }
        if let Some(slot) = self
            .tabs
            .iter()
            .position(|tab| tab.record_request.is_some())
        {
            let tab = &mut self.tabs[slot];
            if let Some(command) = tab.record_request.take() {
                let session = tab.session.clone();
                self.queue(slot, Job::Recording { session, command });
                return;
            }
        }
        while let Some((view, event)) = self.human_inputs.pop_front() {
            if self.drawn_input.as_ref() == Some(&view)
                && self.displayed_input_view().as_ref() == Some(&view)
                && let Some(session) = self.tabs[view.slot].session.clone()
            {
                self.queue(
                    view.slot,
                    Job::Input {
                        session,
                        geometry: view.geometry,
                        event,
                    },
                );
                return;
            }
        }
        let profile = tab_profile(self.selected);
        let tab = &mut self.tabs[self.selected];
        if std::mem::take(&mut tab.discover_requested) {
            self.queue(self.selected, Job::Discover(profile));
            return;
        }
        if let Some(id) = tab.attach_requested.take() {
            self.queue(self.selected, Job::Attach { id, profile });
            return;
        }
        if std::mem::take(&mut tab.launch_requested)
            && let Some(profile) = profile
        {
            self.queue(self.selected, Job::Launch(profile));
            return;
        }
        if tab.hidden || tab.error.is_some() {
            return;
        }
        if let (Some(size), Some(session)) = (self.viewport, &tab.session) {
            let previous_resize = tab
                .frame
                .as_ref()
                .and_then(|frame| frame.resize.map(|geometry| (geometry, frame.pixels)));
            let job = if session.resize_allowed
                && (tab.resync
                    || previous_resize.is_none_or(|(geometry, _)| geometry.requested != size))
            {
                Job::Resize {
                    session: session.clone(),
                    size,
                }
            } else if !session.owner || !session.resize_allowed {
                Job::Preview {
                    session: session.clone(),
                    previous_sha256: tab.frame.as_ref().map(|frame| frame.sha256.clone()),
                    previous_resize,
                }
            } else {
                return;
            };
            self.queue(self.selected, job);
        }
    }

    fn show_selected(&mut self, cx: &mut Cx) {
        self.show_recording(cx);
        let tab = &self.tabs[self.selected];
        let label = self.ui.label(cx, ids!(viewer_status));
        let image = self.ui.image(cx, ids!(preview));
        let name = TAB_NAMES[self.selected];
        let session = tab.session.as_ref().filter(|_| !tab.hidden);
        self.ui
            .label(cx, ids!(viewer_app_id))
            .set_text(cx, session.map_or("", |session| session.id.as_str()));
        let shared = tab
            .discovered
            .iter()
            .map(|(id, pid)| format!("{id} (PID {pid})"))
            .collect::<Vec<_>>()
            .join("    ");
        self.ui.label(cx, ids!(shared_apps)).set_text(cx, &shared);
        if session.is_some()
            && tab.error.is_none()
            && let Some(frame) = tab.frame.as_ref().filter(|frame| {
                frame.resize.as_ref().map_or(
                    !session.is_some_and(|session| session.resize_allowed),
                    |geometry| Some(geometry.requested) == self.viewport,
                )
            })
        {
            let same_image = self
                .displayed
                .as_ref()
                .is_some_and(|(slot, hash)| *slot == self.selected && *hash == frame.sha256);
            if same_image && frame.resize.is_none() {
                return;
            }
            if tab.texture.is_some() {
                if !same_image {
                    image.set_texture(cx, tab.texture.clone());
                }
                self.displayed = Some((self.selected, frame.sha256.clone()));
                let pid = tab
                    .session
                    .as_ref()
                    .expect("a frame has an owning session")
                    .pid;
                let [pixels_wide, pixels_high] = frame.pixels;
                let text = if let Some(geometry) = &frame.resize {
                    let [width, height] = geometry.layout;
                    format!(
                        "{name} · PID {pid} · {width:.1} × {height:.1} pt · {pixels_wide} × {pixels_high} px · DPI ×{:.2}",
                        geometry.dpi
                    )
                } else {
                    format!("{name} · PID {pid} · {pixels_wide} × {pixels_high} px · просмотр")
                };
                let text = if let Some(error) = &tab.input_error {
                    format!("{text} · {error}")
                } else if session.is_some_and(|session| session.resize_allowed) {
                    format!("{text} · Click preview to send input")
                } else {
                    text
                };
                label.set_text(cx, &text);
                self.ui.redraw(cx);
                return;
            }
            label.set_text(cx, &format!("{name} · no decoded frame"));
        } else if let Some(error) = &tab.error {
            label.set_text(cx, &format!("{name} · {error}"));
        } else if session.is_some() {
            label.set_text(cx, &format!("{name} · waiting for a native frame"));
        } else {
            label.set_text(cx, &format!("{name} · view disconnected"));
        }
        self.displayed = None;
        image.set_texture(cx, None);
        self.ui.redraw(cx);
    }

    fn select(&mut self, cx: &mut Cx, slot: usize) {
        if self.selected != slot {
            self.clear_human_focus(cx);
            self.drawn_input = None;
            self.tabs[self.selected].recording_description =
                self.ui.text_input(cx, ids!(recording_description)).text();
            self.ui
                .text_input(cx, ids!(recording_description))
                .set_text(cx, &self.tabs[slot].recording_description);
            self.reset_export_options(cx);
            self.tabs[slot].resync = true;
        }
        self.selected = slot;
        if !self.tabs[slot].detach_requested && self.pending != Some(slot) {
            self.tabs[slot].hidden = false;
        }
        self.show_selected(cx);
        self.schedule_refresh(cx);
    }

    fn complete(&mut self, cx: &mut Cx) {
        let Some(reply) = self.worker.as_ref().and_then(Worker::try_receive) else {
            return;
        };
        let Some(slot) = self.pending.take() else {
            return;
        };
        let mut input_failed = false;
        if reply.slot != slot {
            self.tabs[slot].error = Some("MSS reply did not match the pending tab".into());
        } else {
            let tab = &mut self.tabs[slot];
            match reply.result {
                Ok(Reply::Connected(session)) => {
                    tab.session = Some(session);
                    tab.resync = true;
                    tab.recording = None;
                    tab.prepared_handoff = None;
                    if tab.handoff.is_none() {
                        tab.handoff_result = None;
                    }
                    tab.recording_description.clear();
                    if slot == self.selected {
                        self.ui
                            .text_input(cx, ids!(recording_description))
                            .set_text(cx, "");
                        self.reset_export_options(cx);
                    }
                }
                Ok(Reply::Frame(frame, image)) => {
                    tab.texture = Some(image.into_new_texture(cx));
                    tab.frame = Some(frame);
                    tab.resync = false;
                }
                Ok(Reply::Discovered(apps)) => {
                    if slot == self.selected
                        && let [(id, _)] = apps.as_slice()
                    {
                        self.ui.text_input(cx, ids!(app_id_input)).set_text(cx, id);
                    }
                    tab.discovered = apps;
                }
                Ok(Reply::PreviewUnchanged) => {}
                Ok(Reply::Input {
                    result,
                    recording,
                    refresh,
                }) => {
                    tab.input_error = result.err();
                    input_failed = tab.input_error.is_some();
                    if refresh {
                        tab.resync = !input_failed
                            && tab.session.as_ref().is_some_and(|session| session.owner);
                    }
                    if recording.is_some() {
                        tab.recording = recording;
                    }
                }
                Ok(Reply::Prepared { status, package }) => {
                    tab.record_busy = false;
                    tab.recording = Some(status);
                    tab.prepared_handoff = Some(package);
                }
                Ok(Reply::Recording(result)) => {
                    tab.record_busy = false;
                    match result {
                        Ok(status) => {
                            if status.active
                                && tab.hidden
                                && tab.session.as_ref().is_some_and(|session| session.owner)
                            {
                                tab.record_request = Some(RecordingCommand::Stop);
                                tab.record_busy = true;
                            }
                            tab.recording = Some(status);
                        }
                        Err(message) => {
                            let active = tab.recording.as_ref().is_some_and(|status| status.active);
                            let directory = tab
                                .recording
                                .as_ref()
                                .and_then(|status| status.directory.clone());
                            let recording_directory = tab
                                .recording
                                .as_ref()
                                .and_then(|status| status.recording_directory.clone());
                            tab.recording = Some(RecordingStatus {
                                active,
                                message,
                                directory,
                                recording_directory,
                            });
                        }
                    }
                }
                Ok(Reply::Disconnected(recording)) => {
                    let recording = recording.or_else(|| tab.recording.take());
                    let recording_description = std::mem::take(&mut tab.recording_description);
                    let handoff = tab.handoff.take();
                    let handoff_result = tab.handoff_result.take();
                    let prepared_handoff = tab.prepared_handoff.take();
                    *tab = Tab {
                        recording,
                        recording_description,
                        handoff,
                        handoff_result,
                        prepared_handoff,
                        ..Tab::default()
                    };
                }
                Ok(Reply::SessionError { error, recording }) => {
                    tab.frame = None;
                    tab.texture = None;
                    tab.error = Some(error);
                    if recording.is_some() {
                        tab.recording = recording;
                    }
                }
                Err(error) => {
                    tab.frame = None;
                    tab.texture = None;
                    tab.error = Some(error);
                }
            }
        }
        if slot == self.selected {
            if input_failed {
                self.clear_human_focus(cx);
            }
            self.show_selected(cx);
        }
        if !self.human_inputs.is_empty() || self.tabs.iter().any(|tab| tab.record_request.is_some())
        {
            self.drive_selected();
        }
        self.schedule_refresh(cx);
    }
}

fn open_recording_folder(directory: &std::path::Path) -> Result<(), String> {
    #[cfg(windows)]
    {
        let explorer = std::env::var_os("SystemRoot")
            .map(std::path::PathBuf::from)
            .map(|root| root.join("explorer.exe"))
            .filter(|path| path.is_absolute() && path.is_file())
            .ok_or("Windows Explorer is unavailable")?;
        std::process::Command::new(explorer)
            .arg(directory)
            .spawn()
            .map_err(|error| error.to_string())?;
        Ok(())
    }
    #[cfg(not(windows))]
    {
        Err(format!("Open {} in your file manager", directory.display()))
    }
}

fn tab_profile(slot: usize) -> Option<&'static str> {
    match slot {
        AI_CAD_TAB => Some("ai-cad"),
        OTHER_APP_TAB => None,
        _ => Some("rudraoffice"),
    }
}

fn viewport_points(size: DVec2) -> Option<[u32; 2]> {
    let width = size.x.floor();
    let height = size.y.floor();
    if (1.0..=16384.0).contains(&width) && (1.0..=16384.0).contains(&height) {
        Some([width as u32, height as u32])
    } else {
        None
    }
}

impl MatchEvent for App {
    fn handle_actions(&mut self, cx: &mut Cx, actions: &Actions) {
        if self.recording_action(cx, actions) {
            return;
        }
        if self.ui.button(cx, ids!(first_tab)).clicked(actions) {
            self.select(cx, 0);
        } else if self.ui.button(cx, ids!(second_tab)).clicked(actions) {
            self.select(cx, 1);
        } else if self.ui.button(cx, ids!(cad_tab)).clicked(actions) {
            self.select(cx, AI_CAD_TAB);
        } else if self.ui.button(cx, ids!(shared_tab)).clicked(actions) {
            self.select(cx, OTHER_APP_TAB);
        } else {
            let tab = &mut self.tabs[self.selected];
            if self.ui.button(cx, ids!(discover_app)).clicked(actions) {
                tab.discover_requested = true;
            } else if self.ui.button(cx, ids!(attach_app)).clicked(actions)
                && tab.session.is_none()
                && self.pending != Some(self.selected)
            {
                let id = self.ui.text_input(cx, ids!(app_id_input)).text();
                tab.error = None;
                tab.hidden = false;
                tab.attach_requested = Some(id.trim().to_owned());
                tab.launch_requested = false;
            } else if self.ui.button(cx, ids!(launch_app)).clicked(actions)
                && tab_profile(self.selected).is_some()
                && tab.session.is_none()
                && self.pending != Some(self.selected)
            {
                tab.error = None;
                tab.hidden = false;
                tab.launch_requested = true;
                tab.attach_requested = None;
            } else if self.ui.button(cx, ids!(detach_view)).clicked(actions) {
                tab.hidden = true;
                if tab.session.as_ref().is_some_and(|session| session.owner)
                    && tab.recording.as_ref().is_some_and(|status| status.active)
                {
                    tab.record_request = Some(RecordingCommand::Stop);
                    tab.record_busy = true;
                }
                tab.detach_requested = tab.session.as_ref().is_some_and(|session| !session.owner)
                    || (tab.session.is_none() && self.pending == Some(self.selected));
                tab.launch_requested = false;
                tab.attach_requested = None;
                self.clear_human_focus(cx);
                self.drawn_input = None;
                self.show_selected(cx);
            } else if self.ui.button(cx, ids!(close_tab)).clicked(actions)
                && tab.session.as_ref().is_some_and(|session| session.owner)
            {
                tab.close_requested = true;
                self.clear_human_focus(cx);
                self.drawn_input = None;
            } else {
                return;
            }
            self.drive_selected();
        }
    }
}

impl AppMain for App {
    fn script_mod(vm: &mut ScriptVm) -> ScriptValue {
        crate::makepad_widgets::script_mod(vm);
        self::script_mod(vm)
    }

    fn handle_event(&mut self, cx: &mut Cx, event: &Event) {
        self.handle_human_input(cx, event);
        self.match_event(cx, event);
        self.ui.handle_event(cx, event, &mut Scope::empty());
        match event {
            Event::Draw(_) => {
                let points = viewport_points(self.ui.view(cx, ids!(viewport)).area().rect(cx).size);
                if self.viewport != points {
                    self.clear_human_focus(cx);
                    self.viewport = points;
                    self.show_selected(cx);
                    self.schedule_refresh(cx);
                }
                self.drawn_input = self.displayed_input_view();
            }
            Event::Timer(timer) if self.debounce.is_timer(timer).is_some() => {
                self.drive_selected();
            }
            Event::Signal => {
                self.complete(cx);
                self.poll_handoffs(cx);
            }
            Event::Shutdown => {
                self.worker.take();
            }
            _ => {}
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn viewport_geometry_uses_layout_points_and_rejects_empty_areas() {
        assert_eq!(viewport_points(dvec2(800.9, 600.4)), Some([800, 600]));
        assert_eq!(viewport_points(dvec2(0., 600.)), None);
        assert_eq!(viewport_points(dvec2(800., f64::NAN)), None);
        assert_eq!(viewport_points(dvec2(16385., 1.)), None);
    }
}
