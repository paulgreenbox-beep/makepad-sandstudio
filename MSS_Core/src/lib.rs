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
    pub const fn get(self) -> u64 {
        self.0.get()
    }
}

/// Agent identity allocated by the same registry.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct AgentId(NonZeroU64);

impl AgentId {
    /// Nonzero ID value; not an external model/provider ID.
    pub const fn get(self) -> u64 {
        self.0.get()
    }
}

/// Incarnation version for a session; reserved for future process rebinding.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct SessionGeneration(NonZeroU64);

impl SessionGeneration {
    /// Nonzero generation.
    pub const fn get(self) -> u64 {
        self.0.get()
    }
}

/// Honest logical state. No state here implies an OS process exists.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SessionState {
    /// No application runtime attached.
    Created,
    /// Closed and unavailable for further mutation.
    Closed,
}

/// Exact session identity including incarnation.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct SessionHandle {
    /// Owner-scoped logical ID.
    pub id: SessionId,
    /// Identity generation.
    pub generation: SessionGeneration,
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
    pub fn id(&self) -> SessionId {
        self.id
    }
    /// An exact handle to validate against stale callers.
    pub fn handle(&self) -> SessionHandle {
        SessionHandle {
            id: self.id,
            generation: self.generation,
        }
    }
    /// The current identity generation.
    pub fn generation(&self) -> SessionGeneration {
        self.generation
    }
    /// Its exact owner agent.
    pub fn agent(&self) -> AgentId {
        self.agent
    }
    /// User-visible title.
    pub fn title(&self) -> &str {
        &self.title
    }
    /// Logical state, not runtime evidence.
    pub fn state(&self) -> SessionState {
        self.state
    }
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
    /// Session generation is no longer current.
    StaleGeneration,
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
            Self::StaleGeneration => "stale session generation",
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
    fn default() -> Self {
        Self::new()
    }
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
    pub fn create_session(
        &mut self,
        agent: AgentId,
        title: impl Into<String>,
    ) -> Result<SessionId, RegistryError> {
        if !self.agents.contains(&agent) {
            return Err(RegistryError::UnknownAgent);
        }
        let title = title.into();
        if title.trim().is_empty() || title.len() > 256 {
            return Err(RegistryError::InvalidTitle);
        }
        let id = Self::allocate(&mut self.next_session).map(SessionId)?;
        let generation = SessionGeneration(NonZeroU64::new(1).expect("one is nonzero"));
        let old = self.sessions.insert(
            id,
            Session {
                id,
                generation,
                agent,
                title,
                state: SessionState::Created,
            },
        );
        debug_assert!(old.is_none());
        Ok(id)
    }

    /// Gets a session by exact logical ID; never returns a different active session.
    pub fn get_session(&self, id: SessionId) -> Result<&Session, RegistryError> {
        self.sessions.get(&id).ok_or(RegistryError::UnknownSession)
    }

    /// Checks the exact ID + generation before returning the session.
    pub fn get_by_handle(&self, handle: SessionHandle) -> Result<&Session, RegistryError> {
        let session = self.get_session(handle.id)?;
        if session.generation != handle.generation {
            return Err(RegistryError::StaleGeneration);
        }
        Ok(session)
    }

    /// Checks the caller agent before exposing session details.
    pub fn get_owned_session(
        &self,
        handle: SessionHandle,
        agent: AgentId,
    ) -> Result<&Session, RegistryError> {
        let session = self.get_by_handle(handle)?;
        if session.agent != agent {
            return Err(RegistryError::ForeignSession);
        }
        Ok(session)
    }

    /// Iterates live sessions in stable ID order.
    pub fn list_sessions(&self) -> impl ExactSizeIterator<Item = &Session> {
        self.sessions.values()
    }

    /// Current selected session, if any.
    pub fn selected_session(&self) -> Option<SessionId> {
        self.selected
    }

    /// Selects an exact live session for viewing; does not transfer its ownership.
    pub fn set_selected_session(&mut self, id: SessionId) -> Result<(), RegistryError> {
        if self.get_session(id)?.state == SessionState::Closed {
            return Err(RegistryError::ClosedSession);
        }
        self.selected = Some(id);
        Ok(())
    }

    /// Selects only a session belonging to the requesting agent.
    pub fn select_owned_session(
        &mut self,
        handle: SessionHandle,
        agent: AgentId,
    ) -> Result<(), RegistryError> {
        self.get_owned_session(handle, agent)?;
        self.selected = Some(handle.id);
        Ok(())
    }

    /// Closes only a session owned by the specified agent, then removes it.
    /// This is logical removal, not a process termination or cleanup proof.
    pub fn close_session(
        &mut self,
        id: SessionId,
        agent: AgentId,
    ) -> Result<Session, RegistryError> {
        let existing = self.get_session(id)?;
        if existing.agent != agent {
            return Err(RegistryError::ForeignSession);
        }
        let mut removed = self
            .sessions
            .remove(&id)
            .ok_or(RegistryError::UnknownSession)?;
        removed.state = SessionState::Closed;
        if self.selected == Some(id) {
            self.selected = None;
        }
        Ok(removed)
    }

    /// Closes via an exact generation-aware owned handle.
    pub fn close_owned_session(
        &mut self,
        handle: SessionHandle,
        agent: AgentId,
    ) -> Result<Session, RegistryError> {
        self.get_owned_session(handle, agent)?;
        self.close_session(handle.id, agent)
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
        assert_eq!(
            r.set_selected_session(old),
            Err(RegistryError::UnknownSession)
        );
        assert_eq!(r.close_session(old, a), Err(RegistryError::UnknownSession));
    }

    #[test]
    fn rejects_bad_input_without_allocating_session_id() {
        let mut r = SessionRegistry::new();
        let a = r.register_agent().unwrap();
        assert_eq!(r.create_session(a, "  "), Err(RegistryError::InvalidTitle));
        assert_eq!(
            r.create_session(a, "x".repeat(257)),
            Err(RegistryError::InvalidTitle)
        );
        let x = r.create_session(a, "Valid").unwrap();
        assert_eq!(x.get(), 1);
    }

    #[test]
    fn exact_handle_refuses_stale_generation_and_foreign_agent() {
        let mut r = SessionRegistry::new();
        let agent = r.register_agent().unwrap();
        let foreign = r.register_agent().unwrap();
        let id = r.create_session(agent, "One").unwrap();
        let handle = r.get_session(id).unwrap().handle();
        assert_eq!(
            r.get_owned_session(handle, foreign),
            Err(RegistryError::ForeignSession)
        );
        let forged = SessionHandle {
            id,
            generation: SessionGeneration(NonZeroU64::new(2).unwrap()),
        };
        assert_eq!(r.get_by_handle(forged), Err(RegistryError::StaleGeneration));
        assert_eq!(
            r.select_owned_session(forged, agent),
            Err(RegistryError::StaleGeneration)
        );
        assert_eq!(
            r.close_owned_session(forged, agent),
            Err(RegistryError::StaleGeneration)
        );
        assert_eq!(
            r.close_owned_session(handle, agent).unwrap().state(),
            SessionState::Closed
        );
    }

    #[test]
    fn foreign_registry_agent_must_not_be_assumed_globally_unique() {
        // Numeric IDs are registry-local: same raw value in another registry
        // is not global identity. Callers must never mix registries.
        let mut a = SessionRegistry::new();
        let mut b = SessionRegistry::new();
        assert_eq!(
            a.register_agent().unwrap().get(),
            b.register_agent().unwrap().get()
        );
    }

    #[test]
    fn agent_allocator_exhaustion_preserves_state_and_never_wraps() {
        let mut r = SessionRegistry::new();
        let existing_agent = r.register_agent().unwrap();
        let existing = r.create_session(existing_agent, "Existing").unwrap();
        let existing_handle = r.get_session(existing).unwrap().handle();
        r.select_owned_session(existing_handle, existing_agent)
            .unwrap();

        // Arrange the unreachable-in-practice boundary, then allocate only
        // through the public API rather than iterating through every u64.
        r.next_agent = NonZeroU64::new(u64::MAX);
        let last_agent = r.register_agent().unwrap();
        assert_eq!(last_agent.get(), u64::MAX);
        assert_ne!(last_agent, existing_agent);
        let before = r.list_sessions().cloned().collect::<Vec<_>>();
        assert_eq!(r.register_agent(), Err(RegistryError::IdExhausted));
        assert_eq!(r.register_agent(), Err(RegistryError::IdExhausted));
        assert_eq!(r.list_sessions().cloned().collect::<Vec<_>>(), before);
        assert_eq!(r.selected_session(), Some(existing));
        assert_eq!(
            r.get_owned_session(existing_handle, existing_agent)
                .unwrap()
                .title(),
            "Existing"
        );

        let owned_by_last = r.create_session(last_agent, "Last agent").unwrap();
        assert_eq!(r.get_session(owned_by_last).unwrap().agent(), last_agent);
        let owned_by_existing = r
            .create_session(existing_agent, "Still registered")
            .unwrap();
        assert_eq!(
            r.get_session(owned_by_existing).unwrap().agent(),
            existing_agent
        );
        assert_eq!(r.selected_session(), Some(existing));
    }

    #[test]
    fn session_allocator_exhaustion_preserves_state_and_never_wraps() {
        let mut r = SessionRegistry::new();
        let agent = r.register_agent().unwrap();
        let existing = r.create_session(agent, "Existing").unwrap();
        let existing_handle = r.get_session(existing).unwrap().handle();
        r.select_owned_session(existing_handle, agent).unwrap();

        r.next_session = NonZeroU64::new(u64::MAX);
        let last = r.create_session(agent, "Last").unwrap();
        assert_eq!(last.get(), u64::MAX);
        assert_ne!(last, existing);
        let last_handle = r.get_session(last).unwrap().handle();
        let before = r.list_sessions().cloned().collect::<Vec<_>>();
        assert_eq!(
            r.create_session(agent, "Overflow"),
            Err(RegistryError::IdExhausted)
        );
        assert_eq!(
            r.create_session(agent, "Still exhausted"),
            Err(RegistryError::IdExhausted)
        );
        assert_eq!(r.list_sessions().cloned().collect::<Vec<_>>(), before);
        assert_eq!(r.selected_session(), Some(existing));
        assert_eq!(
            r.get_owned_session(existing_handle, agent).unwrap().title(),
            "Existing"
        );
        assert_eq!(
            r.get_owned_session(last_handle, agent).unwrap().title(),
            "Last"
        );

        assert_eq!(
            r.close_owned_session(last_handle, agent).unwrap().state(),
            SessionState::Closed
        );
        assert_eq!(
            r.create_session(agent, "Do not recycle"),
            Err(RegistryError::IdExhausted)
        );
        assert_eq!(r.list_sessions().count(), 1);
        assert_eq!(r.selected_session(), Some(existing));
        assert_eq!(
            r.get_owned_session(existing_handle, agent).unwrap().title(),
            "Existing"
        );
    }

    #[test]
    fn rejected_exact_handle_operations_preserve_sessions_and_selection() {
        let mut r = SessionRegistry::new();
        let owner = r.register_agent().unwrap();
        let neighbor_owner = r.register_agent().unwrap();
        let target = r.create_session(owner, "Target").unwrap();
        let neighbor = r
            .create_session(neighbor_owner, "Selected neighbor")
            .unwrap();
        let target_handle = r.get_session(target).unwrap().handle();
        let neighbor_handle = r.get_session(neighbor).unwrap().handle();
        let closed = r.create_session(owner, "Already closed").unwrap();
        let closed_handle = r.get_session(closed).unwrap().handle();
        r.close_owned_session(closed_handle, owner).unwrap();
        r.select_owned_session(neighbor_handle, neighbor_owner)
            .unwrap();
        assert_eq!(r.selected_session(), Some(neighbor));
        let before = r.list_sessions().cloned().collect::<Vec<_>>();
        let unchanged = |registry: &SessionRegistry| {
            assert_eq!(
                registry.list_sessions().cloned().collect::<Vec<_>>(),
                before
            );
            assert_eq!(registry.selected_session(), Some(neighbor));
        };

        assert_eq!(
            r.get_owned_session(target_handle, neighbor_owner),
            Err(RegistryError::ForeignSession)
        );
        unchanged(&r);
        assert_eq!(
            r.select_owned_session(target_handle, neighbor_owner),
            Err(RegistryError::ForeignSession)
        );
        unchanged(&r);
        assert_eq!(
            r.close_owned_session(target_handle, neighbor_owner),
            Err(RegistryError::ForeignSession)
        );
        unchanged(&r);

        let stale = SessionHandle {
            id: target,
            generation: SessionGeneration(NonZeroU64::new(2).unwrap()),
        };
        assert_eq!(r.get_by_handle(stale), Err(RegistryError::StaleGeneration));
        unchanged(&r);
        assert_eq!(
            r.get_owned_session(stale, owner),
            Err(RegistryError::StaleGeneration)
        );
        unchanged(&r);
        assert_eq!(
            r.select_owned_session(stale, owner),
            Err(RegistryError::StaleGeneration)
        );
        unchanged(&r);
        assert_eq!(
            r.close_owned_session(stale, owner),
            Err(RegistryError::StaleGeneration)
        );
        unchanged(&r);

        assert_eq!(
            r.get_by_handle(closed_handle),
            Err(RegistryError::UnknownSession)
        );
        unchanged(&r);
        assert_eq!(
            r.get_owned_session(closed_handle, owner),
            Err(RegistryError::UnknownSession)
        );
        unchanged(&r);
        assert_eq!(
            r.select_owned_session(closed_handle, owner),
            Err(RegistryError::UnknownSession)
        );
        unchanged(&r);
        assert_eq!(
            r.close_owned_session(closed_handle, owner),
            Err(RegistryError::UnknownSession)
        );
        unchanged(&r);
    }

    #[test]
    fn closing_unselected_owned_neighbor_preserves_selection() {
        let mut r = SessionRegistry::new();
        let viewer = r.register_agent().unwrap();
        let neighbor_owner = r.register_agent().unwrap();
        let selected = r.create_session(viewer, "Selected").unwrap();
        let neighbor = r.create_session(neighbor_owner, "Neighbor").unwrap();
        let selected_handle = r.get_session(selected).unwrap().handle();
        let neighbor_handle = r.get_session(neighbor).unwrap().handle();
        let selected_before = r
            .get_owned_session(selected_handle, viewer)
            .unwrap()
            .clone();
        r.select_owned_session(selected_handle, viewer).unwrap();
        assert_eq!(r.selected_session(), Some(selected));

        let closed = r
            .close_owned_session(neighbor_handle, neighbor_owner)
            .unwrap();
        assert_eq!(closed.handle(), neighbor_handle);
        assert_eq!(closed.agent(), neighbor_owner);
        assert_eq!(closed.state(), SessionState::Closed);
        assert_eq!(r.selected_session(), Some(selected));
        assert_eq!(
            r.get_owned_session(selected_handle, viewer),
            Ok(&selected_before)
        );
        assert_eq!(
            r.list_sessions().cloned().collect::<Vec<_>>(),
            vec![selected_before]
        );
        assert_eq!(
            r.get_by_handle(neighbor_handle),
            Err(RegistryError::UnknownSession)
        );
    }

    #[test]
    fn unknown_agent_does_not_create_sessions_or_consume_ids() {
        let mut r = SessionRegistry::new();
        let agent = r.register_agent().unwrap();
        let unknown = AgentId(NonZeroU64::new(2).unwrap());
        assert_eq!(
            r.create_session(unknown, "Unknown owner"),
            Err(RegistryError::UnknownAgent)
        );
        assert_eq!(r.list_sessions().count(), 0);
        assert_eq!(r.selected_session(), None);

        let first = r.create_session(agent, "First valid").unwrap();
        assert_eq!(first.get(), 1);
        let handle = r.get_session(first).unwrap().handle();
        r.select_owned_session(handle, agent).unwrap();
        let before = r.list_sessions().cloned().collect::<Vec<_>>();
        assert_eq!(
            r.create_session(unknown, "Still unknown"),
            Err(RegistryError::UnknownAgent)
        );
        assert_eq!(r.list_sessions().cloned().collect::<Vec<_>>(), before);
        assert_eq!(r.selected_session(), Some(first));
        let second = r.create_session(agent, "Second valid").unwrap();
        assert_eq!(second.get(), 2);
        assert_eq!(r.get_session(second).unwrap().agent(), agent);
        assert_eq!(r.selected_session(), Some(first));
    }
}
