//! Public admission contracts only; no transport, input or native session proof.
use mss_api::{Api, ApiError, CancellationToken, RequestContext};
use mss_core::{RegistryError, SessionGeneration, SessionHandle, SessionRegistry};
use mss_remote::{CommandSequence, RemoteCommand, RemoteError, RemoteGate, WidgetTarget};

fn commands(address: &str) -> [RemoteCommand; 3] {
    let target = WidgetTarget {
        automation_id: address.to_owned(),
    };
    [
        RemoteCommand::Read(target.clone()),
        RemoteCommand::Focus(target.clone()),
        RemoteCommand::Text(target, " payload ".to_owned()),
    ]
}

#[test]
fn unicode_padding_is_refused_for_every_intent_and_both_entry_points() {
    let mut registry = SessionRegistry::new();
    let agent = registry.register_agent().unwrap();
    let id = registry.create_session(agent, "one").unwrap();
    let ctx = RequestContext {
        agent,
        session: registry.get_session(id).unwrap().handle(),
    };
    let api = Api::new(&registry);
    let token = CancellationToken::new();
    let mut gate = RemoteGate::new();
    for whitespace in [' ', '\u{00a0}', '\u{2003}', '\u{202f}', '\u{3000}'] {
        assert!(whitespace.is_whitespace());
        for address in [
            format!("{whitespace}input.name"),
            format!("input.name{whitespace}"),
        ] {
            for command in commands(&address) {
                let before = command.clone();
                assert_eq!(
                    gate.submit(&api, ctx, CommandSequence(1), &command),
                    Err(RemoteError::InvalidInput)
                );
                assert_eq!(
                    gate.submit_cancellable(&api, ctx, CommandSequence(1), &command, &token),
                    Err(RemoteError::InvalidInput)
                );
                assert_eq!(command, before);
            }
        }
    }
    assert_eq!(api.authorize(ctx).unwrap().title(), "one");
}

#[test]
fn target_padding_policy_does_not_trim_or_reject_legal_text_payload() {
    let mut registry = SessionRegistry::new();
    let agent = registry.register_agent().unwrap();
    let id = registry.create_session(agent, "one").unwrap();
    let ctx = RequestContext {
        agent,
        session: registry.get_session(id).unwrap().handle(),
    };
    let api = Api::new(&registry);
    let mut gate = RemoteGate::new();
    for text in [" leading ", "\u{00a0}payload\u{2003}", r"\u{00a0}"] {
        let command = RemoteCommand::Text(
            WidgetTarget {
                automation_id: "input.name".to_owned(),
            },
            text.to_owned(),
        );
        let before = command.clone();
        assert_eq!(
            gate.submit(&api, ctx, CommandSequence(1), &command),
            Err(RemoteError::NotDispatched)
        );
        assert_eq!(command, before);
    }
}

#[test]
fn authorization_and_cancellation_precede_noncanonical_address_errors() {
    let mut registry = SessionRegistry::new();
    let owner = registry.register_agent().unwrap();
    let other = registry.register_agent().unwrap();
    let id = registry.create_session(owner, "one").unwrap();
    let ctx = RequestContext {
        agent: owner,
        session: registry.get_session(id).unwrap().handle(),
    };
    let cancelled = CancellationToken::new();
    cancelled.cancel();
    let mut gate = RemoteGate::new();
    for command in commands("\u{00a0}input.name") {
        let api = Api::new(&registry);
        assert_eq!(
            gate.submit_cancellable(&api, ctx, CommandSequence(0), &command, &cancelled),
            Err(RemoteError::Api(ApiError::Cancelled))
        );
        for (context, expected) in [
            (
                RequestContext {
                    agent: other,
                    ..ctx
                },
                RegistryError::ForeignSession,
            ),
            (
                RequestContext {
                    session: SessionHandle {
                        generation: SessionGeneration::new(2).unwrap(),
                        ..ctx.session
                    },
                    ..ctx
                },
                RegistryError::StaleGeneration,
            ),
        ] {
            assert_eq!(
                gate.submit_cancellable(&api, context, CommandSequence(0), &command, &cancelled),
                Err(RemoteError::Api(ApiError::Registry(expected)))
            );
        }
    }
    registry.close_owned_session(ctx.session, owner).unwrap();
    assert_eq!(
        gate.submit_cancellable(
            &Api::new(&registry),
            ctx,
            CommandSequence(0),
            &commands(" input.name")[0],
            &cancelled,
        ),
        Err(RemoteError::Api(ApiError::Registry(
            RegistryError::UnknownSession
        )))
    );
}
