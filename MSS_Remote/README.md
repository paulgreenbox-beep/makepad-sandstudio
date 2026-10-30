# MSS_Remote

## Responsibility

Deliver a command to exactly one session's Makepad application and verify that the reply belongs to the expected app, session generation, and process identity.

## Planned boundary

MSS_Remote is an adapter around an application-owned control channel. It should validate the launched process identity and discovered endpoint, correlate requests, bound payloads and timeouts, classify pre-dispatch refusal versus uncertain outcome, and require independent postcondition observation for mutations. Session policy and business logic stay in MSS_API/Core.

Official Makepad --remote is a concrete source-inspected integration candidate. The inspected implementation is app-local and routes commands through the app event loop. The public source does not prove per-agent authentication, Toolkit operation parity, or that every command can be addressed without desktop-global side effects. The tools-2 adapter remains an experiment.

## Current state

No command transport, security gateway, semantic parity, retry policy, or live app proof is implemented. All are NOT_VERIFIED. A physical input fallback must not silently replace a semantic operation.
