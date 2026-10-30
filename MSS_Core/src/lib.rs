//! In-memory owner-scoped session registry for MSS.
//!
//! This crate does not launch processes, forward input, or claim GUI isolation.
//! A session ID is never a Windows PID or widget handle.

#![forbid(unsafe_code)]

use std::collections::{BTreeMap, BTreeSet};
use std::error::Error;
use std::fmt;
use std::num::NonZeroU64;

/// Stable, nonzero identity allocated by one registry. Never reused in its lifetime.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct SessionId(NonZeroU64);

impl SessionId {
    /// Nonzero ID value; not an OS process identifier.
    pub const fn get(self) -> u64 { self.0.get() }
}

/// Agent identity allocated by the same registry.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct AgentId(NonZeroU64);

impl AgentId {
    /// Nonzero ID value; not an external model/provider ID.
    pub const fn get(self) -> u64 { self.0.get() }
}

/// Incarnation version for a session; reserved for future process rebinding.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct SessionGeneration(NonZeroU64);

impl SessionGeneration {
    /// Nonzero generation.
    pub const fn get(self) -> u64 { self.0.get() }
}

/// Honest logical state. No state here implies an OS process exists.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SessionState {
    /// No application runtime attached.
    Created,
    /// Closed and unavailable for further mutation.
    Closed,
}

/// An immutable description of the currently tracked logical session.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Session {
    id: SessionId,
    generation: SessionGeneration,
    agent: AgentId,
    title: String,
    state: SessionState,
}

impl Session {
    /// The logical identity of this session.
    pub fn id(&self) -> SessionId { self.id }
    /// The current identity generation.
    pub fn generation(&self) -> SessionGeneration { self.generation }
    /// Its exact owner agent.
    pub fn agent(&self) -> AgentId { self.agent }
    /// User-visible title.
    pub fn title(&self) -> &str { &self.title }
    /// Logical state, not runtime evidence.
    pub fn state(&self) -> SessionState { self.state }
}

/// Explicit errors rather than silent fallback or inferred ownership.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RegistryError {
    /// ID allocator reached its bounded range.
    IdExhausted,
    /// Agent has not been registered in this registry.
    UnknownAgent,
    /// ID does not belong to a live session.
    UnknownSession,
    /// A mutation targeted another agent's session.
    ForeignSession,
    /// Selected session must be live.
    ClosedSession,
    /// Session title is empty or oversized.
    InvalidTitle,
}

impl fmt::Display for RegistryError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(match self {
            Self::IdExhausted => "registry identity space exhausted",
            Self::UnknownAgent => "unknown agent",
            Self::UnknownSession => "unknown session",
            Self::ForeignSession => "foreign session owner",
            Self::ClosedSession => "session is closed",
            Self::InvalidTitle => "invalid session title",
        })
    }
}
impl Error for RegistryError {}

/// In-memory registry. No persistence or external process ownership is implied.
///
/// IDs are monotonic; removal never makes an ID reusable. The registry must be
/// shared by all callers that need one namespace.
#[derive(Debug)]
pub struct SessionRegistry {
    next_session: Option<NonZeroU64>,
    next_agent: Option<NonZeroU64>,
    agents: BTreeSet<AgentId>,
    sessions: BTreeMap<SessionId, Session>,
    selected: Option<SessionId>,
}

impl Default for SessionRegistry {
    fn default() -> Self { Self::new() }
}

impl SessionRegistry {
    /// Creates an empty registry.
    pub fn new() -> Self {
        Self {
            next_session: NonZeroU64::new(1),
            next_agent: NonZeroU64::new(1),
            agents: BTreeSet::new(),
            sessions: BTreeMap::new(),
            selected: None,
        }
    }

    /// Registers an agent-scoped identity, without starting an AI provider.
    pub fn register_agent(&mut self) -> Result<AgentId, RegistryError> {
        let id = Self::allocate(&mut self.next_agent).map(AgentId)?;
        self.agents.insert(id);
        Ok(id)
    }

    /// Creates an in-memory session owned by an existing agent.
    pub fn create_session(&mut self, agent: AgentId, title: impl Into<String>) -> Result<SessionId, RegistryError> {
        if !self.agents.contains(&agent) { return Err(RegistryError::UnknownAgent); }
        let title = title.into();
        if title.trim().is_empty() || title.len() > 256 {
            return Err(RegistryError::InvalidTitle);
        }
        let id = Self::allocate(&mut self.next_session).map(SessionId)?;
        let generation = SessionGeneration(NonZeroU64::new(1).expect("one is nonzero"));
        let old = self.sessions.insert(id, Session {
            id, generation, agent, title, state: SessionState::Created,
        });
        debug_assert!(old.is_none());
        Ok(id)
    }

    /// Gets a session by exact logical ID; never returns a different active session.
    pub fn get_session(&self, id: SessionId) -> Result<&Session, RegistryError> {
        self.sessions.get(&id).ok_or(RegistryError::UnknownSession)
    }

    /// Iterates live sessions in stable ID order.
    pub fn list_sessions(&self) -> impl ExactSizeIterator<Item = &Session> {
        self.sessions.values()
    }

    /// Current selected session, if any.
    pub fn selected_session(&self) -> Option<SessionId> { self.selected }

    /// Selects an exact live session for viewing; does not transfer its ownership.
    pub fn set_selected_session(&mut self, id: SessionId) -> Result<(), RegistryError> {
        if self.get_session(id)?.state == SessionState::Closed {
            return Err(RegistryError::ClosedSession);
        }
        self.selected = Some(id);
        Ok(())
    }

    /// Closes only a session owned by the specified agent, then removes it.
    /// This is logical removal, not a process termination or cleanup proof.
    pub fn close_session(&mut self, id: SessionId, agent: AgentId) -> Result<Session, RegistryError> {
        let existing = self.get_session(id)?;
        if existing.agent != agent { return Err(RegistryError::ForeignSession); }
        let mut removed = self.sessions.remove(&id).ok_or(RegistryError::UnknownSession)?;
        removed.state = SessionState::Closed;
        if self.selected == Some(id) { self.selected = None; }
        Ok(removed)
    }

    fn allocate(next: &mut Option<NonZeroU64>) -> Result<NonZeroU64, RegistryError> {
        let id = next.ok_or(RegistryError::IdExhausted)?;
        *next = id.get().checked_add(1).and_then(NonZeroU64::new);
        Ok(id)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn independent_sessions_and_unique_ids() {
        let mut r = SessionRegistry::new();
        let a = r.register_agent().unwrap();
        let b = r.register_agent().unwrap();
        assert_ne!(a, b);
        let x = r.create_session(a, "Editor").unwrap();
        let y = r.create_session(b, "Canvas").unwrap();
        assert_ne!(x, y);
        assert_eq!(r.list_sessions().count(), 2);
        assert_eq!(r.get_session(x).unwrap().title(), "Editor");
        assert_eq!(r.get_session(y).unwrap().agent(), b);
        assert_eq!(r.get_session(x).unwrap().state(), SessionState::Created);
    }

    #[test]
    fn selection_and_close_do_not_touch_neighbor() {
        let mut r = SessionRegistry::new();
        let a = r.register_agent().unwrap();
        let x = r.create_session(a, "X").unwrap();
        let y = r.create_session(a, "Y").unwrap();
        r.set_selected_session(x).unwrap();
        assert_eq!(r.selected_session(), Some(x));
        let removed = r.close_session(x, a).unwrap();
        assert_eq!(removed.state(), SessionState::Closed);
        assert_eq!(r.selected_session(), None);
        assert_eq!(r.get_session(y).unwrap().title(), "Y");
        assert_eq!(r.list_sessions().count(), 1);
        assert_eq!(r.get_session(x), Err(RegistryError::UnknownSession));
    }

    #[test]
    fn foreign_agent_cannot_close_neighbor() {
        let mut r = SessionRegistry::new();
        let a = r.register_agent().unwrap();
        let b = r.register_agent().unwrap();
        let x = r.create_session(a, "Private").unwrap();
        assert_eq!(r.close_session(x, b), Err(RegistryError::ForeignSession));
        assert_eq!(r.get_session(x).unwrap().agent(), a);
    }

    #[test]
    fn stale_ids_never_reused() {
        let mut r = SessionRegistry::new();
        let a = r.register_agent().unwrap();
        let old = r.create_session(a, "Old").unwrap();
        r.close_session(old, a).unwrap();
        let fresh = r.create_session(a, "Fresh").unwrap();
        assert_ne!(old, fresh);
        assert!(fresh.get() > old.get());
        assert_eq!(r.set_selected_session(old), Err(RegistryError::UnknownSession));
        assert_eq!(r.close_session(old, a), Err(RegistryError::UnknownSession));
    }

    #[test]
    fn rejects_bad_input_without_allocating_session_id() {
        let mut r = SessionRegistry::new();
        let a = r.register_agent().unwrap();
        assert_eq!(r.create_session(a, "  "), Err(RegistryError::InvalidTitle));
        assert_eq!(r.create_session(a, "x".repeat(257)), Err(RegistryError::InvalidTitle));
        let x = r.create_session(a, "Valid").unwrap();
        assert_eq!(x.get(), 1);
    }

    #[test]
    fn foreign_registry_agent_must_not_be_assumed_globally_unique() {
        // Numeric IDs are registry-local: same raw value in another registry
        // is not global identity. Callers must never mix registries.
        let mut a = SessionRegistry::new();
        let mut b = SessionRegistry::new();
        assert_eq!(a.register_agent().unwrap().get(), b.register_agent().unwrap().get());
    }
}
