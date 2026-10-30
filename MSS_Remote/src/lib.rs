//! Strict addressed Remote request gate; no transport or native input yet.
#![forbid(unsafe_code)]
use mss_api::{Api, ApiError, RequestContext};
use std::collections::BTreeMap;

/// Monotonic session-local sequence used to prevent duplicate dispatch.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub struct CommandSequence(pub u64);

/// Exact target from an approved application integration.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct WidgetTarget {
    /// Nonempty, explicitly approved semantic address.
    pub automation_id: String,
}

/// Validated command intent, not a delivered user event.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum RemoteCommand {
    /// Read approved target state.
    Read(WidgetTarget),
    /// Request focus; requires a real backend.
    Focus(WidgetTarget),
    /// Request bounded UTF-8 input; requires a real backend.
    Text(WidgetTarget, String),
}

/// Error returned before any native delivery.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum RemoteError {
    /// Session or agent was not authorized.
    Api(ApiError),
    /// Invalid widget address or text.
    InvalidInput,
    /// Replayed or out-of-order command sequence.
    InvalidSequence,
    /// Backend not installed; request has not been dispatched.
    NotDispatched,
}
impl From<ApiError> for RemoteError { fn from(e: ApiError) -> Self { Self::Api(e) } }

/// Side-effect-free admission gate for future Makepad Remote dispatch.
///
/// A sequence is reserved only when a backend has been implemented; until then,
/// every valid input is rejected as NotDispatched. Never infer PASS from admission.
#[derive(Default)]
pub struct RemoteGate {
    last_completed: BTreeMap<u64, CommandSequence>,
}
impl RemoteGate {
    /// New empty gate.
    pub fn new() -> Self { Self::default() }

    /// Check owner and command shape, then refuse absent execution backend.
    pub fn submit(&mut self, api: &Api<'_>, ctx: RequestContext, seq: CommandSequence, command: &RemoteCommand)
        -> Result<(), RemoteError> {
        api.authorize(ctx)?;
        let (target, text) = match command {
            RemoteCommand::Read(w) | RemoteCommand::Focus(w) => (w, None),
            RemoteCommand::Text(w, value) => (w, Some(value)),
        };
        if target.automation_id.trim().is_empty() || target.automation_id.len() > 256
            || text.is_some_and(|v| v.is_empty() || v.len() > 4096 || v.chars().any(char::is_control)) {
            return Err(RemoteError::InvalidInput);
        }
        if seq.0 == 0 || self.last_completed.get(&ctx.session.id.get()).is_some_and(|s| seq <= *s) {
            return Err(RemoteError::InvalidSequence);
        }
        Err(RemoteError::NotDispatched)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use mss_core::{RegistryError, SessionRegistry};
    #[test]
    fn foreign_agent_cannot_submit() {
        let mut r = SessionRegistry::new();
        let a = r.register_agent().unwrap();
        let b = r.register_agent().unwrap();
        let sid = r.create_session(a, "one").unwrap();
        let handle = r.get_session(sid).unwrap().handle();
        let api = Api::new(&r);
        let mut gate = RemoteGate::new();
        let cmd = RemoteCommand::Read(WidgetTarget { automation_id: "input.name".into() });
        assert_eq!(gate.submit(&api, RequestContext { agent:b, session:handle }, CommandSequence(1), &cmd),
            Err(RemoteError::Api(ApiError::Registry(RegistryError::ForeignSession))));
    }
    #[test]
    fn valid_intent_is_not_reported_executed() {
        let mut r = SessionRegistry::new();
        let a = r.register_agent().unwrap();
        let sid = r.create_session(a, "one").unwrap();
        let ctx = RequestContext { agent:a, session:r.get_session(sid).unwrap().handle() };
        let api = Api::new(&r);
        let mut gate = RemoteGate::new();
        let good = RemoteCommand::Text(WidgetTarget { automation_id: "input.name".into() }, "Hello".into());
        assert_eq!(gate.submit(&api, ctx, CommandSequence(1), &good), Err(RemoteError::NotDispatched));
        let bad = RemoteCommand::Text(WidgetTarget { automation_id: "input.name".into() }, "\n".into());
        assert_eq!(gate.submit(&api, ctx, CommandSequence(2), &bad), Err(RemoteError::InvalidInput));
        assert_eq!(gate.submit(&api, ctx, CommandSequence(0), &good), Err(RemoteError::InvalidSequence));
    }
}
