//! In-memory owner-scoped session registry for MSS.
//!
//! This crate does not launch processes, forward input, or claim GUI isolation.
//! A session ID is never a Windows PID or widget handle.

#![forbid(unsafe_code)]

use std::collections::{BTreeMap, BTreeSet};
use std::error::Error;
use std::fmt;
use std::num::NonZeroU64;
use std::sync::atomic::{AtomicU64, Ordering};

static NEXT_REGISTRY_ID: AtomicU64 = AtomicU64::new(1);

/// A nonzero namespace unique to one registry in this process.
///
/// This is not a persistent or authenticated external identity. Process restart
/// starts a new identity domain; no OS process or security authority is implied.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct RegistryId(NonZeroU64);

impl RegistryId {
    /// The process-local registry namespace value.
    pub const fn get(self) -> u64 {
        self.0.get()
    }

    fn allocate_from(next: &AtomicU64) -> Result<Self, RegistryError> {
        let id = next
            .fetch_update(Ordering::Relaxed, Ordering::Relaxed, |current| {
                NonZeroU64::new(current).map(|id| id.get().checked_add(1).unwrap_or(0))
            })
            .map_err(|_| RegistryError::IdExhausted)?;
        NonZeroU64::new(id)
            .map(Self)
            .ok_or(RegistryError::IdExhausted)
    }
}

/// A registry namespace and a nonzero local session number, never reused.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct SessionId {
    registry: RegistryId,
    local: NonZeroU64,
}

impl SessionId {
    /// Nonzero registry-local number; not a complete ID or OS process identifier.
    pub const fn get(self) -> u64 {
        self.local.get()
    }

    /// The namespace that must accompany the local number for comparison.
    pub const fn registry_id(self) -> RegistryId {
        self.registry
    }
}

/// Agent identity allocated by the same registry.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct AgentId {
    registry: RegistryId,
    local: NonZeroU64,
}

impl AgentId {
    /// Nonzero registry-local number; not a complete ID or model/provider ID.
    pub const fn get(self) -> u64 {
        self.local.get()
    }

    /// The registry namespace to which this agent belongs.
    pub const fn registry_id(self) -> RegistryId {
        self.registry
    }
}

/// Incarnation version for a session; reserved for future process rebinding.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct SessionGeneration(NonZeroU64);

impl SessionGeneration {
    /// Constructs a nonzero generation value without granting session authority.
    pub const fn new(value: u64) -> Option<Self> {
        match NonZeroU64::new(value) {
            Some(value) => Some(Self(value)),
            None => None,
        }
    }

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
/// Local numbers are monotonic and full identities include a fresh process-local
/// registry namespace. Removal or dropping a registry never recycles an identity
/// in this process. Callers sharing a session still use the same registry.
#[derive(Debug)]
pub struct SessionRegistry {
    registry_id: RegistryId,
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
    /// Creates an empty registry with a fresh process-local namespace.
    ///
    /// # Panics
    /// Panics if the process-local namespace allocator is exhausted. Use
    /// [`Self::try_new`] to handle this bounded failure explicitly.
    pub fn new() -> Self {
        Self::try_new().expect("process-local registry namespace space exhausted")
    }

    /// Creates an empty registry, refusing namespace exhaustion without reuse.
    pub fn try_new() -> Result<Self, RegistryError> {
        Ok(Self {
            registry_id: RegistryId::allocate_from(&NEXT_REGISTRY_ID)?,
            next_session: NonZeroU64::new(1),
            next_agent: NonZeroU64::new(1),
            agents: BTreeSet::new(),
            sessions: BTreeMap::new(),
            selected: None,
        })
    }

    /// This registry's process-local namespace; not OS or caller authentication.
    pub const fn registry_id(&self) -> RegistryId {
        self.registry_id
    }

    /// Registers an agent-scoped identity, without starting an AI provider.
    pub fn register_agent(&mut self) -> Result<AgentId, RegistryError> {
        let id = AgentId {
            registry: self.registry_id,
            local: Self::allocate(&mut self.next_agent)?,
        };
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
        let id = SessionId {
            registry: self.registry_id,
            local: Self::allocate(&mut self.next_session)?,
        };
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
        // Raw numbers remain registry-local for compatibility. The full typed
        // identity also includes the registry namespace and cannot alias.
        let mut a = SessionRegistry::new();
        let mut b = SessionRegistry::new();
        assert_eq!(
            a.register_agent().unwrap().get(),
            b.register_agent().unwrap().get()
        );
        let a_id = a.register_agent().unwrap();
        let b_id = b.register_agent().unwrap();
        assert_eq!(a_id.get(), b_id.get());
        assert_ne!(a_id, b_id);
        assert_ne!(a_id.registry_id(), b_id.registry_id());
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
        let unknown = AgentId {
            registry: r.registry_id(),
            local: NonZeroU64::new(2).unwrap(),
        };
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

    #[test]
    fn foreign_registry_handles_cannot_alias_equal_local_session_numbers() {
        let mut a = SessionRegistry::new();
        let mut b = SessionRegistry::new();
        let owner_a = a.register_agent().unwrap();
        let owner_b = b.register_agent().unwrap();
        let session_a = a.create_session(owner_a, "A").unwrap();
        let session_b = b.create_session(owner_b, "B").unwrap();
        let handle_a = a.get_session(session_a).unwrap().handle();
        let handle_b = b.get_session(session_b).unwrap().handle();
        b.select_owned_session(handle_b, owner_b).unwrap();
        let before = b.list_sessions().cloned().collect::<Vec<_>>();

        assert_eq!(owner_a.get(), owner_b.get());
        assert_eq!(session_a.get(), session_b.get());
        assert_ne!(owner_a, owner_b);
        assert_ne!(session_a, session_b);
        assert_ne!(a.registry_id(), b.registry_id());
        assert_eq!(session_a.registry_id(), a.registry_id());
        assert_eq!(owner_b.registry_id(), b.registry_id());
        assert_eq!(
            b.create_session(owner_a, "Foreign registry agent"),
            Err(RegistryError::UnknownAgent)
        );
        assert_eq!(
            b.get_by_handle(handle_a),
            Err(RegistryError::UnknownSession)
        );
        assert_eq!(
            b.get_owned_session(handle_b, owner_a),
            Err(RegistryError::ForeignSession)
        );
        assert_eq!(
            b.select_owned_session(handle_a, owner_a),
            Err(RegistryError::UnknownSession)
        );
        assert_eq!(
            b.close_owned_session(handle_a, owner_a),
            Err(RegistryError::UnknownSession)
        );
        assert_eq!(b.list_sessions().cloned().collect::<Vec<_>>(), before);
        assert_eq!(b.selected_session(), Some(session_b));
        assert_eq!(b.get_owned_session(handle_b, owner_b).unwrap().title(), "B");
        assert_eq!(a.get_owned_session(handle_a, owner_a).unwrap().title(), "A");
    }

    #[test]
    fn dropped_registry_namespace_is_not_reused_in_this_process() {
        let first = SessionRegistry::try_new().unwrap().registry_id();
        let next = SessionRegistry::try_new().unwrap().registry_id();
        assert_ne!(first, next);
        assert!(next.get() > first.get());
    }

    #[test]
    fn registry_namespace_exhaustion_allocates_max_once_then_refuses() {
        // A separate allocator fixture never exhausts or resets the real global
        // process namespace used by the other tests or callers.
        let allocator = AtomicU64::new(u64::MAX);
        assert_eq!(
            RegistryId::allocate_from(&allocator).unwrap().get(),
            u64::MAX
        );
        assert_eq!(allocator.load(Ordering::Relaxed), 0);
        assert_eq!(
            RegistryId::allocate_from(&allocator),
            Err(RegistryError::IdExhausted)
        );
        assert_eq!(
            RegistryId::allocate_from(&allocator),
            Err(RegistryError::IdExhausted)
        );
        assert_eq!(allocator.load(Ordering::Relaxed), 0);
    }

    #[test]
    fn public_generation_constructor_is_checked_and_grants_no_authority() {
        assert_eq!(SessionGeneration::new(0), None);
        assert_eq!(SessionGeneration::new(1).unwrap().get(), 1);
        assert_eq!(SessionGeneration::new(u64::MAX).unwrap().get(), u64::MAX);
        let mut registry = SessionRegistry::new();
        let owner = registry.register_agent().unwrap();
        let id = registry.create_session(owner, "Current").unwrap();
        let stale = SessionHandle {
            id,
            generation: SessionGeneration::new(2).unwrap(),
        };
        assert_eq!(
            registry.get_by_handle(stale),
            Err(RegistryError::StaleGeneration)
        );
    }
}
