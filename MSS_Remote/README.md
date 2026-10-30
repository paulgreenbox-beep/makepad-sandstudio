# MSS_Remote

## Responsibility

Deliver a command to exactly one session's Makepad application and verify that the reply belongs to the expected app, session generation, and process identity.

## Planned boundary

MSS_Remote is an adapter around an application-owned control channel. It should validate the launched process identity and discovered endpoint, correlate requests, bound payloads and timeouts, classify pre-dispatch refusal versus uncertain outcome, and require independent postcondition observation for mutations. Session policy and business logic stay in MSS_API/Core.

Official Makepad --remote is a concrete source-inspected integration candidate. The inspected implementation is app-local and routes commands through the app event loop. The public source does not prove per-agent authentication, Toolkit operation parity, or that every command can be addressed without desktop-global side effects. The tools-2 adapter remains an experiment.

## Current state

The Rust `RemoteGate` checks exact session/agent authorization through MSS_API,
nonzero command identity, and typed Read/Focus/Text input shape. AutomationId is
bounded to 256 UTF-8 bytes and text to 4096; empty addresses and control characters
are refused. This does not prove widget existence, an approved WidgetId mapping,
focus ownership, capability, or operation parity.

Every valid command returns `NotDispatched`; no input is emitted and no success
is fabricated. Cancellable submission can refuse before admission. The unused
completed-command map from PR #3 was removed: there is no dispatch to record.
Repeated known-undispatched requests do not consume sequence identities. Actual
replay fencing, bounded outcome tracking and uncertain-outcome recovery must be
implemented together with the real transport. There is no automatic retry.

Command transport, app authentication, native input, semantic execution and live
postconditions remain NOT_IMPLEMENTED / NOT_VERIFIED. There is no physical-input
fallback. See [integration tests and limitations](../doc/testing.md).
