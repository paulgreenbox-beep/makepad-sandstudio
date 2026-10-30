//! Makepad SandStudio: native UI shell, no backend attached yet.
pub use makepad_widgets;
use makepad_widgets::*;

app_main!(App);

script_mod! {
    use mod.prelude.widgets.*

    startup() do #(App::script_component(vm)) {
        ui: Root {
            main_window := Window {
                window.inner_size: vec2(1100, 720)
                body +: {
                    View {
                        width: Fill
                        height: Fill
                        flow: Down
                        spacing: 0
                        draw_bg.color: #151b27

                        View {
                            width: Fill
                            height: 58
                            flow: Right
                            padding: 14
                            spacing: 16
                            align: { y: 0.5 }
                            draw_bg.color: #202b3c
                            Label {
                                text: "Makepad SandStudio"
                                draw_text.text_style.font_size: 20
                            }
                            Label { text: "Native session viewer  /  prototype" }
                        }

                        View {
                            width: Fill
                            height: Fill
                            flow: Right
                            spacing: 0

                            View {
                                width: 255
                                height: Fill
                                flow: Down
                                padding: 16
                                spacing: 13
                                draw_bg.color: #202736
                                Label {
                                    text: "SESSIONS"
                                    draw_text.text_style.font_size: 15
                                }
                                first_session := Button { text: "01  Document UI" }
                                second_session := Button { text: "02  Form Fixture" }
                                third_session := Button { text: "03  Virtual Canvas" }
                                View { height: 20 }
                                Label { text: "SELECTED SESSION" }
                                session_status := Label { text: "01  Document UI" }
                                runtime_status := Label { text: "State: NOT_CONNECTED" }
                                agent_status := Label { text: "Agent: unassigned" }
                                Label { text: "Isolation: no VM / container" }
                            }
                            View {
                                width: Fill
                                height: Fill
                                flow: Down
                                padding: 22
                                spacing: 16
                                draw_bg.color: #151b27
                                selected_title := Label {
                                    text: "Document UI"
                                    draw_text.text_style.font_size: 26
                                }
                                Label { text: "WINDOW PREVIEW  /  LAST FRAME" }
                                View {
                                    width: Fill
                                    height: Fill
                                    flow: Down
                                    align: Center
                                    spacing: 14
                                    draw_bg.color: #293346
                                    Label {
                                        text: "No native frame available"
                                        draw_text.text_style.font_size: 23
                                    }
                                    Label {
                                        text: "MSS_Render is not connected. No fake screenshot is shown."
                                    }
                                }
                                Label { text: "Native Makepad UI shell · no processes started · no test PASS claimed" }
                            }
                        }
                    }
                }
            }
        }
    }
}

#[derive(Script, ScriptHook)]
pub struct App {
    #[live]
    ui: WidgetRef,
}

impl App {
    fn select(&mut self, cx: &mut Cx, name: &str) {
        self.ui.label(cx, ids!(selected_title)).set_text(cx, name);
        self.ui.label(cx, ids!(session_status)).set_text(cx, name);
        self.ui.label(cx, ids!(runtime_status)).set_text(cx, "State: NOT_CONNECTED");
        self.ui.label(cx, ids!(agent_status)).set_text(cx, "Agent: unassigned");
    }
}

impl MatchEvent for App {
    fn handle_actions(&mut self, cx: &mut Cx, actions: &Actions) {
        if self.ui.button(cx, ids!(first_session)).clicked(actions) {
            self.select(cx, "Document UI");
        } else if self.ui.button(cx, ids!(second_session)).clicked(actions) {
            self.select(cx, "Form Fixture");
        } else if self.ui.button(cx, ids!(third_session)).clicked(actions) {
            self.select(cx, "Virtual Canvas");
        }
    }
}

impl AppMain for App {
    fn script_mod(vm: &mut ScriptVm) -> ScriptValue {
        crate::makepad_widgets::script_mod(vm);
        self::script_mod(vm)
    }

    fn handle_event(&mut self, cx: &mut Cx, event: &Event) {
        self.match_event(cx, event);
        self.ui.handle_event(cx, event, &mut Scope::empty());
    }
}
