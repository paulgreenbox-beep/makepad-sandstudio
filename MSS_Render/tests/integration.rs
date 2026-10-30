//! Public-interface composition tests. Synthetic frames are not GPU evidence.
use mss_api::{Api, ApiError, CancellationToken, Operation, RequestContext};
use mss_core::{RegistryError, SessionGeneration, SessionHandle, SessionRegistry, SessionState};
use mss_remote::{CommandSequence, RemoteCommand, RemoteError, RemoteGate, WidgetTarget};
use mss_render::{Frame, FrameError, FrameFormat, FrameIdentity, FrameStore};

fn sessions() -> (SessionRegistry, RequestContext, RequestContext) {
    let mut registry = SessionRegistry::new();
    let first = registry.register_agent().unwrap();
    let second = registry.register_agent().unwrap();
    let one = registry.create_session(first, "first").unwrap();
    let two = registry.create_session(second, "second").unwrap();
    let a = RequestContext {
        agent: first,
        session: registry.get_session(one).unwrap().handle(),
    };
    let b = RequestContext {
        agent: second,
        session: registry.get_session(two).unwrap().handle(),
    };
    (registry, a, b)
}

fn frame(ctx: RequestContext, sequence: u64) -> Frame {
    Frame {
        identity: FrameIdentity {
            session: ctx.session,
            sequence,
        },
        width: 1,
        height: 1,
        format: FrameFormat::Png,
        bytes: include_bytes!("fixtures/rgba1x1.png.bin").to_vec(),
    }
}

fn command() -> RemoteCommand {
    RemoteCommand::Read(WidgetTarget {
        automation_id: "input.name".into(),
    })
}

#[test]
fn separate_agents_access_only_their_exact_sessions_through_api() {
    let (registry, a, b) = sessions();
    assert_ne!(a.agent, b.agent);
    assert_ne!(a.session, b.session);
    let api = Api::new(&registry);
    assert_eq!(api.authorize(a).unwrap().title(), "first");
    assert_eq!(api.authorize(b).unwrap().title(), "second");
    for foreign in [
        RequestContext {
            agent: b.agent,
            ..a
        },
        RequestContext {
            agent: a.agent,
            ..b
        },
    ] {
        assert_eq!(
            api.authorize(foreign),
            Err(ApiError::Registry(RegistryError::ForeignSession))
        );
    }
    assert_eq!(registry.list_sessions().len(), 2);
}

#[test]
fn remote_authorization_refuses_foreign_call_and_never_reports_execution() {
    let (registry, a, b) = sessions();
    let api = Api::new(&registry);
    let mut remote = RemoteGate::new();
    for ctx in [a, b] {
        assert_eq!(
            remote.submit(&api, ctx, CommandSequence(1), &command()),
            Err(RemoteError::NotDispatched)
        );
    }
    assert_eq!(
        remote.submit(
            &api,
            RequestContext {
                agent: b.agent,
                ..a
            },
            CommandSequence(1),
            &command()
        ),
        Err(RemoteError::Api(ApiError::Registry(
            RegistryError::ForeignSession
        )))
    );
    assert_eq!(registry.list_sessions().len(), 2);
}

#[test]
fn stale_generation_is_rejected_by_all_three_consumers_without_frame_changes() {
    let (registry, a, b) = sessions();
    let api = Api::new(&registry);
    let mut remote = RemoteGate::new();
    let mut store = FrameStore::new(1024);
    store.publish(&api, a, frame(a, 1)).unwrap();
    store.publish(&api, b, frame(b, 1)).unwrap();
    let stale = RequestContext {
        session: SessionHandle {
            generation: SessionGeneration::new(2).unwrap(),
            ..a.session
        },
        ..a
    };
    let error = ApiError::Registry(RegistryError::StaleGeneration);
    assert_eq!(api.dispatch(stale, Operation::Input), Err(error));
    assert_eq!(
        remote.submit(&api, stale, CommandSequence(1), &command()),
        Err(RemoteError::Api(error))
    );
    assert_eq!(
        store.publish(&api, stale, frame(stale, 2)),
        Err(FrameError::Api(error))
    );
    assert_eq!(store.latest(&api, stale), Err(FrameError::Api(error)));
    assert_eq!(store.forget(&api, stale), Err(FrameError::Api(error)));
    assert_eq!(
        store.latest(&api, a).unwrap().identity,
        frame(a, 1).identity
    );
    assert_eq!(
        store.latest(&api, b).unwrap().identity,
        frame(b, 1).identity
    );
}

#[test]
fn populated_frame_cache_enforces_owner_and_publisher_session() {
    let (registry, a, b) = sessions();
    let api = Api::new(&registry);
    let mut store = FrameStore::new(1024);
    store.publish(&api, a, frame(a, 1)).unwrap();
    store.publish(&api, b, frame(b, 7)).unwrap();
    let foreign = RequestContext {
        agent: b.agent,
        ..a
    };
    let error = FrameError::Api(ApiError::Registry(RegistryError::ForeignSession));
    assert_eq!(store.latest(&api, foreign), Err(error));
    assert_eq!(store.forget(&api, foreign), Err(error));
    assert_eq!(store.publish(&api, foreign, frame(a, 2)), Err(error));
    assert_eq!(
        store.publish(&api, b, frame(a, 2)),
        Err(FrameError::InvalidFrame)
    );
    assert_eq!(
        store.latest(&api, a).unwrap().identity,
        frame(a, 1).identity
    );
    assert_eq!(
        store.latest(&api, b).unwrap().identity,
        frame(b, 7).identity
    );
    assert_eq!(store.latest(&api, b).unwrap().identity.session, b.session);
    assert_ne!(store.latest(&api, b).unwrap().identity.session, a.session);
}

#[test]
fn close_and_receipt_cleanup_preserve_neighbor_and_refuse_closed_handle() {
    let (mut registry, a, b) = sessions();
    registry.select_owned_session(b.session, b.agent).unwrap();
    let mut store = FrameStore::new(1024);
    store.publish(&Api::new(&registry), a, frame(a, 1)).unwrap();
    store.publish(&Api::new(&registry), b, frame(b, 2)).unwrap();
    // A live public Session snapshot is not authority to perform closed cleanup.
    let live = registry
        .get_owned_session(b.session, b.agent)
        .unwrap()
        .clone();
    assert!(store.forget_closed(&live).is_err());
    let closed = registry.close_owned_session(a.session, a.agent).unwrap();
    assert_eq!(closed.state(), SessionState::Closed);
    assert!(store.forget_closed(&closed).unwrap());
    assert!(!store.forget_closed(&closed).unwrap());
    let api = Api::new(&registry);
    assert_eq!(
        api.authorize(a),
        Err(ApiError::Registry(RegistryError::UnknownSession))
    );
    assert_eq!(
        store.latest(&api, a),
        Err(FrameError::Api(ApiError::Registry(
            RegistryError::UnknownSession
        )))
    );
    assert_eq!(
        RemoteGate::new().submit(&api, a, CommandSequence(2), &command()),
        Err(RemoteError::Api(ApiError::Registry(
            RegistryError::UnknownSession
        )))
    );
    assert_eq!(api.authorize(b).unwrap(), &live);
    assert_eq!(
        store.latest(&api, b).unwrap().identity,
        frame(b, 2).identity
    );
    assert_eq!(registry.selected_session(), Some(b.session.id));
    assert_eq!(registry.list_sessions().len(), 1);
}

#[test]
fn cancellation_before_dispatch_preserves_sessions_frames_and_ownership_checks() {
    let (registry, a, b) = sessions();
    let api = Api::new(&registry);
    let mut store = FrameStore::new(1024);
    store.publish(&api, a, frame(a, 1)).unwrap();
    store.publish(&api, b, frame(b, 2)).unwrap();
    let cancellation = CancellationToken::new();
    let worker_token = cancellation.clone();
    worker_token.cancel();
    for op in [
        Operation::Inspect,
        Operation::Capture,
        Operation::Input,
        Operation::Test,
    ] {
        assert_eq!(
            api.dispatch_cancellable(a, op, &cancellation),
            Err(ApiError::Cancelled)
        );
    }
    let mut remote = RemoteGate::new();
    assert_eq!(
        remote.submit_cancellable(&api, a, CommandSequence(1), &command(), &cancellation),
        Err(RemoteError::Api(ApiError::Cancelled))
    );
    let foreign = RequestContext {
        agent: b.agent,
        ..a
    };
    assert_eq!(
        api.dispatch_cancellable(foreign, Operation::Input, &cancellation),
        Err(ApiError::Registry(RegistryError::ForeignSession))
    );
    assert_eq!(
        remote.submit_cancellable(&api, foreign, CommandSequence(1), &command(), &cancellation),
        Err(RemoteError::Api(ApiError::Registry(
            RegistryError::ForeignSession
        )))
    );
    assert_eq!(
        store.latest(&api, a).unwrap().identity,
        frame(a, 1).identity
    );
    assert_eq!(
        store.latest(&api, b).unwrap().identity,
        frame(b, 2).identity
    );
    assert_eq!(registry.list_sessions().len(), 2);
}

#[test]
fn equal_local_numbers_in_other_registries_cannot_cross_api_remote_or_frame_cache() {
    let (one, a, _) = sessions();
    let (two, b, _) = sessions();
    assert_eq!(a.agent.get(), b.agent.get());
    assert_eq!(a.session.id.get(), b.session.id.get());
    assert_ne!(a.agent, b.agent);
    assert_ne!(a.session.id, b.session.id);
    let mut store = FrameStore::new(1024);
    store.publish(&Api::new(&one), a, frame(a, 5)).unwrap();
    store.publish(&Api::new(&two), b, frame(b, 9)).unwrap();
    let error = ApiError::Registry(RegistryError::UnknownSession);
    assert_eq!(Api::new(&one).authorize(b), Err(error));
    assert_eq!(
        RemoteGate::new().submit(&Api::new(&one), b, CommandSequence(1), &command()),
        Err(RemoteError::Api(error))
    );
    assert_eq!(
        store.latest(&Api::new(&one), b),
        Err(FrameError::Api(error))
    );
    assert_eq!(
        store.forget(&Api::new(&one), b),
        Err(FrameError::Api(error))
    );
    assert_eq!(
        store.latest(&Api::new(&one), a).unwrap().identity.sequence,
        5
    );
    assert_eq!(
        store.latest(&Api::new(&two), b).unwrap().identity.sequence,
        9
    );
    store.forget(&Api::new(&one), a).unwrap();
    assert_eq!(
        store.latest(&Api::new(&two), b).unwrap().identity.sequence,
        9
    );
}

#[test]
fn absent_backends_are_explicit_and_live_frame_removal_does_not_reset_sequence() {
    let (registry, a, _) = sessions();
    let api = Api::new(&registry);
    for op in [
        Operation::Inspect,
        Operation::Capture,
        Operation::Input,
        Operation::Test,
    ] {
        assert_eq!(api.dispatch(a, op), Err(ApiError::Unsupported));
    }
    assert_eq!(
        RemoteGate::new().submit(&api, a, CommandSequence(1), &command()),
        Err(RemoteError::NotDispatched)
    );
    let mut store = FrameStore::new(1024);
    assert_eq!(store.latest(&api, a), Err(FrameError::NotAvailable));
    store.publish(&api, a, frame(a, 10)).unwrap();
    assert!(store.forget(&api, a).unwrap());
    assert_eq!(store.latest(&api, a), Err(FrameError::NotAvailable));
    assert_eq!(
        store.publish(&api, a, frame(a, 10)),
        Err(FrameError::StaleSequence)
    );
    store.publish(&api, a, frame(a, 11)).unwrap();
    assert_eq!(store.latest(&api, a).unwrap().identity.sequence, 11);
    assert_eq!(api.authorize(a).unwrap().state(), SessionState::Created);
}
