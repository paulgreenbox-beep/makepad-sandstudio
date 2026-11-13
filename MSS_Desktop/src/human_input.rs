//! Input in the coordinates of a displayed Makepad frame.
use crate::remote_client::InputGeometry;
use makepad_widgets::*;

#[derive(Clone, PartialEq)]
pub struct InputView {
    pub slot: usize,
    pub app_id: String,
    pub geometry: InputGeometry,
}

pub struct Press {
    pub view: InputView,
    pub point: DVec2,
    pub button: u8,
    pub modifiers: KeyModifiers,
}

pub enum Input {
    Move {
        point: DVec2,
        modifiers: KeyModifiers,
    },
    Click {
        point: DVec2,
        button: u8,
        modifiers: KeyModifiers,
    },
    Drag {
        start: DVec2,
        end: DVec2,
        button: u8,
        modifiers: KeyModifiers,
    },
    Scroll {
        point: DVec2,
        delta: DVec2,
        modifiers: KeyModifiers,
    },
    Key {
        code: &'static str,
        modifiers: KeyModifiers,
    },
    Text(String),
}

pub fn guest_point(abs: DVec2, image: Rect, clip: Rect, layout: [f64; 2]) -> Option<DVec2> {
    let relative = abs - image.pos;
    let clipped = abs - clip.pos;
    if !(0.0..image.size.x).contains(&relative.x)
        || !(0.0..image.size.y).contains(&relative.y)
        || !(0.0..clip.size.x).contains(&clipped.x)
        || !(0.0..clip.size.y).contains(&clipped.y)
        || !layout.iter().all(|size| size.is_finite() && *size > 0.0)
    {
        return None;
    }
    let x = relative.x / image.size.x * layout[0];
    let y = relative.y / image.size.y * layout[1];
    ((0.0..layout[0]).contains(&x) && (0.0..layout[1]).contains(&y)).then_some(dvec2(x, y))
}

pub fn mouse_button(button: MouseButton) -> Option<u8> {
    match button {
        MouseButton::PRIMARY => Some(0),
        MouseButton::SECONDARY => Some(1),
        MouseButton::MIDDLE => Some(2),
        _ => None,
    }
}

pub fn key_code(event: KeyEvent) -> Option<&'static str> {
    use KeyCode::*;
    let mods = event.modifiers;
    if mods.logo {
        return None;
    }
    // Printable input comes from Makepad's committed TextInput. Sending both would
    // insert twice because Remote synthesizes US-layout text for some key codes.
    let shortcut = mods.control || mods.alt;
    macro_rules! names {
        ($key:expr; $($code:ident),+ $(,)?) => {
            match $key {
                $($code => Some(stringify!($code)),)+
                _ => None,
            }
        };
    }
    let key = event.key_code;
    names!(key;
        Escape, Backspace, Tab, ReturnKey, NumpadEnter, Insert, Delete,
        Home, End, PageUp, PageDown, ArrowUp, ArrowDown, ArrowLeft, ArrowRight,
        F1, F2, F3, F4, F5, F6, F7, F8, F9, F10, F11, F12,
    )
    .or_else(|| {
        if !shortcut {
            return None;
        }
        names!(key;
            KeyA, KeyB, KeyC, KeyD, KeyE, KeyF, KeyG, KeyH, KeyI, KeyJ, KeyK, KeyL, KeyM,
            KeyN, KeyO, KeyP, KeyQ, KeyR, KeyS, KeyT, KeyU, KeyV, KeyW, KeyX, KeyY, KeyZ,
            Key0, Key1, Key2, Key3, Key4, Key5, Key6, Key7, Key8, Key9, Space,
            Backtick, Minus, Equals, LBracket, RBracket, Semicolon, Quote, Backslash, Comma,
            Period, Slash,
        )
    })
}

pub fn committed_text(event: TextInputEvent) -> Option<String> {
    (!event.was_paste
        && !event.replace_last
        && event.composition.is_none()
        && event.full_state_sync.is_none()
        && event.replace_range.is_none()
        && !event.input.is_empty()
        && !event.input.chars().any(char::is_control))
    .then_some(event.input)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn maps_painted_points_to_guest_layout_without_using_png_or_desktop_pixels() {
        let image = Rect {
            pos: dvec2(240.0, 90.0),
            size: dvec2(800.0, 500.0),
        };
        let clip = Rect {
            pos: image.pos,
            size: dvec2(760.0, 500.0),
        };
        let layout = [960.0, 600.0];
        assert_eq!(
            guest_point(dvec2(640.0, 340.0), image, clip, layout),
            Some(dvec2(480.0, 300.0))
        );
        for point in [
            dvec2(239.9, 340.0),
            dvec2(1000.0, 340.0),
            dvec2(640.0, 590.0),
        ] {
            assert_eq!(guest_point(point, image, clip, layout), None);
        }
    }

    #[test]
    fn navigation_and_shortcuts_use_keys_but_printable_input_uses_text() {
        let key = |key_code, modifiers| KeyEvent {
            key_code,
            modifiers,
            ..Default::default()
        };
        let ctrl = KeyModifiers {
            control: true,
            ..Default::default()
        };
        assert_eq!(key_code(key(KeyCode::KeyA, ctrl)), Some("KeyA"));
        assert_eq!(key_code(key(KeyCode::KeyA, KeyModifiers::default())), None);
        assert_eq!(
            key_code(key(KeyCode::Backspace, KeyModifiers::default())),
            Some("Backspace")
        );
        let text = TextInputEvent {
            input: "Привет ✓".into(),
            ..Default::default()
        };
        assert_eq!(committed_text(text.clone()).as_deref(), Some("Привет ✓"));
        assert_eq!(
            committed_text(TextInputEvent {
                was_paste: true,
                ..text
            }),
            None
        );
    }
}
