# MSS_API

## Responsibility

Define the single backend contract used by MSS_Desktop, MSS_MCP, MSS_Remote, test workers, and MSS_Render for sessions, applications, GUI operations, tests, frames, evidence, and cleanup.

## Planned contract

The API owns authorization, session routing, capability checks, request correlation, idempotency declarations, failure taxonomy, and evidence linkage. It distinguishes a request accepted for dispatch from an independently observed result. Mutations with uncertain outcomes are never retried automatically.

Draft operation names and status envelopes are documented in doc/architecture.md. They are design proposals, not stable public APIs.

## Current state

`Api` borrows the single authoritative `SessionRegistry`. `RequestContext`
contains the caller's logical agent and exact session generation. Authorization
delegates to Core; API holds no parallel registry. Inspect/Capture are classified
as observations and Input/Test as mutations. Every dispatch authorizes first,
then returns `Unsupported` because no executor exists. These four classes are
not replacements for the Toolkit operation catalog or `.aiui.json` schema.

`CancellationToken` is an explicit shared, one-way flag. Cancellable authorization
and dispatch check ownership before cancellation. Cancellation covers admission
only; there is no running application operation to stop or roll back.
`Operation::try_from` accepts exactly the four local class names; `dispatch_named`
authorizes before parsing and refuses unknown names without a default. No wire
protocol is implemented. Unimplemented operation classes never return a success.

The in-process caller must already be trusted to supply its registered identity.
Network/MCP authentication, per-widget capabilities, process identity, server,
transport, Toolkit execution and native cancellation remain NOT_IMPLEMENTED or
NOT_VERIFIED. See [contracts and tests](../doc/testing.md).
