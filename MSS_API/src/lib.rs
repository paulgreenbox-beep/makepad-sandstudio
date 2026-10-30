//! Session-bound API request envelopes. No network, GUI or MCP transport.
#![forbid(unsafe_code)]
use mss_core::{AgentId, RegistryError, SessionHandle, SessionRegistry, Session};

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
    pub const fn mutating(self) -> bool { matches!(self, Self::Input | Self::Test) }
}

/// One exact authenticated context. The caller cannot use a bare PID.
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
}
impl From<RegistryError> for ApiError {
    fn from(value: RegistryError) -> Self { Self::Registry(value) }
}

/// Narrow authorization facade; never starts a process.
pub struct Api<'a> {
    registry: &'a SessionRegistry,
}
impl<'a> Api<'a> {
    /// Bind the already-authoritative registry for permission checks.
    pub fn new(registry: &'a SessionRegistry) -> Self { Self { registry } }

    /// Authorize a live exact session and agent.
    pub fn authorize(&self, ctx: RequestContext) -> Result<&Session, ApiError> {
        Ok(self.registry.get_owned_session(ctx.session, ctx.agent)?)
    }

    /// Dispatch is intentionally refused until a concrete Toolkit adapter exists.
    /// Authorization is always checked before reporting missing backend support.
    pub fn dispatch(&self, ctx: RequestContext, _op: Operation) -> Result<(), ApiError> {
        self.authorize(ctx)?;
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
    fn denied_foreign_then_unsupported_for_valid_owner() {
        let mut registry = SessionRegistry::new();
        let a = registry.register_agent().unwrap();
        let b = registry.register_agent().unwrap();
        let id = registry.create_session(a, "one").unwrap();
        let handle = registry.get_session(id).unwrap().handle();
        let api = Api::new(&registry);
        assert_eq!(api.dispatch(RequestContext { agent: b, session: handle }, Operation::Input),
            Err(ApiError::Registry(RegistryError::ForeignSession)));
        assert_eq!(api.dispatch(RequestContext { agent: a, session: handle }, Operation::Input),
            Err(ApiError::Unsupported));
    }
}
