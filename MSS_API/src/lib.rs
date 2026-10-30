//! Session-bound API request envelopes. No network, GUI or MCP transport.
#![forbid(unsafe_code)]
use mss_core::{AgentId, RegistryError, Session, SessionHandle, SessionRegistry};
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};

/// Shared, monotonic cancellation request checked before logical dispatch.
///
/// Clones observe the same flag. This does not cancel an in-flight operation,
/// establish process cleanup, or resolve an uncertain mutation outcome.
#[derive(Clone, Debug, Default)]
pub struct CancellationToken {
    cancelled: Arc<AtomicBool>,
}

impl CancellationToken {
    /// Creates an independent token with no cancellation requested.
    pub fn new() -> Self {
        Self::default()
    }

    /// Requests cancellation for this token and all its clones; it cannot reset.
    pub fn cancel(&self) {
        self.cancelled.store(true, Ordering::Release);
    }

    /// Whether cancellation has been requested at this observation boundary.
    pub fn is_cancelled(&self) -> bool {
        self.cancelled.load(Ordering::Acquire)
    }
}

/// Declared GUI operation class, not a claim of backend support.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Operation {
    /// Read the current semantic tree.
    Inspect,
    /// Request a new frame.
    Capture,
    /// Address a widget for user-like input.
    Input,
    /// Run an approved Toolkit script.
    Test,
}
impl Operation {
    /// Whether the operation changes app state.
    pub const fn mutating(self) -> bool {
        matches!(self, Self::Input | Self::Test)
    }
}

impl TryFrom<&str> for Operation {
    type Error = ApiError;

    /// Parse only the four local class names. This is not a Toolkit wire schema.
    fn try_from(value: &str) -> Result<Self, Self::Error> {
        match value {
            "inspect" => Ok(Self::Inspect),
            "capture" => Ok(Self::Capture),
            "input" => Ok(Self::Input),
            "test" => Ok(Self::Test),
            _ => Err(ApiError::Unsupported),
        }
    }
}

/// One exact logical context supplied by trusted in-process calling code.
/// This does not authenticate a network/MCP client and cannot use a bare PID.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct RequestContext {
    /// Exact owner agent identity.
    pub agent: AgentId,
    /// Logical session ID plus incarnation.
    pub session: SessionHandle,
}

/// Response metadata must distinguish lack of implementation from success.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ApiError {
    /// Invalid owner, session, or generation.
    Registry(RegistryError),
    /// The requested backend has no implemented executor.
    Unsupported,
    /// Cancellation was observed after authorization and before dispatch.
    Cancelled,
}
impl From<RegistryError> for ApiError {
    fn from(value: RegistryError) -> Self {
        Self::Registry(value)
    }
}

/// Narrow authorization facade; never starts a process.
pub struct Api<'a> {
    registry: &'a SessionRegistry,
}
impl<'a> Api<'a> {
    /// Bind the already-authoritative registry for permission checks.
    pub fn new(registry: &'a SessionRegistry) -> Self {
        Self { registry }
    }

    /// Authorize a live exact session and agent.
    pub fn authorize(&self, ctx: RequestContext) -> Result<&Session, ApiError> {
        Ok(self.registry.get_owned_session(ctx.session, ctx.agent)?)
    }

    /// Authorizes the exact caller first, then observes pre-dispatch cancellation.
    /// A cancellation request never masks an invalid or foreign session.
    pub fn authorize_cancellable(
        &self,
        ctx: RequestContext,
        cancellation: &CancellationToken,
    ) -> Result<&Session, ApiError> {
        let session = self.authorize(ctx)?;
        if cancellation.is_cancelled() {
            return Err(ApiError::Cancelled);
        }
        Ok(session)
    }

    /// Dispatch is intentionally refused until a concrete Toolkit adapter exists.
    /// Authorization is always checked before reporting missing backend support.
    pub fn dispatch(&self, ctx: RequestContext, _op: Operation) -> Result<(), ApiError> {
        self.authorize(ctx)?;
        Err(ApiError::Unsupported)
    }

    /// Fail closed on unknown class names, authenticating the logical owner
    /// before parsing. This adds no network endpoint or implicit default class.
    pub fn dispatch_named(&self, ctx: RequestContext, name: &str) -> Result<(), ApiError> {
        self.authorize(ctx)?;
        self.dispatch(ctx, Operation::try_from(name)?)
    }

    /// Checks authorization and cancellation before refusing the absent backend.
    /// All operation variants remain unsupported; no command is dispatched.
    pub fn dispatch_cancellable(
        &self,
        ctx: RequestContext,
        _op: Operation,
        cancellation: &CancellationToken,
    ) -> Result<(), ApiError> {
        self.authorize_cancellable(ctx, cancellation)?;
        Err(ApiError::Unsupported)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn operations_classify_mutations() {
        assert!(!Operation::Inspect.mutating());
        assert!(!Operation::Capture.mutating());
        assert!(Operation::Input.mutating());
        assert!(Operation::Test.mutating());
    }

    #[test]
    fn unknown_operation_has_no_default_and_does_not_bypass_authorization() {
        let mut registry = SessionRegistry::new();
        let owner = registry.register_agent().unwrap();
        let other = registry.register_agent().unwrap();
        let id = registry.create_session(owner, "one").unwrap();
        let ctx = RequestContext {
            agent: owner,
            session: registry.get_session(id).unwrap().handle(),
        };
        let api = Api::new(&registry);
        for name in [
            "inspect",
            "capture",
            "input",
            "test",
            "",
            "unknown",
            "input\0",
            "INPUT",
            "session.close",
            "set_value",
        ] {
            assert_eq!(api.dispatch_named(ctx, name), Err(ApiError::Unsupported));
            assert_eq!(
                api.dispatch_named(
                    RequestContext {
                        agent: other,
                        ..ctx
                    },
                    name
                ),
                Err(ApiError::Registry(RegistryError::ForeignSession))
            );
        }
        for name in [
            "",
            "unknown",
            "input\0",
            "INPUT",
            "session.close",
            "set_value",
        ] {
            assert_eq!(Operation::try_from(name), Err(ApiError::Unsupported));
        }
        assert_eq!(Operation::try_from("inspect"), Ok(Operation::Inspect));
        assert_eq!(Operation::try_from("capture"), Ok(Operation::Capture));
        assert_eq!(Operation::try_from("input"), Ok(Operation::Input));
        assert_eq!(Operation::try_from("test"), Ok(Operation::Test));
        assert_eq!(registry.list_sessions().len(), 1);
    }
    #[test]
    fn denied_foreign_then_unsupported_for_valid_owner() {
        let mut registry = SessionRegistry::new();
        let a = registry.register_agent().unwrap();
        let b = registry.register_agent().unwrap();
        let id = registry.create_session(a, "one").unwrap();
        let handle = registry.get_session(id).unwrap().handle();
        let api = Api::new(&registry);
        assert_eq!(
            api.dispatch(
                RequestContext {
                    agent: b,
                    session: handle
                },
                Operation::Input
            ),
            Err(ApiError::Registry(RegistryError::ForeignSession))
        );
        assert_eq!(
            api.dispatch(
                RequestContext {
                    agent: a,
                    session: handle
                },
                Operation::Input
            ),
            Err(ApiError::Unsupported)
        );
    }

    fn operations() -> [Operation; 4] {
        [
            Operation::Inspect,
            Operation::Capture,
            Operation::Input,
            Operation::Test,
        ]
    }

    #[test]
    fn cancellation_is_monotonic_shared_by_clones_and_independent_of_other_tokens() {
        let token = CancellationToken::new();
        let shared = token.clone();
        let independent = CancellationToken::default();
        assert!(!token.is_cancelled());
        assert!(!shared.is_cancelled());
        shared.cancel();
        assert!(token.is_cancelled());
        assert!(shared.is_cancelled());
        token.cancel();
        assert!(shared.is_cancelled());
        assert!(!independent.is_cancelled());
    }

    #[test]
    fn every_operation_authenticates_before_reporting_unsupported_or_cancelled() {
        let mut registry = SessionRegistry::new();
        let owner = registry.register_agent().unwrap();
        let foreign = registry.register_agent().unwrap();
        let id = registry.create_session(owner, "Target").unwrap();
        let handle = registry.get_session(id).unwrap().handle();
        registry.select_owned_session(handle, owner).unwrap();
        let before = registry.list_sessions().cloned().collect::<Vec<_>>();
        let valid = RequestContext {
            agent: owner,
            session: handle,
        };
        let denied = RequestContext {
            agent: foreign,
            session: handle,
        };
        let token = CancellationToken::new();
        let cancelled = CancellationToken::new();
        cancelled.cancel();
        let api = Api::new(&registry);

        assert_eq!(
            api.authorize_cancellable(valid, &token).unwrap().handle(),
            handle
        );
        assert_eq!(
            api.authorize_cancellable(valid, &cancelled),
            Err(ApiError::Cancelled)
        );
        for operation in operations() {
            assert_eq!(api.dispatch(valid, operation), Err(ApiError::Unsupported));
            assert_eq!(
                api.dispatch_cancellable(valid, operation, &token),
                Err(ApiError::Unsupported)
            );
            assert_eq!(
                api.dispatch_cancellable(valid, operation, &cancelled),
                Err(ApiError::Cancelled)
            );
            assert_eq!(
                api.dispatch(denied, operation),
                Err(ApiError::Registry(RegistryError::ForeignSession))
            );
            assert_eq!(
                api.dispatch_cancellable(denied, operation, &cancelled),
                Err(ApiError::Registry(RegistryError::ForeignSession))
            );
        }
        assert_eq!(
            registry.list_sessions().cloned().collect::<Vec<_>>(),
            before
        );
        assert_eq!(registry.selected_session(), Some(id));
    }

    #[test]
    fn stale_closed_and_foreign_registry_requests_are_refused_before_cancellation() {
        use mss_core::SessionGeneration;

        let mut registry = SessionRegistry::new();
        let owner = registry.register_agent().unwrap();
        let id = registry.create_session(owner, "Live").unwrap();
        let handle = registry.get_session(id).unwrap().handle();
        let closed = registry.create_session(owner, "Closed").unwrap();
        let closed_handle = registry.get_session(closed).unwrap().handle();
        registry.close_owned_session(closed_handle, owner).unwrap();
        let stale = SessionHandle {
            id,
            generation: SessionGeneration::new(2).unwrap(),
        };
        let mut other = SessionRegistry::new();
        let other_owner = other.register_agent().unwrap();
        let other_id = other.create_session(other_owner, "Other registry").unwrap();
        let other_handle = other.get_session(other_id).unwrap().handle();
        assert_eq!(owner.get(), other_owner.get());
        assert_eq!(id.get(), other_id.get());
        assert_ne!(owner, other_owner);
        assert_ne!(id, other_id);
        let cancelled = CancellationToken::new();
        cancelled.cancel();
        let api = Api::new(&registry);
        for (context, error) in [
            (
                RequestContext {
                    agent: owner,
                    session: stale,
                },
                RegistryError::StaleGeneration,
            ),
            (
                RequestContext {
                    agent: owner,
                    session: closed_handle,
                },
                RegistryError::UnknownSession,
            ),
            (
                RequestContext {
                    agent: other_owner,
                    session: other_handle,
                },
                RegistryError::UnknownSession,
            ),
        ] {
            assert_eq!(
                api.authorize_cancellable(context, &cancelled),
                Err(ApiError::Registry(error))
            );
            for operation in operations() {
                assert_eq!(
                    api.dispatch(context, operation),
                    Err(ApiError::Registry(error))
                );
                assert_eq!(
                    api.dispatch_cancellable(context, operation, &cancelled),
                    Err(ApiError::Registry(error))
                );
            }
        }
        assert_eq!(
            registry.get_owned_session(handle, owner).unwrap().title(),
            "Live"
        );
        assert_eq!(registry.list_sessions().count(), 1);
        assert_eq!(
            other
                .get_owned_session(other_handle, other_owner)
                .unwrap()
                .title(),
            "Other registry"
        );
    }
}
