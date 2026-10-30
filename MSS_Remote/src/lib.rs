//! Strict addressed Remote request gate; no transport or native input yet.
#![forbid(unsafe_code)]
use mss_api::{Api, ApiError, CancellationToken, RequestContext};

/// Nonzero session-local command identity for a future dispatch protocol.
/// Replay fencing is NOT_IMPLEMENTED while there is no dispatch backend.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub struct CommandSequence(pub u64);

/// Requested semantic target; shape validation does not prove app-side existence
/// or capability. No WidgetId mapping or approved producer is installed yet.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct WidgetTarget {
    /// Nonempty semantic address, at most 256 UTF-8 bytes without controls.
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
    /// Zero command identity. No completed-dispatch ledger exists yet.
    InvalidSequence,
    /// Backend not installed; request has not been dispatched.
    NotDispatched,
}
impl From<ApiError> for RemoteError {
    fn from(e: ApiError) -> Self {
        Self::Api(e)
    }
}

/// Side-effect-free admission gate for future Makepad Remote dispatch.
///
/// Every valid input is rejected as NotDispatched. No sequence is consumed, no
/// completion is recorded, and no request is retried. A real backend must add
/// authenticated transport, capability checks and a bounded replay/outcome ledger.
#[derive(Default)]
pub struct RemoteGate;
impl RemoteGate {
    /// New empty gate.
    pub fn new() -> Self {
        Self
    }

    /// Check owner and command shape, then refuse absent execution backend.
    pub fn submit(
        &mut self,
        api: &Api<'_>,
        ctx: RequestContext,
        seq: CommandSequence,
        command: &RemoteCommand,
    ) -> Result<(), RemoteError> {
        api.authorize(ctx)?;
        Self::validate_then_refuse(seq, command)
    }

    /// Cancel before admission without claiming cancellation of app-side work.
    /// Ownership is checked before revealing cancellation or command errors.
    pub fn submit_cancellable(
        &mut self,
        api: &Api<'_>,
        ctx: RequestContext,
        seq: CommandSequence,
        command: &RemoteCommand,
        cancellation: &CancellationToken,
    ) -> Result<(), RemoteError> {
        api.authorize_cancellable(ctx, cancellation)?;
        Self::validate_then_refuse(seq, command)
    }

    fn validate_then_refuse(
        seq: CommandSequence,
        command: &RemoteCommand,
    ) -> Result<(), RemoteError> {
        let (target, text) = match command {
            RemoteCommand::Read(w) | RemoteCommand::Focus(w) => (w, None),
            RemoteCommand::Text(w, value) => (w, Some(value)),
        };
        if target.automation_id.trim().is_empty()
            || target.automation_id.len() > 256
            || target.automation_id.chars().any(char::is_control)
            || text
                .is_some_and(|v| v.is_empty() || v.len() > 4096 || v.chars().any(char::is_control))
        {
            return Err(RemoteError::InvalidInput);
        }
        if seq.0 == 0 {
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
        let cmd = RemoteCommand::Read(WidgetTarget {
            automation_id: "input.name".into(),
        });
        assert_eq!(
            gate.submit(
                &api,
                RequestContext {
                    agent: b,
                    session: handle
                },
                CommandSequence(1),
                &cmd
            ),
            Err(RemoteError::Api(ApiError::Registry(
                RegistryError::ForeignSession
            )))
        );
    }
    #[test]
    fn valid_intent_is_not_reported_executed() {
        let mut r = SessionRegistry::new();
        let a = r.register_agent().unwrap();
        let sid = r.create_session(a, "one").unwrap();
        let ctx = RequestContext {
            agent: a,
            session: r.get_session(sid).unwrap().handle(),
        };
        let api = Api::new(&r);
        let mut gate = RemoteGate::new();
        let good = RemoteCommand::Text(
            WidgetTarget {
                automation_id: "input.name".into(),
            },
            "Hello".into(),
        );
        assert_eq!(
            gate.submit(&api, ctx, CommandSequence(1), &good),
            Err(RemoteError::NotDispatched)
        );
        let bad = RemoteCommand::Text(
            WidgetTarget {
                automation_id: "input.name".into(),
            },
            "\n".into(),
        );
        assert_eq!(
            gate.submit(&api, ctx, CommandSequence(2), &bad),
            Err(RemoteError::InvalidInput)
        );
        assert_eq!(
            gate.submit(&api, ctx, CommandSequence(0), &good),
            Err(RemoteError::InvalidSequence)
        );
    }

    #[test]
    fn every_supported_shape_refuses_without_delivery_or_completion() {
        let mut registry = SessionRegistry::new();
        let agent = registry.register_agent().unwrap();
        let id = registry.create_session(agent, "one").unwrap();
        let ctx = RequestContext {
            agent,
            session: registry.get_session(id).unwrap().handle(),
        };
        let api = Api::new(&registry);
        let mut gate = RemoteGate::new();
        let target = WidgetTarget {
            automation_id: "input.name".into(),
        };
        for command in [
            RemoteCommand::Read(target.clone()),
            RemoteCommand::Focus(target.clone()),
            RemoteCommand::Text(target, "Hello".into()),
        ] {
            // A refusal before dispatch does not manufacture a completed replay entry.
            for _ in 0..2 {
                assert_eq!(
                    gate.submit(&api, ctx, CommandSequence(1), &command),
                    Err(RemoteError::NotDispatched)
                );
            }
        }
        assert_eq!(
            registry
                .get_owned_session(ctx.session, agent)
                .unwrap()
                .title(),
            "one"
        );
    }

    #[test]
    fn utf8_byte_bounds_and_controls_are_checked_without_truncation() {
        let mut registry = SessionRegistry::new();
        let agent = registry.register_agent().unwrap();
        let id = registry.create_session(agent, "one").unwrap();
        let ctx = RequestContext {
            agent,
            session: registry.get_session(id).unwrap().handle(),
        };
        let api = Api::new(&registry);
        let mut gate = RemoteGate::new();
        for invalid in [
            "".to_owned(),
            " \t ".to_owned(),
            "a\0b".to_owned(),
            "a\nb".to_owned(),
            "я".repeat(129),
        ] {
            let command = RemoteCommand::Read(WidgetTarget {
                automation_id: invalid,
            });
            assert_eq!(
                gate.submit(&api, ctx, CommandSequence(1), &command),
                Err(RemoteError::InvalidInput)
            );
        }
        let target = WidgetTarget {
            automation_id: "я".repeat(128),
        };
        let bounded = RemoteCommand::Text(target.clone(), "я".repeat(2048));
        assert_eq!(
            gate.submit(&api, ctx, CommandSequence(u64::MAX), &bounded),
            Err(RemoteError::NotDispatched)
        );
        for invalid in [
            String::new(),
            "a\0b".to_owned(),
            "\r".to_owned(),
            "я".repeat(2049),
        ] {
            let command = RemoteCommand::Text(target.clone(), invalid);
            assert_eq!(
                gate.submit(&api, ctx, CommandSequence(1), &command),
                Err(RemoteError::InvalidInput)
            );
        }
    }

    #[test]
    fn cancellation_and_invalid_shape_never_bypass_owner_generation_or_close() {
        use mss_core::SessionGeneration;
        let mut registry = SessionRegistry::new();
        let owner = registry.register_agent().unwrap();
        let other = registry.register_agent().unwrap();
        let id = registry.create_session(owner, "one").unwrap();
        let ctx = RequestContext {
            agent: owner,
            session: registry.get_session(id).unwrap().handle(),
        };
        let cancellation = CancellationToken::new();
        let command = RemoteCommand::Read(WidgetTarget {
            automation_id: "input.name".into(),
        });
        let mut gate = RemoteGate::new();
        assert_eq!(
            gate.submit_cancellable(
                &Api::new(&registry),
                ctx,
                CommandSequence(1),
                &command,
                &cancellation
            ),
            Err(RemoteError::NotDispatched)
        );
        cancellation.cancel();
        assert_eq!(
            gate.submit_cancellable(
                &Api::new(&registry),
                ctx,
                CommandSequence(1),
                &command,
                &cancellation
            ),
            Err(RemoteError::Api(ApiError::Cancelled))
        );
        assert_eq!(
            gate.submit_cancellable(
                &Api::new(&registry),
                RequestContext {
                    agent: other,
                    ..ctx
                },
                CommandSequence(0),
                &command,
                &cancellation
            ),
            Err(RemoteError::Api(ApiError::Registry(
                RegistryError::ForeignSession
            )))
        );
        let stale = RequestContext {
            session: mss_core::SessionHandle {
                generation: SessionGeneration::new(2).unwrap(),
                ..ctx.session
            },
            ..ctx
        };
        assert_eq!(
            gate.submit_cancellable(
                &Api::new(&registry),
                stale,
                CommandSequence(1),
                &command,
                &cancellation
            ),
            Err(RemoteError::Api(ApiError::Registry(
                RegistryError::StaleGeneration
            )))
        );
        registry.close_owned_session(ctx.session, owner).unwrap();
        assert_eq!(
            gate.submit(&Api::new(&registry), ctx, CommandSequence(1), &command),
            Err(RemoteError::Api(ApiError::Registry(
                RegistryError::UnknownSession
            )))
        );
    }
}
